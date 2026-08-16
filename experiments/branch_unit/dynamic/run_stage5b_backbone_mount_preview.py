#!/usr/bin/env python3
"""Render stage-5B backbone and flower-relation review strips."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from backbone_variation_v1 import generate_and_analyze_variant
from flower_mounting_v1 import build_flower_mount_plan
from prototype_strategy_v1 import DEFAULT_REGISTRY, resolve_prototype_strategy
from strict_p0_v2 import StrictP0V2, load_materialized_strict_p0_v2


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
STAGE1_ROOT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_backbone_mount_preview_v1"
MORPHOLOGY_CONTRACT = DYNAMIC_DIR / "MORPHOLOGY_CONTRACT.json"
STAGE3_CONTRACT = DYNAMIC_DIR / "STAGE3_PLAN_CONTRACT.json"
PROTOTYPE_IDS = ("proto_sw_1_1", "proto_sw_2_3", "proto_sw_3_2")
LEVELS = (("baseline", 0.0), ("regular", 0.675), ("strong", 1.0))
COLORS = {
    "baseline": "#17222b",
    "regular": "#137f82",
    "strong": "#b45b25",
    "mount": "#4f7e29",
    "flower": "#c42d72",
    "ghost": "#c6cdd1",
    "grid": "#d8dddf",
    "background": "#f7f6f1",
}


class Stage5BPreviewError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5BPreviewError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ):
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _xy(
    strict_p0: StrictP0V2,
    point: Sequence[float],
    box: tuple[int, int, int, int],
    shift_x: float = 0.0,
) -> tuple[float, float]:
    left, top, right, bottom = box
    height = float(strict_p0.frame.local_canvas_bounds[3])
    x_min, x_max = -0.08, 1.08
    y_min, y_max = -0.03, height + 0.03
    scale = min((right - left) / (x_max - x_min), (bottom - top) / (y_max - y_min))
    used_width = (x_max - x_min) * scale
    used_height = (y_max - y_min) * scale
    offset_x = left + 0.5 * ((right - left) - used_width)
    offset_y = top + 0.5 * ((bottom - top) - used_height)
    return (
        offset_x + (float(point[0]) + shift_x - x_min) * scale,
        offset_y + (float(point[1]) - y_min) * scale,
    )


def _scale(strict_p0: StrictP0V2, box: tuple[int, int, int, int]) -> float:
    left, top, right, bottom = box
    height = float(strict_p0.frame.local_canvas_bounds[3])
    return min((right - left) / 1.16, (bottom - top) / (height + 0.06))


def _render_row(
    prototype_id: str,
    variants: Sequence[tuple[str, StrictP0V2, Mapping[str, Any], Mapping[str, Any]]],
    output: Path,
) -> None:
    width, height = 1550, 500
    image = Image.new("RGB", (width, height), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((28, 16), f"5B 主干/花朵关系 · {prototype_id}", font=_font(24, bold=True), fill="#17222b")
    draw.text((1170, 20), "VISUAL_REVIEW_PENDING", font=_font(14), fill="#69747b")
    panel_width = 490
    baseline_backbone = [sample.point for sample in variants[0][1].backbone_samples]
    for index, (label, strict_p0, variation, mount_plan) in enumerate(variants):
        left = 28 + index * 505
        box = (left + 12, 92, left + panel_width - 12, 415)
        draw.rounded_rectangle((left, 62, left + panel_width, 472), radius=14, fill="#ffffff", outline=COLORS["grid"], width=2)
        for boundary in (0.0, 1.0):
            draw.line([_xy(strict_p0, (boundary, 0.0), box), _xy(strict_p0, (boundary, strict_p0.frame.local_canvas_bounds[3]), box)], fill=COLORS["grid"], width=1)
        backbone = [sample.point for sample in strict_p0.backbone_samples]
        for shift in (-1.0, 1.0):
            draw.line([_xy(strict_p0, point, box, shift) for point in backbone], fill=COLORS["ghost"], width=3, joint="curve")
        path = [_xy(strict_p0, point, box) for point in backbone]
        if index > 0:
            baseline_path = [_xy(strict_p0, point, box) for point in baseline_backbone]
            draw.line(baseline_path, fill="#b8c0c5", width=3, joint="curve")
        draw.line(path, fill="#ffffff", width=11, joint="curve")
        draw.line(path, fill=COLORS[label], width=6, joint="curve")
        for mount in mount_plan["mounts"]:
            centerline = [_xy(strict_p0, point, box) for point in mount["centerline"]]
            draw.line(centerline, fill="#ffffff", width=9, joint="curve")
            draw.line(centerline, fill=COLORS["mount"], width=5, joint="curve")
        scale = _scale(strict_p0, box)
        for flower in strict_p0.flowers:
            center = _xy(strict_p0, flower.center, box)
            rx, ry = flower.rx * scale, flower.ry * scale
            draw.ellipse((center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry), fill=(255, 248, 251, 215), outline=COLORS["flower"], width=3)
        achieved = variation["achieved_descriptors"]
        baseline = variation["baseline_descriptors"]
        delta = {key: achieved[key] - baseline[key] for key in baseline}
        deformation = variation.get("skeleton_deformation", {})
        draw.text((left + 16, 72), f"{label}  ρ={float(variation['rho']):.3f}", font=_font(14, bold=True), fill=COLORS[label])
        draw.text(
            (left + 16, 432),
            "Δ振幅 {:+.3f}  Δ弧长 {:+.3f}  Δ曲率集中 {:+.3f}  Δ不对称 {:+.3f}".format(
                delta["amplitude"], delta["arc_length"], delta["curvature_concentration"], delta["asymmetry"]
            ),
            font=_font(12),
            fill="#4e5960",
        )
    image.save(output, "PNG", optimize=True)


def run(output: Path, backbone_seed: int = 4101) -> None:
    if output.exists():
        raise Stage5BPreviewError(f"output already exists: {output}")
    morphology = _read_json(MORPHOLOGY_CONTRACT)
    stage3_contract = _read_json(STAGE3_CONTRACT)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage5b_preview_", dir=str(output.parent)) as directory:
        temporary = Path(directory)
        rows: list[Path] = []
        tasks: list[dict[str, Any]] = []
        for prototype_id in PROTOTYPE_IDS:
            source = STAGE1_ROOT / prototype_id / "strict_p0_v2.json"
            strict = load_materialized_strict_p0_v2(_read_json(source))
            strategy = resolve_prototype_strategy({"prototype_id": prototype_id}, DEFAULT_REGISTRY)
            prototype_dir = temporary / prototype_id
            prototype_dir.mkdir(parents=True)
            variants = []
            levels = []
            for label, rho in LEVELS:
                variant, analysis, variation = generate_and_analyze_variant(
                    strict,
                    backbone_seed,
                    rho,
                    prototype_strategy=strategy,
                )
                mounts = build_flower_mount_plan(
                    analysis,
                    morphology,
                    stage3_contract,
                    seed=backbone_seed,
                    prototype_strategy=strategy,
                )
                level_dir = prototype_dir / label
                level_dir.mkdir()
                _write_json(level_dir / "strict_p0_variant.json", variant.as_dict())
                _write_json(level_dir / "prototype_analysis_variant.json", analysis)
                _write_json(level_dir / "flower_mount_plan.json", mounts)
                variants.append((label, variant, variation, mounts))
                levels.append({"label": label, "rho": rho, "variation": variation, "mount_count": len(mounts["mounts"])})
            row = prototype_dir / "backbone_mount_comparison.png"
            _render_row(prototype_id, variants, row)
            rows.append(row)
            tasks.append({"prototype_id": prototype_id, "levels": levels, "comparison_path": str(row.relative_to(temporary)).replace("\\", "/")})
        images = [Image.open(path).convert("RGB") for path in rows]
        try:
            sheet = Image.new("RGB", (images[0].width, images[0].height * len(images)), COLORS["background"])
            for index, image in enumerate(images):
                sheet.paste(image, (0, index * image.height))
            sheet.save(temporary / "stage5b_backbone_mount_contact_sheet.png", "PNG", optimize=True)
        finally:
            for image in images:
                image.close()
        _write_json(temporary / "manifest.json", {"schema": "dynamic_branch_stage5b_backbone_mount_preview_v1", "stage": "5B", "backbone_seed": backbone_seed, "tasks": tasks, "review_gate": {"status": "VISUAL_REVIEW_PENDING", "numeric_checks_cannot_approve_visual_quality": True}})
        temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--backbone-seed", type=int, default=4101)
    args = parser.parse_args()
    run(args.output.resolve(), args.backbone_seed)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
