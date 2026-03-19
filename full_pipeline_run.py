# -*- coding: utf-8 -*-
"""
完整全流程生成脚本：KG推理 -> Blueprint -> 控制信号 -> SDXL+ControlNet

Stage 0: HybridGraphEngine 语义推理 -> blueprint
Stage 1: PorcelainGenerationPipeline.process_blueprint -> lineart_map, masks
Stage 2: SDXL + ControlNet(tile) -> final image

[ablation/no-ipa] 去除 IP-Adapter 和 seg ControlNet，只保留 tile ControlNet
"""
from __future__ import annotations

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
BASE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
CN_TILE_ID = "xinsir/controlnet-tile-sdxl-1.0"
OUTPUT_DIR = Path("d:/SD/outputs/ablation_no_ipa")
KG_PATH    = Path("MMKG/data_csv/mmkg_final_v53_optimized.csv")
CANVAS     = (768, 768)
# ────────────────────────────────────────────────────────────


def build_sdxl_pipe(device: str = "cuda"):
    print("[*] 加载 ControlNet (tile)...")
    cn_tile = ControlNetModel.from_pretrained(CN_TILE_ID, torch_dtype=torch.float16)

    print("[*] 加载 SDXL base...")
    pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
        BASE_MODEL,
        controlnet=cn_tile,
        torch_dtype=torch.float16,
        use_safetensors=True,
    ).to(device)

    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()
    print("[OK] SDXL pipeline 加载完成")
    return pipe


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
    prompt         = out["prompts"]["global"]
    neg_prompt     = out["prompts"]["negative"]
    canvas         = (
        out["resolved_blueprint"]["canvas"]["width"],
        out["resolved_blueprint"]["canvas"]["height"],
    )
    print(f" OK ({time.time()-t1:.2f}s)")
    print(f"  ControlNet tile 权重: {lineart_weight}")
    print(f"  Prompt: {prompt[:80]}...")

    # 转换控制图像
    lineart_pil = Image.fromarray(lineart_map.astype(np.uint8)).resize(CANVAS)

    # 保存调试图
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_q = "".join(c if c.isalnum() else "_" for c in query)
    lineart_pil.save(output_dir / f"{safe_q}_lineart.png")
    Image.fromarray(out["debug_image"].astype(np.uint8)).save(
        output_dir / f"{safe_q}_layout.png"
    )

    # Stage 2: SDXL 渲染
    print(f"[Stage 2] SDXL 渲染 ({num_images} 张)...")
    saved: list[Path] = []
    for i in range(num_images):
        cur_seed = seed + i
        print(f"  [{i+1}/{num_images}] seed={cur_seed}...", end="", flush=True)
        t2 = time.time()

        with torch.no_grad():
            result = pipe(
                prompt=prompt,
                negative_prompt=neg_prompt,
                image=lineart_pil,
                controlnet_conditioning_scale=lineart_weight,
                guidance_scale=7.5,
                num_inference_steps=20,
                generator=torch.Generator("cuda").manual_seed(cur_seed),
            ).images[0]

        print(f" 完成 ({time.time()-t2:.1f}s)")
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
    print("全流程：KG推理 -> Blueprint -> ControlNet(tile only) -> SDXL")
    print("[ablation] 无 IP-Adapter，无 seg ControlNet")
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
