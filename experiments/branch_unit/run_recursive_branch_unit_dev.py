#!/usr/bin/env python3
"""Render and retain the first bounded recursive BranchUnit experiment."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont

import recursive_branch_unit as core


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "run57_reproduction"
    / "01_skeleton_analysis"
    / "proto_sw_1_3"
    / "skeleton_profile.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "runs" / "_scratch_recursive_branch_unit_v1"
SCALE = 4
TOP_MARGIN = 44
PLOT_BACKGROUND = (250, 248, 242)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _xy(point: tuple[float, float], x0: float) -> tuple[float, float]:
    return (point[0] - x0) * SCALE, point[1] * SCALE + TOP_MARGIN


def _unit_for_curve(result: core.RecursiveResult, curve_id: str) -> str:
    if curve_id in core.UNIT_ORDER:
        return curve_id
    return result.plan.metadata_by_id[curve_id].unit_id


def _draw_scene(
    p0: core.StrictP0,
    result: core.RecursiveResult,
    validation: dict[str, object],
    *,
    debug: bool,
    focus_unit: str | None = None,
) -> Image.Image:
    x0, x1 = p0.repeat_x_range
    width = round((x1 - x0) * SCALE)
    height = round(p0.canvas_height * SCALE) + TOP_MARGIN
    image = Image.new("RGB", (width, height), PLOT_BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    envelope_top = float(result.plan.style_latents["envelope_top_y"])
    envelope_bottom = float(result.plan.style_latents["envelope_bottom_y"])
    plot_top = TOP_MARGIN
    plot_bottom = TOP_MARGIN + round(p0.canvas_height * SCALE)
    draw.rectangle((0, plot_top, width - 1, plot_bottom - 1), outline=(190, 190, 184), width=2)

    if debug:
        for side, y in (("top", envelope_top), ("bottom", envelope_bottom)):
            y_pixel = round(y * SCALE) + TOP_MARGIN
            draw.line(((0, y_pixel), (width, y_pixel)), fill=(194, 70, 70), width=2)
            draw.text((5, y_pixel + (3 if side == "top" else -13)), side, fill=(150, 50, 50), font=font)

    backbone = [_xy(point, x0) for point in p0.backbone_points]
    draw.line(backbone, fill=(143, 106, 73), width=20, joint="curve")
    for flower in p0.flowers:
        box = (
            (flower.center[0] - flower.rx - x0) * SCALE,
            (flower.center[1] - flower.ry) * SCALE + TOP_MARGIN,
            (flower.center[0] + flower.rx - x0) * SCALE,
            (flower.center[1] + flower.ry) * SCALE + TOP_MARGIN,
        )
        if debug:
            draw.ellipse(box, fill=(244, 241, 255), outline=(86, 78, 215), width=5)
        else:
            draw.ellipse(box, fill=(247, 243, 235), outline=(175, 151, 127), width=4)

    level_colors = {1: (28, 31, 35), 2: (18, 125, 73), 3: (221, 120, 8)}
    level_widths = {1: 12, 2: 8, 3: 6}
    for node in sorted(result.curves, key=lambda item: item.level):
        curve_unit = _unit_for_curve(result, node.curve.curve_id)
        focused = focus_unit is None or curve_unit == focus_unit
        if focus_unit is not None and not focused:
            color = (215, 213, 205)
            width_px = max(3, level_widths[node.level] // 2)
        else:
            color = level_colors[node.level] if debug or focus_unit is not None else (28, 31, 35)
            width_px = level_widths[node.level]
        points = [_xy(point, x0) for point in node.curve.points(192)]
        draw.line(points, fill=color, width=width_px, joint="curve")
        if debug and focused:
            root = points[0]
            radius = 9 if node.level == 1 else 7
            draw.ellipse(
                (root[0] - radius, root[1] - radius, root[0] + radius, root[1] + radius),
                fill=(215, 45, 45) if node.level > 1 else color,
            )
            meta = result.plan.metadata_by_id.get(node.curve.curve_id)
            if meta is not None and meta.is_edge_heir:
                tip = points[-1]
                draw.ellipse(
                    (tip[0] - 9, tip[1] - 9, tip[0] + 9, tip[1] + 9),
                    fill=(215, 45, 45),
                )

    counts = result.as_dict()["topology"]["levels"]
    status = "PASS" if validation["valid"] else "FAIL"
    title = (
        f"seed {result.plan.seed} | P{counts['1']} S{counts['2']} T{counts['3']} | "
        f"recursive structure {status}"
    )
    draw.text((7, 8), title, fill=(20, 22, 24), font=font)
    if debug:
        draw.text(
            (7, 25),
            "black=P1 green=P2 orange=P3 red=root/edge-heir",
            fill=(20, 22, 24),
            font=font,
        )
    return image


def _contact_sheet(images: Iterable[Image.Image], *, columns: int | None = None) -> Image.Image:
    rows = list(images)
    if not rows:
        raise ValueError("contact sheet requires at least one image")
    columns = columns or len(rows)
    cell_width = max(image.width for image in rows)
    cell_height = max(image.height for image in rows)
    row_count = (len(rows) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, row_count * cell_height), (238, 238, 234))
    for index, image in enumerate(rows):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        sheet.paste(image, (x, y))
    return sheet


def _unit_sheet(
    p0: core.StrictP0,
    result: core.RecursiveResult,
    validation: dict[str, object],
) -> Image.Image:
    full = _draw_scene(p0, result, validation, debug=True)
    x0, _ = p0.repeat_x_range
    tiles: list[Image.Image] = []
    font = ImageFont.load_default()
    for unit_id in core.UNIT_ORDER:
        focused = _draw_scene(p0, result, validation, debug=True, focus_unit=unit_id)
        nodes = [node for node in result.curves if _unit_for_curve(result, node.curve.curve_id) == unit_id]
        xs = [point[0] for node in nodes for point in node.curve.points(96)]
        ys = [point[1] for node in nodes for point in node.curve.points(96)]
        left = max(0, round((min(xs) - x0 - 24.0) * SCALE))
        right = min(focused.width, round((max(xs) - x0 + 24.0) * SCALE))
        top = max(TOP_MARGIN, round((min(ys) - 24.0) * SCALE) + TOP_MARGIN)
        bottom = min(focused.height, round((max(ys) + 24.0) * SCALE) + TOP_MARGIN)
        crop = focused.crop((left, top, max(left + 1, right), max(top + 1, bottom)))
        crop.thumbnail((310, 275), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (320, 310), PLOT_BACKGROUND)
        tile.paste(crop, ((tile.width - crop.width) // 2, 27 + (275 - crop.height) // 2))
        draw = ImageDraw.Draw(tile)
        descendant_count = sum(node.level > 1 for node in nodes)
        tertiary_count = sum(node.level == 3 for node in nodes)
        draw.text(
            (6, 7),
            f"{unit_id} | descendants={descendant_count} T={tertiary_count}",
            fill=(20, 22, 24),
            font=font,
        )
        tiles.append(tile)
    del full
    return _contact_sheet(tiles, columns=4)


def _repeat_2x(image: Image.Image) -> Image.Image:
    plot = image.crop((0, TOP_MARGIN, image.width, image.height))
    tiled = Image.new("RGB", (plot.width * 2, plot.height), PLOT_BACKGROUND)
    tiled.paste(plot, (0, 0))
    tiled.paste(plot, (plot.width, 0))
    return tiled


def run(profile_path: Path, output_dir: Path, seeds: Sequence[int] = core.DEV_SEEDS) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    p0 = core.strip_profile(profile)
    results: list[core.RecursiveResult] = []
    validations: list[dict[str, object]] = []
    clean_images: list[Image.Image] = []
    debug_images: list[Image.Image] = []
    unit_images: list[Image.Image] = []
    repeat_images: list[Image.Image] = []

    for seed in seeds:
        result = core.build_recursive(p0, int(seed))
        validation = core.validate_result(p0, result)
        results.append(result)
        validations.append(validation)
        _write_json(
            output_dir / f"record_{seed}.json",
            {"result": result.as_dict(), "validation": validation},
        )
        clean = _draw_scene(p0, result, validation, debug=False)
        debug = _draw_scene(p0, result, validation, debug=True)
        units = _unit_sheet(p0, result, validation)
        repeat = _repeat_2x(clean)
        clean.save(output_dir / f"seed_{seed}.png")
        debug.save(output_dir / f"seed_{seed}_debug.png")
        units.save(output_dir / f"seed_{seed}_units.png")
        repeat.save(output_dir / f"seed_{seed}_repeat_2x.png")
        clean_images.append(clean)
        debug_images.append(debug)
        unit_images.append(units)
        repeat_images.append(repeat)

    _contact_sheet(clean_images).save(output_dir / "contact_sheet.png")
    _contact_sheet(debug_images).save(output_dir / "contact_sheet_debug.png")
    _contact_sheet(unit_images, columns=1).save(output_dir / "contact_sheet_units.png")
    _contact_sheet(repeat_images, columns=1).save(output_dir / "contact_sheet_repeat_2x.png")

    variation = core.seed_variation_proof(p0, seeds)
    _write_json(output_dir / "seed_variation.json", variation)
    topology_by_seed = {
        str(result.plan.seed): result.as_dict()["topology"] for result in results
    }
    manifest = {
        "schema": "recursive_branch_unit_dev_manifest_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "profile": str(profile_path),
        "output_dir": str(output_dir),
        "seeds": [int(seed) for seed in seeds],
        "plan_id": core.PLAN_ID,
        "geometry_kernel_id": core.GEOMETRY_KERNEL_ID,
        "topology_by_seed": topology_by_seed,
        "structural_valid_by_seed": {
            str(result.plan.seed): validation["valid"]
            for result, validation in zip(results, validations)
        },
        "issues_by_seed": {
            str(result.plan.seed): validation["issues"]
            for result, validation in zip(results, validations)
        },
        "seed_variation_pass": variation["passes"],
        "generation_policy": {
            "candidate_count": 1,
            "retry_count": 0,
            "resample_count": 0,
            "repair_count": 0,
            "validation_feedback_consumed": False,
        },
        "visual_status": "pending_manual_review",
        "claim_boundary": (
            "This artifact tests bounded recursive planning only. Structural validity and "
            "seed variation do not imply visual success."
        ),
        "artifacts": [
            "contact_sheet.png",
            "contact_sheet_debug.png",
            "contact_sheet_units.png",
            "contact_sheet_repeat_2x.png",
            "seed_variation.json",
        ],
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(core.DEV_SEEDS))
    args = parser.parse_args()
    manifest = run(args.profile, args.output, tuple(args.seeds))
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

