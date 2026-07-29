#!/usr/bin/env python3
"""Convert semantic Chanzhi branch plans into validated local curve geometry."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

try:
    from . import chanzhi_terminal_primitives as terminal_geo
except ImportError:
    import chanzhi_terminal_primitives as terminal_geo


Point = tuple[float, float]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_ROOT = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_skeleton_analysis" / "run6_flower_connectors"
DEFAULT_PLAN_ROOT = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_branch_layout_grammar" / "run5_flower_connectors"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_branch_geometry" / "run1"
DEFAULT_PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)

PAPER = "#fbfaf5"
INK = "#0b1f46"
FLOWER = "#db2777"
PRIMARY = "#1d4ed8"
SECONDARY = "#0891b2"
TERTIARY = "#15803d"
TERMINAL_HINT = "#64748b"
TERMINAL_PLAN = "#7c3aed"
REJECTED = "#dc2626"


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scale: float) -> Point:
    return a[0] * scale, a[1] * scale


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


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


def _sample_polyline(points: list[Point], fraction: float) -> tuple[Point, Point]:
    if len(points) < 2:
        return (points[0] if points else (0.0, 0.0), (1.0, 0.0))
    fraction = max(0.0, min(1.0, fraction))
    lengths = [_dist(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    if total < 1e-9:
        return points[0], (1.0, 0.0)
    target = total * fraction
    traversed = 0.0
    for (a, b), length in zip(zip(points, points[1:]), lengths):
        if traversed + length >= target:
            local = 0.0 if length < 1e-9 else (target - traversed) / length
            return _add(a, _mul(_sub(b, a), local)), _norm(_sub(b, a))
        traversed += length
    return points[-1], _norm(_sub(points[-1], points[-2]))


def _stable_sign(key: str) -> int:
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    return -1 if digest[0] % 2 == 0 else 1


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, samples: int = 36) -> list[Point]:
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


def _path_length(points: list[Point]) -> float:
    return sum(_dist(a, b) for a, b in zip(points, points[1:]))


def _curve_shape_metrics(points: list[Point]) -> dict[str, float]:
    if len(points) < 2:
        return {
            "chord_length": 0.0,
            "path_length": 0.0,
            "arc_ratio": 1.0,
            "max_deviation_ratio": 0.0,
            "absolute_turn_degrees": 0.0,
        }
    chord_vector = _sub(points[-1], points[0])
    chord_length = math.hypot(chord_vector[0], chord_vector[1])
    path_length = _path_length(points)
    if chord_length < 1e-6:
        return {
            "chord_length": chord_length,
            "path_length": path_length,
            "arc_ratio": 1.0,
            "max_deviation_ratio": 0.0,
            "absolute_turn_degrees": 0.0,
        }
    axis = _norm(chord_vector)
    normal = _normal(axis)
    max_deviation = max(abs(_dot(_sub(point, points[0]), normal)) for point in points)
    absolute_turn = 0.0
    previous: Point | None = None
    for a, b in zip(points, points[1:]):
        direction = _norm(_sub(b, a))
        if previous is not None:
            absolute_turn += math.degrees(math.acos(max(-1.0, min(1.0, _dot(previous, direction)))))
        previous = direction
    return {
        "chord_length": chord_length,
        "path_length": path_length,
        "arc_ratio": path_length / chord_length,
        "max_deviation_ratio": max_deviation / chord_length,
        "absolute_turn_degrees": absolute_turn,
    }


def _delayed_bulge(points: list[Point], side: int, amplitude: float) -> list[Point]:
    """Open and close one calligraphic bow with a smooth zero-slope envelope."""
    if len(points) < 5 or amplitude <= 1e-6:
        return points
    axis = _norm(_sub(points[-1], points[0]))
    normal = _normal(axis)
    count = len(points) - 1
    result: list[Point] = []
    for index, point in enumerate(points):
        t = index / count
        if t <= 0.06 or t >= 0.98:
            envelope = 0.0
        else:
            local = (t - 0.06) / 0.92
            envelope = max(0.0, math.sin(local * math.pi)) ** 2.05
        result.append(_add(point, _mul(normal, side * amplitude * envelope)))
    return result


def _counter_bend(points: list[Point], side: int, amplitude: float) -> list[Point]:
    """Add a smooth two-lobed reverse bend to long S-flow branches."""
    if len(points) < 7 or amplitude <= 1e-6:
        return points
    axis = _norm(_sub(points[-1], points[0]))
    normal = _normal(axis)
    count = len(points) - 1
    result: list[Point] = []
    for index, point in enumerate(points):
        t = index / count
        if t <= 0.08 or t >= 0.98:
            envelope = 0.0
        else:
            local = (t - 0.08) / 0.90
            envelope = (
                math.sin(local * math.tau)
                * max(0.0, math.sin(local * math.pi)) ** 2.0
                * 0.58
            )
        result.append(_add(point, _mul(normal, side * amplitude * envelope)))
    return result


def _style_amplitude(role: str, length: float, strength: float) -> float:
    if role in {"primary_long", "gap_long"}:
        base = min(20.0, max(7.5, length * 0.145))
    elif role in {"primary_short", "secondary_long"}:
        base = min(14.0, max(5.5, length * 0.135))
    elif role == "secondary_sprig":
        base = min(9.0, max(3.0, length * 0.120))
    elif role == "tertiary_sprig":
        base = min(6.0, max(2.0, length * 0.105))
    elif role == "flower_connector":
        base = min(5.5, max(1.4, length * 0.050))
    else:
        base = min(8.5, max(2.5, length * 0.105))
    return base * strength


def _limit_tangent_to_axis(
    tangent: Point,
    axis: Point,
    max_angle_radians: float,
) -> Point:
    axis = _norm(axis)
    tangent = _norm(tangent)
    signed_angle = math.atan2(
        axis[0] * tangent[1] - axis[1] * tangent[0],
        _dot(axis, tangent),
    )
    limited = max(-max_angle_radians, min(max_angle_radians, signed_angle))
    cosine = math.cos(limited)
    sine = math.sin(limited)
    return (
        axis[0] * cosine - axis[1] * sine,
        axis[0] * sine + axis[1] * cosine,
    )


def _shape_targets(role: str, chord_length: float) -> tuple[float, float, float, float]:
    if role in {"primary_long", "gap_long"}:
        target_deviation, minimum_deviation, minimum_ratio = 0.160, 0.100, 1.028
    elif role in {"primary_short", "secondary_long"}:
        target_deviation, minimum_deviation, minimum_ratio = 0.145, 0.090, 1.024
    elif role == "secondary_sprig":
        target_deviation, minimum_deviation, minimum_ratio = 0.120, 0.075, 1.018
    elif role == "tertiary_sprig":
        target_deviation, minimum_deviation, minimum_ratio = 0.100, 0.065, 1.014
    else:
        target_deviation, minimum_deviation, minimum_ratio = 0.105, 0.060, 1.012
    if chord_length < 19.0:
        minimum_deviation *= 0.78
        minimum_ratio = min(minimum_ratio, 1.007)
    target_ratio = 1.0 + 2.65 * target_deviation * target_deviation
    return target_deviation, target_ratio, minimum_deviation, minimum_ratio


def _shape_score(
    metrics: dict[str, float],
    role: str,
    *,
    strength: float,
    target_scale: float,
    family_mismatch: bool,
) -> tuple[float, bool]:
    target_deviation, target_ratio, minimum_deviation, minimum_ratio = _shape_targets(
        role,
        metrics["chord_length"],
    )
    near_straight = (
        metrics["max_deviation_ratio"] < minimum_deviation
        or metrics["arc_ratio"] < minimum_ratio
    )
    score = (
        abs(metrics["max_deviation_ratio"] - target_deviation) * 7.0
        + abs(metrics["arc_ratio"] - target_ratio) * 3.0
        + abs(strength - 1.0) * 0.035
        + (1.0 - target_scale) * 0.18
        + (0.025 if family_mismatch else 0.0)
    )
    return score, near_straight


def _curve_candidate(
    source_points: list[Point],
    parent_points: list[Point],
    mount_fraction: float,
    *,
    role: str,
    family: str,
    bow_sign: int,
    target_scale: float,
    style_strength: float,
    graft_scale: float = 1.0,
) -> list[Point]:
    root, parent_tangent = _sample_polyline(parent_points, mount_fraction)
    old_root = source_points[0]
    target_vector = _sub(source_points[-1], old_root)
    target = _add(root, _mul(target_vector, target_scale))
    direct = _sub(target, root)
    length = max(1.0, math.hypot(direct[0], direct[1]))
    initial_hint = _norm(_sub(source_points[min(2, len(source_points) - 1)], old_root))
    if _dot(parent_tangent, initial_hint) < 0.0:
        parent_tangent = _mul(parent_tangent, -1.0)
    if len(source_points) >= 3:
        end_tangent = _norm(_sub(source_points[-1], source_points[-3]))
    else:
        end_tangent = _norm(direct)
    if _dot(end_tangent, direct) < 0.15:
        end_tangent = _norm(direct)
    end_tangent = _limit_tangent_to_axis(
        end_tangent,
        _norm(direct),
        math.radians(46.0 if role in {"primary_long", "gap_long"} else 54.0),
    )

    if role in {"primary_long", "gap_long"}:
        start_handle = min(32.0, max(8.0, length * 0.36 * graft_scale))
    elif role in {"primary_short", "secondary_long"}:
        start_handle = min(26.0, max(6.0, length * 0.30 * graft_scale))
    else:
        start_handle = min(22.0, max(4.5, length * 0.26 * graft_scale))
    end_handle = min(28.0, max(7.0, length * 0.32))
    if family == "s_flow" and length >= 34.0:
        direct_axis = _norm(direct)
        side_axis = _normal(direct_axis)
        midpoint = _add(
            _add(root, _mul(direct, 0.52)),
            _mul(side_axis, bow_sign * min(12.0, length * 0.10) * style_strength),
        )
        mid_tangent = _norm(_add(direct_axis, _mul(side_axis, -bow_sign * 0.26)))
        first = _cubic(
            root,
            _add(root, _mul(parent_tangent, start_handle)),
            _add(midpoint, _mul(mid_tangent, -min(13.0, length * 0.16))),
            midpoint,
            samples=20,
        )
        second = _cubic(
            midpoint,
            _add(midpoint, _mul(mid_tangent, min(13.0, length * 0.16))),
            _add(target, _mul(end_tangent, -end_handle)),
            target,
            samples=20,
        )
        curve = first + second[1:]
    else:
        p1 = _add(root, _mul(parent_tangent, start_handle))
        p2 = _add(target, _mul(end_tangent, -end_handle))
        curve = _cubic(root, p1, p2, target)

    amplitude = _style_amplitude(role, length, style_strength)
    curve = _delayed_bulge(curve, bow_sign, amplitude)
    if family == "s_flow" and length >= 34.0:
        curve = _counter_bend(curve, bow_sign, amplitude * 0.52)
    return curve


def _inside_flower(point: Point, flower: dict[str, object], padding: float = 1.05) -> bool:
    center = tuple(float(value) for value in flower["center"])
    rx = max(1.0, float(flower["rx"]) * padding)
    ry = max(1.0, float(flower["ry"]) * padding)
    return ((point[0] - center[0]) / rx) ** 2 + ((point[1] - center[1]) / ry) ** 2 <= 1.0


def _flower_level(point: Point, flower: dict[str, object]) -> float:
    center = tuple(float(value) for value in flower["center"])
    rx = max(1.0, float(flower["rx"]))
    ry = max(1.0, float(flower["ry"]))
    return ((point[0] - center[0]) / rx) ** 2 + ((point[1] - center[1]) / ry) ** 2


def _flower_intrusion(points: list[Point], flower: dict[str, object]) -> bool:
    states = [_inside_flower(point, flower) for point in points]
    if not states[0]:
        return any(states[1:])
    exited = False
    for inside in states[1:]:
        if not inside:
            exited = True
        elif exited:
            return True
    return not exited


def _flower_inward(points: list[Point], flowers: list[dict[str, object]]) -> bool:
    if len(points) < 4:
        return False
    root = points[0]
    probe = points[min(len(points) - 1, max(3, len(points) // 3))]
    growth = _norm(_sub(probe, root))
    for flower in flowers:
        center = tuple(float(value) for value in flower["center"])
        radius = float(flower["radius"])
        to_flower = _sub(center, root)
        distance = math.hypot(to_flower[0], to_flower[1])
        if distance - radius > 95.0 or distance < 1e-9:
            continue
        if _flower_level(root, flower) <= 1.0:
            continue
        if min(_flower_level(point, flower) for point in points) >= 1.85:
            continue
        if _dot(growth, _norm(to_flower)) > 0.58 and _dist(probe, center) < distance - 4.0:
            return True
    return False


def _clip_to_flower_interface(points: list[Point], flower: dict[str, object]) -> list[Point]:
    for index, point in enumerate(points):
        if not _inside_flower(point, flower, padding=1.08):
            continue
        if index == 0:
            return points[:1]
        outside = points[index - 1]
        inside = point
        for _ in range(14):
            midpoint = ((outside[0] + inside[0]) * 0.5, (outside[1] + inside[1]) * 0.5)
            if _inside_flower(midpoint, flower, padding=1.08):
                inside = midpoint
            else:
                outside = midpoint
        return points[:index] + [outside]
    return points


def _redirect_source_around_flower(
    source_points: list[Point],
    parent_points: list[Point],
    mount_fraction: float,
    flowers: list[dict[str, object]],
) -> list[Point] | None:
    root, _ = _sample_polyline(parent_points, mount_fraction)
    original_root = source_points[0]
    original_vector = _sub(source_points[-1], original_root)
    length = math.hypot(original_vector[0], original_vector[1])
    if length < 8.0:
        return None
    original_direction = _norm(original_vector)
    candidates: list[tuple[float, dict[str, object]]] = []
    for flower in flowers:
        center = tuple(float(value) for value in flower["center"])
        radius = float(flower["radius"])
        vector = _sub(center, root)
        distance = math.hypot(vector[0], vector[1])
        if distance - radius > 105.0 or distance < 1e-9:
            continue
        alignment = _dot(original_direction, _norm(vector))
        if alignment > 0.22:
            candidates.append((alignment + max(0.0, 70.0 - (distance - radius)) * 0.01, flower))
    if not candidates:
        return None
    _, flower = max(candidates, key=lambda item: item[0])
    center = tuple(float(value) for value in flower["center"])
    outward = _norm(_sub(root, center))
    tangent_a = _normal(outward)
    tangent_b = _mul(tangent_a, -1.0)
    tangent = tangent_a if _dot(tangent_a, original_direction) >= _dot(tangent_b, original_direction) else tangent_b
    redirected = _norm(_add(_mul(tangent, 0.92), _mul(outward, 0.28)))
    new_target = _add(original_root, _mul(redirected, length * 0.92))
    return [original_root, _add(original_root, _mul(redirected, length * 0.42)), new_target]


def _orientation(a: Point, b: Point, c: Point) -> float:
    return _cross(_sub(b, a), _sub(c, a))


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    if max(a[0], b[0]) + 1e-6 < min(c[0], d[0]) or max(c[0], d[0]) + 1e-6 < min(a[0], b[0]):
        return False
    if max(a[1], b[1]) + 1e-6 < min(c[1], d[1]) or max(c[1], d[1]) + 1e-6 < min(a[1], b[1]):
        return False
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    return o1 * o2 < -1e-7 and o3 * o4 < -1e-7


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    segment = _sub(end, start)
    length_sq = _dot(segment, segment)
    if length_sq < 1e-12:
        return _dist(point, start)
    fraction = max(0.0, min(1.0, _dot(_sub(point, start), segment) / length_sq))
    projection = _add(start, _mul(segment, fraction))
    return _dist(point, projection)


def _segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _path_min_distance(first: list[Point], second: list[Point]) -> float:
    if len(first) < 2 or len(second) < 2:
        return float("inf")
    best = float("inf")
    for a, b in zip(first, first[1:]):
        for c, d in zip(second, second[1:]):
            best = min(best, _segment_distance(a, b, c, d))
            if best <= 1e-9:
                return 0.0
    return best


def _paths_within_distance(first: list[Point], second: list[Point], threshold: float) -> bool:
    if len(first) < 2 or len(second) < 2:
        return False
    for a, b in zip(first, first[1:]):
        first_min_x = min(a[0], b[0]) - threshold
        first_max_x = max(a[0], b[0]) + threshold
        first_min_y = min(a[1], b[1]) - threshold
        first_max_y = max(a[1], b[1]) + threshold
        for c, d in zip(second, second[1:]):
            if first_max_x < min(c[0], d[0]) or first_min_x > max(c[0], d[0]):
                continue
            if first_max_y < min(c[1], d[1]) or first_min_y > max(c[1], d[1]):
                continue
            if _segment_distance(a, b, c, d) < threshold:
                return True
    return False


def _crosses_path(points: list[Point], obstacle: list[Point], root: Point, allow_root_contact: bool) -> bool:
    for a, b in zip(points, points[1:]):
        for c, d in zip(obstacle, obstacle[1:]):
            if not _segments_intersect(a, b, c, d):
                continue
            if allow_root_contact and min(_dist(root, a), _dist(root, b), _dist(root, c), _dist(root, d)) < 7.0:
                continue
            return True
    return False


def _closed_points(points: list[Point], closed: bool) -> list[Point]:
    if closed and points and _dist(points[0], points[-1]) > 1e-6:
        return points + [points[0]]
    return points


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    inside = False
    if len(polygon) < 3:
        return False
    previous = polygon[-1]
    for current in polygon:
        if (current[1] > point[1]) != (previous[1] > point[1]):
            denominator = previous[1] - current[1]
            if abs(denominator) < 1e-9:
                previous = current
                continue
            x_cross = (previous[0] - current[0]) * (point[1] - current[1]) / denominator + current[0]
            if point[0] < x_cross:
                inside = not inside
        previous = current
    return inside


def _paths_overlap(
    first: list[Point],
    first_closed: bool,
    second: list[Point],
    second_closed: bool,
    *,
    shared_root: Point | None = None,
) -> bool:
    first_edges = _closed_points(first, first_closed)
    second_edges = _closed_points(second, second_closed)
    for a, b in zip(first_edges, first_edges[1:]):
        for c, d in zip(second_edges, second_edges[1:]):
            if not _segments_intersect(a, b, c, d):
                continue
            if shared_root is not None and min(
                _dist(shared_root, a),
                _dist(shared_root, b),
                _dist(shared_root, c),
                _dist(shared_root, d),
            ) < 5.0:
                continue
            return True
    if first_closed and first and _point_in_polygon(second[0], first):
        return True
    if second_closed and second and _point_in_polygon(first[0], second):
        return True
    return False


def _terminal_obstacle_crossing(
    points: list[Point],
    terminal_obstacles: dict[str, list[dict[str, object]]],
) -> str | None:
    for terminal_id, obstacle_paths in terminal_obstacles.items():
        for obstacle in obstacle_paths:
            obstacle_points = _as_points(obstacle["points"])
            obstacle_closed = bool(obstacle["closed"])
            if _paths_overlap(points, False, obstacle_points, obstacle_closed):
                return terminal_id
    return None


def _candidate_issues(
    points: list[Point],
    flowers: list[dict[str, object]],
    backbone: list[Point],
    accepted: dict[str, list[Point]],
    accepted_terminals: dict[str, list[dict[str, object]]],
    parent_id: str,
    *,
    allow_flower_inward: bool = False,
    minimum_clearance: float = 0.0,
) -> list[str]:
    issues: list[str] = []
    if any(_flower_intrusion(points, flower) for flower in flowers):
        issues.append("flower_inside")
    if not allow_flower_inward and _flower_inward(points, flowers):
        issues.append("flower_inward")
    if _crosses_path(points, backbone, points[0], parent_id.startswith("backbone_edge_")):
        issues.append("backbone_crossing")
    for other_id, obstacle in accepted.items():
        if _crosses_path(points, obstacle, points[0], other_id == parent_id):
            issues.append(f"branch_crossing:{other_id}")
            break
        if (
            minimum_clearance > 0.0
            and other_id != parent_id
            and _paths_within_distance(points, obstacle, minimum_clearance)
        ):
            issues.append(f"branch_clearance:{other_id}")
            break
    terminal_id = _terminal_obstacle_crossing(points, accepted_terminals)
    if terminal_id is not None:
        issues.append(f"terminal_crossing:{terminal_id}")
    return issues


def _terminal_path_issues(
    paths: list[tuple[list[Point], bool]],
    branch_points: list[Point],
    flowers: list[dict[str, object]],
    backbone: list[Point],
    accepted: dict[str, list[Point]],
    accepted_terminals: dict[str, list[dict[str, object]]],
    bounds: tuple[float, float, float, float],
) -> list[str]:
    issues: list[str] = []
    min_x, min_y, max_x, max_y = bounds
    root = branch_points[-1]
    for points, closed in paths:
        if any(
            point[0] < min_x or point[0] > max_x or point[1] < min_y or point[1] > max_y
            for point in points
        ):
            issues.append("terminal_boundary")
            break
        if any(_inside_flower(point, flower, padding=1.04) for point in points[1:] for flower in flowers):
            issues.append("terminal_flower_overlap")
            break
        if _paths_overlap(points, closed, branch_points, False, shared_root=root):
            issues.append("terminal_self_crossing")
            break
        if _paths_overlap(points, closed, backbone, False):
            issues.append("terminal_backbone_crossing")
            break
        for other_id, obstacle in accepted.items():
            if _paths_overlap(points, closed, obstacle, False):
                issues.append(f"terminal_branch_crossing:{other_id}")
                break
            if _paths_within_distance(_closed_points(points, closed), obstacle, 3.5):
                issues.append(f"terminal_branch_clearance:{other_id}")
                break
        if issues:
            break
        for other_terminal_id, obstacle_paths in accepted_terminals.items():
            for obstacle in obstacle_paths:
                if _paths_overlap(
                    points,
                    closed,
                    _as_points(obstacle["points"]),
                    bool(obstacle["closed"]),
                ):
                    issues.append(f"terminal_overlap:{other_terminal_id}")
                    break
                if _paths_within_distance(
                    _closed_points(points, closed),
                    _closed_points(
                        _as_points(obstacle["points"]),
                        bool(obstacle["closed"]),
                    ),
                    4.5,
                ):
                    issues.append(f"terminal_clearance:{other_terminal_id}")
                    break
            if issues:
                break
        if issues:
            break
    return issues


def _fit_terminal_for_branch(
    branch: dict[str, object],
    branch_points: list[Point],
    flowers: list[dict[str, object]],
    backbone: list[Point],
    accepted: dict[str, list[Point]],
    accepted_terminals: dict[str, list[dict[str, object]]],
    bounds: tuple[float, float, float, float],
    motif_kind_counts: dict[str, int],
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    terminal = dict(branch["terminal"])
    requested_kind = str(terminal["kind"])
    visual_tier = str(terminal.get("visual_tier", "accent"))
    origin = branch_points[-1]
    tangent = _norm(_sub(branch_points[-1], branch_points[-3]))
    base_size = terminal_geo.size_value(str(terminal["scale_class"]), 1.0)
    base_sign = terminal_geo.terminal_sign(str(branch["branch_id"]))
    attempts: list[dict[str, object]] = []
    for kind_index, candidate_kind in enumerate(terminal_geo.candidate_kinds(requested_kind, visual_tier)):
        if candidate_kind == "leaf_cluster" and motif_kind_counts.get(candidate_kind, 0) >= 2:
            continue
        if candidate_kind == "paired_leaf" and motif_kind_counts.get(candidate_kind, 0) >= 2:
            continue
        for scale in terminal_geo.scale_trials(visual_tier):
            for sign in (base_sign, -base_sign):
                paths = terminal_geo.motif_paths(candidate_kind, origin, tangent, base_size * scale, sign)
                issues = _terminal_path_issues(
                    paths,
                    branch_points,
                    flowers,
                    backbone,
                    accepted,
                    accepted_terminals,
                    bounds,
                )
                attempts.append(
                    {
                        "kind": candidate_kind,
                        "scale": scale,
                        "sign": sign,
                        "issues": issues,
                    }
                )
                if issues:
                    continue
                penalty = kind_index * 0.035 + (1.0 - scale) * 0.22
                plan = {
                    "selected": True,
                    "kind": candidate_kind,
                    "requested_kind": requested_kind,
                    "scale_class": terminal["scale_class"],
                    "visual_tier": visual_tier,
                    "applied_scale": scale,
                    "sign": sign,
                    "paths": [
                        {"points": points, "closed": closed}
                        for points, closed in paths
                    ],
                    "fit_penalty": penalty,
                }
                return plan, attempts
    return None, attempts


def _path_cells(
    points: list[Point],
    closed: bool,
    bounds: tuple[float, float, float, float],
    cell_size: float,
) -> set[tuple[int, int]]:
    min_x, min_y, max_x, max_y = bounds
    columns = max(1, math.ceil((max_x - min_x) / cell_size))
    rows = max(1, math.ceil((max_y - min_y) / cell_size))
    cells: set[tuple[int, int]] = set()
    for point in points:
        column = int((point[0] - min_x) // cell_size)
        row = int((point[1] - min_y) // cell_size)
        if 0 <= column < columns and 0 <= row < rows:
            cells.add((column, row))
    if not closed or len(points) < 3:
        return cells
    box_min_x = max(min_x, min(point[0] for point in points))
    box_max_x = min(max_x, max(point[0] for point in points))
    box_min_y = max(min_y, min(point[1] for point in points))
    box_max_y = min(max_y, max(point[1] for point in points))
    start_column = max(0, int((box_min_x - min_x) // cell_size))
    end_column = min(columns - 1, int((box_max_x - min_x) // cell_size))
    start_row = max(0, int((box_min_y - min_y) // cell_size))
    end_row = min(rows - 1, int((box_max_y - min_y) // cell_size))
    for column in range(start_column, end_column + 1):
        for row in range(start_row, end_row + 1):
            center = (
                min_x + (column + 0.5) * cell_size,
                min_y + (row + 0.5) * cell_size,
            )
            if _point_in_polygon(center, points):
                cells.add((column, row))
    return cells


def _joint_coverage_cells(
    branch_points: list[Point],
    terminal_plan: dict[str, object],
    bounds: tuple[float, float, float, float],
    cell_size: float,
) -> set[tuple[int, int]]:
    cells = _path_cells(branch_points, False, bounds, cell_size)
    if not terminal_plan.get("selected"):
        return cells
    for path in terminal_plan["paths"]:
        cells.update(
            _path_cells(
                _as_points(path["points"]),
                bool(path["closed"]),
                bounds,
                cell_size,
            )
        )
    return cells


def _coverage_summary(
    occupied_cells: set[tuple[int, int]],
    bounds: tuple[float, float, float, float],
    flowers: list[dict[str, object]],
    cell_size: float,
) -> dict[str, object]:
    min_x, min_y, max_x, max_y = bounds
    columns = max(1, math.ceil((max_x - min_x) / cell_size))
    rows = max(1, math.ceil((max_y - min_y) / cell_size))
    available: set[tuple[int, int]] = set()
    upper: set[tuple[int, int]] = set()
    lower: set[tuple[int, int]] = set()
    middle_y = (min_y + max_y) * 0.5
    for column in range(columns):
        for row in range(rows):
            center = (
                min_x + (column + 0.5) * cell_size,
                min_y + (row + 0.5) * cell_size,
            )
            if any(_inside_flower(center, flower, padding=1.0) for flower in flowers):
                continue
            cell = (column, row)
            available.add(cell)
            (upper if center[1] < middle_y else lower).add(cell)
    covered = occupied_cells & available
    upper_covered = covered & upper
    lower_covered = covered & lower
    return {
        "cell_size": cell_size,
        "available_cell_count": len(available),
        "covered_cell_count": len(covered),
        "coverage_ratio": len(covered) / len(available) if available else 0.0,
        "upper_coverage_ratio": len(upper_covered) / len(upper) if upper else 0.0,
        "lower_coverage_ratio": len(lower_covered) / len(lower) if lower else 0.0,
    }


def _coverage_adjusted_score(
    base_score: float,
    branch_points: list[Point],
    terminal_plan: dict[str, object],
    occupied_cells: set[tuple[int, int]],
    bounds: tuple[float, float, float, float],
    cell_size: float,
) -> tuple[float, int]:
    candidate_cells = _joint_coverage_cells(branch_points, terminal_plan, bounds, cell_size)
    gain = len(candidate_cells - occupied_cells)
    tier = str(terminal_plan.get("visual_tier", "accent"))
    tier_weight = {"dominant": 0.034, "support": 0.026, "accent": 0.014}.get(tier, 0.012)
    return base_score - min(gain, 18) * tier_weight, gain


def _family_for(branch: dict[str, object]) -> str:
    role = str(branch["role"])
    length = float(branch["length_budget"])
    if role == "secondary_long":
        return "s_flow"
    if role in {"primary_long", "gap_long"} and length >= 48.0:
        return "s_flow"
    if role == "primary_short" and length >= 38.0:
        return "s_flow"
    return "c_flow"


def _build_geometry(
    profile: dict[str, object],
    layout: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, list[Point]], dict[str, object]]:
    graph = profile["region_graph"]
    guide_map = {str(guide["guide_id"]): guide for guide in graph["guide_edges"]}
    backbone = _as_points(sample["point"] for sample in profile["backbone"]["arc_samples"])
    flowers = list(profile["flowers"])
    accepted: dict[str, list[Point]] = {}
    accepted_terminals: dict[str, list[dict[str, object]]] = {}
    geometry: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    skipped_terminal_components = 0
    selected_terminal_entries, budget_skipped = terminal_geo.select_terminal_entries(list(layout["branches"]))
    selected_terminal_ids = {str(entry["branch_id"]) for entry in selected_terminal_entries}
    terminal_skip_reasons = {
        str(entry["branch_id"]): str(entry["reason"])
        for entry in budget_skipped
    }
    skipped_terminal_ids = set(terminal_skip_reasons)
    motif_kind_counts: dict[str, int] = {}
    pruned_ids: set[str] = set()
    pruned: list[dict[str, object]] = []
    repeat_x_range = tuple(float(value) for value in profile["repeat_x_range"])
    bounds = (
        repeat_x_range[0] + 1.5,
        1.5,
        repeat_x_range[1] - 1.5,
        float(profile["canvas"]["height"]) - 1.5,
    )
    coverage_cell_size = 18.0
    occupied_cells = _path_cells(backbone, False, bounds, coverage_cell_size)
    tier_rank = {"dominant": 0, "support": 1, "accent": 2, "interface": 3}
    branches = sorted(
        layout["branches"],
        key=lambda branch: (
            int(branch["generation"]),
            0 if branch["source"] == "existing_svg_guide" else 1,
            tier_rank.get(str(branch["terminal"].get("visual_tier", "accent")), 4),
            -float(branch.get("length_budget", 0.0)),
            str(branch["branch_id"]),
        ),
    )
    for branch in branches:
        branch_id = str(branch["branch_id"])
        parent_id = str(branch["parent_id"])
        if branch["role"] == "terminal_component":
            skipped_terminal_components += 1
            geometry.append(
                {
                    "branch_id": branch_id,
                    "status": branch["role"],
                    "parent_id": parent_id,
                    "generation": branch["generation"],
                    "role": branch["role"],
                    "terminal": branch["terminal"],
                }
            )
            continue
        parent_points = backbone if parent_id.startswith("backbone_edge_") else accepted.get(parent_id)
        if parent_points is None:
            if parent_id in pruned_ids or branch["source"] == "grammar_slot":
                pruned_ids.add(branch_id)
                pruned.append(
                    {
                        "branch_id": branch_id,
                        "reason": "parent_pruned" if parent_id in pruned_ids else "missing_optional_parent",
                    }
                )
                geometry.append(
                    {
                        "branch_id": branch_id,
                        "status": "pruned_joint_conflict",
                        "source": branch["source"],
                        "generation": branch["generation"],
                        "role": branch["role"],
                        "parent_id": parent_id,
                        "terminal": branch["terminal"],
                    }
                )
                continue
            rejected.append({"branch_id": branch_id, "reasons": ["missing_parent_geometry"]})
            continue
        if branch["source"] == "existing_svg_guide":
            source_points = _as_points(guide_map[branch_id]["points"])
            target_scales = (1.0, 0.94)
        else:
            source_points = _as_points(branch["preview_points"])
            target_scales = (1.0, 0.88, 0.76)
        role = str(branch["role"])
        minimum_clearance = (
            0.0
            if branch["source"] == "existing_svg_guide"
            else 7.0
            if int(branch["generation"]) == 1
            else 5.5
            if int(branch["generation"]) == 2
            else 4.5
        )
        preferred_family = _family_for(branch)
        families = (preferred_family, "c_flow" if preferred_family == "s_flow" else "s_flow")
        base_sign = _stable_sign(branch_id)
        strengths = (0.78, 1.0, 1.24, 1.48, 1.72)
        terminal_required = branch_id in selected_terminal_ids
        chosen: tuple[
            list[Point],
            str,
            int,
            float,
            float,
            dict[str, float],
            float,
            dict[str, object],
        ] | None = None
        attempts: list[dict[str, object]] = []
        for target_scale in target_scales:
            for family in families:
                for bow_sign in (base_sign, -base_sign):
                    for style_strength in strengths:
                        points = _curve_candidate(
                            source_points,
                            parent_points,
                            float(branch["mount_fraction"]),
                            role=role,
                            family=family,
                            bow_sign=bow_sign,
                            target_scale=target_scale,
                            style_strength=style_strength,
                        )
                        if role == "flower_connector":
                            connector_id = str(branch["connector_flower_id"])
                            connector_flower = next(flower for flower in flowers if flower["flower_id"] == connector_id)
                            points = _clip_to_flower_interface(points, connector_flower)
                        issues = _candidate_issues(
                            points,
                            flowers,
                            backbone,
                            accepted,
                            accepted_terminals,
                            parent_id,
                            allow_flower_inward=role == "flower_connector",
                            minimum_clearance=minimum_clearance,
                        )
                        metrics = _curve_shape_metrics(points)
                        score, near_straight = _shape_score(
                            metrics,
                            role,
                            strength=style_strength,
                            target_scale=target_scale,
                            family_mismatch=family != preferred_family,
                        )
                        attempt_issues = issues + (
                            ["near_straight"] if near_straight and role != "flower_connector" else []
                        )
                        attempts.append(
                            {
                                "family": family,
                                "bow_sign": bow_sign,
                                "target_scale": target_scale,
                                "style_strength": style_strength,
                                "shape_score": score,
                                "shape_metrics": metrics,
                                "issues": attempt_issues,
                            }
                        )
                        if attempt_issues:
                            continue
                        if terminal_required:
                            terminal_plan, terminal_attempts = _fit_terminal_for_branch(
                                branch,
                                points,
                                flowers,
                                backbone,
                                accepted,
                                accepted_terminals,
                                bounds,
                                motif_kind_counts,
                            )
                            if terminal_plan is None:
                                attempts[-1]["issues"] = ["terminal_no_fit"]
                                attempts[-1]["terminal_attempts"] = terminal_attempts
                                continue
                        else:
                            terminal_plan = {
                                "selected": False,
                                "reason": (
                                    "visual_hierarchy_budget"
                                    if terminal_skip_reasons.get(branch_id) == "visual_hierarchy_budget"
                                    else "continued_by_child"
                                    if branch_id in skipped_terminal_ids
                                    else "not_terminal_role"
                                ),
                            }
                        joint_score, coverage_gain = _coverage_adjusted_score(
                            score + float(terminal_plan.get("fit_penalty", 0.0)),
                            points,
                            terminal_plan,
                            occupied_cells,
                            bounds,
                            coverage_cell_size,
                        )
                        terminal_plan["coverage_gain_cells"] = coverage_gain
                        candidate = (
                            points,
                            family,
                            bow_sign,
                            target_scale,
                            style_strength,
                            metrics,
                            joint_score,
                            terminal_plan,
                        )
                        if chosen is None or joint_score < chosen[-2]:
                            chosen = candidate
        if chosen is None and branch["source"] == "existing_svg_guide":
            fallback = source_points
            if role == "flower_connector":
                connector_id = str(branch["connector_flower_id"])
                connector_flower = next(flower for flower in flowers if flower["flower_id"] == connector_id)
                fallback = _clip_to_flower_interface(fallback, connector_flower)
            issues = _candidate_issues(
                fallback,
                flowers,
                backbone,
                accepted,
                accepted_terminals,
                parent_id,
                allow_flower_inward=role == "flower_connector",
                minimum_clearance=minimum_clearance,
            )
            metrics = _curve_shape_metrics(fallback)
            score, near_straight = _shape_score(
                metrics,
                role,
                strength=1.0,
                target_scale=1.0,
                family_mismatch=True,
            )
            if not issues and (not near_straight or role == "flower_connector"):
                if terminal_required:
                    terminal_plan, terminal_attempts = _fit_terminal_for_branch(
                        branch,
                        fallback,
                        flowers,
                        backbone,
                        accepted,
                        accepted_terminals,
                        bounds,
                        motif_kind_counts,
                    )
                else:
                    terminal_plan, terminal_attempts = (
                        {
                            "selected": False,
                            "reason": (
                                "visual_hierarchy_budget"
                                if terminal_skip_reasons.get(branch_id) == "visual_hierarchy_budget"
                                else "continued_by_child"
                                if branch_id in skipped_terminal_ids
                                else "not_terminal_role"
                            ),
                        },
                        [],
                    )
                if terminal_plan is not None:
                    joint_score, coverage_gain = _coverage_adjusted_score(
                        score + float(terminal_plan.get("fit_penalty", 0.0)),
                        fallback,
                        terminal_plan,
                        occupied_cells,
                        bounds,
                        coverage_cell_size,
                    )
                    terminal_plan["coverage_gain_cells"] = coverage_gain
                    chosen = (
                        fallback,
                        "source_fallback",
                        base_sign,
                        1.0,
                        1.0,
                        metrics,
                        joint_score,
                        terminal_plan,
                    )
                elif terminal_attempts:
                    attempts.append(
                        {
                            "family": "source_fallback",
                            "issues": ["terminal_no_fit"],
                            "terminal_attempts": terminal_attempts,
                        }
                    )
        if chosen is None and role != "flower_connector":
            redirected_source = _redirect_source_around_flower(
                source_points,
                parent_points,
                float(branch["mount_fraction"]),
                flowers,
            )
            if redirected_source is not None:
                for target_scale in (1.0, 0.88, 0.76, 0.62, 0.52):
                    for family in ("c_flow", "s_flow"):
                        for graft_scale in (0.55, 0.35, 0.20):
                            for bow_sign in (base_sign, -base_sign):
                                for style_strength in strengths:
                                    points = _curve_candidate(
                                        redirected_source,
                                        parent_points,
                                        float(branch["mount_fraction"]),
                                        role=role,
                                        family=family,
                                        bow_sign=bow_sign,
                                        target_scale=target_scale,
                                        style_strength=style_strength,
                                        graft_scale=graft_scale,
                                    )
                                    issues = _candidate_issues(
                                        points,
                                        flowers,
                                        backbone,
                                        accepted,
                                        accepted_terminals,
                                        parent_id,
                                        minimum_clearance=minimum_clearance,
                                    )
                                    metrics = _curve_shape_metrics(points)
                                    score, near_straight = _shape_score(
                                        metrics,
                                        role,
                                        strength=style_strength,
                                        target_scale=target_scale,
                                        family_mismatch=family != preferred_family,
                                    )
                                    attempt_issues = issues + (["near_straight"] if near_straight else [])
                                    attempts.append(
                                        {
                                            "family": family,
                                            "bow_sign": bow_sign,
                                            "target_scale": target_scale,
                                            "style_strength": style_strength,
                                            "graft_scale": graft_scale,
                                            "redirect": "flower_tangent",
                                            "shape_score": score,
                                            "shape_metrics": metrics,
                                            "issues": attempt_issues,
                                        }
                                    )
                                    if attempt_issues:
                                        continue
                                    if terminal_required:
                                        terminal_plan, terminal_attempts = _fit_terminal_for_branch(
                                            branch,
                                            points,
                                            flowers,
                                            backbone,
                                            accepted,
                                            accepted_terminals,
                                            bounds,
                                            motif_kind_counts,
                                        )
                                        if terminal_plan is None:
                                            attempts[-1]["issues"] = ["terminal_no_fit"]
                                            attempts[-1]["terminal_attempts"] = terminal_attempts
                                            continue
                                    else:
                                        terminal_plan = {
                                            "selected": False,
                                            "reason": (
                                                "visual_hierarchy_budget"
                                                if terminal_skip_reasons.get(branch_id) == "visual_hierarchy_budget"
                                                else "continued_by_child"
                                                if branch_id in skipped_terminal_ids
                                                else "not_terminal_role"
                                            ),
                                        }
                                    joint_score, coverage_gain = _coverage_adjusted_score(
                                        score + float(terminal_plan.get("fit_penalty", 0.0)),
                                        points,
                                        terminal_plan,
                                        occupied_cells,
                                        bounds,
                                        coverage_cell_size,
                                    )
                                    terminal_plan["coverage_gain_cells"] = coverage_gain
                                    candidate = (
                                        points,
                                        f"{family}_flower_tangent",
                                        bow_sign,
                                        target_scale,
                                        style_strength,
                                        metrics,
                                        joint_score,
                                        terminal_plan,
                                    )
                                    if chosen is None or joint_score < chosen[-2]:
                                        chosen = candidate
        if chosen is None:
            if branch["source"] in {"grammar_slot", "growth_region", "coverage_region"}:
                pruned_ids.add(branch_id)
                reason = (
                    "joint_terminal_no_fit"
                    if any("terminal_no_fit" in attempt.get("issues", []) for attempt in attempts)
                    else "joint_branch_conflict"
                )
                pruned.append({"branch_id": branch_id, "reason": reason})
                geometry.append(
                    {
                        "branch_id": branch_id,
                        "status": "pruned_joint_conflict",
                        "source": branch["source"],
                        "generation": branch["generation"],
                        "role": branch["role"],
                        "parent_id": parent_id,
                        "terminal": branch["terminal"],
                        "prune_reason": reason,
                    }
                )
                continue
            rejected.append({"branch_id": branch_id, "reasons": attempts[-1]["issues"] if attempts else ["no_candidate"], "attempts": attempts})
            continue
        points, family, bow_sign, target_scale, style_strength, shape_metrics, shape_score, terminal_plan = chosen
        accepted[branch_id] = points
        if terminal_plan.get("selected"):
            accepted_terminals[f"{branch_id}_motif"] = list(terminal_plan["paths"])
            kind = str(terminal_plan["kind"])
            motif_kind_counts[kind] = motif_kind_counts.get(kind, 0) + 1
        occupied_cells.update(
            _joint_coverage_cells(
                points,
                terminal_plan,
                bounds,
                coverage_cell_size,
            )
        )
        root_tangent = _norm(_sub(points[1], points[0]))
        _, parent_tangent = _sample_polyline(parent_points, float(branch["mount_fraction"]))
        tangent_alignment = abs(_dot(root_tangent, parent_tangent))
        geometry.append(
            {
                "branch_id": branch_id,
                "status": "accepted",
                "source": branch["source"],
                "generation": branch["generation"],
                "role": branch["role"],
                "parent_id": parent_id,
                "family": family,
                "bow_sign": bow_sign,
                "target_scale": target_scale,
                "style_strength": style_strength,
                "shape_score": shape_score,
                "shape_metrics": shape_metrics,
                "root_tangent_alignment": tangent_alignment,
                "terminal": branch["terminal"],
                "terminal_plan": terminal_plan,
                "points": points,
            }
        )

    accepted_entries = [entry for entry in geometry if entry["status"] == "accepted"]
    crossing_count = 0
    flower_inside_count = 0
    flower_inward_count = 0
    straight_branch_count = 0
    deviation_ratios: list[float] = []
    arc_ratios: list[float] = []
    for entry in accepted_entries:
        points = _as_points(entry["points"])
        flower_inside_count += int(any(_flower_intrusion(points, flower) for flower in flowers))
        if entry["role"] != "flower_connector":
            flower_inward_count += int(_flower_inward(points, flowers))
            metrics = _curve_shape_metrics(points)
            _, near_straight = _shape_score(
                metrics,
                str(entry["role"]),
                strength=float(entry.get("style_strength", 1.0)),
                target_scale=float(entry.get("target_scale", 1.0)),
                family_mismatch=False,
            )
            straight_branch_count += int(near_straight)
            deviation_ratios.append(metrics["max_deviation_ratio"])
            arc_ratios.append(metrics["arc_ratio"])
    for index, first in enumerate(accepted_entries):
        first_points = _as_points(first["points"])
        for second in accepted_entries[index + 1 :]:
            if first["parent_id"] == second["branch_id"] or second["parent_id"] == first["branch_id"]:
                continue
            second_points = _as_points(second["points"])
            if _crosses_path(first_points, second_points, first_points[0], False):
                crossing_count += 1
    terminal_branch_crossing_count = 0
    terminal_overlap_count = 0
    terminal_boundary_violation_count = 0
    terminal_flower_overlap_count = 0
    visual_clearance_violations: list[dict[str, object]] = []
    terminal_items = list(accepted_terminals.items())
    for terminal_id, terminal_paths in terminal_items:
        owner_id = terminal_id.removesuffix("_motif")
        owner_points = accepted[owner_id]
        owner_root = owner_points[-1]
        for terminal_path in terminal_paths:
            points = _as_points(terminal_path["points"])
            closed = bool(terminal_path["closed"])
            terminal_boundary_violation_count += int(
                any(
                    point[0] < bounds[0]
                    or point[0] > bounds[2]
                    or point[1] < bounds[1]
                    or point[1] > bounds[3]
                    for point in points
                )
            )
            terminal_flower_overlap_count += int(
                any(
                    _inside_flower(point, flower, padding=1.04)
                    for point in points[1:]
                    for flower in flowers
                )
            )
            for branch_id, branch_points in accepted.items():
                if _paths_overlap(
                    points,
                    closed,
                    branch_points,
                    False,
                    shared_root=owner_root if branch_id == owner_id else None,
                ):
                    terminal_branch_crossing_count += 1
    for index, (_, first_paths) in enumerate(terminal_items):
        for _, second_paths in terminal_items[index + 1 :]:
            if any(
                _paths_overlap(
                    _as_points(first_path["points"]),
                    bool(first_path["closed"]),
                    _as_points(second_path["points"]),
                    bool(second_path["closed"]),
                )
                for first_path in first_paths
                for second_path in second_paths
            ):
                terminal_overlap_count += 1
    for index, first in enumerate(accepted_entries):
        first_points = _as_points(first["points"])
        for second in accepted_entries[index + 1 :]:
            if first["parent_id"] == second["branch_id"] or second["parent_id"] == first["branch_id"]:
                continue
            distance = _path_min_distance(first_points, _as_points(second["points"]))
            if distance < 6.0:
                visual_clearance_violations.append(
                    {
                        "first_branch_id": first["branch_id"],
                        "second_branch_id": second["branch_id"],
                        "distance": distance,
                    }
                )
    coverage = _coverage_summary(occupied_cells, bounds, flowers, coverage_cell_size)
    qa = {
        "valid": (
            crossing_count == 0
            and flower_inside_count == 0
            and flower_inward_count == 0
            and straight_branch_count == 0
            and terminal_branch_crossing_count == 0
            and terminal_overlap_count == 0
            and terminal_boundary_violation_count == 0
            and terminal_flower_overlap_count == 0
            and not rejected
        ),
        "accepted_count": len(accepted_entries),
        "rejected_count": len(rejected),
        "pruned_count": len(pruned),
        "pruned": pruned,
        "terminal_component_count": skipped_terminal_components,
        "terminal_hint_count": sum(1 for entry in accepted_entries if entry["role"] == "terminal_hint"),
        "joint_terminal_count": len(accepted_terminals),
        "budget_skipped_terminal_count": len(budget_skipped),
        "budget_skipped_terminals": budget_skipped,
        "terminal_branch_crossing_count": terminal_branch_crossing_count,
        "terminal_overlap_count": terminal_overlap_count,
        "terminal_boundary_violation_count": terminal_boundary_violation_count,
        "terminal_flower_overlap_count": terminal_flower_overlap_count,
        "visual_clearance_violation_count": len(visual_clearance_violations),
        "visual_clearance_violations": visual_clearance_violations,
        "coverage": coverage,
        "terminal_kind_counts": motif_kind_counts,
        "crossing_count": crossing_count,
        "flower_inside_count": flower_inside_count,
        "flower_inward_count": flower_inward_count,
        "straight_branch_count": straight_branch_count,
        "minimum_deviation_ratio": min(deviation_ratios, default=0.0),
        "mean_deviation_ratio": sum(deviation_ratios) / max(1, len(deviation_ratios)),
        "minimum_arc_ratio": min(arc_ratios, default=1.0),
        "mean_arc_ratio": sum(arc_ratios) / max(1, len(arc_ratios)),
        "minimum_root_tangent_alignment": min(
            (float(entry["root_tangent_alignment"]) for entry in accepted_entries),
            default=1.0,
        ),
        "rejected": rejected,
    }
    return geometry, accepted, qa


def _font(size: int) -> ImageFont.ImageFont:
    for path in (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/msyh.ttc")):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _render(
    profile: dict[str, object],
    geometry: list[dict[str, object]],
    accepted: dict[str, list[Point]],
    qa: dict[str, object],
) -> Image.Image:
    source_width = 256.0
    source_height = float(profile["canvas"]["height"])
    scale = 2.5
    margin_x = 24
    header = 72
    footer = 36
    image = Image.new(
        "RGB",
        (round(source_width * scale) + margin_x * 2, round(source_height * scale) + header + footer),
        PAPER,
    )
    draw = ImageDraw.Draw(image)
    transform = lambda point: (margin_x + round(point[0] * scale), header + round(point[1] * scale))
    title_font = _font(18)
    label_font = _font(12)
    draw.text((16, 14), f"{profile['prototype_id']} | local branch geometry", fill=INK, font=title_font)
    status = "PASS" if qa["valid"] else "FAIL"
    draw.text(
        (16, 42),
        f"{status} accepted={qa['accepted_count']} rejected={qa['rejected_count']} "
        f"pruned={qa['pruned_count']} terminal={qa['joint_terminal_count']} "
        f"cross={qa['crossing_count']} inward={qa['flower_inward_count']} "
        f"straight={qa['straight_branch_count']} curve={qa['mean_deviation_ratio']:.3f} "
        f"tangent={qa['minimum_root_tangent_alignment']:.3f}",
        fill=PRIMARY if qa["valid"] else REJECTED,
        font=label_font,
    )
    backbone = _as_points(sample["point"] for sample in profile["backbone"]["arc_samples"])
    draw.line([transform(point) for point in backbone], fill=INK, width=7, joint="curve")
    for flower in profile["flowers"]:
        center = tuple(float(value) for value in flower["center"])
        rx = float(flower["rx"])
        ry = float(flower["ry"])
        draw.ellipse(
            [transform((center[0] - rx, center[1] - ry)), transform((center[0] + rx, center[1] + ry))],
            outline=FLOWER,
            width=3,
        )
    by_id = {str(entry["branch_id"]): entry for entry in geometry}
    for branch_id, points in accepted.items():
        entry = by_id[branch_id]
        generation = int(entry["generation"])
        role = str(entry["role"])
        color = TERMINAL_HINT if role == "terminal_hint" else PRIMARY if generation == 1 else SECONDARY if generation == 2 else TERTIARY
        width = 5 if generation == 1 else 4 if generation == 2 else 3
        draw.line([transform(point) for point in points], fill=color, width=width, joint="curve")
    for entry in geometry:
        if entry["status"] != "accepted":
            continue
        terminal_plan = dict(entry.get("terminal_plan", {}))
        if not terminal_plan.get("selected"):
            continue
        for terminal_path in terminal_plan["paths"]:
            points = _as_points(terminal_path["points"])
            transformed = [transform(point) for point in points]
            draw.line(transformed, fill=TERMINAL_PLAN, width=3, joint="curve")
            if terminal_path["closed"]:
                draw.line([transformed[-1], transformed[0]], fill=TERMINAL_PLAN, width=3)
    draw.text(
        (16, image.height - 27),
        "dark=backbone  blue=primary  cyan=secondary  green=tertiary  gray=terminal hint  purple=joint terminal plan",
        fill="#475569",
        font=label_font,
    )
    return image


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


def _build_one(profile_path: Path, plan_path: Path, output_dir: Path) -> tuple[dict[str, object], Path]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    layout = json.loads(plan_path.read_text(encoding="utf-8"))
    geometry, accepted, qa = _build_geometry(profile, layout)
    result = {
        "schema": "chanzhi_branch_geometry_v1",
        "prototype_id": profile["prototype_id"],
        "source_profile": str(profile_path),
        "source_layout_plan": str(plan_path),
        "branches": geometry,
        "qa": qa,
    }
    case_dir = output_dir / str(profile["prototype_id"])
    case_dir.mkdir(parents=True, exist_ok=True)
    geometry_path = case_dir / "branch_geometry.json"
    geometry_path.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
    preview = _render(profile, geometry, accepted, qa)
    preview_path = case_dir / "branch_geometry_preview.png"
    preview.save(preview_path)
    return result, preview_path


def run(args: argparse.Namespace) -> dict[str, object]:
    profile_root = args.profile_root.resolve()
    plan_root = args.plan_root.resolve()
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
                output_dir,
            )
            results.append(result)
            previews.append(preview_path)
            print(f"Built {prototype_id}: {preview_path}")
        except Exception as exc:
            errors.append({"prototype_id": prototype_id, "error": repr(exc)})
            print(f"Failed {prototype_id}: {exc}")
    contact_sheet = output_dir / "branch_geometry_contact_sheet.png"
    _contact_sheet(previews, contact_sheet)
    manifest = {
        "schema": "chanzhi_branch_geometry_manifest_v1",
        "profile_root": str(profile_root),
        "plan_root": str(plan_root),
        "output_dir": str(output_dir),
        "success_count": len(results),
        "error_count": len(errors),
        "errors": errors,
        "contact_sheet": str(contact_sheet),
        "summary": [
            {
                "prototype_id": result["prototype_id"],
                "valid": result["qa"]["valid"],
                "accepted_count": result["qa"]["accepted_count"],
                "rejected_count": result["qa"]["rejected_count"],
                "pruned_count": result["qa"]["pruned_count"],
                "joint_terminal_count": result["qa"]["joint_terminal_count"],
                "budget_skipped_terminal_count": result["qa"]["budget_skipped_terminal_count"],
                "terminal_branch_crossing_count": result["qa"]["terminal_branch_crossing_count"],
                "terminal_overlap_count": result["qa"]["terminal_overlap_count"],
                "terminal_boundary_violation_count": result["qa"]["terminal_boundary_violation_count"],
                "terminal_flower_overlap_count": result["qa"]["terminal_flower_overlap_count"],
                "crossing_count": result["qa"]["crossing_count"],
                "flower_inside_count": result["qa"]["flower_inside_count"],
                "flower_inward_count": result["qa"]["flower_inward_count"],
                "straight_branch_count": result["qa"]["straight_branch_count"],
                "minimum_deviation_ratio": result["qa"]["minimum_deviation_ratio"],
                "mean_deviation_ratio": result["qa"]["mean_deviation_ratio"],
                "minimum_arc_ratio": result["qa"]["minimum_arc_ratio"],
                "mean_arc_ratio": result["qa"]["mean_arc_ratio"],
                "minimum_root_tangent_alignment": result["qa"]["minimum_root_tangent_alignment"],
            }
            for result in results
        ],
    }
    manifest_path = output_dir / "branch_geometry_manifest.json"
    manifest_path.write_text(json.dumps(_jsonable(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {contact_sheet}")
    print(f"Saved {manifest_path}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate validated local branch geometry from layout plans.")
    parser.add_argument("--profile-root", type=Path, default=DEFAULT_PROFILE_ROOT)
    parser.add_argument("--plan-root", type=Path, default=DEFAULT_PLAN_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prototype-ids", nargs="+", default=list(DEFAULT_PROTOTYPE_IDS))
    manifest = run(parser.parse_args())
    return 0 if not manifest["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
