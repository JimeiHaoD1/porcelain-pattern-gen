#!/usr/bin/env python3
"""Generate the D0A five-prototype backbone/flower variation review sheet."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from backbone_variation_v1 import generate_and_analyze_variant, validate_seed
from prototype_analysis import analyze_prototype
from strict_p0_v2 import StrictP0V2, load_materialized_strict_p0_v2


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE1_ROOT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_backbone_variation_d0a_v2"
)
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
LEVELS = (
    ("baseline", 0.0),
    ("low", 0.35),
    ("medium", 0.675),
    ("high", 1.0),
)
COLORS = {
    "baseline": "#17222b",
    "low": "#188977",
    "medium": "#d27b24",
    "high": "#b43b3b",
    "flower": "#b22f71",
    "ghost": "#bac1c5",
    "grid": "#d8dddf",
    "muted": "#657079",
    "background": "#f7f6f1",
}


class BackbonePreviewError(RuntimeError):
    """The D0A preview package cannot be produced."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BackbonePreviewError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _panel_xy(
    strict_p0: StrictP0V2,
    point: Sequence[float],
    box: tuple[int, int, int, int],
    shift_x: float = 0.0,
) -> tuple[float, float]:
    left, top, right, bottom = box
    local_height = float(strict_p0.frame.local_canvas_bounds[3])
    x_min, x_max = -0.08, 1.08
    y_min, y_max = -0.03, local_height + 0.03
    scale = min((right - left) / (x_max - x_min), (bottom - top) / (y_max - y_min))
    used_width = (x_max - x_min) * scale
    used_height = (y_max - y_min) * scale
    offset_x = left + 0.5 * ((right - left) - used_width)
    offset_y = top + 0.5 * ((bottom - top) - used_height)
    return (
        offset_x + (float(point[0]) + shift_x - x_min) * scale,
        offset_y + (float(point[1]) - y_min) * scale,
    )


def _panel_scale(strict_p0: StrictP0V2, box: tuple[int, int, int, int]) -> float:
    left, top, right, bottom = box
    local_height = float(strict_p0.frame.local_canvas_bounds[3])
    return min((right - left) / 1.16, (bottom - top) / (local_height + 0.06))


def _render_prototype_row(
    prototype_id: str,
    variants: Sequence[tuple[str, StrictP0V2, Mapping[str, Any]]],
    output: Path,
) -> None:
    width, height = 1480, 410
    image = Image.new("RGB", (width, height), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((28, 18), prototype_id, font=_font(24, bold=True), fill="#17222b")
    draw.text(
        (width - 292, 22),
        "D0A · VISUAL_REVIEW_PENDING",
        font=_font(14),
        fill=COLORS["muted"],
    )
    panel_width = 350
    for index, (label, strict_p0, metadata) in enumerate(variants):
        left = 28 + index * 360
        box = (left + 14, 82, left + panel_width - 14, 365)
        draw.rounded_rectangle(
            (left, 62, left + panel_width, 390),
            radius=14,
            fill="#ffffff",
            outline=COLORS["grid"],
            width=2,
        )
        for boundary in (0.0, 1.0):
            start = _panel_xy(strict_p0, (boundary, 0.0), box)
            end = _panel_xy(
                strict_p0,
                (boundary, strict_p0.frame.local_canvas_bounds[3]),
                box,
            )
            draw.line([start, end], fill=COLORS["grid"], width=1)
        points = [sample.point for sample in strict_p0.backbone_samples]
        for shift in (-1.0, 1.0):
            ghost = [_panel_xy(strict_p0, point, box, shift) for point in points]
            draw.line(ghost, fill=COLORS["ghost"], width=3, joint="curve")
        path = [_panel_xy(strict_p0, point, box) for point in points]
        draw.line(path, fill="#ffffff", width=10, joint="curve")
        draw.line(path, fill=COLORS[label], width=5, joint="curve")
        scale = _panel_scale(strict_p0, box)
        for flower in strict_p0.flowers:
            center = _panel_xy(strict_p0, flower.center, box)
            rx = flower.rx * scale
            ry = flower.ry * scale
            draw.ellipse(
                (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry),
                fill=(255, 248, 251, 210),
                outline=COLORS["flower"],
                width=3,
            )
        budget_pixels = (
            float(metadata["applied_displacement_budget"])
            * strict_p0.frame.repeat_width
        )
        draw.text(
            (left + 16, 72),
            f"{label}  ρ={float(metadata['rho']):.3f}  max={budget_pixels:.2f}px",
            font=_font(14, bold=True),
            fill=COLORS[label],
        )
    image.save(output, "PNG", optimize=True)


def _render_contact_sheet(rows: Sequence[Path], output: Path) -> None:
    images = [Image.open(path).convert("RGB") for path in rows]
    try:
        sheet = Image.new(
            "RGB",
            (images[0].width, images[0].height * len(images)),
            COLORS["background"],
        )
        for index, image in enumerate(images):
            sheet.paste(image, (0, index * image.height))
        sheet.save(output, "PNG", optimize=True)
    finally:
        for image in images:
            image.close()


def run(output: Path, backbone_seed: int = 4101) -> None:
    seed = validate_seed(backbone_seed, "backbone_seed")
    if output.exists():
        raise BackbonePreviewError(f"D0A output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="backbone_d0a_", dir=str(output.parent)) as directory:
        temporary = Path(directory)
        task_rows: list[dict[str, Any]] = []
        row_paths: list[Path] = []
        for prototype_id in PROTOTYPE_IDS:
            source = STAGE1_ROOT / prototype_id / "strict_p0_v2.json"
            if not source.is_file():
                raise BackbonePreviewError(f"missing StrictP0: {source}")
            strict = load_materialized_strict_p0_v2(_read_json(source))
            prototype_dir = temporary / prototype_id
            prototype_dir.mkdir(parents=True)
            variants: list[tuple[str, StrictP0V2, Mapping[str, Any]]] = []
            level_rows: list[dict[str, Any]] = []
            for label, rho in LEVELS:
                if rho == 0.0:
                    variant = strict
                    analysis = analyze_prototype(strict)
                    _, _, metadata = generate_and_analyze_variant(strict, seed, 0.0)
                else:
                    variant, analysis, metadata = generate_and_analyze_variant(
                        strict,
                        seed,
                        rho,
                    )
                level_dir = prototype_dir / label
                level_dir.mkdir()
                strict_path = level_dir / "strict_p0_variant.json"
                analysis_path = level_dir / "prototype_analysis_variant.json"
                _write_json(strict_path, variant.as_dict())
                _write_json(analysis_path, analysis)
                variants.append((label, variant, metadata))
                level_rows.append(
                    {
                        "label": label,
                        "rho": rho,
                        "backbone_variation": metadata,
                        "strict_p0_variant_path": str(
                            strict_path.relative_to(temporary)
                        ).replace("\\", "/"),
                        "prototype_analysis_variant_path": str(
                            analysis_path.relative_to(temporary)
                        ).replace("\\", "/"),
                        "repeat_seam_position_gap": analysis["repeat_seam"][
                            "position_gap"
                        ],
                    }
                )
            row_path = prototype_dir / "backbone_variation_comparison.png"
            _render_prototype_row(prototype_id, variants, row_path)
            row_paths.append(row_path)
            task_rows.append(
                {
                    "prototype_id": prototype_id,
                    "backbone_seed": seed,
                    "levels": level_rows,
                    "comparison_path": str(row_path.relative_to(temporary)).replace(
                        "\\", "/"
                    ),
                    "visual_status": "VISUAL_REVIEW_PENDING",
                }
            )
        contact_sheet = temporary / "backbone_variation_contact_sheet.png"
        _render_contact_sheet(row_paths, contact_sheet)
        _write_json(
            temporary / "manifest.json",
            {
                "schema": "dynamic_branch_backbone_variation_preview_v2",
                "stage": "D0A",
                "backbone_seed": seed,
                "prototype_ids": list(PROTOTYPE_IDS),
                "levels": [label for label, _ in LEVELS],
                "tasks": task_rows,
                "contact_sheet": contact_sheet.name,
                "review_gate": {
                    "status": "VISUAL_REVIEW_PENDING",
                    "criteria": [
                        "same_morphology_family",
                        "natural_flower_backbone_relation",
                        "periodic_seam_continuity",
                    ],
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
