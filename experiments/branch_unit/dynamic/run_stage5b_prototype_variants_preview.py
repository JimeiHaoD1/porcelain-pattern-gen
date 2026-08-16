#!/usr/bin/env python3
"""Render strong, coupled stage-5B variants inside each prototype domain."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from global_backbone_wave_v4 import (
    generate_global_wave_variant,
    generate_named_global_wave_variant,
    load_prototype_variant_library,
)
from prototype_analysis import analyze_prototype
from prototype_strategy_v1 import DEFAULT_REGISTRY, resolve_prototype_strategy
from strict_p0_v2 import StrictP0V2, load_materialized_strict_p0_v2


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE1_ROOT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_prototype_variants_v2"
)
PROTOTYPE_IDS = ("proto_sw_1_1", "proto_sw_2_3", "proto_sw_3_2")
VARIANT_IDS = ("baseline", "expanded", "compact", "swept")
COLORS = {
    "baseline": "#202a31",
    "expanded": "#167c80",
    "compact": "#b45b25",
    "swept": "#6b4aa2",
    "flower": "#c42d72",
    "ghost": "#c1c7ca",
    "grid": "#d8dddf",
    "background": "#f5f3ed",
}


class Stage5BPrototypeVariantPreviewError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5BPrototypeVariantPreviewError(f"JSON root must be an object: {path}")
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


def _single_xy(
    strict_p0: StrictP0V2,
    point: Sequence[float],
    box: tuple[int, int, int, int],
) -> tuple[float, float]:
    left, top, right, bottom = box
    y_max = float(strict_p0.frame.local_canvas_bounds[3])
    x_min, x_max = -0.08, 1.08
    y_min, y_upper = -0.03, y_max + 0.03
    scale = min((right - left) / (x_max - x_min), (bottom - top) / (y_upper - y_min))
    offset_x = left + 0.5 * ((right - left) - (x_max - x_min) * scale)
    offset_y = top + 0.5 * ((bottom - top) - (y_upper - y_min) * scale)
    return (
        offset_x + (float(point[0]) - x_min) * scale,
        offset_y + (float(point[1]) - y_min) * scale,
    )


def _fixed_xy(
    point: Sequence[float],
    box: tuple[int, int, int, int],
    y_max: float,
    canvas_width: float,
) -> tuple[float, float]:
    left, top, right, bottom = box
    y_min, y_upper = -0.03, y_max + 0.03
    scale = min((right - left) / canvas_width, (bottom - top) / (y_upper - y_min))
    offset_x = left + 0.5 * ((right - left) - canvas_width * scale)
    offset_y = top + 0.5 * ((bottom - top) - (y_upper - y_min) * scale)
    return offset_x + float(point[0]) * scale, offset_y + (float(point[1]) - y_min) * scale


def _draw_single_repeat(
    draw: ImageDraw.ImageDraw,
    strict_p0: StrictP0V2,
    baseline: StrictP0V2,
    box: tuple[int, int, int, int],
    color: str,
    show_baseline: bool,
) -> None:
    if show_baseline:
        draw.line(
            [_single_xy(strict_p0, row.point, box) for row in baseline.backbone_samples],
            fill=COLORS["ghost"],
            width=3,
            joint="curve",
        )
    path = [_single_xy(strict_p0, row.point, box) for row in strict_p0.backbone_samples]
    draw.line(path, fill="#ffffff", width=10, joint="curve")
    draw.line(path, fill=color, width=5, joint="curve")
    scale = min((box[2] - box[0]) / 1.16, (box[3] - box[1]) / 1.2475)
    for flower in strict_p0.flowers:
        center = _single_xy(strict_p0, flower.center, box)
        rx, ry = flower.rx * scale, flower.ry * scale
        draw.ellipse(
            (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry),
            fill=(255, 248, 251, 215),
            outline=COLORS["flower"],
            width=3,
        )


def _periodic_world_points(
    strict_p0: StrictP0V2,
    wavelength: float,
    canvas_width: float,
) -> list[list[tuple[float, float]]]:
    unique = strict_p0.backbone_samples[:-1]
    repeats: list[list[tuple[float, float]]] = []
    repeat_index = 0
    while repeat_index * wavelength <= canvas_width:
        points = [
            ((repeat_index + row.point[0]) * wavelength, row.point[1])
            for row in unique
        ]
        points.append(((repeat_index + 1.0) * wavelength, unique[0].point[1]))
        clipped = [point for point in points if point[0] <= canvas_width]
        if len(clipped) < len(points) and clipped:
            first_outside = points[len(clipped)]
            previous = clipped[-1]
            dx = first_outside[0] - previous[0]
            if dx > 1e-12:
                fraction = (canvas_width - previous[0]) / dx
                clipped.append(
                    (
                        canvas_width,
                        previous[1] + fraction * (first_outside[1] - previous[1]),
                    )
                )
        if len(clipped) >= 2:
            repeats.append(clipped)
        repeat_index += 1
    return repeats


def _draw_fixed_canvas(
    draw: ImageDraw.ImageDraw,
    strict_p0: StrictP0V2,
    baseline: StrictP0V2,
    wavelength: float,
    box: tuple[int, int, int, int],
    color: str,
    show_baseline: bool,
    canvas_width: float = 3.35,
) -> None:
    y_max = float(strict_p0.frame.local_canvas_bounds[3])
    if show_baseline:
        for repeat in _periodic_world_points(baseline, 1.0, canvas_width):
            draw.line(
                [_fixed_xy(point, box, y_max, canvas_width) for point in repeat],
                fill=COLORS["ghost"],
                width=2,
                joint="curve",
            )
    for repeat in _periodic_world_points(strict_p0, wavelength, canvas_width):
        path = [_fixed_xy(point, box, y_max, canvas_width) for point in repeat]
        draw.line(path, fill="#ffffff", width=8, joint="curve")
        draw.line(path, fill=color, width=4, joint="curve")
    scale = min((box[2] - box[0]) / canvas_width, (box[3] - box[1]) / (y_max + 0.06))
    repeat_index = 0
    while repeat_index * wavelength <= canvas_width:
        for flower in strict_p0.flowers:
            center_world = (
                (repeat_index + flower.center[0]) * wavelength,
                flower.center[1],
            )
            flower_half_width = flower.rx * wavelength
            if not (
                center_world[0] - flower_half_width >= 0.0
                and center_world[0] + flower_half_width <= canvas_width
            ):
                continue
            center = _fixed_xy(center_world, box, y_max, canvas_width)
            rx, ry = flower.rx * wavelength * scale, flower.ry * scale
            draw.ellipse(
                (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry),
                fill=(255, 248, 251, 205),
                outline=COLORS["flower"],
                width=2,
            )
        repeat_index += 1


def _render_sheet(rows: Sequence[Mapping[str, Any]], output: Path) -> None:
    width, header, row_height = 1840, 92, 485
    image = Image.new("RGB", (width, header + row_height * len(rows)), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((28, 17), "5B 原型组合变体：一次联动振幅、波长、节奏与圆钝", font=_font(28, bold=True), fill="#17222b")
    draw.text((28, 56), "上：归一化单元形态（灰线为基准）　下：固定画布中的真实周期频率", font=_font(15), fill="#5f6b72")
    draw.text((1560, 24), "VISUAL_REVIEW_PENDING", font=_font(14), fill="#69747b")
    for row_index, row in enumerate(rows):
        top = header + row_index * row_height
        draw.text((28, top + 10), str(row["prototype_id"]), font=_font(20, bold=True), fill="#17222b")
        for column, variant_id in enumerate(VARIANT_IDS):
            left = 28 + column * 452
            panel = (left, top + 42, left + 432, top + 464)
            draw.rounded_rectangle(panel, radius=13, fill="#ffffff", outline=COLORS["grid"], width=2)
            item = row[variant_id]
            label = str(item["label"])
            color = COLORS[variant_id]
            draw.text((left + 14, top + 52), label, font=_font(17, bold=True), fill=color)
            _draw_single_repeat(
                draw,
                item["strict"],
                row["baseline"]["strict"],
                (left + 12, top + 80, left + 420, top + 258),
                color,
                variant_id != "baseline",
            )
            draw.line((left + 14, top + 274, left + 418, top + 274), fill=COLORS["grid"], width=1)
            _draw_fixed_canvas(
                draw,
                item["strict"],
                row["baseline"]["strict"],
                float(item["metadata"]["physical_repeat_width"]),
                (left + 12, top + 286, left + 420, top + 405),
                color,
                variant_id != "baseline",
            )
            controls = item["metadata"]["applied_controls"]
            detail = (
                f"A {float(controls['amplitude_scale']):.2f}  "
                f"λ {float(controls['wavelength_scale']):.2f}  "
                f"q {float(controls['rhythm_warp']):+.2f}  "
                f"r {float(controls['roundness']):+.2f}"
            )
            draw.text((left + 14, top + 425), detail, font=_font(13), fill="#536067")
            scale = float(item["metadata"]["selected_feasibility_scale"])
            if variant_id != "baseline" and scale < 0.999:
                draw.text((left + 330, top + 54), f"投影 {scale:.2f}", font=_font(11), fill="#8b5a31")
    image.save(output, "PNG", optimize=True)


def run(output: Path, backbone_seed: int) -> None:
    if output.exists():
        raise Stage5BPrototypeVariantPreviewError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    library = load_prototype_variant_library()
    with tempfile.TemporaryDirectory(prefix="stage5b_proto_variants_", dir=str(output.parent)) as directory:
        temporary = Path(directory)
        rows: list[dict[str, Any]] = []
        manifest_rows: list[dict[str, Any]] = []
        for prototype_id in PROTOTYPE_IDS:
            strict = load_materialized_strict_p0_v2(
                _read_json(STAGE1_ROOT / prototype_id / "strict_p0_v2.json")
            )
            strategy = resolve_prototype_strategy({"prototype_id": prototype_id}, DEFAULT_REGISTRY)
            baseline, baseline_metadata = generate_global_wave_variant(
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
            row: dict[str, Any] = {
                "prototype_id": prototype_id,
                "baseline": {"strict": baseline, "metadata": baseline_metadata, "label": "基准原型"},
            }
            row_manifest: dict[str, Any] = {"prototype_id": prototype_id, "variants": []}
            definitions = library["variants_per_prototype"][prototype_id]
            for definition in definitions:
                variant_id = str(definition["variant_id"])
                variant, metadata = generate_named_global_wave_variant(
                    strict,
                    backbone_seed,
                    strategy,
                    variant_id,
                )
                analysis = analyze_prototype(variant)
                variant_dir = temporary / prototype_id / variant_id
                variant_dir.mkdir(parents=True)
                _write_json(variant_dir / "strict_p0_variant.json", variant.as_dict())
                _write_json(variant_dir / "prototype_analysis_variant.json", analysis)
                _write_json(variant_dir / "backbone_wave_metadata.json", metadata)
                row[variant_id] = {
                    "strict": variant,
                    "metadata": metadata,
                    "label": str(definition["label_zh"]),
                }
                row_manifest["variants"].append(
                    {
                        "variant_id": variant_id,
                        "label_zh": str(definition["label_zh"]),
                        "applied_controls": metadata["applied_controls"],
                        "selected_feasibility_scale": metadata["selected_feasibility_scale"],
                    }
                )
            rows.append(row)
            manifest_rows.append(row_manifest)
        sheet = temporary / "stage5b_prototype_combined_variants.png"
        _render_sheet(rows, sheet)
        _write_json(
            temporary / "manifest.json",
            {
                "schema": "dynamic_branch_stage5b_prototype_variants_preview_v1",
                "stage": "5B-2",
                "variant_library": library["library_id"],
                "backbone_seed": backbone_seed,
                "prototype_rows": manifest_rows,
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
