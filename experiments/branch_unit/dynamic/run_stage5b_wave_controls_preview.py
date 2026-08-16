#!/usr/bin/env python3
"""Render isolated stage-5B global waveform controls for visual review."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from backbone_variation_v1 import generate_and_analyze_variant
from prototype_strategy_v1 import (
    DEFAULT_REGISTRY,
    resolve_prototype_strategy,
)
from strict_p0_v2 import StrictP0V2, load_materialized_strict_p0_v2


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE1_ROOT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_wave_controls_v4"
)
PROTOTYPE_IDS = ("proto_sw_1_1", "proto_sw_2_3", "proto_sw_3_2")
CONTROL_ROWS = (
    ("amplitude", "振幅", "小振幅", "大振幅"),
    ("wavelength", "真实波长／频率", "短波长／高频", "长波长／低频"),
    ("rhythm", "周期内节奏", "长坡偏左", "长坡偏右"),
    ("roundness", "峰谷圆润度", "舒展", "收紧"),
)
COLORS = {
    "baseline": "#1a2730",
    "negative": "#137f82",
    "positive": "#b45b25",
    "flower": "#c42d72",
    "ghost": "#bdc5c9",
    "grid": "#d8dddf",
    "background": "#f7f6f1",
}


class Stage5BWavePreviewError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5BWavePreviewError(f"JSON root must be an object: {path}")
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
    shift_x: float = 0.0,
) -> tuple[float, float]:
    left, top, right, bottom = box
    y_max = float(strict_p0.frame.local_canvas_bounds[3])
    x_min, x_max = -0.08, 1.08
    y_min, y_upper = -0.03, y_max + 0.03
    scale = min((right - left) / (x_max - x_min), (bottom - top) / (y_upper - y_min))
    offset_x = left + 0.5 * ((right - left) - (x_max - x_min) * scale)
    offset_y = top + 0.5 * ((bottom - top) - (y_upper - y_min) * scale)
    return (
        offset_x + (float(point[0]) + shift_x - x_min) * scale,
        offset_y + (float(point[1]) - y_min) * scale,
    )


def _fixed_canvas_xy(
    point: Sequence[float],
    box: tuple[int, int, int, int],
    y_max: float,
    canvas_width: float,
) -> tuple[float, float]:
    left, top, right, bottom = box
    x_min, x_max = 0.0, canvas_width
    y_min, y_upper = -0.03, y_max + 0.03
    scale = min((right - left) / (x_max - x_min), (bottom - top) / (y_upper - y_min))
    offset_x = left + 0.5 * ((right - left) - (x_max - x_min) * scale)
    offset_y = top + 0.5 * ((bottom - top) - (y_upper - y_min) * scale)
    return (
        offset_x + (float(point[0]) - x_min) * scale,
        offset_y + (float(point[1]) - y_min) * scale,
    )


def _draw_single_repeat(
    draw: ImageDraw.ImageDraw,
    strict_p0: StrictP0V2,
    baseline: StrictP0V2,
    box: tuple[int, int, int, int],
    color: str,
    *,
    show_baseline: bool,
) -> None:
    if show_baseline:
        baseline_path = [_single_xy(strict_p0, row.point, box) for row in baseline.backbone_samples]
        draw.line(baseline_path, fill=COLORS["ghost"], width=3, joint="curve")
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


def _periodic_world_points(strict_p0: StrictP0V2, wavelength: float, canvas_width: float) -> list[list[tuple[float, float]]]:
    unique = strict_p0.backbone_samples[:-1]
    repeats: list[list[tuple[float, float]]] = []
    repeat_index = -1
    while repeat_index * wavelength <= canvas_width + wavelength:
        points = [
            ((repeat_index + row.point[0]) * wavelength, row.point[1])
            for row in unique
        ]
        points.append(((repeat_index + 1.0) * wavelength, unique[0].point[1]))
        repeats.append(points)
        repeat_index += 1
    return repeats


def _draw_fixed_canvas(
    draw: ImageDraw.ImageDraw,
    strict_p0: StrictP0V2,
    baseline: StrictP0V2,
    wavelength: float,
    box: tuple[int, int, int, int],
    color: str,
    *,
    show_baseline: bool,
    canvas_width: float = 3.35,
) -> None:
    y_max = float(strict_p0.frame.local_canvas_bounds[3])
    if show_baseline:
        for repeat in _periodic_world_points(baseline, 1.0, canvas_width):
            draw.line(
                [_fixed_canvas_xy(point, box, y_max, canvas_width) for point in repeat],
                fill=COLORS["ghost"],
                width=2,
                joint="curve",
            )
    for repeat in _periodic_world_points(strict_p0, wavelength, canvas_width):
        path = [_fixed_canvas_xy(point, box, y_max, canvas_width) for point in repeat]
        draw.line(path, fill="#ffffff", width=8, joint="curve")
        draw.line(path, fill=color, width=4, joint="curve")
    scale = min((box[2] - box[0]) / canvas_width, (box[3] - box[1]) / (y_max + 0.06))
    repeat_index = -1
    while repeat_index * wavelength <= canvas_width + wavelength:
        for flower in strict_p0.flowers:
            center_world = (
                (repeat_index + flower.center[0]) * wavelength,
                flower.center[1],
            )
            center = _fixed_canvas_xy(center_world, box, y_max, canvas_width)
            rx, ry = flower.rx * scale, flower.ry * scale
            draw.ellipse(
                (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry),
                fill=(255, 248, 251, 205),
                outline=COLORS["flower"],
                width=2,
            )
        repeat_index += 1


def _render_control_sheet(
    control: str,
    title: str,
    negative_label: str,
    positive_label: str,
    rows: Sequence[Mapping[str, Any]],
    output: Path,
) -> None:
    width, row_height = 1580, 390
    image = Image.new("RGB", (width, 70 + row_height * len(rows)), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((28, 18), f"5B 单变量：{title}", font=_font(28, bold=True), fill="#17222b")
    draw.text((1230, 22), "VISUAL_REVIEW_PENDING", font=_font(14), fill="#69747b")
    labels = (("baseline", "基线"), ("negative", negative_label), ("positive", positive_label))
    for row_index, row in enumerate(rows):
        top = 70 + row_index * row_height
        draw.text((28, top + 12), str(row["prototype_id"]), font=_font(21, bold=True), fill="#17222b")
        for column, (variant_name, label) in enumerate(labels):
            left = 28 + column * 510
            panel = (left, top + 44, left + 490, top + 365)
            draw.rounded_rectangle(panel, radius=13, fill="#ffffff", outline=COLORS["grid"], width=2)
            draw.text((left + 14, top + 53), label, font=_font(15, bold=True), fill=COLORS[variant_name])
            strict_p0 = row[variant_name]["strict"]
            metadata = row[variant_name]["metadata"]
            plot = (left + 12, top + 82, left + 478, top + 330)
            if control == "wavelength":
                wavelength = float(metadata["physical_repeat_width"])
                _draw_fixed_canvas(
                    draw,
                    strict_p0,
                    row["baseline"]["strict"],
                    wavelength,
                    plot,
                    COLORS[variant_name],
                    show_baseline=variant_name != "baseline",
                )
                detail = f"实际周期宽度 λ={wavelength:.3f}"
            else:
                _draw_single_repeat(
                    draw,
                    strict_p0,
                    row["baseline"]["strict"],
                    plot,
                    COLORS[variant_name],
                    show_baseline=variant_name != "baseline",
                )
                controls = metadata["applied_controls"]
                detail = {
                    "amplitude": f"振幅倍率 A={float(controls['amplitude_scale']):.3f}",
                    "rhythm": f"节奏偏置 q={float(controls['rhythm_warp']):+.3f}",
                    "roundness": f"圆润度 r={float(controls['roundness']):+.3f}",
                }[control]
            draw.text((left + 14, top + 335), detail, font=_font(13), fill="#536067")
    image.save(output, "PNG", optimize=True)


def run(output: Path, backbone_seed: int) -> None:
    if output.exists():
        raise Stage5BWavePreviewError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage5b_wave_v4_", dir=str(output.parent)) as directory:
        temporary = Path(directory)
        manifests: list[dict[str, Any]] = []
        for control, title, negative_label, positive_label in CONTROL_ROWS:
            control_rows: list[dict[str, Any]] = []
            control_dir = temporary / control
            control_dir.mkdir()
            for prototype_id in PROTOTYPE_IDS:
                strict = load_materialized_strict_p0_v2(
                    _read_json(STAGE1_ROOT / prototype_id / "strict_p0_v2.json")
                )
                strategy = resolve_prototype_strategy(
                    {"prototype_id": prototype_id}, DEFAULT_REGISTRY
                )
                row: dict[str, Any] = {"prototype_id": prototype_id}
                variants = (
                    ("baseline", 0.0),
                    ("negative", -1.0),
                    ("positive", 1.0),
                )
                for variant_name, value in variants:
                    overrides = {
                        "amplitude": 0.0,
                        "wavelength": 0.0,
                        "rhythm": 0.0,
                        "roundness": 0.0,
                    }
                    overrides[control] = value
                    variant, analysis, metadata = generate_and_analyze_variant(
                        strict,
                        backbone_seed,
                        1.0,
                        prototype_strategy=strategy,
                        shape_targets=overrides,
                    )
                    variant_dir = control_dir / prototype_id / variant_name
                    variant_dir.mkdir(parents=True)
                    _write_json(variant_dir / "strict_p0_variant.json", variant.as_dict())
                    _write_json(variant_dir / "prototype_analysis_variant.json", analysis)
                    _write_json(variant_dir / "backbone_wave_metadata.json", metadata)
                    row[variant_name] = {"strict": variant, "metadata": metadata}
                control_rows.append(row)
            sheet = temporary / f"stage5b_{control}_single_variable.png"
            _render_control_sheet(
                control,
                title,
                negative_label,
                positive_label,
                control_rows,
                sheet,
            )
            manifests.append(
                {
                    "control": control,
                    "sheet": sheet.name,
                    "prototype_ids": list(PROTOTYPE_IDS),
                }
            )
        _write_json(
            temporary / "manifest.json",
            {
                "schema": "dynamic_branch_stage5b_wave_controls_preview_v4",
                "stage": "5B-2",
                "backbone_seed": backbone_seed,
                "controls": manifests,
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
