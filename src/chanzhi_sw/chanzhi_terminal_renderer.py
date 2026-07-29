#!/usr/bin/env python3
"""Attach scalable Chanzhi terminal motifs to validated branch geometry."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    from . import chanzhi_branch_geometry as geo
    from . import chanzhi_terminal_primitives as terminal_geo
except ImportError:
    import chanzhi_branch_geometry as geo
    import chanzhi_terminal_primitives as terminal_geo


Point = tuple[float, float]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_ROOT = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_skeleton_analysis" / "run6_flower_connectors"
DEFAULT_PLAN_ROOT = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_branch_layout_grammar" / "run5_flower_connectors"
DEFAULT_GEOMETRY_ROOT = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_branch_geometry" / "run6_clearance_aware_inward"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_terminal_render" / "run1"
DEFAULT_PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)

PAPER = "#fbfaf5"
INK = "#0b1f46"
REJECTED = "#dc2626"
COMPOSITION_COVERAGE_TARGET = 0.75
COMPOSITION_INK_TARGET = 0.265
MIN_LEAVES_SINGLE_FLOWER = 55
MIN_LEAVES_MULTI_FLOWER = 42
# At the 256 px structural scale, 10 px approximates half the width of a
# medium leaf and measures occupied visual territory without closing white gaps.
COMPOSITION_DILATION_RADIUS = 10
CURVE_STYLES = ("soft_c", "deep_c", "s_sweep", "hook", "recurve")
FINAL_SUMMARY_OUTPUT_DIR = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_final"


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scale: float) -> Point:
    return a[0] * scale, a[1] * scale


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _norm(v: Point) -> Point:
    length = math.hypot(v[0], v[1])
    if length < 1e-9:
        return (1.0, 0.0)
    return (v[0] / length, v[1] / length)


def _normal(v: Point) -> Point:
    return (-v[1], v[0])


def _as_points(raw: Iterable[Iterable[float]]) -> list[Point]:
    return [(float(point[0]), float(point[1])) for point in raw]


def _local_to_world(origin: Point, tangent: Point, point: Point) -> Point:
    normal = _normal(tangent)
    return _add(origin, _add(_mul(tangent, point[0]), _mul(normal, point[1])))


def _stable_fraction(key: str) -> float:
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, samples: int = 18) -> list[Point]:
    result: list[Point] = []
    for index in range(samples + 1):
        t = index / samples
        mt = 1.0 - t
        result.append(
            (
                mt**3 * p0[0] + 3.0 * mt**2 * t * p1[0] + 3.0 * mt * t**2 * p2[0] + t**3 * p3[0],
                mt**3 * p0[1] + 3.0 * mt**2 * t * p1[1] + 3.0 * mt * t**2 * p2[1] + t**3 * p3[1],
            )
        )
    return result


def _closed_outline(
    origin: Point,
    tangent: Point,
    spine: list[Point],
    left_halves: list[float],
    right_halves: list[float],
) -> list[Point]:
    """Expand a local centerline into one continuous closed terminal outline."""
    left: list[Point] = []
    right: list[Point] = []
    for index, point in enumerate(spine):
        if index == 0:
            local_tangent = _norm(_sub(spine[1], spine[0]))
        elif index == len(spine) - 1:
            local_tangent = _norm(_sub(spine[-1], spine[-2]))
        else:
            local_tangent = _norm(_sub(spine[index + 1], spine[index - 1]))
        local_normal = _normal(local_tangent)
        left_local = _add(point, _mul(local_normal, left_halves[index]))
        right_local = _add(point, _mul(local_normal, -right_halves[index]))
        left.append(_local_to_world(origin, tangent, left_local))
        right.append(_local_to_world(origin, tangent, right_local))
    return left + list(reversed(right))


def _leaf_envelope(t: float, peak: float = 0.50) -> float:
    if t <= peak:
        return math.sin((t / peak) * math.pi / 2.0) ** 0.84
    return math.cos(((t - peak) / (1.0 - peak)) * math.pi / 2.0) ** 1.12


def _swollen_leaf_paths(
    origin: Point,
    tangent: Point,
    size: float,
    sign: int,
    *,
    compact: bool = False,
) -> list[tuple[list[Point], bool]]:
    """A leaf grown from the real branch tip rather than pasted onto it."""
    length = size * (1.58 if compact else 2.05)
    bend = size * (0.42 if compact else 0.62)
    spine = _cubic(
        (0.0, 0.0),
        (length * 0.28, sign * bend * 0.04),
        (length * 0.68, sign * bend),
        (length, sign * bend * 0.34),
        samples=34,
    )
    peak = 0.48 if compact else 0.52
    max_half = size * (0.31 if compact else 0.43)
    root_half = max(0.72, size * 0.055)
    left_halves: list[float] = []
    right_halves: list[float] = []
    for index in range(len(spine)):
        t = index / (len(spine) - 1)
        envelope = _leaf_envelope(t, peak)
        entry = min(1.0, t / 0.20)
        half = root_half * (1.0 - entry) + max_half * envelope * entry
        lobe = 1.0 + 0.12 * math.sin(math.pi * min(1.0, t / 0.82))
        outer = half * lobe
        inner = half * (0.88 if t > 0.22 else 1.0)
        if sign > 0:
            left_halves.append(outer)
            right_halves.append(inner)
        else:
            left_halves.append(inner)
            right_halves.append(outer)
    return [(_closed_outline(origin, tangent, spine, left_halves, right_halves), True)]


def _swollen_comma_paths(
    origin: Point,
    tangent: Point,
    size: float,
    sign: int,
    *,
    compact: bool = False,
) -> list[tuple[list[Point], bool]]:
    """A broad comma-shaped scroll based on the earlier swollen-tip route."""
    length = size * (1.42 if compact else 1.92)
    rise = size * (0.82 if compact else 1.18)
    spine = _cubic(
        (0.0, 0.0),
        (length * 0.36, sign * rise * 0.02),
        (length * 0.98, sign * rise * 0.58),
        (length * 0.54, sign * rise),
        samples=40,
    )
    peak = 0.66
    max_half = size * (0.34 if compact else 0.48)
    root_half = max(0.74, size * 0.058)
    left_halves: list[float] = []
    right_halves: list[float] = []
    for index in range(len(spine)):
        t = index / (len(spine) - 1)
        envelope = _leaf_envelope(t, peak)
        entry = min(1.0, t / 0.18)
        half = root_half * (1.0 - entry) + max_half * envelope * entry
        outer = half * (1.20 - 0.10 * t)
        inner = half * (0.70 + 0.12 * t)
        if sign > 0:
            left_halves.append(inner)
            right_halves.append(outer)
        else:
            left_halves.append(outer)
            right_halves.append(inner)
    return [(_closed_outline(origin, tangent, spine, left_halves, right_halves), True)]


def _paired_leaf_paths(origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    """Two unequal leaves sharing a branch tip, adapted from the old double motif."""
    first = _swollen_leaf_paths(origin, tangent, size * 0.88, sign, compact=True)
    second_tangent = _norm(
        _add(
            _mul(tangent, math.cos(0.42)),
            _mul(_normal(tangent), -sign * math.sin(0.42)),
        )
    )
    second = _swollen_leaf_paths(origin, second_tangent, size * 0.70, -sign, compact=True)
    return first + second


def _size_value(scale_class: str, scale: float) -> float:
    base = {
        "small": 9.0,
        "medium": 13.5,
        "large": 17.5,
        "hero": 22.0,
        "none": 0.0,
    }.get(scale_class, 11.0)
    return base * scale


def _scroll_paths(origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    neck = size * 0.44
    radius = size * 0.72
    local: list[Point] = [(0.0, 0.0), (neck, 0.0)]
    center = (neck, sign * radius)
    start_angle = -sign * math.pi / 2.0
    turns = math.pi * 1.72
    samples = 32
    for index in range(1, samples + 1):
        t = index / samples
        angle = start_angle + sign * turns * t
        current_radius = radius * (1.0 - 0.58 * t)
        local.append(
            (
                center[0] + math.cos(angle) * current_radius,
                center[1] + math.sin(angle) * current_radius,
            )
        )
    return [([_local_to_world(origin, tangent, point) for point in local], False)]


def _droplet_paths(origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    length = size * 1.72
    width = size * 0.72
    top = _cubic(
        (0.0, 0.0),
        (length * 0.26, sign * width * 0.08),
        (length * 0.61, sign * width),
        (length, 0.0),
        samples=24,
    )
    bottom = _cubic(
        (length, 0.0),
        (length * 0.60, -sign * width * 0.88),
        (length * 0.24, -sign * width * 0.04),
        (0.0, 0.0),
        samples=24,
    )
    local = top + bottom[1:]
    return [([_local_to_world(origin, tangent, point) for point in local], True)]


def _bifurcated_paths(origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    fork = size * 0.48
    shared = [_local_to_world(origin, tangent, (0.0, 0.0)), _local_to_world(origin, tangent, (fork, 0.0))]
    result: list[tuple[list[Point], bool]] = []
    for branch_sign, ratio in ((sign, 1.0), (-sign, 0.82)):
        length = size * (1.20 * ratio)
        local = _cubic(
            (fork, 0.0),
            (fork + length * 0.28, branch_sign * size * 0.10),
            (fork + length * 0.58, branch_sign * size * 0.62),
            (fork + length, branch_sign * size * 0.52),
        )
        world = [shared[0], shared[1]] + [_local_to_world(origin, tangent, point) for point in local[1:]]
        result.append((world, False))
    return result


def _motif_paths(kind: str, origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    return terminal_geo.motif_paths(kind, origin, tangent, size, sign)


def _path_issues(
    paths: list[tuple[list[Point], bool]],
    flowers: list[dict[str, object]],
    obstacles: dict[str, list[Point]],
    owner_id: str,
    origin: Point,
    bounds: tuple[float, float, float, float],
) -> list[str]:
    issues: list[str] = []
    min_x, min_y, max_x, max_y = bounds
    for points, _ in paths:
        if any(
            point[0] < min_x or point[0] > max_x or point[1] < min_y or point[1] > max_y
            for point in points
        ):
            issues.append("repeat_boundary_violation")
            break
        if any(geo._inside_flower(point, flower, padding=1.04) for point in points[1:] for flower in flowers):
            issues.append("flower_overlap")
            break
        for obstacle_id, obstacle in obstacles.items():
            if obstacle_id == owner_id:
                continue
            if geo._crosses_path(points, obstacle, origin, False):
                issues.append(f"structure_crossing:{obstacle_id}")
                break
        if issues:
            break
    return issues


def _terminal_sign(branch_id: str) -> int:
    return terminal_geo.terminal_sign(branch_id)


def _terminal_priority(entry: dict[str, object]) -> tuple[int, float, str]:
    tier = str(entry.get("terminal", {}).get("visual_tier", "accent"))
    tier_rank = {"dominant": 0, "support": 1, "accent": 2}.get(tier, 3)
    return tier_rank, -float(entry.get("length_budget", 0.0)), str(entry["branch_id"])


def _motif_bbox_area(motif: dict[str, object]) -> float:
    points = [
        point
        for path in motif["paths"]
        for point in _as_points(path["points"])
    ]
    if not points:
        return 0.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def _draw_composition_mask(
    profile: dict[str, object],
    geometry: dict[str, object],
    motifs: list[dict[str, object]],
) -> Image.Image:
    width = 256
    height = max(1, round(float(profile["canvas"]["height"])))
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    backbone = _as_points(sample["point"] for sample in profile["backbone"]["arc_samples"])
    draw.line(backbone, fill=255, width=5, joint="curve")
    for entry in geometry["branches"]:
        if entry["status"] != "accepted":
            continue
        generation = int(entry["generation"])
        branch_width = 4 if generation == 1 else 2 if generation == 2 else 1
        draw.line(_as_points(entry["points"]), fill=255, width=branch_width, joint="curve")
    for motif in motifs:
        for path in motif["paths"]:
            points = _as_points(path["points"])
            if bool(path["closed"]) and len(points) >= 3:
                draw.polygon(points, fill=255)
            elif len(points) >= 2:
                draw.line(points, fill=255, width=2, joint="curve")
    for motif in motifs:
        for path in motif.get("detail_paths", []):
            points = _as_points(path["points"])
            if bool(path["closed"]) and len(points) >= 3:
                draw.polygon(points, fill=0)
            elif len(points) >= 2:
                draw.line(points, fill=0, width=2, joint="curve")
    return mask


def _mask_ratio(mask: Image.Image) -> float:
    histogram = mask.histogram()
    total = mask.width * mask.height
    return (total - histogram[0]) / total


def _coverage_mask(mask: Image.Image) -> Image.Image:
    size = COMPOSITION_DILATION_RADIUS * 2 + 1
    return mask.filter(ImageFilter.MaxFilter(size=size))


def _composition_density(
    profile: dict[str, object],
    geometry: dict[str, object],
    motifs: list[dict[str, object]],
) -> dict[str, float]:
    mask = _draw_composition_mask(profile, geometry, motifs)
    projected = mask.copy()
    projected_draw = ImageDraw.Draw(projected)
    for flower in _normalized_flowers(profile):
        center = tuple(float(value) for value in flower["center"])
        rx = float(flower["rx"])
        ry = float(flower["ry"])
        projected_draw.ellipse(
            [center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry],
            fill=255,
        )
    ink_ratio = _mask_ratio(mask)
    coverage_ratio = _mask_ratio(_coverage_mask(mask))
    return {
        "foliage_ink_ratio": ink_ratio,
        "actual_ink_ratio": ink_ratio,
        "composition_coverage_ratio": coverage_ratio,
        "projected_with_flower_ratio": _mask_ratio(projected),
        "coverage_target": COMPOSITION_COVERAGE_TARGET,
        "ink_target": COMPOSITION_INK_TARGET,
        "dilation_radius": float(COMPOSITION_DILATION_RADIUS),
        "coverage_target_met": float(coverage_ratio >= COMPOSITION_COVERAGE_TARGET),
        "ink_target_met": float(ink_ratio >= COMPOSITION_INK_TARGET),
    }


def _normalized_flower(flower: dict[str, object]) -> dict[str, object]:
    raw_rx = float(flower["rx"])
    raw_ry = float(flower["ry"])
    scale = min(1.0, 49.0 / max(raw_rx, 1.0), 72.0 / max(raw_ry, 1.0))
    return {
        **flower,
        "rx": raw_rx * scale,
        "ry": raw_ry * scale,
    }


def _normalized_flowers(profile: dict[str, object]) -> list[dict[str, object]]:
    return [_normalized_flower(flower) for flower in profile["flowers"]]


def _flower_head_paths(
    flower: dict[str, object],
) -> tuple[list[tuple[list[Point], bool]], list[tuple[list[Point], bool]]]:
    normalized = _normalized_flower(flower)
    center = tuple(float(value) for value in normalized["center"])
    rx = float(normalized["rx"])
    ry = float(normalized["ry"])
    outer: list[Point] = []
    for index in range(128):
        angle = math.tau * index / 128
        radius = 0.96 + 0.08 * math.cos(8.0 * angle)
        outer.append(
            (
                center[0] + math.cos(angle) * rx * radius,
                center[1] + math.sin(angle) * ry * radius,
            )
        )
    details: list[tuple[list[Point], bool]] = []
    for index in range(8):
        angle = -math.pi / 2.0 + math.tau * index / 8
        radial = (math.cos(angle) * rx, math.sin(angle) * ry)
        side = (-math.sin(angle) * rx, math.cos(angle) * ry)
        details.append(
            (
                _cubic(
                    _add(center, _mul(radial, 0.22)),
                    _add(center, _add(_mul(radial, 0.42), _mul(side, 0.055))),
                    _add(center, _add(_mul(radial, 0.66), _mul(side, -0.045))),
                    _add(center, _mul(radial, 0.82)),
                    samples=18,
                ),
                False,
            )
        )
    center_path = [
        (
            center[0] + math.cos(math.tau * index / 24) * rx * 0.13,
            center[1] + math.sin(math.tau * index / 24) * ry * 0.13,
        )
        for index in range(24)
    ]
    details.append((center_path, True))
    return [(outer, True)], details


def _flower_head_motifs(profile: dict[str, object]) -> list[dict[str, object]]:
    motifs: list[dict[str, object]] = []
    for flower in profile["flowers"]:
        flower_id = str(flower["flower_id"])
        paths, detail_paths = _flower_head_paths(flower)
        motifs.append(
            {
                "terminal_id": f"{flower_id}_head",
                "branch_id": flower_id,
                "role": "flower_head",
                "kind": "flower_head",
                "requested_kind": "flower_head",
                "scale_class": "hero",
                "visual_tier": "hero",
                "applied_scale": 1.0,
                "sign": 1,
                "path_ids": [f"{flower_id}_petal_{index + 1}" for index in range(len(paths))],
                "paths": [
                    {"points": points, "closed": closed}
                    for points, closed in paths
                ],
                "detail_paths": [
                    {"points": points, "closed": closed}
                    for points, closed in detail_paths
                ],
                "planning_mode": "reserved_flower_shape",
            }
        )
    return motifs


def _candidate_mask(
    profile: dict[str, object],
    paths: list[tuple[list[Point], bool]],
) -> Image.Image:
    mask = Image.new(
        "L",
        (256, max(1, round(float(profile["canvas"]["height"])))),
        0,
    )
    draw = ImageDraw.Draw(mask)
    for points, closed in paths:
        if closed and len(points) >= 3:
            draw.polygon(points, fill=255)
        elif len(points) >= 2:
            draw.line(points, fill=255, width=2, joint="curve")
    return mask


def _maximum_local_turn_degrees(points: list[Point]) -> float:
    previous: Point | None = None
    maximum_turn = 0.0
    for first, second in zip(points, points[1:]):
        delta = _sub(second, first)
        if math.hypot(delta[0], delta[1]) <= 1e-6:
            continue
        direction = _norm(delta)
        if previous is not None:
            maximum_turn = max(
                maximum_turn,
                math.degrees(
                    math.acos(
                        max(-1.0, min(1.0, geo._dot(previous, direction)))
                    )
                ),
            )
        previous = direction
    return maximum_turn


def _carrier_curve_is_smooth(
    paths: list[tuple[list[Point], bool]],
) -> bool:
    if not paths or paths[0][1]:
        return True
    points = paths[0][0]
    metrics = geo._curve_shape_metrics(points)
    if metrics["chord_length"] < 25.0:
        return True
    return (
        metrics["max_deviation_ratio"] >= 0.065
        and 1.015 <= metrics["arc_ratio"] <= 1.52
        and _maximum_local_turn_degrees(points) <= 23.0
    )


def _foliage_candidate_valid(
    paths: list[tuple[list[Point], bool]],
    *,
    owner_id: str,
    flowers: list[dict[str, object]],
    structure_paths: dict[str, tuple[list[Point], bool]],
    obstacle_paths: list[tuple[list[Point], bool]],
    bounds: tuple[float, float, float, float],
    allow_flower_underpass: bool = False,
) -> bool:
    if not _carrier_curve_is_smooth(paths):
        return False
    min_x, min_y, max_x, max_y = bounds
    for path_index, (points, closed) in enumerate(paths):
        if any(
            point[0] < min_x
            or point[0] > max_x
            or point[1] < min_y
            or point[1] > max_y
            for point in points
        ):
            return False
        if _invalid_flower_overlap(
            points,
            flowers,
            allow_prefix=allow_flower_underpass and path_index == 0 and not closed,
        ):
            return False
        for structure_id, (structure, structure_closed) in structure_paths.items():
            if structure_id == owner_id:
                continue
            if geo._paths_overlap(points, closed, structure, structure_closed):
                return False
        for obstacle, obstacle_closed in obstacle_paths:
            if geo._paths_overlap(points, closed, obstacle, obstacle_closed):
                return False
    return True


def _invalid_flower_overlap(
    points: list[Point],
    flowers: list[dict[str, object]],
    *,
    allow_prefix: bool,
) -> bool:
    for flower in flowers:
        inside = [
            geo._inside_flower(point, flower, padding=1.02)
            for point in points
        ]
        if not any(inside):
            continue
        if not allow_prefix or all(inside) or inside[-1]:
            return True
        entered = False
        exited = False
        for is_inside in inside:
            if is_inside:
                if exited:
                    return True
                entered = True
            elif entered:
                exited = True
        if not entered or not exited:
            return True
    return False


def _soft_flow_curve(
    origin: Point,
    start_tangent: Point,
    target: Point,
    end_tangent: Point,
    *,
    bend_sign: int,
    s_flow: bool,
    amplitude_scale: float = 1.0,
    curve_style: str = "soft_c",
    samples: int = 40,
) -> list[Point]:
    """Build a tangent-continuous C/S carrier with gradual curvature changes."""
    direct = _sub(target, origin)
    length = max(1.0, math.hypot(direct[0], direct[1]))
    direct_axis = _norm(direct)
    side_axis = _normal(direct_axis)
    start_tangent = _norm(start_tangent)
    end_tangent = _norm(end_tangent)
    start_handle = min(34.0, max(8.0, length * 0.35))
    end_handle = min(30.0, max(7.0, length * 0.31))

    if length >= 30.0:
        style = curve_style if curve_style in CURVE_STYLES else "soft_c"
        style_settings = {
            "soft_c": (1.00, 0.54, 0.18, 0.50, 0.80),
            "deep_c": (1.28, 0.94, 0.30, 0.48, 0.80),
            "s_sweep": (1.04, -0.82, -0.32, 0.46, 0.78),
            "hook": (0.88, 1.34, 0.46, 0.50, 0.84),
            "recurve": (-0.62, 1.14, 0.38, 0.43, 0.79),
        }
        mid_factor, late_factor, tail_turn, mid_pos, late_pos = style_settings[style]
        midpoint_amplitude = (
            min(18.0, length * 0.125)
            if s_flow
            else min(22.0, length * 0.155)
        ) * amplitude_scale
        midpoint = _add(
            _add(origin, _mul(direct, mid_pos)),
            _mul(side_axis, bend_sign * midpoint_amplitude * mid_factor),
        )
        latepoint = _add(
            _add(origin, _mul(direct, late_pos)),
            _mul(side_axis, bend_sign * midpoint_amplitude * late_factor),
        )
        mid_tangent = _norm(
            _add(
                direct_axis,
                _mul(
                    side_axis,
                    bend_sign
                    * (
                        0.34 * late_factor
                        - 0.12 * mid_factor
                        - (0.18 if s_flow else 0.0)
                    ),
                ),
            )
        )
        late_tangent = _norm(
            _add(
                direct_axis,
                _mul(side_axis, bend_sign * (0.30 * late_factor)),
            )
        )
        end_tangent = terminal_geo.turn(end_tangent, bend_sign * tail_turn)
        mid_handle = min(20.0, max(8.0, length * 0.16))
        late_handle = min(18.0, max(7.0, length * 0.13))
        first_samples = max(14, samples // 3)
        second_samples = max(14, samples // 3)
        third_samples = max(14, samples - first_samples - second_samples)
        first = _cubic(
            origin,
            _add(origin, _mul(start_tangent, start_handle)),
            _add(midpoint, _mul(mid_tangent, -mid_handle)),
            midpoint,
            samples=first_samples,
        )
        second = _cubic(
            midpoint,
            _add(midpoint, _mul(mid_tangent, mid_handle)),
            _add(latepoint, _mul(late_tangent, -late_handle)),
            latepoint,
            samples=second_samples,
        )
        third = _cubic(
            latepoint,
            _add(latepoint, _mul(late_tangent, late_handle)),
            _add(target, _mul(end_tangent, -end_handle)),
            target,
            samples=third_samples,
        )
        curve = first + second[1:] + third[1:]
        return curve

    curve = _cubic(
        origin,
        _add(origin, _mul(start_tangent, start_handle)),
        _add(target, _mul(end_tangent, -end_handle)),
        target,
        samples=samples,
    )
    return curve


def _curve_style_options(key: str, stem_length: float) -> tuple[str, ...]:
    if stem_length < 30.0:
        base = ("soft_c", "hook", "recurve")
    elif stem_length < 52.0:
        base = ("deep_c", "s_sweep", "hook", "soft_c")
    else:
        base = CURVE_STYLES
    start = int(_stable_fraction(key) * len(base)) % len(base)
    count = 1
    return tuple(base[(start + offset) % len(base)] for offset in range(count))


def _branch_leaf_unit_paths(
    origin: Point,
    carrier_tangent: Point,
    *,
    angle: float,
    stem_length: float,
    leaf_size: float,
    sign: int,
    leaf_count: int,
    curve_style: str,
) -> list[tuple[list[Point], bool]]:
    """Create one coherent sprig: delayed-turn stem, alternating leaves, terminal leaf."""
    terminal_bias = {
        "soft_c": 0.04,
        "deep_c": 0.10,
        "s_sweep": -0.12,
        "hook": 0.18,
        "recurve": 0.14,
    }.get(curve_style, 0.04)
    growth_tangent = terminal_geo.turn(carrier_tangent, sign * (angle + terminal_bias))
    target = _add(origin, _mul(growth_tangent, stem_length))
    stem = _soft_flow_curve(
        origin,
        carrier_tangent,
        target,
        growth_tangent,
        bend_sign=sign,
        s_flow=curve_style in {"s_sweep", "recurve"} or stem_length >= 46.0,
        amplitude_scale={
            "soft_c": 1.05,
            "deep_c": 1.22,
            "s_sweep": 1.12,
            "hook": 1.18,
            "recurve": 1.20,
        }.get(curve_style, 1.05),
        curve_style=curve_style,
        samples=42,
    )
    paths: list[tuple[list[Point], bool]] = [(stem, False)]
    side_fractions = (
        (0.26, 0.46, 0.65, 0.84)
        if curve_style in {"deep_c", "hook"}
        else (0.32, 0.50, 0.69, 0.86)
        if curve_style == "s_sweep"
        else (0.28, 0.48, 0.66, 0.82)
    )
    for leaf_index, fraction in enumerate(side_fractions[: max(1, leaf_count - 1)]):
        leaf_origin, stem_tangent = geo._sample_polyline(stem, fraction)
        leaf_sign = -sign if leaf_index % 2 == 0 else sign
        leaf_tangent = terminal_geo.turn(
            stem_tangent,
            leaf_sign * (0.72 if leaf_index == 0 else 0.58),
        )
        paths.extend(
            terminal_geo.swollen_leaf_paths(
                leaf_origin,
                leaf_tangent,
                leaf_size * (0.76 if leaf_index == 0 else 0.64),
                leaf_sign,
                compact=True,
                width_scale=1.08,
            )
        )
    tip_tangent = _norm(_sub(stem[-1], stem[-3]))
    paths.extend(
        terminal_geo.swollen_leaf_paths(
            stem[-1],
            terminal_geo.turn(
                tip_tangent,
                sign
                * (
                    0.30
                    if curve_style == "hook"
                    else 0.24
                    if curve_style in {"deep_c", "recurve"}
                    else 0.16
                ),
            ),
            leaf_size,
            sign,
            width_scale=1.08,
        )
    )
    return paths


def _flower_flank_unit_paths(
    origin: Point,
    carrier_tangent: Point,
    flower: dict[str, object],
    *,
    flank_sign: int,
) -> list[tuple[list[Point], bool]]:
    """Grow a long leaf-bearing branch behind one flower and out along its flank."""
    center = tuple(float(value) for value in flower["center"])
    rx = float(flower["rx"])
    ry = float(flower["ry"])
    vertical_sign = (
        -1
        if str(flower.get("vertical_relation", "above_backbone")) == "above_backbone"
        else 1
    )
    target = (
        center[0] + flank_sign * rx * 1.15,
        center[1] + vertical_sign * ry * 1.15,
    )
    waypoint = (
        center[0] + flank_sign * rx * 1.38,
        center[1] + vertical_sign * ry * 0.05,
    )
    incoming_axis = _norm(_sub(waypoint, origin))
    outgoing_axis = _norm(_sub(target, waypoint))
    waypoint_tangent = _norm(
        _add(incoming_axis, outgoing_axis)
    )
    end_tangent = outgoing_axis
    total_length = max(1.0, _dist(origin, waypoint) + _dist(waypoint, target))
    start_handle = min(34.0, max(10.0, total_length * 0.18))
    mid_handle = min(24.0, max(10.0, total_length * 0.13))
    end_handle = min(28.0, max(9.0, total_length * 0.16))
    first = _cubic(
        origin,
        _add(origin, _mul(_norm(carrier_tangent), start_handle)),
        _add(waypoint, _mul(waypoint_tangent, -mid_handle)),
        waypoint,
        samples=24,
    )
    second = _cubic(
        waypoint,
        _add(waypoint, _mul(waypoint_tangent, mid_handle)),
        _add(target, _mul(end_tangent, -end_handle)),
        target,
        samples=24,
    )
    stem = first + second[1:]
    paths: list[tuple[list[Point], bool]] = [(stem, False)]
    for leaf_index, fraction in enumerate((0.74, 0.86, 0.94)):
        leaf_origin, stem_tangent = geo._sample_polyline(stem, fraction)
        leaf_sign = -flank_sign if leaf_index % 2 == 0 else flank_sign
        paths.extend(
            terminal_geo.swollen_leaf_paths(
                leaf_origin,
                terminal_geo.turn(stem_tangent, leaf_sign * 0.62),
                8.5,
                leaf_sign,
                compact=True,
                width_scale=1.04,
            )
        )
    tip_tangent = _norm(_sub(stem[-1], stem[-3]))
    paths.extend(
        terminal_geo.swollen_leaf_paths(
            stem[-1],
            terminal_geo.turn(tip_tangent, flank_sign * 0.16),
            11.5,
            flank_sign,
            width_scale=1.05,
        )
    )
    return paths


def _carrier_leaf_pair_paths(
    origin: Point,
    carrier_tangent: Point,
    *,
    leaf_size: float,
    sign: int,
) -> list[tuple[list[Point], bool]]:
    """Attach two staggered medium leaves to an existing carrier branch."""
    paths: list[tuple[list[Point], bool]] = []
    for index, (offset, leaf_sign, scale) in enumerate(
        (
            (0.0, sign, 1.0),
            (leaf_size * 0.62, -sign, 0.86),
        )
    ):
        petiole_origin = _add(origin, _mul(carrier_tangent, offset))
        leaf_tangent = terminal_geo.turn(
            carrier_tangent,
            leaf_sign * (0.84 if index == 0 else 0.72),
        )
        petiole_length = leaf_size * (0.48 if index == 0 else 0.40)
        leaf_origin = _add(petiole_origin, _mul(leaf_tangent, petiole_length))
        paths.append(([petiole_origin, leaf_origin], False))
        paths.extend(
            terminal_geo.swollen_leaf_paths(
                leaf_origin,
                leaf_tangent,
                leaf_size * scale,
                leaf_sign,
                compact=True,
                width_scale=1.05,
            )
        )
    return paths


def _carrier_single_leaf_paths(
    origin: Point,
    carrier_tangent: Point,
    *,
    leaf_size: float,
    sign: int,
) -> list[tuple[list[Point], bool]]:
    leaf_tangent = terminal_geo.turn(carrier_tangent, sign * 0.78)
    leaf_origin = _add(origin, _mul(leaf_tangent, leaf_size * 0.44))
    return [
        ([origin, leaf_origin], False),
        *terminal_geo.swollen_leaf_paths(
            leaf_origin,
            leaf_tangent,
            leaf_size,
            sign,
            compact=True,
            width_scale=1.06,
        ),
    ]


def _coverage_gap_targets(
    profile: dict[str, object],
    geometry: dict[str, object],
    motifs: list[dict[str, object]],
    *,
    limit: int = 12,
) -> list[Point]:
    coverage = np.asarray(
        _coverage_mask(_draw_composition_mask(profile, geometry, motifs)),
        dtype=np.uint8,
    )
    uncovered = coverage == 0
    height, width = uncovered.shape
    cell = 24
    margin_x = 12
    margin_y = 8
    scored: list[tuple[int, Point]] = []
    for y0 in range(margin_y, height - margin_y, cell):
        for x0 in range(margin_x, width - margin_x, cell):
            y1 = min(height - margin_y, y0 + cell)
            x1 = min(width - margin_x, x0 + cell)
            block = uncovered[y0:y1, x0:x1]
            score = int(np.count_nonzero(block))
            if score < cell * cell * 0.42:
                continue
            ys, xs = np.nonzero(block)
            if len(xs) == 0:
                continue
            target = (
                float(x0 + np.mean(xs)),
                min(
                    float(height - 30),
                    max(30.0, float(y0 + np.mean(ys))),
                ),
            )
            scored.append((score, target))
    scored.sort(key=lambda item: item[0], reverse=True)
    targets: list[Point] = []
    for _, target in scored:
        if any(_dist(target, existing) < 42.0 for existing in targets):
            continue
        targets.append(target)
        if len(targets) >= limit:
            break
    return targets


def _gap_target_unit_paths(
    origin: Point,
    carrier_tangent: Point,
    target: Point,
    *,
    bend_sign: int,
    leaf_size: float,
    curve_style: str,
) -> list[tuple[list[Point], bool]]:
    direct = _norm(_sub(target, origin))
    distance = _dist(origin, target)
    target_tangent = terminal_geo.turn(
        direct,
        -bend_sign * (0.20 if distance >= 90.0 else 0.12),
    )
    stem = _soft_flow_curve(
        origin,
        carrier_tangent,
        target,
        target_tangent,
        bend_sign=bend_sign,
        s_flow=curve_style in {"s_sweep", "recurve"} or distance >= 68.0,
        amplitude_scale={
            "soft_c": 1.08,
            "deep_c": 1.22,
            "s_sweep": 1.14,
            "hook": 1.18,
            "recurve": 1.20,
        }.get(curve_style, 1.08),
        curve_style=curve_style,
        samples=46,
    )
    paths: list[tuple[list[Point], bool]] = [(stem, False)]
    side_fractions = (
        (0.28, 0.43, 0.58, 0.73, 0.86)
        if distance >= 90.0
        else (0.48, 0.66, 0.82)
    )
    for leaf_index, fraction in enumerate(side_fractions):
        leaf_origin, stem_tangent = geo._sample_polyline(stem, fraction)
        leaf_sign = -bend_sign if leaf_index % 2 == 0 else bend_sign
        paths.extend(
            terminal_geo.swollen_leaf_paths(
                leaf_origin,
                terminal_geo.turn(stem_tangent, leaf_sign * 0.62),
                leaf_size * (0.78 if leaf_index == 0 else 0.68),
                leaf_sign,
                compact=True,
                width_scale=1.04,
            )
        )
    tip_tangent = _norm(_sub(stem[-1], stem[-3]))
    paths.extend(
        terminal_geo.swollen_leaf_paths(
            stem[-1],
            terminal_geo.turn(tip_tangent, bend_sign * 0.18),
            leaf_size,
            bend_sign,
            width_scale=1.06,
        )
    )
    return paths


def _foliage_candidates(
    profile: dict[str, object],
    geometry: dict[str, object],
    motifs: list[dict[str, object]],
) -> list[dict[str, object]]:
    repeat_x_range = tuple(float(value) for value in profile["repeat_x_range"])
    bounds = (
        repeat_x_range[0] + 1.5,
        1.5,
        repeat_x_range[1] - 1.5,
        float(profile["canvas"]["height"]) - 1.5,
    )
    flowers = _normalized_flowers(profile)
    backbone = _as_points(sample["point"] for sample in profile["backbone"]["arc_samples"])
    structure_paths: dict[str, tuple[list[Point], bool]] = {
        "backbone": (backbone, False)
    }
    carriers: list[tuple[str, list[Point], int]] = [("backbone", backbone, 0)]
    for entry in geometry["branches"]:
        if entry["status"] != "accepted":
            continue
        branch_id = str(entry["branch_id"])
        points = _as_points(entry["points"])
        structure_paths[branch_id] = (points, False)
        generation = int(entry["generation"])
        if generation <= 2:
            carriers.append((branch_id, points, generation))
    obstacle_paths = [
        (_as_points(path["points"]), bool(path["closed"]))
        for motif in motifs
        if motif.get("kind") != "flower_head"
        for path in motif["paths"]
    ]
    candidates: list[dict[str, object]] = []
    for owner_id, carrier, generation in carriers:
        if generation == 0:
            fractions = (
                0.05,
                0.12,
                0.19,
                0.26,
                0.33,
                0.40,
                0.48,
                0.56,
                0.64,
                0.72,
                0.80,
                0.88,
                0.95,
            )
            angles = (0.54, 0.84)
            unit_options = (
                (22.0, 9.0),
                (34.0, 13.5),
                (46.0, 13.5),
                (58.0, 16.5),
                (72.0, 13.5),
            )
        elif generation == 1:
            fractions = (0.12, 0.24, 0.36, 0.48, 0.60, 0.72, 0.84, 0.92)
            angles = (0.50, 0.80)
            unit_options = (
                (20.0, 8.0),
                (30.0, 12.5),
                (42.0, 12.5),
                (54.0, 15.5),
                (68.0, 12.5),
            )
        else:
            fractions = (0.20, 0.36, 0.52, 0.68, 0.84)
            angles = (0.58, 0.78)
            unit_options = (
                (18.0, 7.5),
                (26.0, 10.0),
                (38.0, 12.5),
            )
        for fraction in fractions:
            origin, carrier_tangent = geo._sample_polyline(carrier, fraction)
            origin_in_flower = any(
                geo._inside_flower(origin, flower, padding=1.20)
                for flower in flowers
            )
            if origin_in_flower and owner_id != "backbone":
                continue
            for sign in (-1, 1):
                for angle in angles:
                    for stem_length, size in unit_options:
                        leaf_count = (
                            2
                            if stem_length <= 34.0
                            else 3
                            if stem_length < 50.0
                            else 4
                            if stem_length <= 64.0
                            else 5
                        )
                        style_key = (
                            f"{owner_id}:{fraction:.3f}:{sign}:{angle:.2f}:"
                            f"{stem_length:.1f}"
                        )
                        for curve_style in _curve_style_options(style_key, stem_length):
                            paths = _branch_leaf_unit_paths(
                                origin,
                                carrier_tangent,
                                angle=angle,
                                stem_length=stem_length,
                                leaf_size=size,
                                sign=sign,
                                leaf_count=leaf_count,
                                curve_style=curve_style,
                            )
                            if not _foliage_candidate_valid(
                                paths,
                                owner_id=owner_id,
                                flowers=flowers,
                                structure_paths=structure_paths,
                                obstacle_paths=obstacle_paths,
                                bounds=bounds,
                                allow_flower_underpass=origin_in_flower and owner_id == "backbone",
                            ):
                                continue
                            curve_metrics = geo._curve_shape_metrics(paths[0][0])
                            candidates.append(
                                {
                                    "candidate_id": (
                                        f"{owner_id}_unit_{round(fraction * 100):02d}_"
                                        f"{'p' if sign > 0 else 'n'}_{round(angle * 100):02d}_"
                                        f"{stem_length:g}_{size:g}_{curve_style}"
                                    ),
                                    "owner_id": owner_id,
                                    "fraction": fraction,
                                    "kind": "branch_leaf_unit",
                                    "mode": "branch_leaf_unit",
                                    "size": size,
                                    "leaf_count": leaf_count,
                                    "stem_length": stem_length,
                                    "sign": sign,
                                    "curve_style": curve_style,
                                    "curve_deviation_ratio": curve_metrics["max_deviation_ratio"],
                                    "curve_arc_ratio": curve_metrics["arc_ratio"],
                                    "origin": origin,
                                    "paths": paths,
                                    "mask": _candidate_mask(profile, paths),
                                }
                            )
            if generation <= 1:
                for sign in (-1, 1):
                    pair_size = 9.5 if generation == 0 else 8.8
                    paths = _carrier_leaf_pair_paths(
                        origin,
                        carrier_tangent,
                        leaf_size=pair_size,
                        sign=sign,
                    )
                    if not _foliage_candidate_valid(
                        paths,
                        owner_id=owner_id,
                        flowers=flowers,
                        structure_paths=structure_paths,
                        obstacle_paths=obstacle_paths,
                        bounds=bounds,
                    ):
                        continue
                    candidates.append(
                        {
                            "candidate_id": (
                                f"{owner_id}_pair_{round(fraction * 100):02d}_"
                                f"{'p' if sign > 0 else 'n'}"
                            ),
                            "owner_id": owner_id,
                            "fraction": fraction,
                            "kind": "branch_leaf_unit",
                            "mode": "carrier_leaf_pair",
                            "size": pair_size,
                            "leaf_count": 2,
                            "stem_length": 0.0,
                            "sign": sign,
                            "origin": origin,
                            "paths": paths,
                            "mask": _candidate_mask(profile, paths),
                        }
                    )
                    single_size = 10.0 if generation == 0 else 9.2
                    single_paths = _carrier_single_leaf_paths(
                        origin,
                        carrier_tangent,
                        leaf_size=single_size,
                        sign=sign,
                    )
                    if not _foliage_candidate_valid(
                        single_paths,
                        owner_id=owner_id,
                        flowers=flowers,
                        structure_paths=structure_paths,
                        obstacle_paths=obstacle_paths,
                        bounds=bounds,
                    ):
                        continue
                    candidates.append(
                        {
                            "candidate_id": (
                                f"{owner_id}_single_{round(fraction * 100):02d}_"
                                f"{'p' if sign > 0 else 'n'}"
                            ),
                            "owner_id": owner_id,
                            "fraction": fraction,
                            "kind": "branch_leaf_unit",
                            "mode": "carrier_single_leaf",
                            "size": single_size,
                            "leaf_count": 1,
                            "stem_length": 0.0,
                            "sign": sign,
                            "origin": origin,
                            "paths": single_paths,
                            "mask": _candidate_mask(profile, single_paths),
                        }
                    )
    for flower in flowers:
        nearest_s = float(flower.get("nearest_backbone_s", 0.5))
        for direction in (-1, 1):
            for offset in (0.12, 0.16):
                mount_fraction = nearest_s + direction * offset
                if not 0.04 <= mount_fraction <= 0.96:
                    continue
                origin, carrier_tangent = geo._sample_polyline(
                    backbone,
                    mount_fraction,
                )
                for flank_sign in (-1, 1):
                    paths = _flower_flank_unit_paths(
                        origin,
                        carrier_tangent,
                        flower,
                        flank_sign=flank_sign,
                    )
                    if not _foliage_candidate_valid(
                        paths,
                        owner_id="backbone",
                        flowers=flowers,
                        structure_paths=structure_paths,
                        obstacle_paths=obstacle_paths,
                        bounds=bounds,
                        allow_flower_underpass=True,
                    ):
                        continue
                    candidates.append(
                        {
                            "candidate_id": (
                                f"backbone_flower_flank_{flower['flower_id']}_"
                                f"{round(mount_fraction * 100):02d}_"
                                f"{'p' if flank_sign > 0 else 'n'}"
                            ),
                            "owner_id": "backbone",
                            "fraction": mount_fraction,
                            "kind": "branch_leaf_unit",
                            "mode": "flower_flank_unit",
                            "size": 11.5,
                            "leaf_count": 4,
                            "stem_length": sum(
                                _dist(first, second)
                                for first, second in zip(
                                    paths[0][0],
                                    paths[0][0][1:],
                                )
                            ),
                            "sign": flank_sign,
                            "origin": origin,
                            "paths": paths,
                            "mask": _candidate_mask(profile, paths),
                        }
                    )
    gap_targets = _coverage_gap_targets(profile, geometry, motifs)
    for target_index, target in enumerate(gap_targets):
        carrier_mounts: list[
            tuple[float, str, list[Point], int, float, Point, Point]
        ] = []
        for owner_id, carrier, generation in carriers:
            if generation > 1:
                continue
            for mount_fraction in (
                0.08,
                0.16,
                0.24,
                0.32,
                0.40,
                0.48,
                0.56,
                0.64,
                0.72,
                0.80,
                0.88,
                0.94,
            ):
                origin, carrier_tangent = geo._sample_polyline(
                    carrier,
                    mount_fraction,
                )
                distance = _dist(origin, target)
                if 38.0 <= distance <= 145.0:
                    carrier_mounts.append(
                        (
                            distance,
                            owner_id,
                            carrier,
                            generation,
                            mount_fraction,
                            origin,
                            carrier_tangent,
                        )
                    )
        carrier_mounts.sort(key=lambda item: item[0])
        used_owners: set[str] = set()
        mount_count = 0
        for (
            distance,
            owner_id,
            _,
            _,
            mount_fraction,
            origin,
            carrier_tangent,
        ) in carrier_mounts:
            if owner_id in used_owners:
                continue
            used_owners.add(owner_id)
            mount_count += 1
            leaf_size = 10.5 if distance >= 92.0 else 9.5
            for bend_sign in (-1, 1):
                style_key = (
                    f"gap:{target_index}:{owner_id}:{mount_fraction:.3f}:"
                    f"{bend_sign}:{distance:.1f}"
                )
                for curve_style in _curve_style_options(style_key, distance):
                    paths = _gap_target_unit_paths(
                        origin,
                        carrier_tangent,
                        target,
                        bend_sign=bend_sign,
                        leaf_size=leaf_size,
                        curve_style=curve_style,
                    )
                    if not _foliage_candidate_valid(
                        paths,
                        owner_id=owner_id,
                        flowers=flowers,
                        structure_paths=structure_paths,
                        obstacle_paths=obstacle_paths,
                        bounds=bounds,
                    ):
                        continue
                    curve_metrics = geo._curve_shape_metrics(paths[0][0])
                    candidates.append(
                        {
                            "candidate_id": (
                                f"{owner_id}_gap_{target_index + 1}_"
                                f"{round(mount_fraction * 100):02d}_"
                                f"{'p' if bend_sign > 0 else 'n'}_{curve_style}"
                            ),
                            "owner_id": owner_id,
                            "fraction": mount_fraction,
                            "kind": "branch_leaf_unit",
                            "mode": "gap_target_unit",
                            "size": leaf_size,
                            "leaf_count": 6 if distance >= 90.0 else 4,
                            "stem_length": distance,
                            "sign": bend_sign,
                            "curve_style": curve_style,
                            "curve_deviation_ratio": curve_metrics["max_deviation_ratio"],
                            "curve_arc_ratio": curve_metrics["arc_ratio"],
                            "origin": origin,
                            "target": target,
                            "edge_target": (
                                target[1] <= 36.0
                                or target[1] >= float(profile["canvas"]["height"]) - 36.0
                            ),
                            "paths": paths,
                            "mask": _candidate_mask(profile, paths),
                        }
                    )
            if mount_count >= 3:
                break
    for candidate in candidates:
        candidate["mask_array"] = np.asarray(candidate["mask"], dtype=np.uint8) > 0
        candidate["coverage_array"] = (
            np.asarray(_coverage_mask(candidate["mask"]), dtype=np.uint8) > 0
        )
    return candidates


def _audit_dense_composition(
    profile: dict[str, object],
    geometry: dict[str, object],
    terminal_motifs: list[dict[str, object]],
    composition_motifs: list[dict[str, object]],
) -> dict[str, int]:
    repeat_x_range = tuple(float(value) for value in profile["repeat_x_range"])
    bounds = (
        repeat_x_range[0] + 1.5,
        1.5,
        repeat_x_range[1] - 1.5,
        float(profile["canvas"]["height"]) - 1.5,
    )
    flowers = _normalized_flowers(profile)
    backbone = _as_points(sample["point"] for sample in profile["backbone"]["arc_samples"])
    structure_paths: dict[str, tuple[list[Point], bool, str]] = {
        "backbone": (backbone, False, "backbone")
    }
    for entry in geometry["branches"]:
        if entry["status"] == "accepted":
            structure_paths[str(entry["branch_id"])] = (
                _as_points(entry["points"]),
                False,
                str(entry["role"]),
            )
    terminal_paths = [
        (_as_points(path["points"]), bool(path["closed"]))
        for motif in terminal_motifs
        for path in motif["paths"]
    ]
    foliage = [
        motif for motif in composition_motifs if motif["role"] == "interior_foliage"
    ]
    flower_heads = [
        motif for motif in composition_motifs if motif["role"] == "flower_head"
    ]
    boundary_violation_count = 0
    flower_overlap_count = 0
    structure_overlap_count = 0
    terminal_overlap_count = 0
    foliage_overlap_count = 0
    flower_structure_overlap_count = 0

    for motif in foliage:
        owner_id = str(motif["branch_id"])
        for path_index, path in enumerate(motif["paths"]):
            points = _as_points(path["points"])
            closed = bool(path["closed"])
            boundary_violation_count += int(
                any(
                    point[0] < bounds[0]
                    or point[0] > bounds[2]
                    or point[1] < bounds[1]
                    or point[1] > bounds[3]
                    for point in points
                )
            )
            flower_overlap_count += int(
                _invalid_flower_overlap(
                    points,
                    flowers,
                    allow_prefix=(
                        owner_id == "backbone"
                        and path_index == 0
                        and not closed
                    ),
                )
            )
            structure_overlap_count += int(
                any(
                    structure_id != owner_id
                    and geo._paths_overlap(
                        points,
                        closed,
                        structure,
                        structure_closed,
                    )
                    for structure_id, (structure, structure_closed, _) in structure_paths.items()
                )
            )
            terminal_overlap_count += int(
                any(
                    geo._paths_overlap(
                        points,
                        closed,
                        terminal,
                        terminal_closed,
                    )
                    for terminal, terminal_closed in terminal_paths
                )
            )
    for index, first in enumerate(foliage):
        for second in foliage[index + 1 :]:
            foliage_overlap_count += int(
                any(
                    geo._paths_overlap(
                        _as_points(first_path["points"]),
                        bool(first_path["closed"]),
                        _as_points(second_path["points"]),
                        bool(second_path["closed"]),
                    )
                    for first_path in first["paths"]
                    for second_path in second["paths"]
                )
            )
    for flower_head in flower_heads:
        flower_id = str(flower_head["branch_id"])
        flower = next(
            item for item in flowers if str(item["flower_id"]) == flower_id
        )
        flower_structure_overlap_count += int(
            any(
                role not in {"flower_connector", "backbone"}
                and any(
                    geo._inside_flower(point, flower, padding=0.90)
                    for point in structure
                )
                for structure, _, role in structure_paths.values()
            )
        )
    return {
        "composition_boundary_violation_count": boundary_violation_count,
        "composition_flower_overlap_count": flower_overlap_count,
        "composition_structure_overlap_count": structure_overlap_count,
        "composition_terminal_overlap_count": terminal_overlap_count,
        "composition_foliage_overlap_count": foliage_overlap_count,
        "flower_structure_overlap_count": flower_structure_overlap_count,
        "composition_overlap_count": (
            flower_overlap_count
            + structure_overlap_count
            + terminal_overlap_count
            + foliage_overlap_count
            + flower_structure_overlap_count
        ),
    }


def _composition_curve_quality(
    motifs: list[dict[str, object]],
) -> dict[str, float | int]:
    deviation_ratios: list[float] = []
    arc_ratios: list[float] = []
    maximum_local_turns: list[float] = []
    for motif in motifs:
        if motif.get("placement_mode") not in {
            "branch_leaf_unit",
            "flower_flank_unit",
            "gap_target_unit",
        }:
            continue
        paths = list(motif.get("paths", []))
        if not paths or bool(paths[0].get("closed")):
            continue
        points = _as_points(paths[0]["points"])
        metrics = geo._curve_shape_metrics(points)
        if metrics["chord_length"] < 25.0:
            continue
        deviation_ratios.append(metrics["max_deviation_ratio"])
        arc_ratios.append(metrics["arc_ratio"])
        maximum_local_turns.append(_maximum_local_turn_degrees(points))
    return {
        "measured_curve_count": len(deviation_ratios),
        "mean_deviation_ratio": (
            sum(deviation_ratios) / len(deviation_ratios)
            if deviation_ratios
            else 0.0
        ),
        "mean_arc_ratio": (
            sum(arc_ratios) / len(arc_ratios)
            if arc_ratios
            else 1.0
        ),
        "mean_maximum_local_turn_degrees": (
            sum(maximum_local_turns) / len(maximum_local_turns)
            if maximum_local_turns
            else 0.0
        ),
        "worst_local_turn_degrees": max(maximum_local_turns, default=0.0),
        "abrupt_curve_count": sum(turn > 23.0 for turn in maximum_local_turns),
    }


def _build_dense_composition(
    profile: dict[str, object],
    geometry: dict[str, object],
    terminal_motifs: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    flower_motifs = _flower_head_motifs(profile)
    fixed_motifs = terminal_motifs + flower_motifs
    current_mask = _draw_composition_mask(profile, geometry, fixed_motifs)
    current_array = np.asarray(current_mask, dtype=np.uint8) > 0
    total_pixels = current_array.size
    candidates = _foliage_candidates(profile, geometry, fixed_motifs)
    selected: list[dict[str, object]] = []
    selected_paths: list[tuple[list[Point], bool]] = []
    selected_by_owner: dict[str, list[dict[str, object]]] = {}
    selected_style_counts: dict[str, int] = {}
    short_unit_count = 0
    leaf_pair_count = 0
    single_leaf_count = 0
    minimum_leaf_count = (
        MIN_LEAVES_SINGLE_FLOWER
        if len(profile["flowers"]) == 1
        else MIN_LEAVES_MULTI_FLOWER
    )
    while len(selected) < 42:
        current_mask = Image.fromarray(current_array.astype(np.uint8) * 255, mode="L")
        current_coverage_array = (
            np.asarray(_coverage_mask(current_mask), dtype=np.uint8) > 0
        )
        current_coverage = float(np.count_nonzero(current_coverage_array)) / total_pixels
        current_ink = float(np.count_nonzero(current_array)) / total_pixels
        current_leaf_count = sum(
            int(candidate.get("leaf_count", 1))
            for candidate in selected
        )
        if (
            current_coverage >= COMPOSITION_COVERAGE_TARGET
            and current_ink >= COMPOSITION_INK_TARGET
            and current_leaf_count >= minimum_leaf_count
        ):
            break
        best: dict[str, object] | None = None
        best_score = 0.0
        for candidate in candidates:
            paths = list(candidate["paths"])
            if any(
                geo._paths_overlap(
                    points,
                    closed,
                    obstacle,
                    obstacle_closed,
                )
                for points, closed in paths
                for obstacle, obstacle_closed in selected_paths
            ):
                continue
            candidate_array = candidate["mask_array"]
            ink_gain = float(
                np.count_nonzero(candidate_array & ~current_array)
            ) / total_pixels
            coverage_gain = float(
                np.count_nonzero(candidate["coverage_array"] & ~current_coverage_array)
            ) / total_pixels
            owner_id = str(candidate["owner_id"])
            owner_selected = selected_by_owner.get(owner_id, [])
            owner_limit = 14 if owner_id == "backbone" else 8
            if len(owner_selected) >= owner_limit:
                continue
            is_leaf_pair = candidate["mode"] == "carrier_leaf_pair"
            if is_leaf_pair and leaf_pair_count >= 10:
                continue
            is_single_leaf = candidate["mode"] == "carrier_single_leaf"
            if is_single_leaf and single_leaf_count >= 8:
                continue
            is_short_unit = (
                candidate["mode"] == "branch_leaf_unit"
                and float(candidate.get("stem_length", 0.0)) <= 26.0
            )
            if is_short_unit and short_unit_count >= 4:
                continue
            if any(
                abs(float(candidate["fraction"]) - float(existing["fraction"])) < 0.060
                for existing in owner_selected
            ):
                continue
            unit_bonus = (
                0.0032
                if candidate["mode"] == "flower_flank_unit"
                else 0.0029
                if candidate["mode"] == "gap_target_unit"
                else 0.0024
                if candidate["mode"] == "branch_leaf_unit"
                else 0.0014
                if is_leaf_pair
                else 0.0006
                if is_single_leaf
                else -0.0008
            )
            curve_style = str(candidate.get("curve_style", "plain"))
            curve_deviation = float(candidate.get("curve_deviation_ratio", 0.0))
            curve_arc = float(candidate.get("curve_arc_ratio", 1.0))
            curve_bonus = (
                min(0.0030, max(0.0, curve_deviation - 0.060) * 0.030)
                + min(0.0014, max(0.0, curve_arc - 1.030) * 0.018)
            )
            style_bonus = (
                0.0016
                if curve_style in CURVE_STYLES and selected_style_counts.get(curve_style, 0) == 0
                else -0.00035 * selected_style_counts.get(curve_style, 0)
            )
            rhythm_bonus = 0.0
            if owner_selected:
                nearest = min(
                    owner_selected,
                    key=lambda existing: abs(
                        float(candidate["fraction"]) - float(existing["fraction"])
                    ),
                )
                rhythm_bonus = (
                    0.0022
                    if int(candidate["sign"]) != int(nearest["sign"])
                    else -0.0028
                )
                if curve_style == str(nearest.get("curve_style", "plain")):
                    rhythm_bonus -= 0.0015
            score = (
                coverage_gain * 1.45
                + ink_gain * 0.52
                + unit_bonus
                + curve_bonus
                + style_bonus
                + rhythm_bonus
                - (0.0010 if is_short_unit else 0.0)
                - (leaf_pair_count * 0.00012 if is_leaf_pair else 0.0)
                - (single_leaf_count * 0.00010 if is_single_leaf else 0.0)
                - (
                    0.0020
                    if candidate.get("edge_target", False)
                    else 0.0
                )
                - len(owner_selected) * 0.00035
            )
            if score > best_score:
                best = candidate
                best_score = score
        if best is None or best_score < 0.00015:
            break
        selected.append(best)
        selected_by_owner.setdefault(str(best["owner_id"]), []).append(best)
        selected_paths.extend(best["paths"])
        if (
            best["mode"] == "branch_leaf_unit"
            and float(best.get("stem_length", 0.0)) <= 26.0
        ):
            short_unit_count += 1
        if best["mode"] == "carrier_leaf_pair":
            leaf_pair_count += 1
        if best["mode"] == "carrier_single_leaf":
            single_leaf_count += 1
        best_style = str(best.get("curve_style", "plain"))
        selected_style_counts[best_style] = selected_style_counts.get(best_style, 0) + 1
        current_array |= best["mask_array"]
        candidates = [
            candidate
            for candidate in candidates
            if candidate["candidate_id"] != best["candidate_id"]
            and not (
                candidate["owner_id"] == best["owner_id"]
                and abs(float(candidate["fraction"]) - float(best["fraction"])) < 0.060
            )
        ]

    foliage_motifs: list[dict[str, object]] = []
    for index, candidate in enumerate(selected):
        paths = list(candidate["paths"])
        foliage_motifs.append(
            {
                "terminal_id": f"dense_foliage_{index + 1}",
                "branch_id": candidate["owner_id"],
                "role": "interior_foliage",
                "kind": candidate["kind"],
                "requested_kind": candidate["kind"],
                "scale_class": "large" if float(candidate["size"]) >= 18.0 else "medium",
                "visual_tier": "support",
                "applied_scale": 1.0,
                "sign": candidate["sign"],
                "mount_fraction": candidate["fraction"],
                "leaf_count": candidate.get("leaf_count", 1),
                "stem_length": candidate.get("stem_length", 0.0),
                "curve_style": candidate.get("curve_style", "plain"),
                "curve_deviation_ratio": candidate.get("curve_deviation_ratio", 0.0),
                "curve_arc_ratio": candidate.get("curve_arc_ratio", 1.0),
                "path_ids": [
                    f"dense_foliage_{index + 1}_path_{path_index + 1}"
                    for path_index in range(len(paths))
                ],
                "paths": [
                    {"points": points, "closed": closed}
                    for points, closed in paths
                ],
                "planning_mode": "global_coverage_foliage",
                "placement_mode": candidate.get("mode", "direct"),
            }
        )
    all_motifs = terminal_motifs + foliage_motifs + flower_motifs
    density = _composition_density(profile, geometry, all_motifs)
    composition_motifs = foliage_motifs + flower_motifs
    audit = _audit_dense_composition(
        profile,
        geometry,
        terminal_motifs,
        composition_motifs,
    )
    curve_quality = _composition_curve_quality(foliage_motifs)
    return composition_motifs, {
        "foliage_cluster_count": len(foliage_motifs),
        "branch_leaf_unit_count": sum(
            1
            for motif in foliage_motifs
            if motif.get("placement_mode")
            in {"branch_leaf_unit", "flower_flank_unit", "gap_target_unit"}
        ),
        "carrier_leaf_pair_count": sum(
            1
            for motif in foliage_motifs
            if motif.get("placement_mode") == "carrier_leaf_pair"
        ),
        "side_leaf_count": sum(
            1
            for motif in foliage_motifs
            if motif.get("placement_mode") == "carrier_single_leaf"
        ),
        "generated_leaf_count": sum(
            int(motif.get("leaf_count", 1)) for motif in foliage_motifs
        ),
        "minimum_leaf_count": minimum_leaf_count,
        "leaf_quantity_target_met": sum(
            int(motif.get("leaf_count", 1)) for motif in foliage_motifs
        )
        >= minimum_leaf_count,
        "flower_head_count": len(flower_motifs),
        "candidate_count": len(candidates) + len(selected),
        "composition_density": density,
        "coverage_target_met": bool(
            density["composition_coverage_ratio"] >= COMPOSITION_COVERAGE_TARGET
        ),
        "ink_target_met": bool(density["actual_ink_ratio"] >= COMPOSITION_INK_TARGET),
        "curve_quality": curve_quality,
        **audit,
    }


def _select_terminal_entries(entries: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    return terminal_geo.select_terminal_entries(entries)


def _scale_trials(visual_tier: str) -> tuple[float, ...]:
    return terminal_geo.scale_trials(visual_tier)


def _candidate_kinds(kind: str, visual_tier: str) -> list[str]:
    return terminal_geo.candidate_kinds(kind, visual_tier)


def _build_terminal_hint_stem(
    hint: dict[str, object],
    guide: dict[str, object],
    parent_points: list[Point],
) -> list[Point]:
    source = _as_points(guide["points"])
    return geo._curve_candidate(
        source,
        parent_points,
        float(hint["mount_fraction"]),
        role="tertiary_sprig",
        family="c_flow",
        bow_sign=_terminal_sign(str(hint["branch_id"])),
        target_scale=0.82,
        style_strength=0.86,
        graft_scale=0.58,
    )


def _build_joint_terminals(
    profile: dict[str, object],
    geometry: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, list[Point]], dict[str, object]]:
    """Read terminal paths selected together with each branch candidate."""
    flowers = list(profile["flowers"])
    motifs: list[dict[str, object]] = []
    motif_paths: dict[str, list[Point]] = {}
    kind_counts = {
        "leaf_cluster": 0,
        "swollen_comma": 0,
        "swollen_leaf": 0,
        "paired_leaf": 0,
        "compact_leaf": 0,
        "scroll": 0,
        "droplet": 0,
        "bifurcated": 0,
    }
    budget_skipped: list[dict[str, object]] = []
    for entry in geometry["branches"]:
        if entry["status"] != "accepted":
            continue
        plan = dict(entry.get("terminal_plan", {}))
        if not plan.get("selected"):
            if plan.get("reason") == "visual_hierarchy_budget":
                budget_skipped.append(
                    {
                        "branch_id": entry["branch_id"],
                        "role": entry["role"],
                        "visual_tier": entry["terminal"].get("visual_tier", "accent"),
                        "reason": plan["reason"],
                    }
                )
            continue
        terminal_id = f"{entry['branch_id']}_motif"
        paths: list[dict[str, object]] = []
        path_ids: list[str] = []
        terminal_origin = _as_points(entry["points"])[-1]
        visual_tier = str(plan["visual_tier"])
        terminal_scale = {
            "dominant": 0.80,
            "support": 0.90,
            "accent": 0.95,
        }.get(visual_tier, 0.90)
        for path_index, raw_path in enumerate(plan["paths"]):
            points = [
                _add(
                    terminal_origin,
                    _mul(_sub(point, terminal_origin), terminal_scale),
                )
                for point in _as_points(raw_path["points"])
            ]
            closed = bool(raw_path["closed"])
            path_id = f"{terminal_id}_path_{path_index + 1}"
            paths.append({"points": points, "closed": closed})
            path_ids.append(path_id)
            motif_paths[path_id] = points
        kind = str(plan["kind"])
        motifs.append(
            {
                "terminal_id": terminal_id,
                "branch_id": entry["branch_id"],
                "role": entry["role"],
                "kind": kind,
                "requested_kind": plan["requested_kind"],
                "scale_class": plan["scale_class"],
                "visual_tier": visual_tier,
                "applied_scale": plan["applied_scale"],
                "sign": plan["sign"],
                "path_ids": path_ids,
                "paths": paths,
                "planning_mode": "joint_branch_terminal",
            }
        )
        kind_counts[kind] += 1

    crossing_count = 0
    flower_overlap_count = 0
    flat_paths: list[tuple[str, list[Point]]] = list(motif_paths.items())
    for _, points in flat_paths:
        flower_overlap_count += int(
            any(
                geo._inside_flower(point, flower, padding=1.04)
                for point in points[1:]
                for flower in flowers
            )
        )
    for index, (first_id, first) in enumerate(flat_paths):
        first_terminal = first_id.split("_path_")[0]
        for second_id, second in flat_paths[index + 1 :]:
            if second_id.split("_path_")[0] == first_terminal:
                continue
            if geo._crosses_path(first, second, first[0], False):
                crossing_count += 1

    average_area_by_tier: dict[str, float] = {}
    for tier in ("dominant", "support", "accent"):
        tier_areas = [
            _motif_bbox_area(motif)
            for motif in motifs
            if motif["visual_tier"] == tier
        ]
        average_area_by_tier[tier] = sum(tier_areas) / len(tier_areas) if tier_areas else 0.0
    accent_area = average_area_by_tier["accent"]
    hierarchy_area_ratio = (
        average_area_by_tier["dominant"] / accent_area
        if accent_area > 1e-9 and average_area_by_tier["dominant"] > 0.0
        else 0.0
    )
    density = _composition_density(profile, geometry, motifs)
    qa = {
        "valid": (
            crossing_count == 0
            and flower_overlap_count == 0
            and int(geometry["qa"].get("terminal_branch_crossing_count", 0)) == 0
            and int(geometry["qa"].get("terminal_overlap_count", 0)) == 0
            and int(geometry["qa"].get("terminal_boundary_violation_count", 0)) == 0
            and int(geometry["qa"].get("terminal_flower_overlap_count", 0)) == 0
        ),
        "planning_mode": "joint_branch_terminal",
        "accepted_terminal_count": len(motifs),
        "rejected_terminal_count": 0,
        "suppressed_terminal_count": 0,
        "budget_skipped_terminal_count": len(budget_skipped),
        "budget_skipped": budget_skipped,
        "kind_counts": kind_counts,
        "tier_counts": {
            tier: sum(1 for motif in motifs if motif["visual_tier"] == tier)
            for tier in ("dominant", "support", "accent")
        },
        "average_bbox_area_by_tier": average_area_by_tier,
        "dominant_to_accent_area_ratio": hierarchy_area_ratio,
        "composition_density": density,
        "crossing_count": crossing_count,
        "flower_overlap_count": flower_overlap_count,
        "terminal_branch_crossing_count": geometry["qa"].get("terminal_branch_crossing_count", 0),
        "terminal_overlap_count": geometry["qa"].get("terminal_overlap_count", 0),
        "terminal_boundary_violation_count": geometry["qa"].get("terminal_boundary_violation_count", 0),
        "rejected": [],
        "suppressed": [],
    }
    return motifs, motif_paths, qa


def _build_terminals(
    profile: dict[str, object],
    layout: dict[str, object],
    geometry: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, list[Point]], dict[str, object]]:
    accepted_entries = [entry for entry in geometry["branches"] if entry["status"] == "accepted"]
    if accepted_entries and all("terminal_plan" in entry for entry in accepted_entries):
        return _build_joint_terminals(profile, geometry)

    flowers = list(profile["flowers"])
    repeat_x_range = tuple(float(value) for value in profile["repeat_x_range"])
    bounds = (repeat_x_range[0] + 1.5, 1.5, repeat_x_range[1] - 1.5, float(profile["canvas"]["height"]) - 1.5)
    backbone = _as_points(sample["point"] for sample in profile["backbone"]["arc_samples"])
    geometry_entries = {str(entry["branch_id"]): entry for entry in geometry["branches"]}
    branch_paths = {
        branch_id: _as_points(entry["points"])
        for branch_id, entry in geometry_entries.items()
        if entry["status"] == "accepted"
    }
    guide_map = {str(guide["guide_id"]): guide for guide in profile["region_graph"]["guide_edges"]}
    obstacles: dict[str, list[Point]] = {"backbone": backbone, **branch_paths}
    motifs: list[dict[str, object]] = []
    motif_paths: dict[str, list[Point]] = {}
    rejected: list[dict[str, object]] = []
    suppressed: list[dict[str, object]] = []
    kind_counts = {
        "swollen_comma": 0,
        "swollen_leaf": 0,
        "paired_leaf": 0,
        "compact_leaf": 0,
        "scroll": 0,
        "droplet": 0,
        "bifurcated": 0,
    }

    layout_entries, budget_skipped = _select_terminal_entries(list(layout["branches"]))
    for entry in layout_entries:
        branch_id = str(entry["branch_id"])
        role = str(entry["role"])
        if role in {"flower_connector", "terminal_component"}:
            continue
        if role == "terminal_hint":
            parent_id = str(entry["parent_id"])
            parent_points = backbone if parent_id.startswith("backbone_edge_") else branch_paths.get(parent_id)
            if parent_points is None:
                rejected.append({"terminal_id": f"{branch_id}_motif", "reason": "missing_parent"})
                continue
            stem = _build_terminal_hint_stem(entry, guide_map[branch_id], parent_points)
            owner_id = parent_id
            terminal_origin = stem[-1]
            terminal_tangent = _norm(_sub(stem[-1], stem[-3]))
            structure_paths = [(stem, False)]
        else:
            branch_points = branch_paths.get(branch_id)
            if branch_points is None:
                continue
            owner_id = branch_id
            terminal_origin = branch_points[-1]
            terminal_tangent = _norm(_sub(branch_points[-1], branch_points[-3]))
            structure_paths = []

        terminal = dict(entry["terminal"])
        kind = str(terminal["kind"])
        visual_tier = str(terminal.get("visual_tier", "accent"))
        if kind not in {"scroll", "droplet", "bifurcated"}:
            continue
        base_size = _size_value(str(terminal["scale_class"]), 1.0)
        sign = _terminal_sign(branch_id)
        chosen: tuple[list[tuple[list[Point], bool]], float, int, str] | None = None
        attempts: list[dict[str, object]] = []
        candidate_kinds = _candidate_kinds(kind, visual_tier)
        for candidate_kind in candidate_kinds:
            if candidate_kind == "paired_leaf" and kind_counts["paired_leaf"] >= 1:
                continue
            for scale in _scale_trials(visual_tier):
                size = base_size * scale
                for candidate_sign in (sign, -sign):
                    terminal_paths = _motif_paths(candidate_kind, terminal_origin, terminal_tangent, size, candidate_sign)
                    combined = structure_paths + terminal_paths
                    issues = _path_issues(
                        combined,
                        flowers,
                        obstacles,
                        owner_id,
                        structure_paths[0][0][0] if structure_paths else terminal_origin,
                        bounds,
                    )
                    attempts.append({"kind": candidate_kind, "scale": scale, "sign": candidate_sign, "issues": issues})
                    if not issues:
                        chosen = (combined, scale, candidate_sign, candidate_kind)
                        break
                if chosen:
                    break
            if chosen:
                break
        terminal_id = f"{branch_id}_motif"
        if chosen is None:
            issue_names = {
                str(issue)
                for attempt in attempts
                for issue in attempt["issues"]
            }
            suppressible = issue_names and all(
                issue in {"flower_overlap", "repeat_boundary_violation"}
                or issue.startswith("structure_crossing:")
                for issue in issue_names
            )
            if suppressible:
                suppressed.append(
                    {
                        "terminal_id": terminal_id,
                        "branch_id": branch_id,
                        "kind": kind,
                        "reason": (
                            "flower_reserved_tip"
                            if issue_names == {"flower_overlap"}
                            else "boundary_limited_tip"
                            if issue_names == {"repeat_boundary_violation"}
                            else "occupied_branch_tip"
                        ),
                        "blocking_structures": sorted(
                            issue.split(":", 1)[1] for issue in issue_names
                            if issue.startswith("structure_crossing:")
                        ),
                    }
                )
            else:
                rejected.append({"terminal_id": terminal_id, "branch_id": branch_id, "kind": kind, "attempts": attempts})
            continue
        chosen_paths, chosen_scale, chosen_sign, chosen_kind = chosen
        path_ids: list[str] = []
        for path_index, (points, closed) in enumerate(chosen_paths):
            path_id = f"{terminal_id}_path_{path_index + 1}"
            motif_paths[path_id] = points
            obstacles[path_id] = points
            path_ids.append(path_id)
        motifs.append(
            {
                "terminal_id": terminal_id,
                "branch_id": branch_id,
                "role": role,
                "kind": chosen_kind,
                "requested_kind": kind,
                "scale_class": terminal["scale_class"],
                "visual_tier": visual_tier,
                "applied_scale": chosen_scale,
                "sign": chosen_sign,
                "path_ids": path_ids,
                "paths": [{"points": points, "closed": closed} for points, closed in chosen_paths],
            }
        )
        kind_counts[chosen_kind] += 1

    crossing_count = 0
    flower_overlap_count = 0
    flat_paths: list[tuple[str, list[Point]]] = list(motif_paths.items())
    for path_id, points in flat_paths:
        flower_overlap_count += int(any(geo._inside_flower(point, flower, padding=1.04) for point in points[1:] for flower in flowers))
    for index, (first_id, first) in enumerate(flat_paths):
        first_terminal = first_id.split("_path_")[0]
        for second_id, second in flat_paths[index + 1 :]:
            if second_id.split("_path_")[0] == first_terminal:
                continue
            if geo._crosses_path(first, second, first[0], False):
                crossing_count += 1
    average_area_by_tier: dict[str, float] = {}
    for tier in ("dominant", "support", "accent"):
        tier_areas = [
            _motif_bbox_area(motif)
            for motif in motifs
            if motif["visual_tier"] == tier
        ]
        average_area_by_tier[tier] = sum(tier_areas) / len(tier_areas) if tier_areas else 0.0
    accent_area = average_area_by_tier["accent"]
    hierarchy_area_ratio = (
        average_area_by_tier["dominant"] / accent_area
        if accent_area > 1e-9 and average_area_by_tier["dominant"] > 0.0
        else 0.0
    )
    qa = {
        "valid": not rejected and crossing_count == 0 and flower_overlap_count == 0,
        "accepted_terminal_count": len(motifs),
        "rejected_terminal_count": len(rejected),
        "suppressed_terminal_count": len(suppressed),
        "budget_skipped_terminal_count": len(budget_skipped),
        "budget_skipped": budget_skipped,
        "kind_counts": kind_counts,
        "tier_counts": {
            tier: sum(1 for motif in motifs if motif["visual_tier"] == tier)
            for tier in ("dominant", "support", "accent")
        },
        "average_bbox_area_by_tier": average_area_by_tier,
        "dominant_to_accent_area_ratio": hierarchy_area_ratio,
        "crossing_count": crossing_count,
        "flower_overlap_count": flower_overlap_count,
        "rejected": rejected,
        "suppressed": suppressed,
    }
    return motifs, motif_paths, qa


def _font(size: int) -> ImageFont.ImageFont:
    for path in (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/msyh.ttc")):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _render(
    profile: dict[str, object],
    geometry: dict[str, object],
    motifs: list[dict[str, object]],
    qa: dict[str, object],
) -> Image.Image:
    source_width = 256.0
    source_height = float(profile["canvas"]["height"])
    scale = 3.0
    margin_x = 26
    header = 74
    footer = 34
    image = Image.new(
        "RGB",
        (round(source_width * scale) + margin_x * 2, round(source_height * scale) + header + footer),
        PAPER,
    )
    draw = ImageDraw.Draw(image)
    transform = lambda point: (margin_x + round(point[0] * scale), header + round(point[1] * scale))
    draw.text((16, 14), f"{profile['prototype_id']} | branches + terminal motifs", fill=INK, font=_font(18))
    status = "PASS" if qa["valid"] else "FAIL"
    draw.text(
        (16, 42),
        f"{status} terminals={qa['accepted_terminal_count']} rejected={qa['rejected_terminal_count']} "
        f"suppressed={qa['suppressed_terminal_count']} budget_skip={qa['budget_skipped_terminal_count']} "
        f"units={qa.get('branch_leaf_unit_count', 0)} "
        f"leaves={qa.get('generated_leaf_count', 0)}/{qa.get('minimum_leaf_count', 0)} "
        f"pairs={qa.get('carrier_leaf_pair_count', 0)} singles={qa.get('side_leaf_count', 0)} "
        f"flowers={qa.get('flower_head_count', 0)} "
        f"coverage={qa['composition_density']['composition_coverage_ratio']:.3f} "
        f"ink={qa['composition_density']['actual_ink_ratio']:.3f} "
        f"cluster={qa['kind_counts'].get('leaf_cluster', 0)} "
        f"swollen={qa['kind_counts']['swollen_comma'] + qa['kind_counts']['swollen_leaf']} "
        f"paired={qa['kind_counts']['paired_leaf']} compact={qa['kind_counts']['compact_leaf']} "
        f"small={qa['kind_counts']['scroll'] + qa['kind_counts']['droplet']}",
        fill=INK if qa["valid"] else REJECTED,
        font=_font(12),
    )
    backbone = _as_points(sample["point"] for sample in profile["backbone"]["arc_samples"])
    draw.line([transform(point) for point in backbone], fill=INK, width=10, joint="curve")
    for entry in geometry["branches"]:
        if entry["status"] != "accepted":
            continue
        points = _as_points(entry["points"])
        generation = int(entry["generation"])
        width = 8 if generation == 1 else 5 if generation == 2 else 3
        draw.line([transform(point) for point in points], fill=INK, width=width, joint="curve")
    for motif in motifs:
        tier = str(motif.get("visual_tier", "accent"))
        motif_width = {"hero": 4, "dominant": 5, "support": 4, "accent": 3}.get(tier, 3)
        for path in motif["paths"]:
            points = _as_points(path["points"])
            if len(points) < 2:
                continue
            transformed = [transform(point) for point in points]
            if path["closed"] and len(transformed) >= 3:
                draw.polygon(transformed, fill=INK)
            draw.line(transformed, fill=INK, width=motif_width, joint="curve")
            if path["closed"]:
                draw.line([transformed[-1], transformed[0]], fill=INK, width=motif_width)
    for motif in motifs:
        for path in motif.get("detail_paths", []):
            points = _as_points(path["points"])
            if len(points) < 2:
                continue
            transformed = [transform(point) for point in points]
            if path["closed"] and len(transformed) >= 3:
                draw.polygon(transformed, fill=PAPER)
                draw.line(
                    transformed + [transformed[0]],
                    fill=PAPER,
                    width=4,
                    joint="curve",
                )
            else:
                draw.line(transformed, fill=PAPER, width=5, joint="curve")
    draw.text(
        (16, image.height - 25),
        f"composition target: coverage >= {COMPOSITION_COVERAGE_TARGET:.1%}, "
        f"actual ink >= {COMPOSITION_INK_TARGET:.1%}; coverage comes from coordinated branch-leaf units",
        fill="#475569",
        font=_font(12),
    )
    return image


def _svg_path(points: list[Point], closed: bool = False) -> str:
    if not points:
        return ""
    body = " ".join(f"L {point[0]:.3f} {point[1]:.3f}" for point in points[1:])
    return f"M {points[0][0]:.3f} {points[0][1]:.3f} {body}{' Z' if closed else ''}"


def _write_svg(
    path: Path,
    profile: dict[str, object],
    geometry: dict[str, object],
    motifs: list[dict[str, object]],
) -> None:
    height = float(profile["canvas"]["height"])
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 {height:.3f}" width="256" height="{height:.3f}">',
        f'<rect width="256" height="{height:.3f}" fill="{PAPER}"/>',
    ]
    backbone = _as_points(sample["point"] for sample in profile["backbone"]["arc_samples"])
    elements.append(f'<path d="{_svg_path(backbone)}" fill="none" stroke="{INK}" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>')
    for entry in geometry["branches"]:
        if entry["status"] != "accepted":
            continue
        points = _as_points(entry["points"])
        generation = int(entry["generation"])
        width = 3.0 if generation == 1 else 1.8 if generation == 2 else 1.0
        elements.append(f'<path d="{_svg_path(points)}" fill="none" stroke="{INK}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')
    for motif in motifs:
        tier = str(motif.get("visual_tier", "accent"))
        terminal_width = {"hero": 1.55, "dominant": 1.85, "support": 1.50, "accent": 1.15}.get(tier, 1.15)
        for motif_path in motif["paths"]:
            points = _as_points(motif_path["points"])
            fill = INK if bool(motif_path["closed"]) else "none"
            elements.append(
                f'<path d="{_svg_path(points, bool(motif_path["closed"]))}" fill="{fill}" stroke="{INK}" '
                f'stroke-width="{terminal_width}" stroke-linecap="round" stroke-linejoin="round"/>'
            )
    for motif in motifs:
        for detail_path in motif.get("detail_paths", []):
            points = _as_points(detail_path["points"])
            fill = PAPER if bool(detail_path["closed"]) else "none"
            elements.append(
                f'<path d="{_svg_path(points, bool(detail_path["closed"]))}" fill="{fill}" stroke="{PAPER}" '
                f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'
            )
    elements.append("</svg>")
    path.write_text("\n".join(elements), encoding="utf-8")


def _jsonable(value: object) -> object:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, float):
        return round(value, 6)
    return value


def _contact_sheet(paths: list[Path], output_path: Path) -> None:
    images = [Image.open(path).convert("RGB") for path in paths]
    _contact_sheet_images(images, output_path)


def _contact_sheet_images(images: list[Image.Image], output_path: Path) -> None:
    if not images:
        return
    columns = 2
    rows = math.ceil(len(images) / columns)
    cell_w = max(image.width for image in images)
    cell_h = max(image.height for image in images)
    sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), "#eef2f7")
    for index, image in enumerate(images):
        sheet.paste(image, ((index % columns) * cell_w, (index // columns) * cell_h))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def _build_render_data(
    profile_path: Path,
    plan_path: Path,
    geometry_path: Path,
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]], dict[str, object]]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    layout = json.loads(plan_path.read_text(encoding="utf-8"))
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    terminal_motifs, _, qa = _build_terminals(profile, layout, geometry)
    composition_motifs, composition_qa = _build_dense_composition(
        profile,
        geometry,
        terminal_motifs,
    )
    motifs = terminal_motifs + composition_motifs
    qa["foliage_cluster_count"] = composition_qa["foliage_cluster_count"]
    qa["branch_leaf_unit_count"] = composition_qa["branch_leaf_unit_count"]
    qa["carrier_leaf_pair_count"] = composition_qa["carrier_leaf_pair_count"]
    qa["side_leaf_count"] = composition_qa["side_leaf_count"]
    qa["generated_leaf_count"] = composition_qa["generated_leaf_count"]
    qa["minimum_leaf_count"] = composition_qa["minimum_leaf_count"]
    qa["leaf_quantity_target_met"] = composition_qa[
        "leaf_quantity_target_met"
    ]
    qa["flower_head_count"] = composition_qa["flower_head_count"]
    qa["composition_candidate_count"] = composition_qa["candidate_count"]
    qa["composition_density"] = composition_qa["composition_density"]
    qa["composition_curve_quality"] = composition_qa["curve_quality"]
    qa["coverage_target_met"] = composition_qa["coverage_target_met"]
    qa["ink_target_met"] = composition_qa["ink_target_met"]
    for key in (
        "composition_boundary_violation_count",
        "composition_flower_overlap_count",
        "composition_structure_overlap_count",
        "composition_terminal_overlap_count",
        "composition_foliage_overlap_count",
        "flower_structure_overlap_count",
        "composition_overlap_count",
    ):
        qa[key] = composition_qa[key]
    qa["valid"] = bool(
        qa["valid"]
        and qa["coverage_target_met"]
        and qa["ink_target_met"]
        and qa["leaf_quantity_target_met"]
        and qa["composition_boundary_violation_count"] == 0
        and qa["composition_overlap_count"] == 0
    )
    result = {
        "schema": "chanzhi_terminal_render_v1",
        "prototype_id": profile["prototype_id"],
        "motifs": motifs,
        "qa": qa,
    }
    return profile, geometry, motifs, result


def _build_one(profile_path: Path, plan_path: Path, geometry_path: Path, output_dir: Path) -> tuple[dict[str, object], Path]:
    profile, geometry, motifs, result = _build_render_data(
        profile_path,
        plan_path,
        geometry_path,
    )
    case_dir = output_dir / str(profile["prototype_id"])
    case_dir.mkdir(parents=True, exist_ok=True)
    result_path = case_dir / "terminal_render.json"
    result_path.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
    preview = _render(profile, geometry, motifs, qa)
    preview_path = case_dir / "terminal_lineart_preview.png"
    preview.save(preview_path)
    _write_svg(case_dir / "terminal_lineart.svg", profile, geometry, motifs)
    return result, preview_path


def run(args: argparse.Namespace) -> dict[str, object]:
    profile_root = args.profile_root.resolve()
    plan_root = args.plan_root.resolve()
    geometry_root = args.geometry_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    previews: list[Path] = []
    errors: list[dict[str, str]] = []
    for prototype_id in args.prototype_ids:
        try:
            result, preview_path = _build_one(
                profile_root / prototype_id / "skeleton_profile.json",
                plan_root / prototype_id / "branch_layout_plan.json",
                geometry_root / prototype_id / "branch_geometry.json",
                output_dir,
            )
            results.append(result)
            previews.append(preview_path)
            print(f"Rendered {prototype_id}: {preview_path}")
        except Exception as exc:
            errors.append({"prototype_id": prototype_id, "error": repr(exc)})
            print(f"Failed {prototype_id}: {exc}")
    contact_sheet = output_dir / "terminal_lineart_contact_sheet.png"
    _contact_sheet(previews, contact_sheet)
    manifest = {
        "schema": "chanzhi_terminal_render_manifest_v1",
        "success_count": len(results),
        "error_count": len(errors),
        "errors": errors,
        "contact_sheet": str(contact_sheet),
        "summary": [
            {
                "prototype_id": result["prototype_id"],
                "valid": result["qa"]["valid"],
                "accepted_terminal_count": result["qa"]["accepted_terminal_count"],
                "rejected_terminal_count": result["qa"]["rejected_terminal_count"],
                "suppressed_terminal_count": result["qa"]["suppressed_terminal_count"],
                "budget_skipped_terminal_count": result["qa"]["budget_skipped_terminal_count"],
                "kind_counts": result["qa"]["kind_counts"],
                "tier_counts": result["qa"]["tier_counts"],
                "planning_mode": result["qa"].get("planning_mode", "post_attach"),
                "average_bbox_area_by_tier": result["qa"]["average_bbox_area_by_tier"],
                "dominant_to_accent_area_ratio": result["qa"]["dominant_to_accent_area_ratio"],
                "foliage_cluster_count": result["qa"]["foliage_cluster_count"],
                "branch_leaf_unit_count": result["qa"]["branch_leaf_unit_count"],
                "carrier_leaf_pair_count": result["qa"][
                    "carrier_leaf_pair_count"
                ],
                "side_leaf_count": result["qa"]["side_leaf_count"],
                "generated_leaf_count": result["qa"]["generated_leaf_count"],
                "minimum_leaf_count": result["qa"]["minimum_leaf_count"],
                "leaf_quantity_target_met": result["qa"][
                    "leaf_quantity_target_met"
                ],
                "flower_head_count": result["qa"]["flower_head_count"],
                "composition_density": result["qa"]["composition_density"],
                "composition_curve_quality": result["qa"][
                    "composition_curve_quality"
                ],
                "coverage_target_met": result["qa"]["coverage_target_met"],
                "ink_target_met": result["qa"]["ink_target_met"],
                "composition_boundary_violation_count": result["qa"][
                    "composition_boundary_violation_count"
                ],
                "composition_overlap_count": result["qa"]["composition_overlap_count"],
                "crossing_count": result["qa"]["crossing_count"],
                "flower_overlap_count": result["qa"]["flower_overlap_count"],
            }
            for result in results
        ],
    }
    manifest_path = output_dir / "terminal_render_manifest.json"
    manifest_path.write_text(json.dumps(_jsonable(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {contact_sheet}")
    print(f"Saved {manifest_path}")
    return manifest


def _next_final_summary_path(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    used: set[int] = set()
    for path in output_dir.glob("run*.png"):
        stem = path.stem
        suffix = stem[3:]
        if suffix.isdigit():
            used.add(int(suffix))
    run_index = 1
    while run_index in used:
        run_index += 1
    return output_dir / f"run{run_index}.png"


def run_summary_only(args: argparse.Namespace) -> dict[str, object]:
    profile_root = args.profile_root.resolve()
    plan_root = args.plan_root.resolve()
    geometry_root = args.geometry_root.resolve()
    output_dir = args.output_dir.resolve()
    results: list[dict[str, object]] = []
    previews: list[Image.Image] = []
    errors: list[dict[str, str]] = []
    for prototype_id in args.prototype_ids:
        try:
            profile, geometry, motifs, result = _build_render_data(
                profile_root / prototype_id / "skeleton_profile.json",
                plan_root / prototype_id / "branch_layout_plan.json",
                geometry_root / prototype_id / "branch_geometry.json",
            )
            results.append(result)
            previews.append(_render(profile, geometry, motifs, result["qa"]).convert("RGB"))
            print(f"Rendered {prototype_id}")
        except Exception as exc:
            errors.append({"prototype_id": prototype_id, "error": repr(exc)})
            print(f"Failed {prototype_id}: {exc}")
    contact_sheet = _next_final_summary_path(output_dir)
    _contact_sheet_images(previews, contact_sheet)
    print(f"Saved {contact_sheet}")
    return {
        "schema": "chanzhi_terminal_summary_only_v1",
        "success_count": len(results),
        "error_count": len(errors),
        "errors": errors,
        "contact_sheet": str(contact_sheet),
        "summary": [
            {
                "prototype_id": result["prototype_id"],
                "valid": result["qa"]["valid"],
                "generated_leaf_count": result["qa"]["generated_leaf_count"],
                "minimum_leaf_count": result["qa"]["minimum_leaf_count"],
                "composition_density": result["qa"]["composition_density"],
                "composition_curve_quality": result["qa"]["composition_curve_quality"],
                "composition_overlap_count": result["qa"]["composition_overlap_count"],
            }
            for result in results
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render terminal motifs on validated Chanzhi branch geometry.")
    parser.add_argument("--profile-root", type=Path, default=DEFAULT_PROFILE_ROOT)
    parser.add_argument("--plan-root", type=Path, default=DEFAULT_PLAN_ROOT)
    parser.add_argument("--geometry-root", type=Path, default=DEFAULT_GEOMETRY_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prototype-ids", nargs="+", default=list(DEFAULT_PROTOTYPE_IDS))
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only save one auto-numbered contact sheet image in --output-dir.",
    )
    args = parser.parse_args()
    if args.summary_only and args.output_dir == DEFAULT_OUTPUT_DIR:
        args.output_dir = FINAL_SUMMARY_OUTPUT_DIR
    manifest = run_summary_only(args) if args.summary_only else run(args)
    return 0 if not manifest["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
