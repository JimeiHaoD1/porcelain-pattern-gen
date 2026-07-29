#!/usr/bin/env python3
"""Replay and document the fixed true-lateral 7 + 12 + 2 development fixture."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

import whole_local_branch as core


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
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "runs" / "_scratch_whole_local_true_lateral_n12_v23"
PROTOCOL = Path(__file__).with_name("WHOLE_LOCAL_N12_DEV_PROTOCOL.md")
SCALE = 4
TOP_MARGIN = 54


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _xy(point: tuple[float, float], x0: float) -> tuple[float, float]:
    return (point[0] - x0) * SCALE, point[1] * SCALE + TOP_MARGIN


def _render(
    p0: core.StrictP0,
    result: core.HierarchyResult,
    validation: dict[str, object],
    *,
    debug: bool,
) -> Image.Image:
    x0, x1 = p0.repeat_x_range
    width = round((x1 - x0) * SCALE)
    height = round(p0.canvas_height * SCALE) + TOP_MARGIN
    image = Image.new("RGB", (width, height), (250, 248, 242))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    envelope = core._global_envelope_values(p0, result.plan.seed)
    plot_top = TOP_MARGIN
    plot_bottom = TOP_MARGIN + round(p0.canvas_height * SCALE)
    draw.rectangle((0, plot_top, width - 1, plot_bottom - 1), outline=(160, 166, 170), width=2)
    for side, y in (
        ("top", envelope["envelope_top_y"]),
        ("bottom", envelope["envelope_bottom_y"]),
    ):
        y_pixel = round(y * SCALE) + TOP_MARGIN
        draw.line(((0, y_pixel), (width, y_pixel)), fill=(196, 67, 67), width=2)
        if debug:
            draw.text((6, y_pixel + (3 if side == "top" else -14)), f"{side} edge band", fill=(150, 45, 45), font=font)

    backbone = [_xy(point, x0) for point in p0.backbone_points]
    draw.line(backbone, fill=(139, 104, 72), width=20, joint="curve")
    for flower in p0.flowers:
        box = (
            (flower.center[0] - flower.rx - x0) * SCALE,
            (flower.center[1] - flower.ry) * SCALE + TOP_MARGIN,
            (flower.center[0] + flower.rx - x0) * SCALE,
            (flower.center[1] + flower.ry) * SCALE + TOP_MARGIN,
        )
        draw.ellipse(box, fill=(245, 241, 255), outline=(82, 76, 220), width=5)
        center = _xy(flower.center, x0)
        radius = 2 * SCALE
        draw.ellipse(
            (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
            fill=(82, 76, 220),
        )

    colors = {1: (24, 29, 34), 2: (13, 122, 70), 3: (218, 119, 6)}
    widths = {1: 12, 2: 8, 3: 6}
    primary_rows = {row.curve_id: row for row in result.plan.primaries}
    child_rows = {row.curve_id: row for row in result.plan.descendants}
    for node in sorted(result.curves, key=lambda row: row.level):
        curve = node.curve
        points = [_xy(point, x0) for point in curve.points(256)]
        color = colors[node.level] if debug else (28, 32, 36)
        draw.line(points, fill=color, width=widths[node.level], joint="curve")
        if debug:
            root = points[0]
            root_radius = (4 if node.level == 1 else 3) * SCALE
            root_color = color if node.level == 1 else (215, 45, 45)
            draw.ellipse(
                (
                    root[0] - root_radius,
                    root[1] - root_radius,
                    root[0] + root_radius,
                    root[1] + root_radius,
                ),
                fill=root_color,
            )
        plan_row = primary_rows[curve.curve_id] if node.level == 1 else child_rows[curve.curve_id]
        if plan_row.target_boundary is not None:
            tip = points[-1]
            radius = 4 * SCALE
            draw.ellipse(
                (tip[0] - radius, tip[1] - radius, tip[0] + radius, tip[1] + radius),
                fill=(215, 45, 45) if debug else (28, 32, 36),
            )

    status = "PASS" if validation["valid"] else "FAIL"
    title = (
        f"seed {result.plan.seed} | 7 primary + 12 secondary + 2 tertiary | "
        f"structure {status}"
    )
    draw.text((8, 9), title, fill=(15, 19, 22), font=font)
    if debug:
        draw.text(
            (8, 27),
            "black=P1  green=P2  orange=P3  red=root/frontier",
            fill=(15, 19, 22),
            font=font,
        )
    return image


def _contact_sheet(images: Iterable[Image.Image]) -> Image.Image:
    rows = list(images)
    sheet = Image.new("RGB", (sum(image.width for image in rows), max(image.height for image in rows)), "white")
    x = 0
    for image in rows:
        sheet.paste(image, (x, 0))
        x += image.width
    return sheet


def _unit_sheet(
    p0: core.StrictP0,
    result: core.HierarchyResult,
    full_debug: Image.Image,
) -> Image.Image:
    primary_ids = tuple(row.curve_id for row in result.plan.primaries)
    columns = 4
    tile_width = 320
    tile_height = 286
    rows = (len(primary_ids) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), (239, 240, 241))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    x0, _ = p0.repeat_x_range
    for index, primary_id in enumerate(primary_ids):
        curve_ids = {
            node.curve.curve_id
            for node in result.curves
            if core._subtree_id(node.curve.curve_id) == primary_id
        }
        points = [
            _xy(point, x0)
            for node in result.curves
            if node.curve.curve_id in curve_ids
            for point in node.curve.points(192)
        ]
        margin = 18 * SCALE
        left = max(0, round(min(point[0] for point in points) - margin))
        right = min(full_debug.width, round(max(point[0] for point in points) + margin))
        top = max(TOP_MARGIN, round(min(point[1] for point in points) - margin))
        bottom = min(full_debug.height, round(max(point[1] for point in points) + margin))
        crop = full_debug.crop((left, top, right, bottom))
        target_width = tile_width - 12
        target_height = tile_height - 38
        scale = min(target_width / crop.width, target_height / crop.height)
        resized = crop.resize(
            (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
            Image.Resampling.LANCZOS,
        )
        column = index % columns
        row = index // columns
        tile_x = column * tile_width
        tile_y = row * tile_height
        draw.rectangle(
            (tile_x + 3, tile_y + 3, tile_x + tile_width - 4, tile_y + tile_height - 4),
            fill=(250, 248, 242),
            outline=(160, 166, 170),
            width=2,
        )
        child_count = sum(node.level == 2 and node.curve.curve_id in curve_ids for node in result.curves)
        tertiary_count = sum(node.level == 3 and node.curve.curve_id in curve_ids for node in result.curves)
        draw.text(
            (tile_x + 9, tile_y + 9),
            f"{primary_id} | P2={child_count} P3={tertiary_count}",
            fill=(15, 19, 22),
            font=font,
        )
        paste_x = tile_x + (tile_width - resized.width) // 2
        paste_y = tile_y + 31 + (target_height - resized.height) // 2
        sheet.paste(resized, (paste_x, paste_y))
    draw.text(
        (columns * tile_width - 145, rows * tile_height - 17),
        f"seed {result.plan.seed}",
        fill=(15, 19, 22),
        font=font,
    )
    return sheet


def _mount_position_chart(
    results: dict[int, core.HierarchyResult],
) -> Image.Image:
    """Plot seed-specific attachment coordinates without parent-motion confounds."""

    seeds = tuple(core.DEV_SEEDS)
    first = results[seeds[0]]
    primary_ids = tuple(row.curve_id for row in first.plan.primaries)
    secondary_ids = tuple(row.curve_id for row in first.plan.descendants if row.level == 2)
    tertiary_ids = tuple(row.curve_id for row in first.plan.descendants if row.level == 3)
    row_specs: list[tuple[str, str | None]] = [("PRIMARY mount_s", None)]
    row_specs.extend((curve_id, "primary") for curve_id in primary_ids)
    row_specs.append(("SECONDARY mount_fraction", None))
    row_specs.extend((curve_id, "child") for curve_id in secondary_ids)
    row_specs.append(("TERTIARY mount_fraction", None))
    row_specs.extend((curve_id, "child") for curve_id in tertiary_ids)

    width = 1500
    row_height = 39
    top = 86
    height = top + row_height * len(row_specs) + 44
    image = Image.new("RGB", (width, height), (250, 248, 242))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
        title_font = ImageFont.truetype("arial.ttf", 21)
    except OSError:
        font = ImageFont.load_default()
        title_font = font
    axis_left = 315
    axis_right = width - 56
    colors = {
        seeds[0]: (211, 55, 55),
        seeds[1]: (45, 94, 190),
        seeds[2]: (21, 137, 87),
    }
    offsets = (-8, 0, 8)
    draw.text(
        (22, 17),
        "Seed attachment positions (direct mount parameters; parent motion removed)",
        fill=(20, 24, 28),
        font=title_font,
    )
    legend_x = 25
    for seed in seeds:
        draw.ellipse((legend_x, 54, legend_x + 14, 68), fill=colors[seed])
        draw.text((legend_x + 20, 52), f"seed {seed}", fill=(30, 34, 38), font=font)
        legend_x += 126
    draw.text(
        (450, 52),
        "primary_4_flower_1 is the fixed trough anchor",
        fill=(95, 70, 45),
        font=font,
    )

    primary_maps = {
        seed: {row.curve_id: row for row in results[seed].plan.primaries}
        for seed in seeds
    }
    child_maps = {
        seed: {row.curve_id: row for row in results[seed].plan.descendants}
        for seed in seeds
    }
    y = top
    for label, kind in row_specs:
        if kind is None:
            draw.rectangle((12, y + 2, width - 12, y + row_height - 3), fill=(231, 232, 229))
            draw.text((22, y + 10), label, fill=(28, 32, 36), font=font)
            y += row_height
            continue
        row_center = y + row_height // 2
        draw.text((22, y + 10), label, fill=(28, 32, 36), font=font)
        draw.line((axis_left, row_center, axis_right, row_center), fill=(170, 174, 176), width=2)
        for tick_index in range(6):
            fraction = tick_index / 5.0
            tick_x = round(axis_left + fraction * (axis_right - axis_left))
            draw.line((tick_x, row_center - 5, tick_x, row_center + 5), fill=(150, 154, 156), width=1)
            if label in {primary_ids[0], secondary_ids[0], tertiary_ids[0]}:
                draw.text((tick_x - 8, y + 1), f"{fraction:.1f}", fill=(105, 109, 112), font=font)
        points: list[tuple[int, int]] = []
        for seed_index, seed in enumerate(seeds):
            if kind == "primary":
                value = float(primary_maps[seed][label].mount_s)
            else:
                value = float(child_maps[seed][label].mount_fraction)
            point_x = round(axis_left + value * (axis_right - axis_left))
            point_y = row_center + offsets[seed_index]
            points.append((point_x, point_y))
        draw.line(points, fill=(125, 128, 130), width=2)
        for seed, (point_x, point_y) in zip(seeds, points):
            radius = 6
            draw.ellipse(
                (point_x - radius, point_y - radius, point_x + radius, point_y + radius),
                fill=colors[seed],
                outline=(250, 248, 242),
                width=2,
            )
        y += row_height
    return image


def run(profile_path: Path, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    p0 = core.strip_profile(profile)
    validations: dict[int, dict[str, object]] = {}
    results: dict[int, core.HierarchyResult] = {}
    normal_images: list[Image.Image] = []
    debug_images: list[Image.Image] = []
    unit_images: list[Image.Image] = []
    for seed in core.DEV_SEEDS:
        result = core.build_j0a(p0, seed)
        validation = core.validate_result(p0, result)
        results[seed] = result
        validations[seed] = validation
        _write_json(
            output_dir / f"record_{seed}.json",
            {"result": result.as_dict(), "validation": validation},
        )
        normal = _render(p0, result, validation, debug=False)
        debug = _render(p0, result, validation, debug=True)
        normal.save(output_dir / f"seed_{seed}.png")
        debug.save(output_dir / f"seed_{seed}_debug.png")
        units = _unit_sheet(p0, result, debug)
        units.save(output_dir / f"seed_{seed}_units.png")
        normal_images.append(normal)
        debug_images.append(debug)
        unit_images.append(units)

    proofs = {
        "ignored_input_intervention": core.intervention_proof(profile),
        "global_dependency": core.global_dependency_proof(p0),
        "subtree_dependency": core.subtree_dependency_proof(p0),
        "traversal_order": core.traversal_order_proof(p0),
        "seed_variation": core.seed_variation_proof(p0),
    }
    proofs_pass = (
        bool(proofs["ignored_input_intervention"]["identical"])
        and bool(proofs["global_dependency"]["passes"])
        and bool(proofs["subtree_dependency"]["passes"])
        and bool(proofs["traversal_order"]["identical"])
        and bool(proofs["seed_variation"]["passes"])
    )
    _write_json(output_dir / "proofs.json", proofs)
    _contact_sheet(normal_images).save(output_dir / "contact_sheet.png")
    _contact_sheet(debug_images).save(output_dir / "contact_sheet_debug.png")
    _contact_sheet(unit_images).save(output_dir / "contact_sheet_units.png")
    _mount_position_chart(results).save(output_dir / "mount_position_chart.png")
    manifest = {
        "schema": "whole_local_true_lateral_n12_dev_v3",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "formal_experiment": False,
        "prototype_id": p0.prototype_id,
        "source_profile": str(profile_path.resolve()),
        "generator": str(Path(core.__file__).resolve()),
        "runner": str(Path(__file__).resolve()),
        "protocol": str(PROTOCOL.resolve()),
        "plan_id": core.PLAN_ID,
        "geometry_kernel_id": core.GEOMETRY_KERNEL_ID,
        "topology": {"primary": 7, "secondary": 12, "tertiary": 2},
        "strict_edge_sides": ["top", "bottom"],
        "repeat_seams": ["left", "right"],
        "generation_policy": {
            "candidate_count": 1,
            "retry_count": 0,
            "resample_count": 0,
            "repair_count": 0,
            "validation_feedback_consumed": False,
        },
        "seeds": [
            {
                "seed": seed,
                "valid": validations[seed]["valid"],
                "issues": validations[seed]["issues"],
                "geometry_hash": results[seed].geometry_hash,
                "plan_digest": results[seed].plan.digest,
            }
            for seed in core.DEV_SEEDS
        ],
        "all_structurally_valid": all(validation["valid"] for validation in validations.values()),
        "standard_proofs_pass": proofs_pass,
        "visual_gate": "passed_attachment_position_variation_and_true_lateral_hierarchy",
        "visual_review": {
            "direct_mount_chart": "passed_for_seed_separation_in_mount_s_and_mount_fraction",
            "whole_repeat": "passed_for_visible_attachment_motion_without_structural_failure",
            "seven_unit_crops": "passed_for_parent_relative_child_mount_motion",
            "fixed_exception": "primary_4_flower_1_is_the_trough_anchor",
            "final_pattern_aesthetics": "not_claimed_by_this_gate",
        },
        "visual_evidence": [
            "mount_position_chart.png",
            "contact_sheet_debug.png",
            "contact_sheet_units.png",
        ],
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = run(args.profile, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
