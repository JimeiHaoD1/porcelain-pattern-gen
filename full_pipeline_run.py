# -*- coding: utf-8 -*-
"""
完整全流程生成脚本：KG推理 -> Blueprint -> 控制信号 -> SDXL+ControlNet+IP-Adapter

Stage 0: HybridGraphEngine 语义推理 -> blueprint
Stage 1: PorcelainGenerationPipeline.process_blueprint -> lineart_map, masks, ip_adapter_data
Stage 2: SDXL + ControlNet(tile+seg) + IP-Adapter(spirit) -> final image
"""
from __future__ import annotations

import inspect
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from diffusers import ControlNetModel, StableDiffusionXLControlNetPipeline

from kg_sketch_reasoning_engine import HybridGraphEngine
from pipeline_controller import PorcelainGenerationPipeline

# ── 配置 ────────────────────────────────────────────────────
BASE_MODEL  = "stabilityai/stable-diffusion-xl-base-1.0"
CN_TILE_ID  = "xinsir/controlnet-tile-sdxl-1.0"
CN_SEG_ID   = "xinsir/controlnet-scribble-sdxl-1.0"
IPA_REPO    = "h94/IP-Adapter"
IPA_WEIGHT    = "ip-adapter_sdxl_vit-h.safetensors"
IPA_SUBFOLDER = "sdxl_models"
IPA_IMAGE_ENCODER = "laion/CLIP-ViT-H-14-laion2B-s32B-b79K"
OUTPUT_DIR  = Path("d:/SD/outputs/full_pipeline")
KG_PATH     = Path("MMKG/data_csv/mmkg_final_v53_optimized.csv")
CANVAS      = (768, 768)
# ────────────────────────────────────────────────────────────


def build_sdxl_pipe(device: str = "cuda"):
    print("[*] 加载 ControlNet (tile + seg)...")
    cn_tile = ControlNetModel.from_pretrained(CN_TILE_ID, torch_dtype=torch.float16)
    cn_seg  = ControlNetModel.from_pretrained(CN_SEG_ID,  torch_dtype=torch.float16)

    print("[*] 加载 image_encoder (ViT-H/14, projection_dim=1024)...")
    from transformers import CLIPVisionModelWithProjection
    image_encoder = CLIPVisionModelWithProjection.from_pretrained(
        IPA_IMAGE_ENCODER,
        torch_dtype=torch.float16,
    )

    print("[*] 加载 SDXL base...")
    pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
        BASE_MODEL,
        controlnet=[cn_tile, cn_seg],
        image_encoder=image_encoder,
        torch_dtype=torch.float16,
        use_safetensors=True,
    ).to(device)

    # 显存优化（在 IP-Adapter 加载前只启用 VAE 优化）
    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()

    print("[*] 加载 IP-Adapter...")
    pipe.load_ip_adapter(IPA_REPO, subfolder=IPA_SUBFOLDER, weight_name=IPA_WEIGHT)
    print("[OK] SDXL pipeline 加载完成")

    # 直接保持在 GPU，RTX 5070 12.8GB 显存足够 float16
    # 不用 CPU offload：会把权重卸到内存导致 48GB 内存占满
    return pipe


def masks_to_seg_image(masks_by_slot: dict, slots: list, canvas: tuple) -> Image.Image:
    """把各槽位 mask 合成 RGB 分割图作为 seg ControlNet 输入"""
    w, h = canvas
    seg = np.zeros((h, w, 3), dtype=np.uint8)
    color_map = {
        "primary":   (0,   0,   255),
        "secondary": (255, 100, 50),
        "border":    (0,   200, 50),
        "symbol":    (200, 0,   200),
        "base":      (30,  30,  30),
    }
    priority = {"base": 0, "border": 1, "symbol": 2, "secondary": 3, "primary": 4}
    for slot in sorted(slots, key=lambda s: priority.get(s["role"], 0)):
        mask = masks_by_slot.get(slot["slot_id"])
        if mask is None:
            continue
        seg[mask > 0] = color_map.get(slot["role"], (128, 128, 128))
    return Image.fromarray(cv2.cvtColor(seg, cv2.COLOR_BGR2RGB))


def build_ip_inputs(ip_adapter_data: list, pipe, supports_mask: bool, target_size: tuple = (768, 768)):
    """用 pipeline 内置的 ViT-H encoder 编码 IP-Adapter 输入"""
    if not ip_adapter_data:
        return None, None, 0.0

    item     = ip_adapter_data[0]
    img_arr  = item["image"]
    mask_arr = item["mask"]
    scale    = float(item.get("ipa_scale", 0.65))

    # resize 到 target_size
    tw, th = target_size
    img_arr  = cv2.resize(img_arr,  (tw, th), interpolation=cv2.INTER_LINEAR)
    mask_arr = cv2.resize(mask_arr, (tw, th), interpolation=cv2.INTER_NEAREST)

    ip_img  = Image.fromarray(img_arr.astype(np.uint8))
    ip_mask = Image.fromarray(mask_arr.astype(np.uint8))

    if not supports_mask:
        arr = np.array(ip_img)
        out = np.full_like(arr, 255)
        out[mask_arr > 0] = arr[mask_arr > 0]
        ip_img = Image.fromarray(out)
        ip_mask = None

    # 直接返回 PIL 图像，让 pipeline 用自己加载的 image_encoder (laion ViT-H-14, projection_dim=1024) 编码
    # 这样能确保编码器和 IP-Adapter 权重完全匹配
    return ip_img, ip_mask, scale


def is_tensor_embeds(obj) -> bool:
    return isinstance(obj, torch.Tensor)


def run_query(
    query: str,
    pipe,
    engine: HybridGraphEngine,
    porcelain: PorcelainGenerationPipeline,
    seed: int = 42,
    num_images: int = 2,
    output_dir: Path = OUTPUT_DIR,
) -> list[Path]:
    print(f"\n{'='*70}")
    print(f"[Query] {query}")
    print(f"{'='*70}")

    # Stage 0: KG 推理
    print("[Stage 0] KG 语义推理...", end="", flush=True)
    t0 = time.time()
    blueprint = engine.build_blueprint_v52(query, seed=seed)
    intent = blueprint["debug"]["intent_category"]
    slots_summary = ", ".join(s["element"] for s in blueprint["slots"])
    print(f" OK ({time.time()-t0:.2f}s)")
    print(f"  意图: {intent}")
    print(f"  槽位: {slots_summary}")

    # Stage 1: 控制信号生成
    print("[Stage 1] 生成控制信号...", end="", flush=True)
    t1 = time.time()
    out = porcelain.process_blueprint(blueprint)
    lineart_map    = out["control_signals"]["lineart_map"]
    lineart_weight = out["control_signals"]["lineart_weight"]
    masks_by_slot  = out["masks"]
    slots          = out["resolved_blueprint"]["slots"]
    ip_data        = out["ip_adapter_data"]
    prompt         = out["prompts"]["global"]
    neg_prompt     = out["prompts"]["negative"]
    canvas         = (
        out["resolved_blueprint"]["canvas"]["width"],
        out["resolved_blueprint"]["canvas"]["height"],
    )
    print(f" OK ({time.time()-t1:.2f}s)")
    print(f"  ControlNet 权重: {lineart_weight}")
    print(f"  IP-Adapter 元素数: {len(ip_data)}")
    print(f"  Prompt: {prompt[:80]}...")

    # 转换控制图像
    lineart_pil = Image.fromarray(lineart_map.astype(np.uint8)).resize(CANVAS)
    seg_pil     = masks_to_seg_image(masks_by_slot, slots, canvas).resize(CANVAS)

    # 保存调试图
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_q = "".join(c if c.isalnum() else "_" for c in query)
    lineart_pil.save(output_dir / f"{safe_q}_lineart.png")
    seg_pil.save(output_dir / f"{safe_q}_seg.png")
    Image.fromarray(out["debug_image"].astype(np.uint8)).save(
        output_dir / f"{safe_q}_layout.png"
    )

    # Stage 2: SDXL 渲染
    print(f"[Stage 2] SDXL 渲染 ({num_images} 张)...")
    supports_mask = "ip_adapter_mask" in inspect.signature(pipe.__call__).parameters
    ip_embed, ip_mask, ip_scale = build_ip_inputs(ip_data, pipe, supports_mask, target_size=CANVAS)

    saved: list[Path] = []
    for i in range(num_images):
        cur_seed = seed + i
        print(f"  [{i+1}/{num_images}] seed={cur_seed}...", end="", flush=True)
        t2 = time.time()

        kwargs = dict(
            prompt=prompt,
            negative_prompt=neg_prompt,
            image=[lineart_pil, seg_pil],
            controlnet_conditioning_scale=[lineart_weight, 0.40],
            guidance_scale=7.5,
            num_inference_steps=20,
            generator=torch.Generator("cuda").manual_seed(cur_seed),
        )

        if ip_embed is not None:
            pipe.set_ip_adapter_scale(ip_scale)
            # 直接传 PIL 图像，pipeline 用 laion ViT-H-14 (projection_dim=1024) 自动编码
            kwargs["ip_adapter_image"] = ip_embed
            if supports_mask and ip_mask is not None:
                kwargs["ip_adapter_mask"] = ip_mask
        else:
            pipe.set_ip_adapter_scale(0.0)

        with torch.no_grad():
            result = pipe(**kwargs).images[0]

        elapsed = time.time() - t2
        print(f" 完成 ({elapsed:.1f}s)")

        out_path = output_dir / f"{safe_q}_seed{cur_seed}.png"
        result.save(str(out_path))
        print(f"  保存: {out_path.name}")
        saved.append(out_path)

    return saved


def main():
    queries = [
        "祝老板生意兴隆",
        "早生贵子",
        "想去山里隐居",
        "新婚快乐",
        "松鹤延年",
    ]

    print("\n" + "="*70)
    print("全流程：KG推理 -> Blueprint -> ControlNet+IP-Adapter -> SDXL")
    print("="*70)

    if not torch.cuda.is_available():
        print("[错误] 需要 CUDA")
        return
    print(f"[GPU] {torch.cuda.get_device_name(0)}  "
          f"{torch.cuda.get_device_properties(0).total_memory/1e9:.1f} GB")

    print("\n[*] 初始化 KG 推理引擎...")
    engine = HybridGraphEngine(KG_PATH)
    print(f"[OK] 元素: {len(engine.all_elements())}  "
          f"共现: {sum(len(v) for v in engine.co_occurs.values())}")

    print("[*] 初始化生成管道...")
    porcelain = PorcelainGenerationPipeline(canvas_size=CANVAS, rng_seed=42)
    print("[OK] 生成管道就绪")

    pipe = build_sdxl_pipe()

    all_saved: list[Path] = []
    for query in queries:
        try:
            paths = run_query(
                query, pipe, engine, porcelain,
                seed=42, num_images=2,
                output_dir=OUTPUT_DIR,
            )
            all_saved.extend(paths)
        except Exception as e:
            print(f"[错误] {query}: {e}")
            import traceback; traceback.print_exc()

    print(f"\n{'='*70}")
    print(f"[完成] 共生成 {len(all_saved)} 张图像")
    print(f"[目录] {OUTPUT_DIR}")
    print(f"{'='*70}")
    for p in all_saved:
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
