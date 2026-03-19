# -*- coding: utf-8 -*-
"""
底纹 LoRA 训练脚本

目标：为海水、卷草、云纹等底纹元素训练专属 LoRA，
      使 SDXL 在看到方向性灰度引导信号时能正确"幻觉"出传统纹样。

用法：
    python train_texture_lora.py --element haishui --data_dir path/to/images
    python train_texture_lora.py --element juancao --data_dir path/to/images
    python train_texture_lora.py --element yun     --data_dir path/to/images

训练数据要求：
    - 图片：白底黑线的传统纹样线稿，或彩色青花瓷底纹图
    - 数量：建议 20~50 张（12 张可以跑，但效果一般）
    - 尺寸：建议 512x512 或 768x768，正方形最佳
    - 格式：PNG 或 JPG
    - 命名：任意，脚本会自动扫描目录

输出：
    lora_output/<element>/  包含 LoRA 权重 (.safetensors)
"""
from __future__ import annotations

import argparse
import math
import os
import random
import shutil
from pathlib import Path

import torch
import torch.nn.functional as F
from accelerate import Accelerator
from accelerate.utils import ProjectConfiguration
from diffusers import (
    AutoencoderKL,
    DDPMScheduler,
    UNet2DConditionModel,
)
from diffusers.optimization import get_scheduler
from peft import LoraConfig, get_peft_model
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from transformers import CLIPTextModel, CLIPTextModelWithProjection, CLIPTokenizer

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# ── 元素配置 ─────────────────────────────────────────────────
ELEMENT_CONFIG = {
    "haishui": {
        "trigger_word": "haishui_texture",
        "caption": (
            "haishui_texture, traditional chinese blue and white porcelain sea water pattern, "
            "dense crashing ocean waves, repeating surf motif, qinghua porcelain linework, "
            "white background, ink line drawing"
        ),
        "steps": 1200,
    },
    "juancao": {
        "trigger_word": "juancao_texture",
        "caption": (
            "juancao_texture, traditional chinese blue and white porcelain scrolling grass pattern, "
            "intertwining vine tendrils, curling leaf motif, qinghua porcelain linework, "
            "white background, ink line drawing"
        ),
        "steps": 1200,
    },
    "yun": {
        "trigger_word": "yun_texture",
        "caption": (
            "yun_texture, traditional chinese blue and white porcelain auspicious cloud pattern, "
            "ruyi cloud heads, layered cloud motif, qinghua porcelain linework, "
            "white background, ink line drawing"
        ),
        "steps": 1000,
    },
    "huiwen": {
        "trigger_word": "huiwen_texture",
        "caption": (
            "huiwen_texture, traditional chinese blue and white porcelain meander border pattern, "
            "greek key geometric border, repeating angular motif, qinghua porcelain linework, "
            "white background, ink line drawing"
        ),
        "steps": 800,
    },
}

BASE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
IMG_EXTS   = {".png", ".jpg", ".jpeg", ".webp"}


# ── 数据集 ───────────────────────────────────────────────────

class TextureDataset(Dataset):
    def __init__(
        self,
        data_dir: str | Path,
        caption: str,
        tokenizer_1: CLIPTokenizer,
        tokenizer_2: CLIPTokenizer,
        resolution: int = 768,
        augment: bool = True,
    ):
        self.paths = sorted(
            p for p in Path(data_dir).iterdir()
            if p.is_file() and p.suffix.lower() in IMG_EXTS
        )
        if not self.paths:
            raise FileNotFoundError(f"No images found in {data_dir}")
        print(f"[dataset] Found {len(self.paths)} images in {data_dir}")

        self.caption     = caption
        self.tokenizer_1 = tokenizer_1
        self.tokenizer_2 = tokenizer_2
        self.resolution  = resolution
        self.augment     = augment

    def _preprocess(self, img: Image.Image) -> torch.Tensor:
        """调整尺寸、随机裁剪/翻转、归一化到 [-1, 1]"""
        img = img.convert("RGB")
        w, h = img.size
        # 缩放短边到 resolution
        scale = self.resolution / min(w, h)
        nw, nh = int(w * scale), int(h * scale)
        img = img.resize((nw, nh), Image.BICUBIC)

        if self.augment:
            # 随机裁剪
            x0 = random.randint(0, max(0, nw - self.resolution))
            y0 = random.randint(0, max(0, nh - self.resolution))
        else:
            x0 = (nw - self.resolution) // 2
            y0 = (nh - self.resolution) // 2

        img = img.crop((x0, y0, x0 + self.resolution, y0 + self.resolution))

        if self.augment and random.random() < 0.5:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if self.augment and random.random() < 0.3:
            # 轻微旋转（底纹纹样旋转后仍然有效）
            angle = random.uniform(-15, 15)
            img = img.rotate(angle, fillcolor=(255, 255, 255))

        tensor = torch.from_numpy(
            __import__("numpy").array(img, dtype="float32")
        ).permute(2, 0, 1) / 127.5 - 1.0
        return tensor

    def _tokenize(self, text: str, tokenizer: CLIPTokenizer) -> torch.Tensor:
        return tokenizer(
            text,
            padding="max_length",
            max_length=tokenizer.model_max_length,
            truncation=True,
            return_tensors="pt",
        ).input_ids[0]

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, idx: int):
        img = Image.open(self.paths[idx % len(self.paths)])
        pixel = self._preprocess(img)
        ids_1  = self._tokenize(self.caption, self.tokenizer_1)
        ids_2  = self._tokenize(self.caption, self.tokenizer_2)
        return {"pixel_values": pixel, "input_ids_1": ids_1, "input_ids_2": ids_2}


# ── 主训练函数 ───────────────────────────────────────────────

def train(
    element: str,
    data_dir: str,
    output_dir: str | None = None,
    resolution: int = 768,
    batch_size: int = 1,
    grad_accum: int = 4,
    lr: float = 1e-4,
    lora_rank: int = 16,
    lora_alpha: int = 16,
    mixed_precision: str = "fp16",
    save_every: int = 200,
):
    cfg = ELEMENT_CONFIG.get(element)
    if cfg is None:
        raise ValueError(f"Unknown element '{element}'. Choose from: {list(ELEMENT_CONFIG)}")

    max_steps    = cfg["steps"]
    trigger_word = cfg["trigger_word"]
    caption      = cfg["caption"]

    if output_dir is None:
        output_dir = f"lora_output/{element}"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"训练底纹 LoRA: {element}")
    print(f"  触发词   : {trigger_word}")
    print(f"  数据目录 : {data_dir}")
    print(f"  输出目录 : {output_dir}")
    print(f"  训练步数 : {max_steps}")
    print(f"  分辨率   : {resolution}")
    print(f"  LoRA rank: {lora_rank}")
    print(f"{'='*60}\n")

    # Accelerator
    accel_cfg = ProjectConfiguration(project_dir=output_dir)
    accelerator = Accelerator(
        gradient_accumulation_steps=grad_accum,
        mixed_precision=mixed_precision,
        project_config=accel_cfg,
    )
    device = accelerator.device
    weight_dtype = torch.float16 if mixed_precision == "fp16" else torch.float32

    # 加载模型组件
    print("[*] 加载 tokenizers...")
    tokenizer_1 = CLIPTokenizer.from_pretrained(BASE_MODEL, subfolder="tokenizer")
    tokenizer_2 = CLIPTokenizer.from_pretrained(BASE_MODEL, subfolder="tokenizer_2")

    print("[*] 加载 text encoders...")
    text_enc_1 = CLIPTextModel.from_pretrained(
        BASE_MODEL, subfolder="text_encoder", torch_dtype=weight_dtype
    ).to(device)
    text_enc_2 = CLIPTextModelWithProjection.from_pretrained(
        BASE_MODEL, subfolder="text_encoder_2", torch_dtype=weight_dtype
    ).to(device)
    text_enc_1.requires_grad_(False)
    text_enc_2.requires_grad_(False)

    print("[*] 加载 VAE...")
    vae = AutoencoderKL.from_pretrained(
        BASE_MODEL, subfolder="vae", torch_dtype=weight_dtype
    ).to(device)
    vae.requires_grad_(False)

    print("[*] 加载 UNet...")
    unet = UNet2DConditionModel.from_pretrained(
        BASE_MODEL, subfolder="unet", torch_dtype=weight_dtype
    )

    # 添加 LoRA 到 UNet
    print(f"[*] 添加 LoRA (rank={lora_rank}, alpha={lora_alpha})...")
    lora_config = LoraConfig(
        r=lora_rank,
        lora_alpha=lora_alpha,
        target_modules=[
            "to_q", "to_k", "to_v", "to_out.0",
            "proj_in", "proj_out",
            "ff.net.0.proj", "ff.net.2",
        ],
        lora_dropout=0.05,
        bias="none",
    )
    unet = get_peft_model(unet, lora_config)
    unet.to(device)
    unet.print_trainable_parameters()

    # Noise scheduler
    noise_scheduler = DDPMScheduler.from_pretrained(BASE_MODEL, subfolder="scheduler")

    # Dataset & DataLoader
    dataset = TextureDataset(
        data_dir, caption, tokenizer_1, tokenizer_2,
        resolution=resolution, augment=True,
    )
    # 如果图片少于 batch_size，重复数据集
    if len(dataset) < batch_size:
        raise ValueError(f"数据集只有 {len(dataset)} 张图，至少需要 {batch_size} 张")

    dataloader = DataLoader(
        dataset, batch_size=batch_size, shuffle=True,
        num_workers=0, drop_last=True,
    )

    # Optimizer
    optimizer = torch.optim.AdamW(
        unet.parameters(), lr=lr,
        betas=(0.9, 0.999), weight_decay=1e-2, eps=1e-8,
    )

    # LR scheduler：cosine with warmup
    total_steps = max_steps
    warmup_steps = max(50, total_steps // 10)
    lr_scheduler = get_scheduler(
        "cosine",
        optimizer=optimizer,
        num_warmup_steps=warmup_steps * grad_accum,
        num_training_steps=total_steps * grad_accum,
    )

    # Prepare with accelerator
    unet, optimizer, dataloader, lr_scheduler = accelerator.prepare(
        unet, optimizer, dataloader, lr_scheduler
    )

    # ── 训练循环 ──────────────────────────────────────────────
    print(f"\n[*] 开始训练，共 {max_steps} 步...")
    global_step  = 0
    running_loss = 0.0
    data_iter    = iter(dataloader)

    unet.train()
    while global_step < max_steps:
        # 循环数据集
        try:
            batch = next(data_iter)
        except StopIteration:
            data_iter = iter(dataloader)
            batch = next(data_iter)

        with accelerator.accumulate(unet):
            # 编码图像到 latent
            pixels = batch["pixel_values"].to(device, dtype=weight_dtype)
            with torch.no_grad():
                latents = vae.encode(pixels).latent_dist.sample()
                latents = latents * vae.config.scaling_factor

            # 随机噪声 + 时间步
            noise    = torch.randn_like(latents)
            bsz      = latents.shape[0]
            timesteps = torch.randint(
                0, noise_scheduler.config.num_train_timesteps,
                (bsz,), device=device,
            ).long()
            noisy_latents = noise_scheduler.add_noise(latents, noise, timesteps)

            # 文本编码
            with torch.no_grad():
                enc1_out = text_enc_1(
                    batch["input_ids_1"].to(device),
                    output_hidden_states=True,
                )
                enc2_out = text_enc_2(
                    batch["input_ids_2"].to(device),
                    output_hidden_states=True,
                )
                # SDXL 需要 pooled + concat hidden states
                prompt_embeds = torch.cat(
                    [enc1_out.hidden_states[-2], enc2_out.hidden_states[-2]], dim=-1
                )
                pooled_embeds = enc2_out.text_embeds

            # SDXL 额外条件（original_size, crop_coords, target_size）
            add_time_ids = torch.tensor(
                [[resolution, resolution, 0, 0, resolution, resolution]],
                dtype=weight_dtype, device=device,
            ).repeat(bsz, 1)

            # UNet 前向
            added_cond_kwargs = {
                "text_embeds": pooled_embeds,
                "time_ids": add_time_ids,
            }
            noise_pred = unet(
                noisy_latents,
                timesteps,
                encoder_hidden_states=prompt_embeds,
                added_cond_kwargs=added_cond_kwargs,
            ).sample

            # v-prediction 或 epsilon prediction
            if noise_scheduler.config.prediction_type == "epsilon":
                target = noise
            elif noise_scheduler.config.prediction_type == "v_prediction":
                target = noise_scheduler.get_velocity(latents, noise, timesteps)
            else:
                raise ValueError(f"Unknown prediction_type: {noise_scheduler.config.prediction_type}")

            loss = F.mse_loss(noise_pred.float(), target.float(), reduction="mean")
            running_loss += loss.item()

            accelerator.backward(loss)
            if accelerator.sync_gradients:
                accelerator.clip_grad_norm_(unet.parameters(), 1.0)
            optimizer.step()
            lr_scheduler.step()
            optimizer.zero_grad()

        # 每步完成后更新计数
        if accelerator.sync_gradients:
            global_step += 1

            # 日志
            if global_step % 50 == 0:
                avg_loss = running_loss / 50
                running_loss = 0.0
                lr_now = lr_scheduler.get_last_lr()[0]
                print(f"  step {global_step:4d}/{max_steps}  loss={avg_loss:.4f}  lr={lr_now:.2e}")

            # 保存检查点
            if global_step % save_every == 0 or global_step == max_steps:
                ckpt_dir = Path(output_dir) / f"checkpoint-{global_step}"
                ckpt_dir.mkdir(parents=True, exist_ok=True)
                # 只保存 LoRA 权重
                unwrapped = accelerator.unwrap_model(unet)
                unwrapped.save_pretrained(str(ckpt_dir))
                print(f"  [saved] checkpoint-{global_step} -> {ckpt_dir}")

    # ── 保存最终 LoRA ─────────────────────────────────────────
    print("\n[*] 保存最终 LoRA 权重...")
    unwrapped = accelerator.unwrap_model(unet)

    # 导出为 safetensors 格式（kohya 兼容）
    from safetensors.torch import save_file
    lora_state = {}
    for name, param in unwrapped.named_parameters():
        if "lora" in name.lower():
            lora_state[name] = param.data.cpu().to(torch.float16)

    out_path = Path(output_dir) / f"{element}_texture_lora.safetensors"
    save_file(lora_state, str(out_path))
    print(f"[OK] LoRA 已保存: {out_path}")
    print(f"     触发词: {trigger_word}")
    print(f"     使用方法: 在 prompt 中加入 '{trigger_word}'")

    return str(out_path)


# ── CLI 入口 ─────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="训练底纹 LoRA")
    parser.add_argument(
        "--element", required=True,
        choices=list(ELEMENT_CONFIG.keys()),
        help="要训练的纹饰元素名称",
    )
    parser.add_argument(
        "--data_dir", required=True,
        help="训练图片目录（白底线稿或青花瓷纹样图）",
    )
    parser.add_argument(
        "--output_dir", default=None,
        help="LoRA 输出目录，默认 lora_output/<element>",
    )
    parser.add_argument(
        "--resolution", type=int, default=768,
        help="训练分辨率，建议 512 或 768",
    )
    parser.add_argument(
        "--batch_size", type=int, default=1,
        help="批大小，12GB 显存建议用 1",
    )
    parser.add_argument(
        "--grad_accum", type=int, default=4,
        help="梯度累积步数，等效 batch_size x grad_accum",
    )
    parser.add_argument(
        "--lr", type=float, default=1e-4,
        help="学习率",
    )
    parser.add_argument(
        "--lora_rank", type=int, default=16,
        help="LoRA rank，越大表达力越强但显存占用越多",
    )
    parser.add_argument(
        "--lora_alpha", type=int, default=16,
        help="LoRA alpha，通常等于 rank",
    )
    parser.add_argument(
        "--mixed_precision", default="fp16",
        choices=["no", "fp16", "bf16"],
        help="混合精度训练",
    )
    parser.add_argument(
        "--save_every", type=int, default=200,
        help="每隔多少步保存一次检查点",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train(
        element=args.element,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        resolution=args.resolution,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        lr=args.lr,
        lora_rank=args.lora_rank,
        lora_alpha=args.lora_alpha,
        mixed_precision=args.mixed_precision,
        save_every=args.save_every,
    )
 