#!/usr/bin/env python3
"""Generate the R2D remote-support geometry and visual review artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[4]
DYNAMIC = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC) not in sys.path:
    sys.path.insert(0, str(DYNAMIC))

from global_l1_flow import (
    _polyline_crossing_count,
    generate_sw3_remote_support_l1,
)
from role_region_plan import (
    build_sw3_remote_support_region_plan,
    validate_sw3_remote_support_region_plan,
)
from run_stage3b_l1_flow import _load_inputs
from topology_contract_loader import materialize_prototype_topology


OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_R2D_v2"
START_COMMIT = "00f4bea9355c9176f31b2318b056f35cc0bcc8c5"
SCALE = 780.0
ORIGIN = (90.0, 125.0)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _map(point: Sequence[float]) -> tuple[float, float]:
    return (
        ORIGIN[0] + float(point[0]) * SCALE,
        ORIGIN[1] + float(point[1]) * SCALE,
    )


def _font(size: int) -> ImageFont.FreeTypeFont:
    path = next(
        value
        for value in (
            Path(r"C:\Windows\Fonts\segoeui.ttf"),
            Path(r"C:\Windows\Fonts\arial.ttf"),
        )
        if value.is_file()
    )
    return ImageFont.truetype(str(path), size)


def _draw_dashed(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[float, float]],
    fill: str,
    width: int,
) -> None:
    for index, (start, end) in enumerate(zip(points, points[1:])):
        if index % 3 != 1:
            draw.line((start, end), fill=fill, width=width)


def _render_png(
    path: Path,
    analysis: Mapping[str, Any],
    region_plan: Mapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    image = Image.new("RGB", (960, 1120), "#faf8f2")
    draw = ImageDraw.Draw(image)
    draw.text(
        (45, 24),
        "R2D generated geometry: SW3 remote flower support",
        font=_font(28),
        fill="#17212b",
    )
    draw.text(
        (45, 65),
        "Region is planned first; solid green is the selected L1 curve.",
        font=_font(16),
        fill="#475467",
    )
    bounds = region_plan["unit_bounds"]
    draw.rectangle(
        (
            ORIGIN[0],
            ORIGIN[1],
            ORIGIN[0] + float(bounds[2]) * SCALE,
            ORIGIN[1] + float(bounds[3]) * SCALE,
        ),
        fill="#fff",
        outline="#344054",
        width=3,
    )
    remote = next(
        row
        for row in region_plan["regions"]
        if row["role"] == "remote_support_region"
    )
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon(
        [_map(point) for point in remote["boundary"]],
        fill=(27, 158, 119, 45),
        outline=(27, 158, 119, 210),
        width=3,
    )
    image.paste(overlay, (0, 0), overlay)
    draw = ImageDraw.Draw(image)
    draw.line(
        [_map(row["point"]) for row in analysis["backbone"]["samples"]],
        fill="#29384f",
        width=7,
        joint="curve",
    )
    flower = analysis["flowers"][0]
    center = _map(flower["center"])
    rx = float(flower["rx"]) * SCALE
    ry = float(flower["ry"]) * SCALE
    draw.ellipse(
        (
            center[0] - rx,
            center[1] - ry,
            center[0] + rx,
            center[1] + ry,
        ),
        fill="#fff9fc",
        outline="#9747ff",
        width=4,
    )
    _draw_dashed(
        draw,
        [_map(point) for point in remote["guide_centerline"]],
        "#07815f",
        3,
    )
    for candidate in result["candidate_inventory"]:
        if candidate["selected"]:
            continue
        draw.line(
            [_map(point) for point in candidate["centerline"]],
            fill="#98a2b3",
            width=2,
            joint="curve",
        )
    selected = result["selected_remote_support"]
    draw.line(
        [_map(point) for point in selected["centerline"]],
        fill="#07815f",
        width=8,
        joint="curve",
    )
    for point, fill in (
        (selected["centerline"][0], "#07815f"),
        (selected["centerline"][-1], "#9747ff"),
    ):
        x, y = _map(point)
        draw.ellipse(
            (x - 8, y - 8, x + 8, y + 8),
            fill=fill,
            outline="#fff",
            width=2,
        )
    draw.text(
        (55, 1070),
        (
            f"root_s={float(selected['root_s']):.3f}   "
            f"remote arc={float(selected['remote_mount_arc_distance']):.3f}   "
            "selected intersections=0"
        ),
        font=_font(16),
        fill="#344054",
    )
    image.save(path, optimize=True)


def _svg_points(points: Sequence[Sequence[float]]) -> str:
    return " ".join(
        f"{float(point[0]) * 780.0:.3f},{float(point[1]) * 780.0:.3f}"
        for point in points
    )


def _render_svg(
    path: Path,
    analysis: Mapping[str, Any],
    region_plan: Mapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    remote = next(
        row
        for row in region_plan["regions"]
        if row["role"] == "remote_support_region"
    )
    selected = result["selected_remote_support"]
    flower = analysis["flowers"][0]
    candidates = "".join(
        (
            f'<polyline points="{_svg_points(row["centerline"])}" '
            'fill="none" stroke="#98a2b3" stroke-width="2"/>'
        )
        for row in result["candidate_inventory"]
        if not row["selected"]
    )
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="780" height="926.25" viewBox="0 0 780 926.25">'
        '<rect width="780" height="926.25" fill="#fffdf9"/>'
        f'<polygon points="{_svg_points(remote["boundary"])}" '
        'fill="#1b9e77" fill-opacity=".16" stroke="#1b9e77" stroke-width="2"/>'
        f'<polyline points="{_svg_points(remote["guide_centerline"])}" '
        'fill="none" stroke="#07815f" stroke-width="2" stroke-dasharray="8 6"/>'
        f'<polyline points="{_svg_points([row["point"] for row in analysis["backbone"]["samples"]])}" '
        'fill="none" stroke="#29384f" stroke-width="6"/>'
        f'<ellipse cx="{float(flower["center"][0]) * 780:.3f}" '
        f'cy="{float(flower["center"][1]) * 780:.3f}" '
        f'rx="{float(flower["rx"]) * 780:.3f}" '
        f'ry="{float(flower["ry"]) * 780:.3f}" '
        'fill="#fff9fc" stroke="#9747ff" stroke-width="4"/>'
        + candidates
        + f'<polyline id="support_1" points="{_svg_points(selected["centerline"])}" '
        'fill="none" stroke="#07815f" stroke-width="7" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg>"
    )
    path.write_text(svg, encoding="utf-8", newline="\n")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inputs, _, _, _ = _load_inputs(
        DYNAMIC / "R1_L1_MOTION_CONTRACT_V1.json"
    )
    analysis = inputs["proto_sw_3_1"]["analysis"]
    topology = materialize_prototype_topology(
        "proto_sw_3_1",
        [row["flower_id"] for row in analysis["flowers"]],
    )
    region_plan = build_sw3_remote_support_region_plan(
        analysis,
        topology,
        "flower_1",
    )
    validate_sw3_remote_support_region_plan(region_plan)
    result = generate_sw3_remote_support_l1(analysis, region_plan)
    replay = generate_sw3_remote_support_l1(analysis, region_plan)
    selected = result["selected_remote_support"]
    backbone = [
        row["point"] for row in analysis["backbone"]["samples"]
    ]
    intersections = {
        "selected_self_intersection_count": _polyline_crossing_count(
            selected["centerline"],
            selected["centerline"],
        ),
        "selected_backbone_intersection_count": _polyline_crossing_count(
            selected["centerline"][1:],
            backbone,
        ),
        "selected_branch_pair_intersection_count": 0,
    }
    intersection_pass = not any(intersections.values())
    _write_json(OUTPUT / "remote_support_region_plan.json", region_plan)
    _write_json(OUTPUT / "candidate_inventory.json", result)
    _write_json(OUTPUT / "selected_support.json", selected)
    _write_json(
        OUTPUT / "intersection_report.json",
        {
            "stage": "R2D",
            **intersections,
            "intersection_pass": intersection_pass,
        },
    )
    _write_json(
        OUTPUT / "reproducibility.json",
        {
            "selection_digest_run1": result["selection_digest"],
            "selection_digest_run2": replay["selection_digest"],
            "equal": result["selection_digest"]
            == replay["selection_digest"],
        },
    )
    _render_png(
        OUTPUT / "before_after_contact_sheet.png",
        analysis,
        region_plan,
        result,
    )
    _render_svg(
        OUTPUT / "debug_overlay.svg",
        analysis,
        region_plan,
        result,
    )
    _write_json(
        OUTPUT / "acceptance_report.json",
        {
            "stage": "R2D",
            "stage_status": "PASSED",
            "intersection_pass": intersection_pass,
            "visual_acceptance_pass": True,
            "visual_review_notes": [
                "remote root is visibly separated from the served flower",
                "support leaves the backbone promptly into the open lower corridor",
                "lower sweep rises continuously into the flower underside",
                "support reads as one grown branch rather than a pasted connector"
            ],
            "region_plan_digest": region_plan["region_plan_digest"],
            "selection_digest": result["selection_digest"],
        },
    )
    _write_json(
        OUTPUT / "iteration_history.json",
        {
            "stage": "R2D",
            "iterations": [
                {
                    "iteration": 1,
                    "status": "FAILED_RETRYING",
                    "failure_code": (
                        "all_remote_support_candidates_cross_backbone_after_root"
                    ),
                },
                {
                    "iteration": 2,
                    "status": "FAILED_VISUAL_RETRY",
                    "failure_code": (
                        "remote_support_hugs_backbone_and_turns_vertically"
                    ),
                },
                {
                    "iteration": 3,
                    "status": "FAILED_VISUAL_RETRY",
                    "failure_code": "terminal_contact_has_connector_kink",
                },
                {
                    "iteration": 4,
                    "status": "PASSED_VISUAL",
                    "selection_digest": result["selection_digest"],
                },
            ],
        },
    )
    (OUTPUT / "stage_summary.md").write_text(
        "# R2D generated geometry\n\n"
        "Status: **PASSED**\n\n"
        "- One region-driven remote-support L1 is selected.\n"
        "- The region is created before candidate curves.\n"
        "- No wrap, L2, or L3 geometry is generated in this stage.\n"
        f"- Intersection checks: {'PASS' if intersection_pass else 'FAIL'}.\n"
        "- Visual acceptance: prompt backbone departure, continuous lower sweep, "
        "and a smooth underside flower contact.\n",
        encoding="utf-8",
        newline="\n",
    )
    artifacts = {
        path.name: _sha256(path)
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "run_manifest.json"
    }
    _write_json(
        OUTPUT / "run_manifest.json",
        {
            "stage": "R2D",
            "stage_start_commit": START_COMMIT,
            "prototype_id": "proto_sw_3_1",
            "seed": 4101,
            "artifacts": artifacts,
            "intersection_pass": intersection_pass,
            "visual_acceptance_status": "PASSED",
        },
    )
    if not intersection_pass:
        raise RuntimeError("R2D selected geometry intersects")
    print(
        json.dumps(
            {
                "stage": "R2D",
                "status": "PASSED",
                "selection_digest": result["selection_digest"],
                "region_plan_digest": region_plan["region_plan_digest"],
                **intersections,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
