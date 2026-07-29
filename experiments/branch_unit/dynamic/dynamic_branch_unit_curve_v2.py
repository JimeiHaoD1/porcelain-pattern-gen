#!/usr/bin/env python3
"""Compile stage-3 macro BranchUnit plans into complete dynamic L1/L2/L3 curves.

Stage 3 fixes the repeat-level position, direction, distance, flower relation,
and occupancy corridor of every BranchUnit.  This compiler deliberately does
not trace the stage-3 direction line.  It first selects a globally compatible
set of visibly curved primary sweeps, then materializes one coordinated child
topology per unit, and finally selects a globally compatible set of complete
unit candidates before emitting the immutable raw candidate.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence


Point = tuple[float, float]
EPSILON = 1e-9
SCHEMA = "dynamic_branch_unit_curve_candidate_v2"
CONTRACT_SCHEMA = "dynamic_branch_stage4_unit_curve_contract_v2"


class UnitCurveCompilationFailure(RuntimeError):
    """Fatal input/compilation failure; never a visual-quality conclusion."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any]):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "dynamic_branch_unit_curve_compilation_failure_v2",
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retry_count": 0,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
        }


@dataclass(frozen=True)
class UnitVariant:
    unit_id: str
    pattern_id: str
    curves: tuple[dict[str, Any], ...]
    topology: dict[str, Any]
    local_score: float
    local_score_trace: dict[str, Any]


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _u01(seed: int, *labels: object) -> float:
    raw = "|".join([str(seed), *(str(label) for label in labels)])
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _round(value: float, digits: int = 9) -> float:
    return round(float(value), digits)


def _point(value: Sequence[float]) -> Point:
    point = (float(value[0]), float(value[1]))
    if not all(math.isfinite(component) for component in point):
        raise UnitCurveCompilationFailure(
            "non_finite_geometry",
            "curve compilation input contains a non-finite coordinate",
            {"value": list(value)},
        )
    return point


def _point_json(point: Point) -> list[float]:
    return [_round(point[0]), _round(point[1])]


def _add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def _mul(a: Point, scale: float) -> Point:
    return (a[0] * scale, a[1] * scale)


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _length(a: Point) -> float:
    return math.hypot(a[0], a[1])


def _distance(a: Point, b: Point) -> float:
    return _length(_sub(a, b))


def _unit(a: Point) -> Point:
    length = _length(a)
    if length < EPSILON:
        raise UnitCurveCompilationFailure(
            "degenerate_geometry",
            "zero-length direction cannot be normalized",
            {"vector": list(a)},
        )
    return (a[0] / length, a[1] / length)


def _normal(a: Point) -> Point:
    direction = _unit(a)
    return (-direction[1], direction[0])


def _rotate(a: Point, degrees: float) -> Point:
    radians = math.radians(degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        a[0] * cosine - a[1] * sine,
        a[0] * sine + a[1] * cosine,
    )


def _blend_direction(first: Point, second: Point, second_weight: float) -> Point:
    weight = max(0.0, min(1.0, second_weight))
    return _unit(_add(_mul(first, 1.0 - weight), _mul(second, weight)))


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point) -> dict[str, list[float]]:
    return {
        "p0": _point_json(p0),
        "p1": _point_json(p1),
        "p2": _point_json(p2),
        "p3": _point_json(p3),
    }


def cubic_point(cubic: Mapping[str, Sequence[float]], t: float) -> Point:
    p0, p1, p2, p3 = (_point(cubic[key]) for key in ("p0", "p1", "p2", "p3"))
    mt = 1.0 - t
    return (
        mt**3 * p0[0]
        + 3.0 * mt**2 * t * p1[0]
        + 3.0 * mt * t**2 * p2[0]
        + t**3 * p3[0],
        mt**3 * p0[1]
        + 3.0 * mt**2 * t * p1[1]
        + 3.0 * mt * t**2 * p2[1]
        + t**3 * p3[1],
    )


def sample_cubics(
    cubics: Sequence[Mapping[str, Sequence[float]]],
    *,
    samples_per_cubic: int = 48,
) -> list[Point]:
    points: list[Point] = []
    for cubic_index, cubic in enumerate(cubics):
        sampled = [
            cubic_point(cubic, index / samples_per_cubic)
            for index in range(samples_per_cubic + 1)
        ]
        points.extend(sampled if cubic_index == 0 else sampled[1:])
    return points


def _polyline_length(points: Sequence[Point]) -> float:
    return sum(_distance(a, b) for a, b in zip(points, points[1:]))


def _sample_polyline(
    points: Sequence[Point],
    fraction: float,
) -> tuple[Point, Point]:
    if len(points) < 2:
        raise UnitCurveCompilationFailure(
            "degenerate_parent_curve",
            "parent curve has fewer than two samples",
            {"point_count": len(points)},
        )
    fraction = max(0.0, min(1.0, fraction))
    lengths = [_distance(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    if total < EPSILON:
        raise UnitCurveCompilationFailure(
            "degenerate_parent_curve",
            "parent curve has zero arc length",
            {},
        )
    target = total * fraction
    traversed = 0.0
    for (start, end), length in zip(zip(points, points[1:]), lengths):
        if traversed + length >= target:
            local = (target - traversed) / max(length, EPSILON)
            return (
                _add(start, _mul(_sub(end, start), local)),
                _unit(_sub(end, start)),
            )
        traversed += length
    return points[-1], _unit(_sub(points[-1], points[-2]))


def _scale_cubics_to_length(
    cubics: Sequence[Mapping[str, Sequence[float]]],
    origin: Point,
    target_length: float,
) -> list[dict[str, list[float]]]:
    current = _polyline_length(sample_cubics(cubics, samples_per_cubic=80))
    scale = target_length / max(current, EPSILON)
    result: list[dict[str, list[float]]] = []
    for cubic in cubics:
        transformed = []
        for key in ("p0", "p1", "p2", "p3"):
            point = _point(cubic[key])
            transformed.append(_add(origin, _mul(_sub(point, origin), scale)))
        result.append(_cubic(*transformed))
    return result


def _shape_metrics(curve: Mapping[str, Any]) -> dict[str, float]:
    points = sample_cubics(curve["cubic_segments"], samples_per_cubic=72)
    chord = _sub(points[-1], points[0])
    chord_length = _length(chord)
    path_length = _polyline_length(points)
    if chord_length < EPSILON:
        return {
            "chord_length": chord_length,
            "path_length": path_length,
            "arc_ratio": 1.0,
            "maximum_deviation_ratio": 0.0,
            "absolute_turn_degrees": 0.0,
        }
    normal = _normal(chord)
    maximum_deviation = max(
        abs(_dot(_sub(point, points[0]), normal)) for point in points
    )
    absolute_turn = 0.0
    previous: Point | None = None
    for start, end in zip(points, points[1:]):
        direction = _unit(_sub(end, start))
        if previous is not None:
            cosine = max(-1.0, min(1.0, _dot(previous, direction)))
            absolute_turn += math.degrees(math.acos(cosine))
        previous = direction
    return {
        "chord_length": _round(chord_length),
        "path_length": _round(path_length),
        "arc_ratio": _round(path_length / chord_length),
        "maximum_deviation_ratio": _round(maximum_deviation / chord_length),
        "absolute_turn_degrees": _round(absolute_turn),
    }


def _oriented_parent_tangent(reference: Point, direction: Point) -> Point:
    tangent = _unit(reference)
    return tangent if _dot(tangent, direction) >= 0.0 else _mul(tangent, -1.0)


def _ordinary_primary(
    unit: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    seed: int,
    bow_sign: int,
) -> dict[str, Any]:
    path_points = [_point(point) for point in unit["directional_layout_intent"]["path_points"]]
    if len(path_points) != 2:
        raise UnitCurveCompilationFailure(
            "invalid_directional_path",
            "ordinary primary needs exactly two stage-3 path points",
            {"branch_unit_id": unit["branch_unit_id"], "point_count": len(path_points)},
        )
    root, tip = path_points
    chord = _sub(tip, root)
    length = _length(chord)
    direction = _unit(chord)
    policy = contract["primary_curve_compilation"]
    parent = _oriented_parent_tangent(
        _point(unit["root_tangent_intent"]["parent_tangent_reference"]),
        direction,
    )
    entry = _blend_direction(
        direction,
        parent,
        float(policy["root_parent_tangent_weight"]),
    )
    role = str(unit["structural_role"])
    ratio_range = (
        policy["flower_support_bow_ratio_range"]
        if "flower_support" in role
        else policy["ordinary_primary_bow_ratio_range"]
    )
    ratio = float(ratio_range[0]) + (
        float(ratio_range[1]) - float(ratio_range[0])
    ) * _u01(seed, unit["branch_unit_id"], "primary_bow")
    occupancy_radius = float(unit["occupancy_envelope"]["radius"])
    amplitude = min(
        length * ratio,
        occupancy_radius
        * float(policy["primary_bow_must_not_exceed_stage3_occupancy_radius_factor"]),
    )
    side = 1 if bow_sign >= 0 else -1
    normal = _normal(direction)
    shape_mode = (
        "c_sweep"
        if _u01(seed, unit["branch_unit_id"], "primary_mode") < 0.68
        else "soft_s"
    )
    join_fraction = 0.50 + 0.07 * (
        _u01(seed, unit["branch_unit_id"], "join_fraction") - 0.5
    )
    join = _add(
        _add(root, _mul(chord, join_fraction)),
        _mul(normal, side * amplitude),
    )
    if shape_mode == "c_sweep":
        join_tangent = _unit(_add(direction, _mul(normal, -side * 0.16)))
        exit_tangent = _unit(_add(direction, _mul(normal, -side * 0.62)))
    else:
        join_tangent = _unit(_add(direction, _mul(normal, -side * 0.38)))
        exit_tangent = _unit(_add(direction, _mul(normal, side * 0.28)))
    first_length = _distance(root, join)
    second_length = _distance(join, tip)
    first = _cubic(
        root,
        _add(root, _mul(entry, max(0.018, first_length * 0.30))),
        _sub(join, _mul(join_tangent, max(0.020, first_length * 0.28))),
        join,
    )
    second = _cubic(
        join,
        _add(join, _mul(join_tangent, max(0.020, second_length * 0.29))),
        _sub(tip, _mul(exit_tangent, max(0.018, second_length * 0.28))),
        tip,
    )
    return _primary_record(
        unit,
        [first, second],
        path_points,
        bow_sign=side,
        shape_mode=shape_mode,
        bow_amplitude=amplitude,
        entry_direction=entry,
    )


def _sw3_primary(
    unit: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    seed: int,
    bow_sign: int,
) -> dict[str, Any]:
    del contract
    path_points = [_point(point) for point in unit["directional_layout_intent"]["path_points"]]
    if len(path_points) != 3:
        raise UnitCurveCompilationFailure(
            "invalid_sw3_route",
            "SW3 terminal support needs root, below-flower waypoint, and underside tip",
            {"branch_unit_id": unit["branch_unit_id"], "point_count": len(path_points)},
        )
    root, waypoint, tip = path_points
    first_vector = _sub(waypoint, root)
    second_vector = _sub(tip, waypoint)
    first_direction = _unit(first_vector)
    second_direction = _unit(second_vector)
    parent = _oriented_parent_tangent(
        _point(unit["root_tangent_intent"]["parent_tangent_reference"]),
        first_direction,
    )
    entry = _blend_direction(first_direction, parent, 0.14)
    joined = _unit(_add(first_direction, second_direction))
    side = 1 if bow_sign >= 0 else -1
    first_normal = _normal(first_direction)
    second_normal = _normal(second_direction)
    first_length = _length(first_vector)
    second_length = _length(second_vector)
    first_bias = side * min(
        float(unit["occupancy_envelope"]["radius"]) * 0.42,
        first_length * 0.065,
    )
    second_bias = -side * min(
        float(unit["occupancy_envelope"]["radius"]) * 0.30,
        second_length * 0.055,
    )
    first = _cubic(
        root,
        _add(
            _add(root, _mul(entry, first_length * 0.27)),
            _mul(first_normal, first_bias),
        ),
        _sub(waypoint, _mul(joined, first_length * 0.24)),
        waypoint,
    )
    exit_tangent = _unit(
        _add(second_direction, _mul(second_normal, second_bias / max(second_length, EPSILON)))
    )
    second = _cubic(
        waypoint,
        _add(waypoint, _mul(joined, second_length * 0.30)),
        _sub(tip, _mul(exit_tangent, second_length * 0.27)),
        tip,
    )
    return _primary_record(
        unit,
        [first, second],
        path_points,
        bow_sign=side,
        shape_mode="sw3_below_flower_reach",
        bow_amplitude=abs(first_bias) + abs(second_bias),
        entry_direction=entry,
    )


def _primary_record(
    unit: Mapping[str, Any],
    cubics: Sequence[Mapping[str, Sequence[float]]],
    path_points: Sequence[Point],
    *,
    bow_sign: int,
    shape_mode: str,
    bow_amplitude: float,
    entry_direction: Point,
) -> dict[str, Any]:
    curve = {
        "curve_id": f'{unit["branch_unit_id"]}.L1',
        "branch_curve_id": f'{unit["branch_unit_id"]}.L1',
        "branch_unit_id": unit["branch_unit_id"],
        "hierarchy_level": 1,
        "level": "L1",
        "parent_curve_id": "backbone",
        "parent_kind": "backbone",
        "mount_fraction": float(unit["parent_ref"]["mount_s"]),
        "structural_role": unit["structural_role"],
        "semantic_function": unit["semantic_function"],
        "width": 3.0,
        "cubic_segments": [dict(cubic) for cubic in cubics],
        "source_stage3_path_points": [_point_json(point) for point in path_points],
        "compiler_trace": {
            "compiler": "dynamic_branchunit_primary_sweep_v2",
            "shape_mode": shape_mode,
            "bow_sign": int(bow_sign),
            "bow_amplitude": _round(bow_amplitude),
            "entry_direction": _point_json(entry_direction),
            "stage3_directional_path_is_not_the_final_centerline": True,
            "stage3_mount_and_tip_preserved": True,
        },
        "flower_relation_intents": list(unit["flower_relation_intents"]),
    }
    curve["shape_metrics"] = _shape_metrics(curve)
    return curve


def _compile_primary_variant(
    unit: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    seed: int,
    bow_sign: int,
) -> dict[str, Any]:
    if str(unit["structural_role"]) == "terminal_flower_support":
        return _sw3_primary(unit, contract, seed=seed, bow_sign=bow_sign)
    return _ordinary_primary(unit, contract, seed=seed, bow_sign=bow_sign)


def _compile_open_child(
    *,
    curve_id: str,
    unit_id: str,
    level: int,
    parent_curve: Mapping[str, Any],
    mount_fraction: float,
    target_length: float,
    turn_sign: int,
    angle_degrees: float,
    bow: float,
    shape_mode: str,
    width: float,
) -> dict[str, Any]:
    parent_points = sample_cubics(
        parent_curve["cubic_segments"],
        samples_per_cubic=96,
    )
    root, parent_tangent = _sample_polyline(parent_points, mount_fraction)
    sign = 1 if turn_sign >= 0 else -1
    angle = max(20.0, min(72.0, angle_degrees))
    bow = max(0.05, min(0.42, bow))
    travel = _rotate(parent_tangent, sign * angle)
    if shape_mode == "soft_s":
        exit_direction = _rotate(
            parent_tangent,
            -sign * (16.0 + 24.0 * bow),
        )
    else:
        exit_direction = _rotate(
            parent_tangent,
            sign * min(80.0, angle + 12.0 + 18.0 * bow),
        )
    tip = _add(root, _mul(travel, target_length * (0.82 + 0.10 * bow)))
    cubic = _cubic(
        root,
        _add(root, _mul(parent_tangent, target_length * (0.12 + 0.04 * bow))),
        _sub(tip, _mul(exit_direction, target_length * (0.23 + 0.08 * bow))),
        tip,
    )
    scaled = _scale_cubics_to_length([cubic], root, target_length)
    curve = {
        "curve_id": curve_id,
        "branch_curve_id": curve_id,
        "branch_unit_id": unit_id,
        "hierarchy_level": level,
        "level": f"L{level}",
        "parent_curve_id": parent_curve["curve_id"],
        "parent_kind": "branch_curve",
        "mount_fraction": _round(mount_fraction),
        "structural_role": (
            "secondary_branch" if level == 2 else "tertiary_branch"
        ),
        "semantic_function": "unit_child_rhythm",
        "width": _round(width),
        "cubic_segments": scaled,
        "flower_relation_intents": [],
        "compiler_trace": {
            "compiler": "parent_local_open_child_v2",
            "actual_parent_curve_id": parent_curve["curve_id"],
            "mount_fraction_is_parent_arc_length_fraction": True,
            "parent_local_entry_tangent": _point_json(parent_tangent),
            "turn_sign": sign,
            "angle_degrees": _round(angle),
            "bow": _round(bow),
            "shape_mode": shape_mode,
            "target_arc_length": _round(target_length),
        },
    }
    curve["shape_metrics"] = _shape_metrics(curve)
    return curve


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    edge = _sub(end, start)
    denominator = _dot(edge, edge)
    if denominator < EPSILON:
        return _distance(point, start)
    projection = max(0.0, min(1.0, _dot(_sub(point, start), edge) / denominator))
    return _distance(point, _add(start, _mul(edge, projection)))


def _segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _orientation(a: Point, b: Point, c: Point) -> float:
    return _cross(_sub(b, a), _sub(c, a))


def _on_segment(start: Point, end: Point, point: Point) -> bool:
    return (
        min(start[0], end[0]) - EPSILON
        <= point[0]
        <= max(start[0], end[0]) + EPSILON
        and min(start[1], end[1]) - EPSILON
        <= point[1]
        <= max(start[1], end[1]) + EPSILON
    )


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if o1 * o2 < -EPSILON and o3 * o4 < -EPSILON:
        return True
    for value, point, start, end in (
        (o1, c, a, b),
        (o2, d, a, b),
        (o3, a, c, d),
        (o4, b, c, d),
    ):
        if abs(value) <= EPSILON and _on_segment(start, end, point):
            return True
    return False


def _polyline_crosses(first: Sequence[Point], second: Sequence[Point]) -> bool:
    return any(
        _segments_intersect(a, b, c, d)
        for a, b in zip(first, first[1:])
        for c, d in zip(second, second[1:])
    )


def _polyline_distance(first: Sequence[Point], second: Sequence[Point]) -> float:
    return min(
        (
            _segment_distance(a, b, c, d)
            for a, b in zip(first, first[1:])
            for c, d in zip(second, second[1:])
        ),
        default=float("inf"),
    )


def _fast_polyline_distance(
    first: Sequence[Point],
    second: Sequence[Point],
) -> float:
    """Cheap symmetric clearance proxy used only during forward set selection."""

    if not first or not second:
        return float("inf")
    if len(first) == 1 and len(second) == 1:
        return _distance(first[0], second[0])
    distances: list[float] = []
    if len(second) >= 2:
        distances.extend(
            _point_segment_distance(point, start, end)
            for point in first
            for start, end in zip(second, second[1:])
        )
    if len(first) >= 2:
        distances.extend(
            _point_segment_distance(point, start, end)
            for point in second
            for start, end in zip(first, first[1:])
        )
    return min(distances, default=float("inf"))


def _inside_flower(
    point: Point,
    flower: Mapping[str, Any],
    *,
    protection: bool = True,
    padding: float = 1.0,
) -> bool:
    center = _point(flower["center"])
    rx_key = "protection_rx" if protection else "rx"
    ry_key = "protection_ry" if protection else "ry"
    rx = max(EPSILON, float(flower[rx_key]) * padding)
    ry = max(EPSILON, float(flower[ry_key]) * padding)
    return (
        ((point[0] - center[0]) / rx) ** 2
        + ((point[1] - center[1]) / ry) ** 2
        <= 1.0
    )


def _curve_signature(curve: Mapping[str, Any]) -> tuple[float, ...]:
    return tuple(
        float(cubic[key][axis])
        for cubic in curve["cubic_segments"]
        for key in ("p0", "p1", "p2", "p3")
        for axis in (0, 1)
    )


@lru_cache(maxsize=8192)
def _sample_curve_signature(
    signature: tuple[float, ...],
    samples: int,
) -> tuple[Point, ...]:
    if len(signature) % 8:
        raise UnitCurveCompilationFailure(
            "invalid_curve_signature",
            "cached curve signature does not contain complete cubics",
            {"coordinate_count": len(signature)},
        )
    points: list[Point] = []
    for cubic_index in range(len(signature) // 8):
        offset = cubic_index * 8
        p0 = (signature[offset], signature[offset + 1])
        p1 = (signature[offset + 2], signature[offset + 3])
        p2 = (signature[offset + 4], signature[offset + 5])
        p3 = (signature[offset + 6], signature[offset + 7])
        sampled: list[Point] = []
        for index in range(samples + 1):
            t = index / samples
            mt = 1.0 - t
            sampled.append(
                (
                    mt**3 * p0[0]
                    + 3.0 * mt**2 * t * p1[0]
                    + 3.0 * mt * t**2 * p2[0]
                    + t**3 * p3[0],
                    mt**3 * p0[1]
                    + 3.0 * mt**2 * t * p1[1]
                    + 3.0 * mt * t**2 * p2[1]
                    + t**3 * p3[1],
                )
            )
        points.extend(sampled if cubic_index == 0 else sampled[1:])
    return tuple(points)


def _curve_points(curve: Mapping[str, Any], samples: int = 24) -> list[Point]:
    return list(_sample_curve_signature(_curve_signature(curve), samples))


def _target_flower_ids(curve: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for relation in curve.get("flower_relation_intents", []):
        flower_id = relation.get("flower_id")
        if flower_id:
            result.add(str(flower_id))
    return result


def _curve_context_penalty(
    curve: Mapping[str, Any],
    *,
    analysis: Mapping[str, Any],
    all_primaries: Sequence[Mapping[str, Any]],
    parent_curve: Mapping[str, Any] | None,
) -> tuple[float, dict[str, float]]:
    points = _curve_points(curve, 14)
    backbone = [_point(row["point"]) for row in analysis["backbone"]["samples"]]
    level = int(curve["hierarchy_level"])
    score = 0.0
    trace = {
        "backbone": 0.0,
        "flowers": 0.0,
        "bounds": 0.0,
        "other_primaries": 0.0,
        "parent_recontact": 0.0,
    }
    height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    for point in points:
        if point[0] < -0.24 or point[0] > 1.24 or point[1] < -0.04 or point[1] > height + 0.04:
            trace["bounds"] += 220.0
    target_flower_ids = _target_flower_ids(curve)
    for flower in analysis["flowers"]:
        flower_id = str(flower["flower_id"])
        checked = points
        if level == 1 and flower_id in target_flower_ids:
            checked = points[:-6]
            intrusions = sum(
                _inside_flower(point, flower, protection=False)
                for point in checked
            )
        else:
            intrusions = sum(_inside_flower(point, flower) for point in checked)
        trace["flowers"] += intrusions * 40.0
    if level == 1:
        checked = points[6:]
    else:
        checked = points
    if _polyline_crosses(checked, backbone):
        trace["backbone"] += 900.0
    backbone_clearance = _fast_polyline_distance(checked, backbone)
    if backbone_clearance < 0.018:
        trace["backbone"] += (0.018 - backbone_clearance) * 900.0
    for primary in all_primaries:
        if primary["curve_id"] == curve["curve_id"]:
            continue
        other = _curve_points(primary, 14)
        if _polyline_crosses(points, other):
            trace["other_primaries"] += 850.0
        distance = _fast_polyline_distance(points, other)
        if distance < 0.018:
            trace["other_primaries"] += (0.018 - distance) * 700.0
    if parent_curve is not None:
        parent_points = _curve_points(parent_curve, 14)
        child_after_root = points[5:]
        if _polyline_crosses(child_after_root, parent_points):
            trace["parent_recontact"] += 700.0
        distance = _fast_polyline_distance(child_after_root, parent_points)
        if distance < 0.010:
            trace["parent_recontact"] += (0.010 - distance) * 600.0
    score = sum(trace.values())
    return score, trace


def _curve_pair_penalty(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    registered_parent_contact: bool = False,
) -> float:
    trim_first = False
    trim_second = False
    if registered_parent_contact:
        if second.get("parent_curve_id") == first.get("curve_id"):
            trim_second = True
        elif first.get("parent_curve_id") == second.get("curve_id"):
            trim_first = True
    return _cached_curve_pair_penalty(
        _curve_signature(first),
        _curve_signature(second),
        trim_first,
        trim_second,
        registered_parent_contact,
    )


@lru_cache(maxsize=16384)
def _cached_curve_pair_penalty(
    first_signature: tuple[float, ...],
    second_signature: tuple[float, ...],
    trim_first: bool,
    trim_second: bool,
    registered_parent_contact: bool,
) -> float:
    first_points = list(_sample_curve_signature(first_signature, 12))
    second_points = list(_sample_curve_signature(second_signature, 12))
    if trim_first:
        first_points = first_points[4:]
    if trim_second:
        second_points = second_points[4:]
    score = 0.0
    if _polyline_crosses(first_points, second_points):
        score += 1000.0
    distance = _fast_polyline_distance(first_points, second_points)
    required = 0.013 if registered_parent_contact else 0.018
    if distance < required:
        score += (required - distance) * 900.0
    return score


def _primary_set(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seed = int(plan["seed"])
    options: list[list[dict[str, Any]]] = []
    for unit in plan["branch_units"]:
        options.append(
            [
                _compile_primary_variant(
                    unit,
                    contract,
                    seed=seed,
                    bow_sign=bow_sign,
                )
                for bow_sign in (-1, 1)
            ]
        )
    best_score = float("inf")
    best_indices: tuple[int, ...] | None = None
    evaluated = 0
    for indices in itertools.product(*(range(len(rows)) for rows in options)):
        curves = [options[index][choice] for index, choice in enumerate(indices)]
        score = 0.0
        for curve in curves:
            local, _ = _curve_context_penalty(
                curve,
                analysis=analysis,
                all_primaries=curves,
                parent_curve=None,
            )
            score += local
            preferred_sign = -1 if _u01(seed, curve["branch_unit_id"], "preferred_bow") < 0.5 else 1
            if int(curve["compiler_trace"]["bow_sign"]) != preferred_sign:
                score += 0.08
        for first, second in itertools.combinations(curves, 2):
            score += _curve_pair_penalty(first, second)
        evaluated += 1
        if score < best_score - EPSILON:
            best_score = score
            best_indices = tuple(indices)
    if best_indices is None:
        raise UnitCurveCompilationFailure(
            "primary_set_selection_failed",
            "no primary curve set could be materialized",
            {"prototype_id": plan["prototype_id"], "seed": seed},
        )
    selected = [
        options[index][choice] for index, choice in enumerate(best_indices)
    ]
    return selected, {
        "schema": "dynamic_branch_primary_set_selection_trace_v2",
        "candidate_set_count": evaluated,
        "selected_variant_indices": list(best_indices),
        "selected_bow_signs": [
            curve["compiler_trace"]["bow_sign"] for curve in selected
        ],
        "selected_score": _round(best_score),
        "selection_is_forward_global_planning_not_retry": True,
    }


def _actual_child_count(
    unit: Mapping[str, Any],
    *,
    seed: int,
    density_class: str,
) -> int:
    envelope = unit["child_rhythm_envelope"]
    minimum = int(envelope["minimum_child_count"])
    maximum = int(envelope["maximum_child_count"])
    if maximum < minimum:
        raise UnitCurveCompilationFailure(
            "invalid_child_envelope",
            "stage-3 child count envelope is inverted",
            {"branch_unit_id": unit["branch_unit_id"]},
        )
    span = maximum - minimum + 1
    exponent = {
        "dense": 2.2,
        "moderate": 1.8,
        "primary_sweep_led": 1.65,
        "sparse": 2.4,
        "light": 2.5,
    }.get(density_class, 1.9)
    token = _u01(seed, unit["branch_unit_id"], "child_count") ** exponent
    choice = min(span - 1, int(token * span))
    return minimum + choice


def _mount_fractions(
    count: int,
    *,
    seed: int,
    unit_id: str,
) -> list[float]:
    base_by_count = {
        0: [],
        1: [0.58],
        2: [0.43, 0.68],
        3: [0.34, 0.55, 0.75],
        4: [0.32, 0.46, 0.62, 0.77],
    }
    if count not in base_by_count:
        raise UnitCurveCompilationFailure(
            "unsupported_child_count",
            "stage-4 v2 supports zero to four L2 curves per unit",
            {"branch_unit_id": unit_id, "child_count": count},
        )
    result = []
    for index, base in enumerate(base_by_count[count], start=1):
        jitter = (_u01(seed, unit_id, "mount", index) - 0.5) * 0.018
        result.append(max(0.32, min(0.78, base + jitter)))
    return result


def _length_class_at(unit: Mapping[str, Any], index: int) -> str:
    sequence = list(unit["child_rhythm_envelope"]["length_sequence"])
    if not sequence:
        return "medium"
    return str(sequence[index % len(sequence)])


def _child_length(
    unit: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    primary_length: float,
    index: int,
    seed: int,
) -> tuple[str, float]:
    length_class = _length_class_at(unit, index)
    ranges = contract["unit_topology_materialization"]["l2_length_ratio_by_class"]
    low, high = (float(value) for value in ranges[length_class])
    ratio = low + (high - low) * _u01(
        seed,
        unit["branch_unit_id"],
        "child_length",
        index,
    )
    return length_class, primary_length * ratio


def _pattern_signs(
    count: int,
    release_side: int,
) -> list[tuple[int, ...]]:
    if count == 0:
        return [()]
    alternating = tuple(
        release_side if index % 2 == 0 else -release_side for index in range(count)
    )
    reverse_alternating = tuple(-value for value in alternating)
    patterns = [
        tuple(release_side for _ in range(count)),
        alternating,
        reverse_alternating,
        tuple(-release_side for _ in range(count)),
    ]
    unique: list[tuple[int, ...]] = []
    for pattern in patterns:
        if pattern not in unique:
            unique.append(pattern)
    return unique


def _l3_enabled(
    unit: Mapping[str, Any],
    *,
    density_class: str,
    child_count: int,
    seed: int,
) -> bool:
    if child_count < 2 or str(unit["structural_role"]) == "terminal_flower_support":
        return False
    probability = {
        "dense": 0.52,
        "moderate": 0.34,
        "primary_sweep_led": 0.30,
        "sparse": 0.16,
        "light": 0.10,
    }.get(density_class, 0.22)
    return _u01(seed, unit["branch_unit_id"], "l3_enabled") < probability


def _unit_variants(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
    unit: Mapping[str, Any],
    primary: Mapping[str, Any],
    all_primaries: Sequence[Mapping[str, Any]],
) -> list[UnitVariant]:
    seed = int(plan["seed"])
    unit_id = str(unit["branch_unit_id"])
    density_class = str(plan["instance_priors"]["density_class"])
    child_count = _actual_child_count(
        unit,
        seed=seed,
        density_class=density_class,
    )
    mounts = _mount_fractions(child_count, seed=seed, unit_id=unit_id)
    primary_length = _polyline_length(_curve_points(primary, 64))
    primary_turn = int(primary["compiler_trace"]["bow_sign"])
    release_side = -primary_turn
    patterns = _pattern_signs(child_count, release_side)
    variants: list[UnitVariant] = []
    for pattern_index, signs in enumerate(patterns):
        curves: list[dict[str, Any]] = [dict(primary)]
        child_specs: list[dict[str, Any]] = []
        local_score = 0.0
        trace_rows: list[dict[str, Any]] = []
        for child_index, (mount, sign) in enumerate(zip(mounts, signs), start=1):
            length_class, target_length = _child_length(
                unit,
                contract,
                primary_length=primary_length,
                index=child_index - 1,
                seed=seed,
            )
            angle_low, angle_high = (
                float(value)
                for value in contract["unit_topology_materialization"][
                    "l2_parent_local_angle_degrees"
                ]
            )
            angle = angle_low + (angle_high - angle_low) * _u01(
                seed,
                unit_id,
                "child_angle",
                child_index,
            )
            bow_low, bow_high = (
                float(value)
                for value in contract["dependent_curve_compilation"]["child_bow_range"]
            )
            bow = bow_low + (bow_high - bow_low) * _u01(
                seed,
                unit_id,
                "child_bow",
                child_index,
            )
            shape_mode = (
                "c_sweep"
                if _u01(seed, unit_id, "child_mode", child_index) < 0.72
                else "soft_s"
            )
            child = _compile_open_child(
                curve_id=f"{unit_id}.L2.{child_index}",
                unit_id=unit_id,
                level=2,
                parent_curve=primary,
                mount_fraction=mount,
                target_length=target_length,
                turn_sign=sign,
                angle_degrees=angle,
                bow=bow,
                shape_mode=shape_mode,
                width=float(
                    contract["dependent_curve_compilation"]["hierarchy_widths"]["L2"]
                ),
            )
            context_score, context_trace = _curve_context_penalty(
                child,
                analysis=analysis,
                all_primaries=all_primaries,
                parent_curve=primary,
            )
            local_score += context_score
            trace_rows.append(
                {
                    "curve_id": child["curve_id"],
                    "context_score": _round(context_score),
                    "context": {key: _round(value) for key, value in context_trace.items()},
                }
            )
            curves.append(child)
            child_specs.append(
                {
                    "curve_id": child["curve_id"],
                    "level": "L2",
                    "parent_curve_id": primary["curve_id"],
                    "mount_fraction": _round(mount),
                    "length_class": length_class,
                    "target_length": _round(target_length),
                    "turn_sign": int(sign),
                    "angle_degrees": _round(angle),
                    "bow": _round(bow),
                    "shape_mode": shape_mode,
                }
            )
        for first, second in itertools.combinations(curves, 2):
            registered = (
                first.get("parent_curve_id") == second.get("curve_id")
                or second.get("parent_curve_id") == first.get("curve_id")
            )
            local_score += _curve_pair_penalty(
                first,
                second,
                registered_parent_contact=registered,
            )
        l3_specs: list[dict[str, Any]] = []
        if _l3_enabled(
            unit,
            density_class=density_class,
            child_count=child_count,
            seed=seed,
        ):
            parent_index = min(
                child_count - 1,
                int(_u01(seed, unit_id, "l3_parent") * child_count),
            )
            parent_child = curves[1 + parent_index]
            ratio_low, ratio_high = (
                float(value)
                for value in contract["unit_topology_materialization"][
                    "l3_to_parent_length_ratio"
                ]
            )
            parent_length = _polyline_length(_curve_points(parent_child, 64))
            target_length = parent_length * (
                ratio_low
                + (ratio_high - ratio_low) * _u01(seed, unit_id, "l3_length")
            )
            mount = 0.55 + 0.12 * _u01(seed, unit_id, "l3_mount")
            angle_low, angle_high = (
                float(value)
                for value in contract["unit_topology_materialization"][
                    "l3_parent_local_angle_degrees"
                ]
            )
            angle = angle_low + (angle_high - angle_low) * _u01(
                seed, unit_id, "l3_angle"
            )
            bow_low, bow_high = (
                float(value)
                for value in contract["dependent_curve_compilation"]["child_bow_range"]
            )
            bow = bow_low + (bow_high - bow_low) * _u01(seed, unit_id, "l3_bow")
            preferred_sign = -int(parent_child["compiler_trace"]["turn_sign"])
            tertiary_options: list[
                tuple[
                    float,
                    int,
                    dict[str, Any],
                    float,
                    dict[str, float],
                ]
            ] = []
            for sign in (preferred_sign, -preferred_sign):
                tertiary = _compile_open_child(
                    curve_id=f"{unit_id}.L3.1",
                    unit_id=unit_id,
                    level=3,
                    parent_curve=parent_child,
                    mount_fraction=mount,
                    target_length=target_length,
                    turn_sign=sign,
                    angle_degrees=angle,
                    bow=bow,
                    shape_mode="c_sweep",
                    width=float(
                        contract["dependent_curve_compilation"][
                            "hierarchy_widths"
                        ]["L3"]
                    ),
                )
                context_score, context_trace = _curve_context_penalty(
                    tertiary,
                    analysis=analysis,
                    all_primaries=all_primaries,
                    parent_curve=parent_child,
                )
                option_score = context_score
                for existing in curves:
                    registered = (
                        existing["curve_id"] == parent_child["curve_id"]
                    )
                    option_score += _curve_pair_penalty(
                        existing,
                        tertiary,
                        registered_parent_contact=registered,
                    )
                if sign != preferred_sign:
                    option_score += 0.04
                tertiary_options.append(
                    (
                        option_score,
                        sign,
                        tertiary,
                        context_score,
                        context_trace,
                    )
                )
            (
                selected_l3_score,
                sign,
                tertiary,
                context_score,
                context_trace,
            ) = min(tertiary_options, key=lambda row: (row[0], row[1]))
            local_score += selected_l3_score
            curves.append(tertiary)
            trace_rows.append(
                {
                    "curve_id": tertiary["curve_id"],
                    "context_score": _round(context_score),
                    "context": {key: _round(value) for key, value in context_trace.items()},
                    "orientation_candidate_scores": [
                        {
                            "turn_sign": option_sign,
                            "score": _round(option_score),
                        }
                        for (
                            option_score,
                            option_sign,
                            _,
                            _,
                            _,
                        ) in tertiary_options
                    ],
                    "orientation_selected_before_final_diagnostics": True,
                }
            )
            l3_specs.append(
                {
                    "curve_id": tertiary["curve_id"],
                    "level": "L3",
                    "parent_curve_id": parent_child["curve_id"],
                    "mount_fraction": _round(mount),
                    "target_length": _round(target_length),
                    "turn_sign": int(sign),
                    "angle_degrees": _round(angle),
                    "bow": _round(bow),
                    "shape_mode": "c_sweep",
                    "orientation_candidate_count": len(tertiary_options),
                    "orientation_selected_before_final_diagnostics": True,
                }
            )
        rhythm = str(unit["child_rhythm_envelope"]["rhythm_policy"])
        sign_balance = abs(sum(signs))
        adjacent_same = sum(
            first == second for first, second in zip(signs, signs[1:])
        )
        if "near_balanced" in rhythm:
            local_score += sign_balance * 0.65
        if "broad_axis_flank" in rhythm:
            local_score += adjacent_same * 0.35
        if "sparse_asymmetric" in rhythm and child_count > 1:
            local_score += max(0, child_count - abs(sum(signs))) * 0.18
        if "upper_side" in rhythm:
            upward_tips = sum(
                _point(curve["cubic_segments"][-1]["p3"])[1]
                < _point(curve["cubic_segments"][0]["p0"])[1]
                for curve in curves[1:]
            )
            local_score += (len(curves) - 1 - upward_tips) * 0.45
        preferred_pattern = int(
            _u01(seed, unit_id, "preferred_side_pattern") * len(patterns)
        )
        if pattern_index != preferred_pattern:
            local_score += 0.05
        topology = {
            "branch_unit_id": unit_id,
            "primary_curve_id": primary["curve_id"],
            "actual_l2_count": child_count,
            "actual_l3_count": len(l3_specs),
            "l2_specs": child_specs,
            "l3_specs": l3_specs,
            "child_rhythm_policy": rhythm,
            "selected_side_pattern": list(signs),
            "source_child_count_envelope": {
                "minimum": int(unit["child_rhythm_envelope"]["minimum_child_count"]),
                "maximum": int(unit["child_rhythm_envelope"]["maximum_child_count"]),
            },
            "topology_selected_before_final_candidate_diagnostics": True,
        }
        variants.append(
            UnitVariant(
                unit_id=unit_id,
                pattern_id=f"{unit_id}.pattern_{pattern_index + 1}",
                curves=tuple(curves),
                topology=topology,
                local_score=local_score,
                local_score_trace={
                    "dependent_context_rows": trace_rows,
                    "seed_preference_penalty_included": True,
                    "family_rhythm_penalty_included": "upper_side" in rhythm,
                },
            )
        )
    return variants


def _global_unit_set(
    variant_rows: Sequence[Sequence[UnitVariant]],
) -> tuple[list[UnitVariant], dict[str, Any]]:
    pair_scores: dict[tuple[int, int, int, int], float] = {}
    for first_unit_index in range(len(variant_rows)):
        for second_unit_index in range(first_unit_index + 1, len(variant_rows)):
            for first_variant_index, first in enumerate(variant_rows[first_unit_index]):
                for second_variant_index, second in enumerate(
                    variant_rows[second_unit_index]
                ):
                    score = sum(
                        _curve_pair_penalty(first_curve, second_curve)
                        for first_curve in first.curves
                        for second_curve in second.curves
                    )
                    pair_scores[
                        (
                            first_unit_index,
                            first_variant_index,
                            second_unit_index,
                            second_variant_index,
                        )
                    ] = score
    best_score = float("inf")
    best_indices: tuple[int, ...] | None = None
    evaluated = 0
    for indices in itertools.product(
        *(range(len(variants)) for variants in variant_rows)
    ):
        score = sum(
            variant_rows[unit_index][variant_index].local_score
            for unit_index, variant_index in enumerate(indices)
        )
        for first_unit_index in range(len(indices)):
            for second_unit_index in range(first_unit_index + 1, len(indices)):
                score += pair_scores[
                    (
                        first_unit_index,
                        indices[first_unit_index],
                        second_unit_index,
                        indices[second_unit_index],
                    )
                ]
        evaluated += 1
        if score < best_score - EPSILON:
            best_score = score
            best_indices = tuple(indices)
    if best_indices is None:
        raise UnitCurveCompilationFailure(
            "unit_set_selection_failed",
            "no complete BranchUnit set could be selected",
            {},
        )
    selected = [
        variant_rows[index][variant_index]
        for index, variant_index in enumerate(best_indices)
    ]
    return selected, {
        "schema": "dynamic_branch_complete_unit_set_selection_trace_v2",
        "candidate_set_count": evaluated,
        "selected_variant_indices": list(best_indices),
        "selected_pattern_ids": [variant.pattern_id for variant in selected],
        "selected_score": _round(best_score),
        "selection_is_forward_global_planning_not_retry": True,
    }


def _validate_inputs(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise UnitCurveCompilationFailure(
            "invalid_contract",
            "stage-4 v2 contract schema mismatch",
            {"actual": contract.get("schema")},
        )
    if plan.get("schema") != "dynamic_branch_plan_v3":
        raise UnitCurveCompilationFailure(
            "invalid_plan",
            "stage-3 plan schema mismatch",
            {"actual": plan.get("schema")},
        )
    if analysis.get("schema") != "dynamic_branch_prototype_analysis_v1":
        raise UnitCurveCompilationFailure(
            "invalid_analysis",
            "prototype analysis schema mismatch",
            {"actual": analysis.get("schema")},
        )
    if plan.get("prototype_id") != analysis.get("prototype_id"):
        raise UnitCurveCompilationFailure(
            "identity_mismatch",
            "plan and analysis prototype ids differ",
            {
                "plan": plan.get("prototype_id"),
                "analysis": analysis.get("prototype_id"),
            },
        )
    units = plan.get("branch_units")
    if not isinstance(units, list) or not units:
        raise UnitCurveCompilationFailure(
            "invalid_plan",
            "stage-3 plan contains no BranchUnits",
            {},
        )


def compile_dynamic_branch_units(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile one immutable raw complete-BranchUnit candidate."""

    _validate_inputs(analysis, plan, contract)
    selected_primaries, primary_trace = _primary_set(analysis, plan, contract)
    primary_by_unit = {
        curve["branch_unit_id"]: curve for curve in selected_primaries
    }
    variant_rows = [
        _unit_variants(
            analysis,
            plan,
            contract,
            unit,
            primary_by_unit[str(unit["branch_unit_id"])],
            selected_primaries,
        )
        for unit in plan["branch_units"]
    ]
    selected_units, unit_trace = _global_unit_set(variant_rows)
    branch_units: list[dict[str, Any]] = []
    branch_curves: list[dict[str, Any]] = []
    for unit_variant in selected_units:
        topology = dict(unit_variant.topology)
        topology["curve_ids"] = [curve["curve_id"] for curve in unit_variant.curves]
        topology["selected_pattern_id"] = unit_variant.pattern_id
        topology["selected_local_score"] = _round(unit_variant.local_score)
        topology["selection_trace"] = dict(unit_variant.local_score_trace)
        branch_units.append(topology)
        branch_curves.extend(dict(curve) for curve in unit_variant.curves)
    topology_payload = {
        "branch_units": branch_units,
        "compile_order": ["L1", "L2", "L3"],
        "topology_frozen_before_final_candidate_diagnostics": True,
    }
    candidate: dict[str, Any] = {
        "schema": SCHEMA,
        "stage4_version": "v2",
        "curve_contract_id": contract["contract_id"],
        "candidate_id": f'{plan["plan_id"]}__stage4_unit_curve_v2_raw_1',
        "task_id": plan["task_id"],
        "prototype_id": plan["prototype_id"],
        "seed": int(plan["seed"]),
        "raw_curve_candidate_index": 1,
        "classification": dict(plan["classification"]),
        "instance_priors": dict(plan["instance_priors"]),
        "coordinate_system": dict(plan["coordinate_system"]),
        "branch_units": branch_units,
        "branch_curves": branch_curves,
        "unit_topology_digest": _canonical_digest(topology_payload),
        "selection_trace": {
            "primary_set": primary_trace,
            "complete_unit_set": unit_trace,
            "unit_candidate_counts": [
                len(variants) for variants in variant_rows
            ],
            "single_forward_generation": True,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
        },
        "stage_boundary": dict(contract["stage_boundary"]),
        "review": {
            "status": contract["review"]["initial_state"],
            "allowed_states": list(contract["review"]["allowed_states"]),
            "criteria": list(contract["review"]["criteria"]),
            "numeric_checks_cannot_auto_approve": True,
        },
        "input_refs": {
            "stage3_plan_digest": plan["plan_digest"],
            "prototype_analysis_digest": analysis["analysis_digest"],
        },
    }
    digest_payload = dict(candidate)
    candidate["candidate_digest"] = _canonical_digest(digest_payload)
    return candidate


def _curve_map(candidate: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(curve["curve_id"]): curve for curve in candidate["branch_curves"]
    }


def _shape_issue(
    curve: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[bool, str | None]:
    metrics = curve["shape_metrics"]
    level = str(curve["level"])
    thresholds = contract["diagnostics"]["shape_thresholds"]
    minimum_deviation = float(
        thresholds[f"{level}_minimum_deviation_ratio"]
    )
    minimum_arc = float(thresholds[f"{level}_minimum_arc_ratio"])
    maximum_deviation = float(thresholds["maximum_deviation_ratio"])
    if float(metrics["maximum_deviation_ratio"]) < minimum_deviation:
        return True, "near-straight maximum chord deviation"
    if float(metrics["arc_ratio"]) < minimum_arc:
        return True, "near-straight arc/chord ratio"
    if float(metrics["maximum_deviation_ratio"]) > maximum_deviation:
        return True, "over-bent maximum chord deviation"
    return False, None


def diagnose_dynamic_branch_units(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Read-only structural diagnostics for a stage-4 v2 candidate."""

    _validate_inputs(analysis, plan, contract)
    if candidate.get("schema") != SCHEMA:
        raise UnitCurveCompilationFailure(
            "invalid_candidate",
            "stage-4 v2 candidate schema mismatch",
            {"actual": candidate.get("schema")},
        )
    issues: list[dict[str, Any]] = []
    curves = list(candidate["branch_curves"])
    curve_by_id = _curve_map(candidate)
    plan_units = {
        str(unit["branch_unit_id"]): unit for unit in plan["branch_units"]
    }
    backbone = [_point(row["point"]) for row in analysis["backbone"]["samples"]]
    near_straight_ids: list[str] = []
    parent_root_error_max = 0.0
    parent_tangent_error_max = 0.0
    non_root_backbone_crossing_ids: list[str] = []
    wrong_flower_entries: list[dict[str, str]] = []
    for curve in curves:
        curve_id = str(curve["curve_id"])
        level = int(curve["hierarchy_level"])
        shape_bad, shape_reason = _shape_issue(curve, contract)
        if shape_bad:
            near_straight_ids.append(curve_id)
            issues.append(
                {
                    "label": "curve_issue",
                    "curve_id": curve_id,
                    "detail": shape_reason,
                    "metrics": dict(curve["shape_metrics"]),
                }
            )
        points = _curve_points(curve, 64)
        if level == 1:
            unit = plan_units[str(curve["branch_unit_id"])]
            expected_root = _point(unit["parent_ref"]["mount_point"])
            expected_tip = _point(
                unit["directional_layout_intent"]["path_points"][-1]
            )
            root_error = _distance(points[0], expected_root)
            tip_error = _distance(points[-1], expected_tip)
            if root_error > 1e-7:
                issues.append(
                    {
                        "label": "attachment_issue",
                        "curve_id": curve_id,
                        "detail": "L1 root differs from the approved stage-3 mount",
                        "error": _round(root_error),
                    }
                )
            if tip_error > 1e-7:
                issues.append(
                    {
                        "label": "curve_issue",
                        "curve_id": curve_id,
                        "detail": "L1 tip differs from the approved stage-3 reach hint",
                        "error": _round(tip_error),
                    }
                )
            checked_backbone = points[6:]
        else:
            parent = curve_by_id.get(str(curve["parent_curve_id"]))
            if parent is None:
                issues.append(
                    {
                        "label": "hierarchy_issue",
                        "curve_id": curve_id,
                        "detail": "dependent curve parent is missing",
                    }
                )
                continue
            parent_points = _curve_points(parent, 96)
            expected_root, expected_tangent = _sample_polyline(
                parent_points,
                float(curve["mount_fraction"]),
            )
            root_error = _distance(points[0], expected_root)
            parent_root_error_max = max(parent_root_error_max, root_error)
            actual_entry = _unit(
                _sub(
                    _point(curve["cubic_segments"][0]["p1"]),
                    _point(curve["cubic_segments"][0]["p0"]),
                )
            )
            cosine = max(-1.0, min(1.0, _dot(actual_entry, expected_tangent)))
            tangent_error = math.degrees(math.acos(cosine))
            parent_tangent_error_max = max(parent_tangent_error_max, tangent_error)
            if root_error > 2e-5:
                issues.append(
                    {
                        "label": "attachment_issue",
                        "curve_id": curve_id,
                        "detail": "child root is off its actual parent curve",
                        "error": _round(root_error),
                    }
                )
            if tangent_error > 2.0:
                issues.append(
                    {
                        "label": "attachment_issue",
                        "curve_id": curve_id,
                        "detail": "child entry derivative does not match parent local tangent",
                        "angle_degrees": _round(tangent_error),
                    }
                )
            checked_backbone = points
        if _polyline_crosses(checked_backbone, backbone):
            non_root_backbone_crossing_ids.append(curve_id)
            issues.append(
                {
                    "label": "collision_issue",
                    "curve_id": curve_id,
                    "detail": "curve crosses the backbone outside its registered root",
                }
            )
        target_flowers = _target_flower_ids(curve)
        for flower in analysis["flowers"]:
            flower_id = str(flower["flower_id"])
            checked = points
            if level == 1 and flower_id in target_flowers:
                checked = points[:-6]
                intrusion = any(
                    _inside_flower(point, flower, protection=False)
                    for point in checked
                )
            else:
                intrusion = any(_inside_flower(point, flower) for point in checked)
            if intrusion:
                wrong_flower_entries.append(
                    {"curve_id": curve_id, "flower_id": flower_id}
                )
                issues.append(
                    {
                        "label": "flower_relation_issue",
                        "curve_id": curve_id,
                        "flower_id": flower_id,
                        "detail": "curve enters a flower protection reserve outside the registered terminal contact",
                    }
                )
    crossing_pairs: list[list[str]] = []
    minimum_curve_clearance = float("inf")
    for first, second in itertools.combinations(curves, 2):
        registered = (
            first.get("parent_curve_id") == second.get("curve_id")
            or second.get("parent_curve_id") == first.get("curve_id")
        )
        first_points = _curve_points(first, 48)
        second_points = _curve_points(second, 48)
        if registered:
            if second.get("parent_curve_id") == first.get("curve_id"):
                second_points = second_points[6:]
            else:
                first_points = first_points[6:]
        distance = _polyline_distance(first_points, second_points)
        minimum_curve_clearance = min(minimum_curve_clearance, distance)
        if _polyline_crosses(first_points, second_points):
            pair = [str(first["curve_id"]), str(second["curve_id"])]
            crossing_pairs.append(pair)
            issues.append(
                {
                    "label": "collision_issue",
                    "curve_ids": pair,
                    "detail": "unregistered branch curves cross",
                }
            )
    for offset in (-1.0, 1.0):
        shifted_curves = []
        for curve in curves:
            shifted = dict(curve)
            shifted["cubic_segments"] = []
            for cubic in curve["cubic_segments"]:
                shifted["cubic_segments"].append(
                    {
                        key: [
                            float(cubic[key][0]) + offset,
                            float(cubic[key][1]),
                        ]
                        for key in ("p0", "p1", "p2", "p3")
                    }
                )
            shifted_curves.append(shifted)
        for first in curves:
            for second in shifted_curves:
                if _polyline_crosses(
                    _curve_points(first, 36),
                    _curve_points(second, 36),
                ):
                    pair = [
                        str(first["curve_id"]),
                        f'{second["curve_id"]}@{offset:+.0f}',
                    ]
                    if pair not in crossing_pairs:
                        crossing_pairs.append(pair)
                        issues.append(
                            {
                                "label": "repeat_issue",
                                "curve_ids": pair,
                                "detail": "curve crosses a periodic-neighbor copy",
                            }
                        )
    level_counts = {
        level: sum(str(curve["level"]) == level for curve in curves)
        for level in ("L1", "L2", "L3")
    }
    issue_labels = sorted({str(issue["label"]) for issue in issues})
    return {
        "schema": "dynamic_branch_unit_curve_diagnostics_v2",
        "candidate_id": candidate["candidate_id"],
        "candidate_digest": candidate["candidate_digest"],
        "prototype_id": candidate["prototype_id"],
        "seed": candidate["seed"],
        "branch_unit_count": len(candidate["branch_units"]),
        "curve_count": len(curves),
        "cubic_segment_count": sum(
            len(curve["cubic_segments"]) for curve in curves
        ),
        "level_counts": level_counts,
        "near_straight_curve_count": len(near_straight_ids),
        "near_straight_curve_ids": near_straight_ids,
        "curve_curve_crossing_count": len(crossing_pairs),
        "curve_curve_crossing_pairs": crossing_pairs,
        "non_root_backbone_crossing_count": len(
            non_root_backbone_crossing_ids
        ),
        "non_root_backbone_crossing_ids": non_root_backbone_crossing_ids,
        "wrong_flower_entry_count": len(wrong_flower_entries),
        "wrong_flower_entries": wrong_flower_entries,
        "maximum_child_root_error": _round(parent_root_error_max),
        "maximum_child_entry_tangent_error_degrees": _round(
            parent_tangent_error_max
        ),
        "minimum_curve_clearance": (
            None
            if not math.isfinite(minimum_curve_clearance)
            else _round(minimum_curve_clearance)
        ),
        "issue_count": len(issues),
        "issue_labels": issue_labels,
        "issues": issues,
        "read_only_diagnostics": True,
        "candidate_modified": False,
        "numeric_checks_cannot_auto_approve_visual_gate": True,
    }
