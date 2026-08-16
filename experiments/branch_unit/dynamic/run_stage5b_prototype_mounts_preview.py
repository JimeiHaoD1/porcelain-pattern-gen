#!/usr/bin/env python3
"""Render flower mounting recomputed from each accepted combined prototype variant."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from flower_mounting_v1 import build_flower_mount_plan, validate_flower_mount_plan
from global_backbone_wave_v4 import (
    generate_global_wave_variant,
    generate_named_global_wave_variant,
    load_prototype_variant_library,
)
from prototype_analysis import analyze_prototype
from prototype_strategy_v1 import DEFAULT_REGISTRY, resolve_prototype_strategy
from strict_p0_v2 import StrictP0V2, load_materialized_strict_p0_v2


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
STAGE1_ROOT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_prototype_mounts_v1"
)
MORPHOLOGY_CONTRACT = DYNAMIC_DIR / "MORPHOLOGY_CONTRACT.json"
STAGE3_CONTRACT = DYNAMIC_DIR / "STAGE3_PLAN_CONTRACT.json"
PROTOTYPE_IDS = ("proto_sw_1_1", "proto_sw_2_3", "proto_sw_3_2")
VARIANT_IDS = ("baseline", "expanded", "compact", "swept")
COLORS = {
    "baseline": "#202a31",
    "expanded": "#167c80",
    "compact": "#b45b25",
    "swept": "#6b4aa2",
    "mount": "#3c7f32",
    "flower": "#c42d72",
    "root": "#186a3b",
    "grid": "#d8dddf",
    "background": "#f5f3ed",
}


class Stage5BPrototypeMountPreviewError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5BPrototypeMountPreviewError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _xy(
    strict_p0: StrictP0V2,
    point: Sequence[float],
    box: tuple[int, int, int, int],
) -> tuple[float, float]:
    left, top, right, bottom = box
    height = float(strict_p0.frame.local_canvas_bounds[3])
    x_min, x_max = -0.10, 1.10
    y_min, y_max = -0.04, height + 0.04
    scale = min((right - left) / (x_max - x_min), (bottom - top) / (y_max - y_min))
    offset_x = left + 0.5 * ((right - left) - (x_max - x_min) * scale)
    offset_y = top + 0.5 * ((bottom - top) - (y_max - y_min) * scale)
    return (
        offset_x + (float(point[0]) - x_min) * scale,
        offset_y + (float(point[1]) - y_min) * scale,
    )


def _scale(strict_p0: StrictP0V2, box: tuple[int, int, int, int]) -> float:
    height = float(strict_p0.frame.local_canvas_bounds[3])
    return min((box[2] - box[0]) / 1.20, (box[3] - box[1]) / (height + 0.08))


def _render_sheet(rows: Sequence[Mapping[str, Any]], output: Path) -> None:
    width, header, row_height = 1840, 88, 425
    image = Image.new("RGB", (width, header + row_height * len(rows)), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((28, 16), "5B-3 组合变体后的花朵关系重算", font=_font(28, bold=True), fill="#17222b")
    draw.text((28, 54), "绿色＝承托/远伸挂接枝　粉色＝花位　SW2 不生成承托枝", font=_font(15), fill="#5f6b72")
    draw.text((1560, 22), "VISUAL_REVIEW_PENDING", font=_font(14), fill="#69747b")
    for row_index, row in enumerate(rows):
        top = header + row_index * row_height
        draw.text((28, top + 8), str(row["prototype_id"]), font=_font(20, bold=True), fill="#17222b")
        for column, variant_id in enumerate(VARIANT_IDS):
            left = 28 + column * 452
            panel = (left, top + 38, left + 432, top + 408)
            draw.rounded_rectangle(panel, radius=13, fill="#ffffff", outline=COLORS["grid"], width=2)
            item = row[variant_id]
            color = COLORS[variant_id]
            draw.text((left + 14, top + 48), str(item["label"]), font=_font(17, bold=True), fill=color)
            box = (left + 14, top + 82, left + 418, top + 336)
            strict = item["strict"]
            path = [_xy(strict, sample.point, box) for sample in strict.backbone_samples]
            draw.line(path, fill="#ffffff", width=11, joint="curve")
            draw.line(path, fill=color, width=6, joint="curve")
            for mount in item["mount_plan"]["mounts"]:
                centerline = [_xy(strict, point, box) for point in mount["centerline"]]
                draw.line(centerline, fill="#ffffff", width=10, joint="curve")
                draw.line(centerline, fill=COLORS["mount"], width=5, joint="curve")
                root = _xy(strict, mount["root"], box)
                draw.ellipse((root[0] - 4, root[1] - 4, root[0] + 4, root[1] + 4), fill=COLORS["root"])
            scale = _scale(strict, box)
            for flower in strict.flowers:
                center = _xy(strict, flower.center, box)
                rx, ry = flower.rx * scale, flower.ry * scale
                draw.ellipse(
                    (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry),
                    fill=(255, 248, 251, 220),
                    outline=COLORS["flower"],
                    width=3,
                )
            plan = item["mount_plan"]
            mechanism = str(plan["flower_mount_mechanism"])
            if mechanism == "axis_integration":
                relation = "主干轴线贯穿花朵｜无承托枝"
            elif mechanism == "valley_flank_support":
                relation = f"波谷/谷侧承托｜{len(plan['mounts'])} 根"
            else:
                relation = f"远端切线延伸至花下｜{len(plan['mounts'])} 根"
            draw.text((left + 14, top + 354), relation, font=_font(13), fill="#536067")
            controls = item["metadata"]["applied_controls"]
            draw.text(
                (left + 14, top + 378),
                f"A {float(controls['amplitude_scale']):.2f}  λ {float(controls['wavelength_scale']):.2f}  "
                f"q {float(controls['rhythm_warp']):+.2f}  r {float(controls['roundness']):+.2f}",
                font=_font(12),
                fill="#657178",
            )
    image.save(output, "PNG", optimize=True)


def run(output: Path, backbone_seed: int) -> None:
    if output.exists():
        raise Stage5BPrototypeMountPreviewError(f"output already exists: {output}")
    morphology = _read_json(MORPHOLOGY_CONTRACT)
    stage3_contract = _read_json(STAGE3_CONTRACT)
    library = load_prototype_variant_library()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage5b_proto_mounts_", dir=str(output.parent)) as directory:
        temporary = Path(directory)
        rows: list[dict[str, Any]] = []
        tasks: list[dict[str, Any]] = []
        for prototype_id in PROTOTYPE_IDS:
            strict = load_materialized_strict_p0_v2(
                _read_json(STAGE1_ROOT / prototype_id / "strict_p0_v2.json")
            )
            strategy = resolve_prototype_strategy({"prototype_id": prototype_id}, DEFAULT_REGISTRY)
            definitions = {
                str(row["variant_id"]): row
                for row in library["variants_per_prototype"][prototype_id]
            }
            row: dict[str, Any] = {"prototype_id": prototype_id}
            task: dict[str, Any] = {"prototype_id": prototype_id, "variants": []}
            for variant_id in VARIANT_IDS:
                if variant_id == "baseline":
                    variant, metadata = generate_global_wave_variant(
                        strict,
                        backbone_seed,
                        1.0,
                        strategy,
                        controls_override={
                            "amplitude": 0.0,
                            "wavelength": 0.0,
                            "rhythm": 0.0,
                            "roundness": 0.0,
                        },
                    )
                    label = "基准原型"
                else:
                    variant, metadata = generate_named_global_wave_variant(
                        strict,
                        backbone_seed,
                        strategy,
                        variant_id,
                    )
                    label = str(definitions[variant_id]["label_zh"])
                analysis = analyze_prototype(variant)
                mount_plan = build_flower_mount_plan(
                    analysis,
                    morphology,
                    stage3_contract,
                    seed=backbone_seed,
                    prototype_strategy=strategy,
                )
                validate_flower_mount_plan(
                    mount_plan,
                    analysis,
                    morphology,
                    prototype_strategy=strategy,
                )
                variant_dir = temporary / prototype_id / variant_id
                variant_dir.mkdir(parents=True)
                _write_json(variant_dir / "strict_p0_variant.json", variant.as_dict())
                _write_json(variant_dir / "prototype_analysis_variant.json", analysis)
                _write_json(variant_dir / "flower_mount_plan.json", mount_plan)
                _write_json(variant_dir / "backbone_wave_metadata.json", metadata)
                row[variant_id] = {
                    "strict": variant,
                    "mount_plan": mount_plan,
                    "metadata": metadata,
                    "label": label,
                }
                checks = mount_plan["mechanical_checks"]
                task["variants"].append(
                    {
                        "variant_id": variant_id,
                        "label_zh": label,
                        "mount_count": len(mount_plan["mounts"]),
                        "mechanism": mount_plan["flower_mount_mechanism"],
                        "backbone_proper_crossing_count": checks["backbone_proper_crossing_count"],
                        "periodic_mount_proper_crossing_count": checks["periodic_mount_proper_crossing_count"],
                    }
                )
            rows.append(row)
            tasks.append(task)
        sheet = temporary / "stage5b_prototype_mount_relations.png"
        _render_sheet(rows, sheet)
        _write_json(
            temporary / "manifest.json",
            {
                "schema": "dynamic_branch_stage5b_prototype_mounts_preview_v1",
                "stage": "5B-3",
                "variant_library": library["library_id"],
                "backbone_seed": backbone_seed,
                "tasks": tasks,
                "review_gate": {
                    "status": "VISUAL_REVIEW_PENDING",
                    "numeric_checks_cannot_approve_visual_quality": True,
                },
            },
        )
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
