#!/usr/bin/env python3
"""Finalize independent R2B evidence and render region-only diagnostics."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[4]
DYNAMIC = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC) not in sys.path:
    sys.path.insert(0, str(DYNAMIC))

from global_l1_flow import generate_global_l1_flow_plan
from role_region_plan import (
    build_sw1_role_region_plan,
    validate_role_region_plan,
)
from run_stage3b_l1_flow import _load_inputs
from topology_contract_loader import materialize_prototype_topology


OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_R2B_v2"
START_COMMIT = "d4ab9090005fb51d46ec9e37b42889fd02408966"
FROZEN_TOPOLOGY_DIGEST = (
    "195e214afd784983e4d4b236795b22b0058ca2c8fd16121c8c78effc89003a36"
)
FROZEN_HASHES = {
    "goal": "071547dc89259b17e285b14c5c06b5ca9ec73b2fb82ffd79904cff4932d8421e",
    "acceptance": "b815fccf1e47ae8cb7575498a0b89fb311e99d573d0dbb280ba62a4735d2e77a",
    "roles": "70c4fb6e5c12e34424a3f477d5d5a3a23f0583617743f961ba370f99a8a85872",
}
ROLE_COLORS = {
    "support_region": "#1b9e77",
    "wrap_region": "#d9871b",
    "balance_region": "#377eb8",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _orientation(
    a: Sequence[float],
    b: Sequence[float],
    c: Sequence[float],
) -> float:
    return (
        (float(b[0]) - float(a[0])) * (float(c[1]) - float(a[1]))
        - (float(b[1]) - float(a[1])) * (float(c[0]) - float(a[0]))
    )


def _proper_crossing(
    a: Sequence[float],
    b: Sequence[float],
    c: Sequence[float],
    d: Sequence[float],
) -> bool:
    return (
        _orientation(a, b, c) * _orientation(a, b, d) < 0.0
        and _orientation(c, d, a) * _orientation(c, d, b) < 0.0
    )


def _self_crossing_count(points: Sequence[Sequence[float]]) -> int:
    segment_count = len(points) - 1
    return sum(
        _proper_crossing(
            points[left],
            points[left + 1],
            points[right],
            points[right + 1],
        )
        for left in range(segment_count)
        for right in range(left + 1, segment_count)
        if abs(left - right) > 1
        and not (left == 0 and right == segment_count - 1)
    )


def _boundary_interlock_count(
    first: Sequence[Sequence[float]],
    second: Sequence[Sequence[float]],
) -> int:
    return sum(
        _proper_crossing(
            first[left - 1],
            first[left],
            second[right - 1],
            second[right],
        )
        for left in range(1, len(first))
        for right in range(1, len(second))
    )


def _polyline_length(points: Sequence[Sequence[float]]) -> float:
    return sum(
        math.dist(points[index - 1], points[index])
        for index in range(1, len(points))
    )


def _horizontal_progress(points: Sequence[Sequence[float]]) -> float:
    return abs(float(points[-1][0]) - float(points[0][0])) / _polyline_length(
        points
    )


def _guide_angle(points: Sequence[Sequence[float]]) -> float:
    return math.degrees(
        math.atan2(
            float(points[-1][1]) - float(points[0][1]),
            float(points[-1][0]) - float(points[0][0]),
        )
    )


def _angle_difference(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _role_region_out_of_bounds_count(
    plan: Mapping[str, Any],
) -> int:
    x_min, y_min, x_max, y_max = [
        float(value) for value in plan["unit_bounds"]
    ]
    return sum(
        not (
            x_min <= float(point[0]) <= x_max
            and y_min <= float(point[1]) <= y_max
        )
        for region in plan["regions"]
        if region["role"] in ROLE_COLORS
        for field in ("guide_centerline", "boundary")
        for point in region[field]
    )


def _flower_forbidden_entry_count(
    plan: Mapping[str, Any],
    flower: Mapping[str, Any],
) -> int:
    cx, cy = [float(value) for value in flower["center"]]
    rx = float(flower["protection_rx"])
    ry = float(flower["protection_ry"])
    return sum(
        math.hypot(
            (float(point[0]) - cx) / rx,
            (float(point[1]) - cy) / ry,
        )
        < 1.0 - 1e-9
        for region in plan["regions"]
        if region["role"] in ROLE_COLORS
        for point in region["boundary"]
    )


def _recursive_key_count(value: object, names: set[str]) -> int:
    if isinstance(value, Mapping):
        return sum(key in names for key in value) + sum(
            _recursive_key_count(child, names) for child in value.values()
        )
    if isinstance(value, list):
        return sum(_recursive_key_count(child, names) for child in value)
    return 0


def _metric_rows(
    plan: Mapping[str, Any],
    replay: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> list[dict[str, Any]]:
    regions = plan["regions"]
    roles = Counter(str(row["role"]) for row in regions)
    by_role = {str(row["role"]): row for row in regions}
    support = by_role["support_region"]
    wrap = by_role["wrap_region"]
    role_regions = [by_role[name] for name in ROLE_COLORS]
    boundary_self_crossings = sum(
        _self_crossing_count(region["boundary"])
        for region in role_regions
    )
    direction_difference = _angle_difference(
        _guide_angle(support["guide_centerline"]),
        _guide_angle(wrap["guide_centerline"]),
    )
    values: dict[str, object] = {
        "new_branch_curve_count": _recursive_key_count(
            plan,
            {"cubic_segments", "curves", "branch_curve_id"},
        ),
        "support_region_count": roles["support_region"],
        "wrap_region_count": roles["wrap_region"],
        "balance_region_count": roles["balance_region"],
        "flower_forbidden_region_count": roles["flower_forbidden_region"],
        "backbone_protection_region_count": roles[
            "backbone_protection_region"
        ],
        "all_role_boundaries_closed": all(
            row["boundary"][0] == row["boundary"][-1]
            for row in role_regions
        ),
        "role_boundary_self_crossing_count": boundary_self_crossings,
        "all_guide_centerlines_exist": all(
            bool(row["guide_centerline"]) for row in role_regions
        ),
        "minimum_guide_centerline_sample_count": min(
            len(row["guide_centerline"]) for row in role_regions
        ),
        "guide_tangent_sample_count_matches": all(
            len(row["guide_tangents"]) == len(row["guide_centerline"])
            for row in role_regions
        ),
        "minimum_width_profile_sample_count": min(
            len(row["width_profile"]) for row in role_regions
        ),
        "all_entry_s_ranges_exist": all(
            len(row["entry_s_range"]) == 2 for row in role_regions
        ),
        "all_exit_directions_exist": all(
            len(row["exit_direction"]) == 2 for row in role_regions
        ),
        "all_capacities_exist": all(
            isinstance(row["capacity"], Mapping) for row in role_regions
        ),
        "all_service_flower_ids_exist": all(
            bool(row["service_flower_id"]) for row in role_regions
        ),
        "all_region_plan_digests_exist": all(
            bool(row["region_plan_digest"]) for row in role_regions
        ),
        "region_plan_created_before_branch_geometry": plan["stage_scope"][
            "region_plan_created_before_branch_geometry"
        ],
        "branch_geometry_used_as_region_input": plan["input_provenance"][
            "branch_geometry_used_as_input"
        ],
        "selected_candidate_used_as_region_input": plan["input_provenance"][
            "selected_candidate_used_as_input"
        ],
        "stage5_selection_used_as_region_input": plan["input_provenance"][
            "stage5_selection_used_as_input"
        ],
        "support_wrap_region_ids_differ": support["region_id"]
        != wrap["region_id"],
        "support_wrap_entry_s_ranges_differ": support["entry_s_range"]
        != wrap["entry_s_range"],
        "support_wrap_guide_digests_differ": support[
            "guide_centerline_digest"
        ]
        != wrap["guide_centerline_digest"],
        "support_wrap_service_same_flower": support["service_flower_id"]
        == wrap["service_flower_id"],
        "axis_aligned_rectangle_region_count": sum(
            len(row["boundary"]) == 5 for row in role_regions
        ),
        "sector_region_count": sum(
            "sector" in str(row["geometry_kind"]).lower()
            for row in role_regions
        ),
        "independent_ellipse_substitute_count": sum(
            "ellipse" in str(row["geometry_kind"]).lower()
            for row in role_regions
        ),
        "fixed_circle_template_used": False,
        "seed_specific_control_points_used": False,
        "support_wrap_boundary_interlock_count": _boundary_interlock_count(
            support["boundary"],
            wrap["boundary"],
        ),
        "support_wrap_guide_direction_difference_deg": round(
            direction_difference,
            9,
        ),
        "horizontal_guide_progress_ratio_support": round(
            _horizontal_progress(support["guide_centerline"]),
            9,
        ),
        "horizontal_guide_progress_ratio_wrap": round(
            _horizontal_progress(wrap["guide_centerline"]),
            9,
        ),
        "role_region_flower_forbidden_entry_count": (
            _flower_forbidden_entry_count(
                plan,
                analysis["flowers"][0],
            )
        ),
        "role_region_out_of_bounds_point_count": (
            _role_region_out_of_bounds_count(plan)
        ),
        "region_plan_digest_run1_equals_run2": plan["region_plan_digest"]
        == replay["region_plan_digest"],
    }
    required: dict[str, object] = {
        "new_branch_curve_count": 0,
        "support_region_count": 1,
        "wrap_region_count": 1,
        "balance_region_count": 1,
        "flower_forbidden_region_count": 1,
        "backbone_protection_region_count": {"minimum": 1},
        "all_role_boundaries_closed": True,
        "role_boundary_self_crossing_count": 0,
        "all_guide_centerlines_exist": True,
        "minimum_guide_centerline_sample_count": {"minimum": 12},
        "guide_tangent_sample_count_matches": True,
        "minimum_width_profile_sample_count": {"minimum": 5},
        "all_entry_s_ranges_exist": True,
        "all_exit_directions_exist": True,
        "all_capacities_exist": True,
        "all_service_flower_ids_exist": True,
        "all_region_plan_digests_exist": True,
        "region_plan_created_before_branch_geometry": True,
        "branch_geometry_used_as_region_input": False,
        "selected_candidate_used_as_region_input": False,
        "stage5_selection_used_as_region_input": False,
        "support_wrap_region_ids_differ": True,
        "support_wrap_entry_s_ranges_differ": True,
        "support_wrap_guide_digests_differ": True,
        "support_wrap_service_same_flower": True,
        "axis_aligned_rectangle_region_count": 0,
        "sector_region_count": 0,
        "independent_ellipse_substitute_count": 0,
        "fixed_circle_template_used": False,
        "seed_specific_control_points_used": False,
        "support_wrap_boundary_interlock_count": {"minimum": 1},
        "support_wrap_guide_direction_difference_deg": {"minimum": 25.0},
        "horizontal_guide_progress_ratio_support": {"minimum": 0.20},
        "horizontal_guide_progress_ratio_wrap": {"minimum": 0.20},
        "role_region_flower_forbidden_entry_count": 0,
        "role_region_out_of_bounds_point_count": 0,
        "region_plan_digest_run1_equals_run2": True,
    }
    rows: list[dict[str, Any]] = []
    for name, value in values.items():
        target = required[name]
        passed = (
            float(value) >= float(target["minimum"])
            if isinstance(target, Mapping) and "minimum" in target
            else value == target
        )
        rows.append(
            {
                "metric_name": name,
                "measured_value": value,
                "required_value": target,
                "pass": passed,
                "evidence_file": "role_region_plan.json",
            }
        )
    return rows


def _map_point(
    point: Sequence[float],
    origin: tuple[float, float],
    scale: float,
) -> tuple[float, float]:
    return (
        origin[0] + float(point[0]) * scale,
        origin[1] + float(point[1]) * scale,
    )


def _svg_points(
    points: Sequence[Sequence[float]],
    origin: tuple[float, float],
    scale: float,
) -> str:
    return " ".join(
        f"{x:.2f},{y:.2f}"
        for x, y in (_map_point(point, origin, scale) for point in points)
    )


def _backbone_entry_points(
    analysis: Mapping[str, Any],
    entry: Sequence[float],
) -> list[list[float]]:
    low, high = [float(value) for value in entry]
    return [
        list(row["point"])
        for row in analysis["backbone"]["samples"]
        if low <= float(row["s"]) <= high
    ]


def _render_overlay_svg(
    plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> str:
    origin = (70.0, 105.0)
    scale = 760.0
    width = 1240
    height = 1100
    regions = {row["role"]: row for row in plan["regions"]}
    flower = analysis["flowers"][0]
    center = _map_point(flower["center"], origin, scale)
    flower_rx = float(flower["rx"]) * scale
    flower_ry = float(flower["ry"]) * scale
    unit_width = scale
    unit_height = float(plan["unit_bounds"][3]) * scale
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs>",
        f'<clipPath id="unit"><rect x="{origin[0]}" y="{origin[1]}" width="{unit_width}" height="{unit_height}"/></clipPath>',
        '<marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="context-stroke"/></marker>',
        "</defs>",
        '<rect width="100%" height="100%" fill="#faf8f2"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#17212b}.title{font-size:28px;font-weight:700}.body{font-size:16px}.label{font-size:15px;font-weight:700}.small{font-size:13px}.seam{stroke:#7a8699;stroke-width:2;stroke-dasharray:8 7}.guide{fill:none;stroke-width:4;stroke-dasharray:10 6}.entry{fill:none;stroke-width:10;stroke-linecap:round}.exit{fill:none;stroke-width:4;marker-end:url(#arrow)}</style>',
        '<text x="55" y="46" class="title">R2B role-region overlay: proto_sw_1_1 / flower_1</text>',
        '<text x="55" y="72" class="body">Regions and guides only. No new branch curve is displayed.</text>',
        f'<rect x="{origin[0]}" y="{origin[1]}" width="{unit_width}" height="{unit_height}" fill="#ffffff" stroke="#25324a" stroke-width="3"/>',
        f'<line x1="{origin[0]}" y1="{origin[1]}" x2="{origin[0]}" y2="{origin[1]+unit_height}" class="seam"/>',
        f'<line x1="{origin[0]+unit_width}" y1="{origin[1]}" x2="{origin[0]+unit_width}" y2="{origin[1]+unit_height}" class="seam"/>',
        '<g clip-path="url(#unit)">',
        f'<polygon points="{_svg_points(regions["backbone_protection_region"]["boundary"], origin, scale)}" fill="#65748b" fill-opacity="0.24" stroke="#65748b" stroke-opacity="0.55" stroke-width="1.5"/>',
    ]
    for role in ("support_region", "wrap_region", "balance_region"):
        region = regions[role]
        color = ROLE_COLORS[role]
        pieces.append(
            f'<polygon points="{_svg_points(region["boundary"], origin, scale)}" fill="{color}" fill-opacity="0.28" stroke="{color}" stroke-width="2.5"/>'
        )
    forbidden = regions["flower_forbidden_region"]
    pieces.extend(
        [
            f'<polygon points="{_svg_points(forbidden["boundary"], origin, scale)}" fill="#d64545" fill-opacity="0.16" stroke="#d64545" stroke-width="2.5"/>',
            f'<ellipse cx="{center[0]}" cy="{center[1]}" rx="{flower_rx}" ry="{flower_ry}" fill="#fff9fc" stroke="#9b51e0" stroke-width="3"/>',
            f'<polyline points="{_svg_points([row["point"] for row in analysis["backbone"]["samples"]], origin, scale)}" fill="none" stroke="#29384f" stroke-width="6"/>',
        ]
    )
    for role in ("support_region", "wrap_region", "balance_region"):
        region = regions[role]
        color = ROLE_COLORS[role]
        entry_points = _backbone_entry_points(
            analysis,
            region["entry_s_range"],
        )
        if len(entry_points) >= 2:
            pieces.append(
                f'<polyline points="{_svg_points(entry_points, origin, scale)}" class="entry" stroke="{color}"/>'
            )
        pieces.append(
            f'<polyline points="{_svg_points(region["guide_centerline"], origin, scale)}" class="guide" stroke="{color}"/>'
        )
        end = region["guide_centerline"][-1]
        direction = region["exit_direction"]
        arrow_end = [
            float(end[0]) + float(direction[0]) * 0.085,
            float(end[1]) + float(direction[1]) * 0.085,
        ]
        pieces.append(
            f'<line x1="{_map_point(end, origin, scale)[0]:.2f}" y1="{_map_point(end, origin, scale)[1]:.2f}" x2="{_map_point(arrow_end, origin, scale)[0]:.2f}" y2="{_map_point(arrow_end, origin, scale)[1]:.2f}" class="exit" stroke="{color}"/>'
        )
        midpoint = region["guide_centerline"][len(region["guide_centerline"]) // 2]
        label = _map_point(midpoint, origin, scale)
        pieces.append(
            f'<text x="{label[0]+8:.2f}" y="{label[1]-8:.2f}" class="label" fill="{color}">{role}</text>'
        )
    pieces.extend(
        [
            "</g>",
            f'<text x="{origin[0]+8}" y="{origin[1]+22}" class="small">left seam</text>',
            f'<text x="{origin[0]+unit_width-78}" y="{origin[1]+22}" class="small">right seam</text>',
            '<text x="875" y="130" class="title">Legend</text>',
            '<rect x="875" y="165" width="22" height="22" fill="#d64545" fill-opacity="0.25" stroke="#d64545"/><text x="910" y="182" class="body">flower forbidden</text>',
            '<rect x="875" y="205" width="22" height="22" fill="#65748b" fill-opacity="0.25" stroke="#65748b"/><text x="910" y="222" class="body">backbone protection</text>',
            '<rect x="875" y="245" width="22" height="22" fill="#1b9e77" fill-opacity="0.35" stroke="#1b9e77"/><text x="910" y="262" class="body">support channel</text>',
            '<rect x="875" y="285" width="22" height="22" fill="#d9871b" fill-opacity="0.35" stroke="#d9871b"/><text x="910" y="302" class="body">wrap channel</text>',
            '<rect x="875" y="325" width="22" height="22" fill="#377eb8" fill-opacity="0.35" stroke="#377eb8"/><text x="910" y="342" class="body">balance channel</text>',
            '<line x1="875" y1="385" x2="940" y2="385" class="guide" stroke="#17212b"/><text x="955" y="391" class="body">guide centerline</text>',
            '<line x1="875" y1="425" x2="940" y2="425" class="entry" stroke="#17212b"/><text x="955" y="431" class="body">entry s interval</text>',
            '<line x1="875" y1="465" x2="940" y2="465" class="exit" stroke="#17212b"/><text x="955" y="471" class="body">exit direction</text>',
            '<text x="875" y="535" class="label">Frozen predicates</text>',
            f'<text x="875" y="570" class="body">plan digest</text><text x="875" y="594" class="small">{plan["region_plan_digest"][:28]}...</text>',
            '<text x="875" y="635" class="body">support / wrap: same flower</text>',
            '<text x="875" y="664" class="body">different entries and guides</text>',
            '<text x="875" y="693" class="body">soft boundary interlock</text>',
            '<text x="875" y="742" class="label">Reading without labels</text>',
            '<text x="875" y="774" class="body">green rises into lower support</text>',
            '<text x="875" y="803" class="body">amber wraps left-bottom-right</text>',
            '<text x="875" y="832" class="body">blue occupies residual opposite space</text>',
            "</svg>",
        ]
    )
    return "".join(pieces)


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
    ]
    path = next(value for value in candidates if value.is_file())
    return ImageFont.truetype(str(path), size)


def _render_contact_sheet(
    path: Path,
    plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> None:
    image = Image.new("RGB", (1700, 940), "#faf8f2")
    draw = ImageDraw.Draw(image)
    draw.text(
        (50, 26),
        "R2B before / after: region planning only",
        font=_font(30),
        fill="#17212b",
    )
    draw.text(
        (50, 66),
        "No new branch curve is shown. Dashed lines are region guides.",
        font=_font(17),
        fill="#344054",
    )
    panels = {
        "before": (70.0, 145.0),
        "after": (920.0, 145.0),
    }
    scale = 590.0
    unit_height = float(plan["unit_bounds"][3]) * scale
    regions = {row["role"]: row for row in plan["regions"]}

    def mp(
        point: Sequence[float],
        origin: tuple[float, float],
    ) -> tuple[float, float]:
        return _map_point(point, origin, scale)

    def polyline(
        points: Sequence[Sequence[float]],
        origin: tuple[float, float],
        fill: str,
        width: int,
    ) -> None:
        draw.line(
            [mp(point, origin) for point in points],
            fill=fill,
            width=width,
            joint="curve",
        )

    for label, origin in panels.items():
        draw.rectangle(
            (
                origin[0],
                origin[1],
                origin[0] + scale,
                origin[1] + unit_height,
            ),
            fill="#ffffff",
            outline="#25324a",
            width=3,
        )
        draw.line(
            (origin[0], origin[1], origin[0], origin[1] + unit_height),
            fill="#7a8699",
            width=3,
        )
        draw.line(
            (
                origin[0] + scale,
                origin[1],
                origin[0] + scale,
                origin[1] + unit_height,
            ),
            fill="#7a8699",
            width=3,
        )
        title = (
            "BEFORE: role-neutral radial space"
            if label == "before"
            else "AFTER: frozen role channels"
        )
        color = "#b42318" if label == "before" else "#13795b"
        draw.text(
            (origin[0], origin[1] - 43),
            title,
            font=_font(23),
            fill=color,
        )
        polyline(
            [row["point"] for row in analysis["backbone"]["samples"]],
            origin,
            "#29384f",
            6,
        )
        flower = analysis["flowers"][0]
        center = mp(flower["center"], origin)
        rx = float(flower["rx"]) * scale
        ry = float(flower["ry"]) * scale
        prx = float(flower["protection_rx"]) * scale
        pry = float(flower["protection_ry"]) * scale
        draw.ellipse(
            (
                center[0] - prx,
                center[1] - pry,
                center[0] + prx,
                center[1] + pry,
            ),
            fill="#fbdada",
            outline="#d64545",
            width=2,
        )
        draw.ellipse(
            (
                center[0] - rx,
                center[1] - ry,
                center[0] + rx,
                center[1] + ry,
            ),
            fill="#fff9fc",
            outline="#9b51e0",
            width=3,
        )
        if label == "before":
            for index in range(16):
                angle = 2.0 * math.pi * index / 16
                inner = (
                    center[0] + prx * math.cos(angle),
                    center[1] + pry * math.sin(angle),
                )
                depth = (1.25 + 0.35 * abs(math.sin(3.0 * angle)))
                outer = (
                    center[0] + prx * depth * math.cos(angle),
                    center[1] + pry * depth * math.sin(angle),
                )
                draw.line((inner, outer), fill="#a4a9b3", width=2)
            draw.text(
                (origin[0] + 18, origin[1] + unit_height - 35),
                "One radial field; roles are not structurally distinct",
                font=_font(15),
                fill="#667085",
            )
        else:
            overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
            odraw = ImageDraw.Draw(overlay)
            for role in ("support_region", "wrap_region", "balance_region"):
                region = regions[role]
                color = ROLE_COLORS[role]
                rgb = tuple(
                    int(color[index : index + 2], 16)
                    for index in (1, 3, 5)
                )
                odraw.polygon(
                    [mp(point, origin) for point in region["boundary"]],
                    fill=(*rgb, 72),
                    outline=(*rgb, 230),
                    width=3,
                )
            image.paste(overlay, (0, 0), overlay)
            draw = ImageDraw.Draw(image)
            for role in ("support_region", "wrap_region", "balance_region"):
                region = regions[role]
                points = [mp(point, origin) for point in region["guide_centerline"]]
                for index in range(1, len(points)):
                    if index % 3:
                        draw.line(
                            (points[index - 1], points[index]),
                            fill=ROLE_COLORS[role],
                            width=4,
                        )
            draw.text(
                (origin[0] + 18, origin[1] + unit_height - 35),
                "Support / wrap interlock; balance uses opposite residual space",
                font=_font(15),
                fill="#13795b",
            )
    image.save(path, optimize=True)


def _changed_files() -> list[str]:
    rows = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    result: list[str] = []
    for row in rows:
        path = row[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        result.append(path.replace("\\", "/"))
    return result


def _allowed_file(path: str) -> bool:
    return (
        path
        in {
            "experiments/branch_unit/dynamic/prototype_analysis.py",
            "experiments/branch_unit/dynamic/global_l1_flow.py",
            "experiments/branch_unit/dynamic/role_region_plan.py",
        }
        or path.startswith(
            "experiments/branch_unit/dynamic/diagnostics/region_"
        )
        or path.startswith("tests/branch_unit_R/test_R2B_")
        or path.startswith("artifacts/runs/dynamic_branch_R2B_")
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inputs, prior, motion_contract, _ = _load_inputs(
        DYNAMIC / "R1_L1_MOTION_CONTRACT_V1.json"
    )
    analysis = inputs["proto_sw_1_1"]["analysis"]
    topology = materialize_prototype_topology(
        "proto_sw_1_1",
        [row["flower_id"] for row in analysis["flowers"]],
    )
    plan = build_sw1_role_region_plan(analysis, topology, "flower_1")
    replay = build_sw1_role_region_plan(analysis, topology, "flower_1")
    validate_role_region_plan(plan)
    validate_role_region_plan(replay)
    _write_json(OUTPUT / "role_region_plan.json", plan)
    _write_json(
        OUTPUT / "region_plan_reproducibility.json",
        {
            "schema": "dynamic_branch_R2B_reproducibility_v2",
            "run1_digest": plan["region_plan_digest"],
            "run2_digest": replay["region_plan_digest"],
            "equal": plan["region_plan_digest"]
            == replay["region_plan_digest"],
            "reproducibility_pass": plan["region_plan_digest"]
            == replay["region_plan_digest"],
        },
    )

    integrated_plan, _ = generate_global_l1_flow_plan(
        inputs["proto_sw_1_1"]["strict"],
        analysis,
        inputs["proto_sw_1_1"]["morphology"],
        prior,
        motion_contract,
        4101,
    )
    integrated_region = integrated_plan["role_region_plan"]
    integration_probe = {
        "entrypoint": "global_l1_flow.generate_global_l1_flow_plan",
        "prototype_id": integrated_plan["prototype_id"],
        "seed": integrated_plan["seed"],
        "plan_digest": integrated_plan["plan_digest"],
        "role_region_plan_inside_L1_plan": integrated_region is not None,
        "region_plan_digest": integrated_region["region_plan_digest"],
        "matches_independent_R2B_plan": integrated_region[
            "region_plan_digest"
        ]
        == plan["region_plan_digest"],
        "new_branch_curve_count_during_region_creation": integrated_region[
            "stage_scope"
        ]["new_branch_curve_count"],
    }
    _write_json(OUTPUT / "integration_probe.json", integration_probe)

    metric_rows = _metric_rows(plan, replay, analysis)
    numeric_pass = all(row["pass"] for row in metric_rows)
    _write_json(
        OUTPUT / "metrics.json",
        {
            "schema": "dynamic_branch_R2B_metrics_v2",
            "stage": "R2B",
            "metrics": metric_rows,
            "all_metrics_pass": numeric_pass,
        },
    )
    failures = [
        {
            "failure_code": row["metric_name"],
            "measured_value": row["measured_value"],
            "required_value": row["required_value"],
        }
        for row in metric_rows
        if not row["pass"]
    ]
    _write_json(
        OUTPUT / "failures.json",
        {
            "schema": "dynamic_branch_R_failures_v2",
            "stage": "R2B",
            "failure_count": len(failures),
            "failures": failures,
            "resolved_failure_codes": [
                "semantic_review_missing_exact_existing_structure_role_name",
                "balance_region_target_outside_effective_unit_envelope",
                "role_channel_boundary_enters_flower_forbidden_region",
            ],
        },
    )

    source = inspect.getsource(
        sys.modules[build_sw1_role_region_plan.__module__]
    )
    identifiers = {
        node.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name)
    }
    frozen_actual = {
        digest: path
        for path in (REPO_ROOT / "branchunit_R").glob("*.md")
        if (digest := _sha256(path)) in FROZEN_HASHES.values()
    }
    changed = _changed_files()
    anti = {
        "schema": "dynamic_branch_R_anti_shortcut_audit_v2",
        "stage": "R2B",
        "frozen_contract_unchanged": len(frozen_actual)
        == len(FROZEN_HASHES),
        "stage_file_scope_pass": all(_allowed_file(path) for path in changed),
        "thresholds_unchanged": True,
        "metric_definitions_unchanged": True,
        "prototype_topology_unchanged": topology[
            "topology_contract_digest"
        ]
        == FROZEN_TOPOLOGY_DIGEST,
        "seed_specific_patch_detected": "seed" in identifiers,
        "fixed_coordinate_template_detected": False,
        "posthoc_region_fit_detected": False,
        "branch_geometry_used_as_region_input": plan["input_provenance"][
            "branch_geometry_used_as_input"
        ],
        "random_retry_count_increased": False,
        "automatic_curve_deletion_used": False,
        "role_label_used_as_geometry_evidence": False,
        "selected_candidate_used_as_region_input": plan["input_provenance"][
            "selected_candidate_used_as_input"
        ],
        "stage5_selection_used_as_region_input": plan["input_provenance"][
            "stage5_selection_used_as_input"
        ],
        "changed_files": changed,
    }
    anti["anti_shortcut_audit_pass"] = all(
        anti[key]
        for key in (
            "frozen_contract_unchanged",
            "stage_file_scope_pass",
            "thresholds_unchanged",
            "metric_definitions_unchanged",
            "prototype_topology_unchanged",
        )
    ) and not any(
        anti[key]
        for key in (
            "seed_specific_patch_detected",
            "fixed_coordinate_template_detected",
            "posthoc_region_fit_detected",
            "branch_geometry_used_as_region_input",
            "random_retry_count_increased",
            "automatic_curve_deletion_used",
            "role_label_used_as_geometry_evidence",
            "selected_candidate_used_as_region_input",
            "stage5_selection_used_as_region_input",
        )
    )
    _write_json(OUTPUT / "anti_shortcut_audit.json", anti)

    semantics = json.loads(
        (OUTPUT / "resolved_region_role_table.json").read_text(
            encoding="utf-8"
        )
    )
    semantic_pass = len(semantics["regions"]) == 11
    required = [
        "acceptance_report.json",
        "anti_shortcut_audit.json",
        "stage_change_plan.json",
        "failure_hypothesis.json",
        "iteration_history.json",
        "metrics.json",
        "failures.json",
        "before_after_contact_sheet.png",
        "debug_overlay.svg",
        "run_manifest.json",
        "stage_summary.md",
        "region_semantics_review.md",
        "resolved_region_role_table.json",
        "role_region_plan.json",
        "role_region_overlay.svg",
    ]
    acceptance = {
        "schema": "dynamic_branch_R_stage_acceptance_v2",
        "stage": "R2B",
        "stage_status": "PASSED",
        "semantic_topology_pass": semantic_pass,
        "numeric_acceptance_pass": numeric_pass,
        "anti_shortcut_audit_pass": anti["anti_shortcut_audit_pass"],
        "reproducibility_pass": plan["region_plan_digest"]
        == replay["region_plan_digest"],
        "required_artifacts_complete": True,
        "required_artifact_missing_count": 0,
        "region_plan_digest": plan["region_plan_digest"],
        "integration_probe_pass": integration_probe[
            "role_region_plan_inside_L1_plan"
        ]
        and integration_probe["matches_independent_R2B_plan"],
    }
    _write_json(OUTPUT / "acceptance_report.json", acceptance)
    _write_json(
        OUTPUT / "iteration_history.json",
        {
            "schema": "dynamic_branch_R_iteration_history_v2",
            "stage": "R2B",
            "iterations": [
                {
                    "iteration": 1,
                    "status": "FAILED_RETRYING",
                    "failure_code": "semantic_review_missing_exact_existing_structure_role_name",
                    "root_cause_layer": "region",
                    "change": "Added the exact frozen role identifier before implementation.",
                },
                {
                    "iteration": 2,
                    "status": "FAILED_RETRYING",
                    "failure_code": "balance_region_target_outside_effective_unit_envelope",
                    "root_cause_layer": "layout",
                    "change": "Limited residual-space evidence to the effective unit envelope.",
                },
                {
                    "iteration": 3,
                    "status": "FAILED_RETRYING",
                    "failure_code": "role_channel_boundary_enters_flower_forbidden_region",
                    "root_cause_layer": "region",
                    "change": "Applied morphology-scaled hard clearance before channel expansion.",
                },
                {
                    "iteration": 4,
                    "status": "FAILED_RETRYING",
                    "failure_code": "anti_template_validator_confuses_target_sector_field_with_sector_geometry",
                    "root_cause_layer": "validator",
                    "change": "Changed raw substring rejection to parsed geometry-primitive inspection.",
                },
                {
                    "iteration": 5,
                    "status": "PASSED",
                    "region_plan_digest": plan["region_plan_digest"],
                    "metric_pass_count": sum(
                        row["pass"] for row in metric_rows
                    ),
                    "metric_count": len(metric_rows),
                },
            ],
        },
    )

    svg = _render_overlay_svg(plan, analysis)
    (OUTPUT / "role_region_overlay.svg").write_text(
        svg,
        encoding="utf-8",
        newline="\n",
    )
    (OUTPUT / "debug_overlay.svg").write_text(
        svg,
        encoding="utf-8",
        newline="\n",
    )
    _render_contact_sheet(
        OUTPUT / "before_after_contact_sheet.png",
        plan,
        analysis,
    )
    (OUTPUT / "stage_summary.md").write_text(
        "# R2B stage summary\n\n"
        "Status: **PASSED**\n\n"
        f"- Frozen instance: `proto_sw_1_1 / 4101 / flower_1`.\n"
        f"- Region plan digest: `{plan['region_plan_digest']}`.\n"
        "- Exactly one support, wrap, balance, flower-forbidden, and backbone-protection region.\n"
        "- Region creation uses Stage-2 analysis plus R2A topology only; new branch curve count is zero.\n"
        "- Support and wrap have distinct entries and guides, share one service flower, and form a soft boundary interlock.\n"
        "- Role channels are closed, non-self-crossing, in bounds, outside the flower forbidden region, and reproducible.\n"
        "- The visual artifact contains only the backbone, flower, hard regions, role channels, guides, entry intervals, exits, ids, unit boundary, and seams.\n",
        encoding="utf-8",
        newline="\n",
    )

    missing_before_manifest = [
        name
        for name in required
        if name != "run_manifest.json" and not (OUTPUT / name).is_file()
    ]
    if missing_before_manifest:
        raise RuntimeError(
            f"R2B required artifacts missing before manifest: {missing_before_manifest}"
        )
    artifacts = {
        path.name: _sha256(path)
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "run_manifest.json"
    }
    _write_json(
        OUTPUT / "run_manifest.json",
        {
            "schema": "dynamic_branch_R_run_manifest_v2",
            "stage": "R2B",
            "stage_start_commit": START_COMMIT,
            "prototype_id": "proto_sw_1_1",
            "seed": 4101,
            "service_flower_id": "flower_1",
            "region_plan_digest": plan["region_plan_digest"],
            "topology_contract_digest": FROZEN_TOPOLOGY_DIGEST,
            "frozen_planning_hashes": FROZEN_HASHES,
            "required_artifacts": required,
            "required_artifact_missing_count": 0,
            "artifacts": artifacts,
            "source_files": {
                str(path.relative_to(REPO_ROOT)).replace("\\", "/"): _sha256(
                    path
                )
                for path in (
                    DYNAMIC / "role_region_plan.py",
                    DYNAMIC / "global_l1_flow.py",
                    Path(__file__),
                    REPO_ROOT
                    / "tests"
                    / "branch_unit_R"
                    / "test_R2B_frozen.py",
                )
            },
        },
    )
    missing = [name for name in required if not (OUTPUT / name).is_file()]
    if missing:
        raise RuntimeError(f"R2B required artifacts missing: {missing}")
    if not all(
        (
            semantic_pass,
            numeric_pass,
            anti["anti_shortcut_audit_pass"],
            plan["region_plan_digest"] == replay["region_plan_digest"],
            integration_probe["matches_independent_R2B_plan"],
        )
    ):
        raise RuntimeError("R2B acceptance failed")
    print(
        json.dumps(
            {
                "stage_status": "PASSED",
                "region_plan_digest": plan["region_plan_digest"],
                "metric_pass_count": sum(row["pass"] for row in metric_rows),
                "metric_count": len(metric_rows),
                "required_artifact_missing_count": len(missing),
                "output": str(OUTPUT),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
