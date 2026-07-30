#!/usr/bin/env python3
"""Stage-3B global L1 flow-lane planner.

This module performs one seeded, forward global solve.  It does not consume the
selected layouts from the rejected stage-3/stage-4 chain, and it does not
repair, delete, retry, or resample a failed result.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from fixed_visual_prior import canonical_digest, validate_fixed_visual_prior
from prototype_analysis import derive_loop_growth_region
from role_region_plan import (
    build_sw1_role_region_plan,
    build_sw3_group_region_plan,
    build_sw3_remote_support_region_plan,
    validate_role_region_plan,
    validate_sw3_group_region_plan,
    validate_sw3_remote_support_region_plan,
)
from topology_contract_loader import materialize_prototype_topology


SCHEMA = "dynamic_branch_global_l1_flow_plan_v1"
CONTRACT_SCHEMA = "dynamic_branch_stage3b_l1_flow_contract_v1"
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
SEEDS = (4101, 4102, 4103)
Point = tuple[float, float]


class GlobalL1FlowError(RuntimeError):
    """The formal L1 global solve is infeasible or violates its contract."""


@dataclass(frozen=True)
class Slot:
    slot_id: str
    role: str
    index: int
    flower_id: str | None
    preferred_s: float
    preferred_vertical_side: str


@dataclass
class BeamState:
    lanes: list[dict[str, Any]]
    score: float


def _finite(value: object, path: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise GlobalL1FlowError(f"{path} must be finite")
    return number


def _point(value: object, path: str) -> Point:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise GlobalL1FlowError(f"{path} must be a two-number point")
    return _finite(value[0], f"{path}[0]"), _finite(value[1], f"{path}[1]")


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scalar: float) -> Point:
    return a[0] * scalar, a[1] * scalar


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _length(a: Point) -> float:
    return math.hypot(a[0], a[1])


def _distance(a: Point, b: Point) -> float:
    return _length(_sub(a, b))


def _unit(vector: Point, path: str = "vector") -> Point:
    length = _length(vector)
    if length <= 1e-12:
        raise GlobalL1FlowError(f"{path} must be non-degenerate")
    return vector[0] / length, vector[1] / length


def _lerp(a: Point, b: Point, fraction: float) -> Point:
    return a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction


def _round_point(point: Point) -> list[float]:
    return [round(point[0], 9), round(point[1], 9)]


def _periodic_delta(a: float, b: float) -> float:
    delta = abs(a - b) % 1.0
    return min(delta, 1.0 - delta)


def _periodic_near_x(x: float, reference_x: float) -> float:
    return min((x - 1.0, x, x + 1.0), key=lambda candidate: abs(candidate - reference_x))


def _cubic_point(segment: Mapping[str, Sequence[float]], t: float) -> Point:
    p0 = _point(segment["p0"], "segment.p0")
    p1 = _point(segment["p1"], "segment.p1")
    p2 = _point(segment["p2"], "segment.p2")
    p3 = _point(segment["p3"], "segment.p3")
    u = 1.0 - t
    return (
        u**3 * p0[0] + 3.0 * u * u * t * p1[0] + 3.0 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3.0 * u * u * t * p1[1] + 3.0 * u * t * t * p2[1] + t**3 * p3[1],
    )


def _sample_segments(
    segments: Sequence[Mapping[str, Sequence[float]]],
    samples_per_segment: int = 18,
) -> list[Point]:
    points: list[Point] = []
    for segment_index, segment in enumerate(segments):
        start = 0 if segment_index == 0 else 1
        points.extend(
            _cubic_point(segment, index / samples_per_segment)
            for index in range(start, samples_per_segment + 1)
        )
    return points


def _segment(
    p0: Point,
    p1: Point,
    p2: Point,
    p3: Point,
) -> dict[str, list[float]]:
    return {
        "p0": _round_point(p0),
        "p1": _round_point(p1),
        "p2": _round_point(p2),
        "p3": _round_point(p3),
    }


def _hermite_segment(
    start: Point,
    end: Point,
    start_direction: Point,
    end_direction: Point,
    start_arm: float,
    end_arm: float,
) -> dict[str, list[float]]:
    d0 = _unit(start_direction, "start_direction")
    d1 = _unit(end_direction, "end_direction")
    return _segment(
        start,
        _add(start, _mul(d0, start_arm)),
        _sub(end, _mul(d1, end_arm)),
        end,
    )


def _motion_policy(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    policy = contract.get("motion_policy")
    if policy is None:
        return {"mode": "legacy_outward_v1"}
    if not isinstance(policy, Mapping):
        raise GlobalL1FlowError("motion_policy must be an object")
    mode = str(policy.get("mode"))
    if mode not in {"legacy_outward_v1", "tangent_led_v1"}:
        raise GlobalL1FlowError(f"unsupported L1 motion mode: {mode}")
    return policy


def _tangent_led_segments(
    *,
    root: Point,
    target: Point,
    flow_direction: Point,
    outward: Point,
    terminal_direction: Point,
    policy: Mapping[str, Any],
) -> list[dict[str, list[float]]]:
    """Build a G1 tangent-led departure followed by one deliberate turn."""

    flow = _unit(flow_direction, "tangent_led_flow_direction")
    outward_unit = _unit(outward, "tangent_led_outward")
    chord = _distance(root, target)
    departure_fraction = float(policy["departure_chord_fraction"])
    departure_length = max(
        float(policy["minimum_departure_length"]),
        chord * departure_fraction,
    )
    clearance = min(
        float(policy["maximum_departure_clearance"]),
        max(
            float(policy["minimum_departure_clearance"]),
            chord * float(policy["departure_clearance_chord_fraction"]),
        ),
    )
    departure = _add(
        root,
        _add(_mul(flow, departure_length), _mul(outward_unit, clearance)),
    )
    join_direction = _unit(
        _add(
            _mul(flow, float(policy["join_flow_weight"])),
            _mul(outward_unit, float(policy["join_outward_weight"])),
        ),
        "tangent_led_join_direction",
    )
    first_chord = _distance(root, departure)
    second_chord = _distance(departure, target)
    return [
        _hermite_segment(
            root,
            departure,
            flow,
            join_direction,
            first_chord * float(policy["first_start_arm_fraction"]),
            first_chord * float(policy["first_end_arm_fraction"]),
        ),
        _hermite_segment(
            departure,
            target,
            join_direction,
            terminal_direction,
            second_chord * float(policy["second_start_arm_fraction"]),
            second_chord * float(policy["second_end_arm_fraction"]),
        ),
    ]


def _polyline_length(points: Sequence[Point]) -> float:
    return sum(_distance(points[index - 1], points[index]) for index in range(1, len(points)))


def _polyline_cumulative_lengths(points: Sequence[Point]) -> list[float]:
    lengths = [0.0]
    for start, end in zip(points, points[1:]):
        lengths.append(lengths[-1] + _distance(start, end))
    return lengths


def _point_at_arc_fraction(points: Sequence[Point], fraction: float) -> Point:
    lengths = _polyline_cumulative_lengths(points)
    target = lengths[-1] * fraction
    for index in range(1, len(points)):
        if lengths[index] + 1e-12 >= target:
            span = lengths[index] - lengths[index - 1]
            local = 0.0 if span <= 1e-12 else (target - lengths[index - 1]) / span
            return _lerp(points[index - 1], points[index], local)
    return points[-1]


def _point_and_tangent_at_arc_fraction(
    points: Sequence[Point],
    fraction: float,
) -> tuple[Point, Point]:
    lengths = _polyline_cumulative_lengths(points)
    target = lengths[-1] * fraction
    for index in range(1, len(points)):
        if lengths[index] + 1e-12 >= target:
            span = lengths[index] - lengths[index - 1]
            local = (
                0.0
                if span <= 1e-12
                else (target - lengths[index - 1]) / span
            )
            return (
                _lerp(points[index - 1], points[index], local),
                _unit(
                    _sub(points[index], points[index - 1]),
                    "polyline arc tangent",
                ),
            )
    return (
        points[-1],
        _unit(_sub(points[-1], points[-2]), "polyline end tangent"),
    )


def _polyline_tangents(points: Sequence[Point]) -> list[Point]:
    if len(points) < 2:
        raise GlobalL1FlowError("guide centerline needs two points")
    tangents: list[Point] = []
    for index in range(len(points)):
        if index == 0:
            direction = _sub(points[1], points[0])
        elif index == len(points) - 1:
            direction = _sub(points[-1], points[-2])
        else:
            direction = _sub(points[index + 1], points[index - 1])
        tangents.append(_unit(direction, "guide tangent"))
    return tangents


def _angle_degrees(first: Point, second: Point, *, unsigned_axis: bool = False) -> float:
    cosine = _dot(_unit(first, "angle.first"), _unit(second, "angle.second"))
    cosine = max(-1.0, min(1.0, abs(cosine) if unsigned_axis else cosine))
    return math.degrees(math.acos(cosine))


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    vector = _sub(end, start)
    denominator = _dot(vector, vector)
    if denominator <= 1e-18:
        return _distance(point, start)
    t = max(0.0, min(1.0, _dot(_sub(point, start), vector) / denominator))
    return _distance(point, _add(start, _mul(vector, t)))


def _orientation(a: Point, b: Point, c: Point) -> float:
    return _cross(_sub(b, a), _sub(c, a))


def _segments_intersect(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    tolerance = 1e-10
    o1 = _orientation(a0, a1, b0)
    o2 = _orientation(a0, a1, b1)
    o3 = _orientation(b0, b1, a0)
    o4 = _orientation(b0, b1, a1)
    if o1 * o2 < -tolerance and o3 * o4 < -tolerance:
        return True
    return False


def _segment_distance(a0: Point, a1: Point, b0: Point, b1: Point) -> float:
    if _segments_intersect(a0, a1, b0, b1):
        return 0.0
    return min(
        _point_segment_distance(a0, b0, b1),
        _point_segment_distance(a1, b0, b1),
        _point_segment_distance(b0, a0, a1),
        _point_segment_distance(b1, a0, a1),
    )


def _prepare_polyline_collision_geometry(
    points: Sequence[Point],
) -> dict[str, Any]:
    normalized = tuple(points)
    return {
        "points": normalized,
        "bounds": (
            min(point[0] for point in normalized),
            max(point[0] for point in normalized),
            min(point[1] for point in normalized),
            max(point[1] for point in normalized),
        ),
        "segments": tuple(
            (
                normalized[index - 1],
                normalized[index],
                min(normalized[index - 1][0], normalized[index][0]),
                max(normalized[index - 1][0], normalized[index][0]),
                min(normalized[index - 1][1], normalized[index][1]),
                max(normalized[index - 1][1], normalized[index][1]),
            )
            for index in range(1, len(normalized))
        ),
    }


def _prepared_polyline_distance(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    offset_b: float = 0.0,
    *,
    stop_below: float | None = None,
) -> float:
    a_min_x, a_max_x, a_min_y, a_max_y = a["bounds"]
    b_min_x, b_max_x, b_min_y, b_max_y = b["bounds"]
    b_min_x += offset_b
    b_max_x += offset_b
    gap_x = max(0.0, a_min_x - b_max_x, b_min_x - a_max_x)
    gap_y = max(0.0, a_min_y - b_max_y, b_min_y - a_max_y)
    box_gap = math.hypot(gap_x, gap_y)
    if box_gap > 0.18:
        return box_gap
    minimum = float("inf")
    for a0, a1, a0x, a1x, a0y, a1y in a["segments"]:
        for (
            b0_unshifted,
            b1_unshifted,
            b0x_unshifted,
            b1x_unshifted,
            b0y,
            b1y,
        ) in b["segments"]:
            b0 = b0_unshifted[0] + offset_b, b0_unshifted[1]
            b1 = b1_unshifted[0] + offset_b, b1_unshifted[1]
            b0x = b0x_unshifted + offset_b
            b1x = b1x_unshifted + offset_b
            segment_gap_x = max(0.0, a0x - b1x, b0x - a1x)
            segment_gap_y = max(0.0, a0y - b1y, b0y - a1y)
            if segment_gap_x * segment_gap_x + segment_gap_y * segment_gap_y >= minimum * minimum:
                continue
            minimum = min(minimum, _segment_distance(a0, a1, b0, b1))
            if minimum <= 0.0:
                return 0.0
            if stop_below is not None and minimum < stop_below:
                return minimum
    return minimum


def _polyline_distance(
    a: Sequence[Point],
    b: Sequence[Point],
    offset_b: float = 0.0,
    *,
    stop_below: float | None = None,
) -> float:
    return _prepared_polyline_distance(
        _prepare_polyline_collision_geometry(a),
        _prepare_polyline_collision_geometry(b),
        offset_b,
        stop_below=stop_below,
    )


def _sample_at_s(analysis: Mapping[str, Any], s: float) -> tuple[Point, Point]:
    samples = analysis["backbone"]["samples"]
    position = (s % 1.0) * (len(samples) - 1)
    lower = int(math.floor(position))
    upper = min(len(samples) - 1, lower + 1)
    fraction = position - lower
    point = _lerp(
        _point(samples[lower]["point"], "backbone.point"),
        _point(samples[upper]["point"], "backbone.point"),
        fraction,
    )
    tangent = _unit(
        _lerp(
            _point(samples[lower]["tangent"], "backbone.tangent"),
            _point(samples[upper]["tangent"], "backbone.tangent"),
            fraction,
        ),
        "backbone.tangent",
    )
    return point, tangent


def _normal(tangent: Point, side_id: str) -> Point:
    left = -tangent[1], tangent[0]
    if side_id == "left_normal":
        return left
    if side_id == "right_normal":
        return -left[0], -left[1]
    raise GlobalL1FlowError(f"unknown side id: {side_id}")


def _closest_side(tangent: Point, direction: Point) -> tuple[str, Point]:
    left = _normal(tangent, "left_normal")
    right = _normal(tangent, "right_normal")
    return (
        ("left_normal", left)
        if _dot(left, direction) >= _dot(right, direction)
        else ("right_normal", right)
    )


def _ellipse_value(point: Point, center: Point, rx: float, ry: float) -> float:
    return ((point[0] - center[0]) / rx) ** 2 + ((point[1] - center[1]) / ry) ** 2


def _flower_center_near(flower: Mapping[str, Any], reference_x: float) -> Point:
    center = _point(flower["center"], "flower.center")
    return _periodic_near_x(center[0], reference_x), center[1]


def _flower_boundary_toward(
    flower: Mapping[str, Any],
    source: Point,
    *,
    underside: bool = False,
) -> Point:
    center = _flower_center_near(flower, source[0])
    rx = _finite(flower["rx"], "flower.rx")
    ry = _finite(flower["ry"], "flower.ry")
    if underside:
        return center[0], center[1] + ry
    vector = _sub(source, center)
    denominator = math.sqrt((vector[0] / rx) ** 2 + (vector[1] / ry) ** 2)
    if denominator <= 1e-12:
        raise GlobalL1FlowError("flower/source direction is degenerate")
    return center[0] + vector[0] / denominator, center[1] + vector[1] / denominator


def _flower_by_id(analysis: Mapping[str, Any], flower_id: str) -> Mapping[str, Any]:
    matches = [flower for flower in analysis["flowers"] if flower["flower_id"] == flower_id]
    if len(matches) != 1:
        raise GlobalL1FlowError(f"flower id is not unique: {flower_id}")
    return matches[0]


def _candidate_regions(analysis: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = analysis.get("candidate_l1_attachment_regions")
    if not isinstance(rows, list) or not rows:
        raise GlobalL1FlowError("analysis has no L1 attachment regions")
    return rows


def _region_s_values(
    region: Mapping[str, Any],
    phase: float,
    fractions: Sequence[float] = (0.10, 0.30, 0.50, 0.70, 0.90),
) -> list[float]:
    values: list[float] = []
    for start, end in region["s_ranges"]:
        start_value = float(start)
        end_value = float(end)
        span = end_value - start_value
        for fraction in fractions:
            shifted = min(0.92, max(0.08, fraction + phase))
            values.append((start_value + span * shifted) % 1.0)
    return values


def _global_latents(prototype_id: str, seed: int) -> dict[str, float]:
    digest = hashlib.sha256(f"{prototype_id}:{seed}:global_l1_flow_v1".encode("utf-8")).digest()
    generator = random.Random(int.from_bytes(digest[:8], "big"))
    return {
        "openness": round(generator.triangular(0.88, 1.14, 1.0), 9),
        "sweep_amplitude": round(generator.triangular(0.88, 1.16, 1.02), 9),
        "asymmetry": round(generator.triangular(-0.16, 0.16, 0.0), 9),
        "flow_phase": round(generator.uniform(-0.035, 0.035), 9),
        "curl_energy": round(generator.triangular(0.86, 1.15, 1.0), 9),
    }


def _required_support_count(family_id: str, flower_count: int) -> int:
    if family_id in {"SW-1_valley_filling", "SW-3_tangent_terminal"}:
        return flower_count
    if family_id == "SW-2_axis_penetrating":
        return 0
    raise GlobalL1FlowError(f"unsupported morphology family: {family_id}")


def _derive_lane_count(
    prototype_id: str,
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    prior: Mapping[str, Any],
) -> dict[str, Any]:
    family_id = morphology["classification"]["flower_branch_relation"]["family_id"]
    support_count = _required_support_count(family_id, len(analysis["flowers"]))
    evidence = morphology["instance_priors"]["source_observation_counts"]
    primary_evidence = int(evidence["primary_branch_count"])
    guide_evidence = int(evidence["branch_guide_count"])
    median_unit_load = float(
        prior["statistics"]["primary_root_rhythm"]["unit_load_curves_including_primary"]["median"]
    )
    guide_equivalent = int(round(guide_evidence / median_unit_load))
    space_evidence = support_count + len(analysis["space_analysis"]["continuous_blank_regions"])
    fixed_visual_capacity = int(prior["paired_baseline_scope"]["topology"]["L1"])
    if prototype_id == "proto_sw_1_3":
        selected = fixed_visual_capacity
        governing_evidence = "strict_paired_fixed_visual_capacity"
    else:
        selected = min(
            fixed_visual_capacity,
            max(support_count, primary_evidence, guide_equivalent, space_evidence),
        )
        governing_evidence = "morphology_and_blank_space_capacity"
    if selected <= support_count:
        raise GlobalL1FlowError(f"{prototype_id} has no capacity for ordinary L1 lanes")
    return {
        "selected_l1_count": selected,
        "required_support_count": support_count,
        "ordinary_lane_count": selected - support_count,
        "primary_branch_evidence": primary_evidence,
        "branch_guide_equivalent_l1": guide_equivalent,
        "blank_region_plus_support_evidence": space_evidence,
        "fixed_visual_capacity": fixed_visual_capacity,
        "governing_evidence": governing_evidence,
        "fixed_count_copied": False,
    }


def _vertical_preferences(
    morphology: Mapping[str, Any],
    count: int,
    seed: int,
) -> list[str]:
    rhythm = str(morphology["instance_priors"]["side_rhythm"])
    if rhythm == "upper_side_emphasis":
        base = ["upper", "upper", "lower"]
    elif rhythm == "sparse_asymmetric_alternation":
        base = ["upper", "lower", "upper", "lower", "lower"]
    else:
        base = ["upper", "lower"]
    offset = seed % len(base)
    return [base[(index + offset) % len(base)] for index in range(count)]


def _slot_roles(family_id: str, count: int) -> list[str]:
    if family_id == "SW-1_valley_filling":
        cycle = ("frontier", "primary_sweep", "balance", "primary_sweep")
    elif family_id == "SW-2_axis_penetrating":
        cycle = ("primary_sweep", "frontier", "primary_sweep", "balance")
    elif family_id == "SW-3_tangent_terminal":
        cycle = ("primary_sweep", "balance", "frontier")
    else:
        raise GlobalL1FlowError(f"unsupported morphology family: {family_id}")
    return [cycle[index % len(cycle)] for index in range(count)]


def _make_slots(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    count_derivation: Mapping[str, Any],
    latents: Mapping[str, float],
    seed: int,
) -> list[Slot]:
    family_id = morphology["classification"]["flower_branch_relation"]["family_id"]
    support_role = (
        "flower_support"
        if family_id == "SW-1_valley_filling"
        else "terminal_flower_support"
    )
    slots: list[Slot] = []
    for index, flower in enumerate(analysis["flowers"][: count_derivation["required_support_count"]]):
        slots.append(
            Slot(
                slot_id=f"support_{index + 1}",
                role=support_role,
                index=index,
                flower_id=str(flower["flower_id"]),
                preferred_s=float(flower["nearest_backbone_s"]),
                preferred_vertical_side="lower",
            )
        )

    ordinary_count = int(count_derivation["ordinary_lane_count"])
    vertical = _vertical_preferences(morphology, ordinary_count, seed)
    roles = _slot_roles(family_id, ordinary_count)
    for index in range(ordinary_count):
        preferred_s = (
            (index + 0.5) / ordinary_count + float(latents["flow_phase"])
        ) % 1.0
        slots.append(
            Slot(
                slot_id=f"ordinary_{index + 1}",
                role=roles[index],
                index=index,
                flower_id=None,
                preferred_s=preferred_s,
                preferred_vertical_side=vertical[index],
            )
        )
    return slots


def _candidate_base(
    *,
    candidate_id: str,
    slot: Slot,
    source_channel: str,
    side_id: str,
    root_s: float,
    root: Point,
    target: Point,
    segments: Sequence[Mapping[str, Sequence[float]]],
    flower_id: str | None,
    curvature_signature: str,
    features: Mapping[str, float],
    individual_score: float,
) -> dict[str, Any]:
    centerline = _sample_segments(segments)
    return {
        "candidate_id": candidate_id,
        "slot_id": slot.slot_id,
        "source_channel": source_channel,
        "role": slot.role,
        "flower_id": flower_id,
        "side_id": side_id,
        "root_s": round(root_s % 1.0, 9),
        "root": _round_point(root),
        "target": _round_point(target),
        "curvature_signature": curvature_signature,
        "segments": list(segments),
        "centerline": [_round_point(point) for point in centerline],
        "planning_length": round(_polyline_length(centerline), 9),
        "occupancy_radius": 0.018,
        "features": {key: round(float(value), 9) for key, value in features.items()},
        "individual_score": round(individual_score, 9),
    }


def _ordinary_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    latents: Mapping[str, float],
    motion_policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    primary_stats = prior["statistics"]["primary_geometry"]["chord_length_repeat"]
    if slot.role == "frontier":
        base_length = float(primary_stats["q75"])
    elif slot.role == "balance":
        base_length = 0.5 * (
            float(primary_stats["median"]) + float(primary_stats["q75"])
        )
    else:
        base_length = float(primary_stats["median"])
    length_scales = (0.90, 1.08)
    phase = float(latents["flow_phase"]) * (1.0 if slot.index % 2 == 0 else -1.0)
    canvas_height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    root_gap_median = float(
        prior["statistics"]["primary_root_rhythm"]["consecutive_mount_gap"]["median"]
    )
    candidates: list[dict[str, Any]] = []
    index = 0
    for region in _candidate_regions(analysis):
        side_id = str(region["side_id"])
        root_fractions = (
            tuple(float(value) for value in motion_policy["region_sample_fractions"])
            if motion_policy["mode"] == "tangent_led_v1"
            else (0.10, 0.30, 0.50, 0.70, 0.90)
        )
        for root_s in _region_s_values(region, phase, root_fractions):
            root, tangent = _sample_at_s(analysis, root_s)
            outward = _normal(tangent, side_id)
            for along_sign in (-1.0, 1.0):
                for length_scale in length_scales:
                    radial_scales = (
                        tuple(
                            float(value)
                            for value in motion_policy["ordinary_radial_scales"]
                        )
                        if motion_policy["mode"] == "tangent_led_v1"
                        else (1.0,)
                    )
                    for radial_scale in radial_scales:
                        index += 1
                        planned = (
                            base_length
                            * length_scale
                            * float(latents["openness"])
                            * (1.08 if slot.role == "frontier" else 1.0)
                        )
                        if motion_policy["mode"] == "tangent_led_v1":
                            base_radial = min(
                                float(motion_policy["ordinary_maximum_radial"]),
                                max(
                                    float(motion_policy["ordinary_minimum_radial"]),
                                    planned
                                    * float(
                                        motion_policy[
                                            "ordinary_radial_planned_length_fraction"
                                        ]
                                    ),
                                ),
                            )
                            radial = base_radial * radial_scale
                        else:
                            radial = min(0.36, max(0.20, planned * 0.68))
                        longitudinal = math.sqrt(
                            max(planned * planned - radial * radial, 0.0144)
                        )
                        longitudinal *= (
                            along_sign * float(latents["sweep_amplitude"])
                        )
                        target = _add(
                            root,
                            _add(
                                _mul(outward, radial),
                                _mul(tangent, longitudinal),
                            ),
                        )
                        if not (0.035 <= target[1] <= canvas_height - 0.035):
                            continue
                        if not (-0.32 <= target[0] <= 1.32):
                            continue
                        start_direction = (
                            _mul(tangent, along_sign)
                            if motion_policy["mode"] == "tangent_led_v1"
                            else _unit(
                                _add(
                                    _mul(outward, 0.91),
                                    _mul(tangent, 0.18 * along_sign),
                                ),
                                "ordinary_start_direction",
                            )
                        )
                        terminal_direction = _unit(
                            _add(
                                _mul(tangent, 0.78 * along_sign),
                                _mul(outward, 0.34),
                            ),
                            "ordinary_terminal_direction",
                        )
                        chord = _distance(root, target)
                        entry_arm = chord * (
                            0.28 + 0.05 * float(latents["curl_energy"])
                        )
                        exit_arm = chord * (
                            0.34 + 0.06 * float(latents["curl_energy"])
                        )
                        if (slot.index + (1 if along_sign > 0 else 0)) % 2 == 0:
                            terminal_direction = _unit(
                                _add(
                                    _mul(terminal_direction, 0.72),
                                    _mul(outward, -0.46),
                                ),
                                "ordinary_s_terminal",
                            )
                            signature = "S"
                        else:
                            signature = "C"
                        segments = (
                            _tangent_led_segments(
                                root=root,
                                target=target,
                                flow_direction=start_direction,
                                outward=outward,
                                terminal_direction=terminal_direction,
                                policy=motion_policy,
                            )
                            if motion_policy["mode"] == "tangent_led_v1"
                            else [
                                _hermite_segment(
                                    root,
                                    target,
                                    start_direction,
                                    terminal_direction,
                                    entry_arm,
                                    exit_arm,
                                )
                            ]
                        )
                        root_preference = 1.0 - min(
                            1.0,
                            _periodic_delta(root_s, slot.preferred_s)
                            / max(root_gap_median * 2.5, 0.20),
                        )
                        vertical_side = (
                            "upper" if target[1] < root[1] else "lower"
                        )
                        vertical_match = (
                            1.0
                            if vertical_side == slot.preferred_vertical_side
                            else 0.0
                        )
                        individual_score = (
                            3.0 * root_preference
                            + 1.4 * vertical_match
                            + 1.0 * float(region["mean_clearance"]) / 0.38
                            + (0.7 if signature == "S" else 0.45)
                        )
                        candidate = _candidate_base(
                            candidate_id=f"{slot.slot_id}_dynamic_{index:03d}",
                            slot=slot,
                            source_channel="dynamic_prior_conditioned",
                            side_id=side_id,
                            root_s=root_s,
                            root=root,
                            target=target,
                            segments=segments,
                            flower_id=None,
                            curvature_signature=signature,
                            features={
                                "outward_alignment": _dot(start_direction, outward),
                                "root_preference": root_preference,
                                "vertical_match": vertical_match,
                                "planned_chord": chord,
                                "radial_scale": radial_scale,
                            },
                            individual_score=individual_score,
                        )
                        if motion_policy["mode"] == "tangent_led_v1":
                            _annotate_motion_candidate(
                                candidate,
                                analysis,
                                motion_policy,
                            )
                        candidates.append(candidate)
    return candidates


def _trough_s_values(analysis: Mapping[str, Any]) -> list[float]:
    troughs = [
        float(row["s"])
        for row in analysis["backbone"]["extrema"]
        if row["kind"] == "trough"
    ]
    if not troughs:
        raise GlobalL1FlowError("SW-1 support planning requires a detected trough")
    return troughs


def _sw1_support_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    latents: Mapping[str, float],
    motion_policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if slot.flower_id is None:
        raise GlobalL1FlowError("SW-1 support slot has no flower id")
    flower = _flower_by_id(analysis, slot.flower_id)
    troughs = _trough_s_values(analysis)
    base_trough = min(
        troughs,
        key=lambda value: _periodic_delta(value, float(flower["nearest_backbone_s"])),
    )
    offsets = (
        tuple(float(value) for value in motion_policy["sw1_trough_offsets"])
        if motion_policy["mode"] == "tangent_led_v1"
        else (-0.105, -0.075, -0.045, 0.045, 0.075, 0.105)
    )
    candidates: list[dict[str, Any]] = []
    candidate_index = 0
    for offset in offsets:
        signed_offset = offset + float(latents["flow_phase"]) * 0.35
        root_s = (base_trough + signed_offset) % 1.0
        root, tangent = _sample_at_s(analysis, root_s)
        target = _flower_boundary_toward(flower, root)
        center = _flower_center_near(flower, root[0])
        if motion_policy["mode"] == "tangent_led_v1":
            horizontal_sign = -1.0 if root[0] <= center[0] else 1.0
            waypoint = (
                center[0]
                + horizontal_sign
                * (
                    float(motion_policy["sw1_waypoint_rx_fraction"])
                    * float(flower["rx"])
                    + float(motion_policy["sw1_waypoint_horizontal_margin"])
                ),
                center[1]
                + float(flower["ry"])
                + float(motion_policy["sw1_waypoint_vertical_margin"]),
            )
            direction = _unit(_sub(waypoint, root), "sw1_support_direction")
        else:
            waypoint = None
            direction = _unit(_sub(target, root), "sw1_support_direction")
        side_id, outward = _closest_side(tangent, direction)
        preferred_along_sign = (
            1.0 if _dot(tangent, direction) >= 0.0 else -1.0
        )
        flow_options = (
            (preferred_along_sign, -preferred_along_sign)
            if motion_policy["mode"] == "tangent_led_v1"
            else (preferred_along_sign,)
        )
        for flow_index, along_sign in enumerate(flow_options):
            candidate_index += 1
            if motion_policy["mode"] == "tangent_led_v1":
                start_direction = _mul(tangent, along_sign)
            else:
                start_direction = _unit(
                    _add(_mul(outward, 0.86), _mul(direction, 0.40)),
                    "sw1_support_start",
                )
            radial = _unit(_sub(target, center), "sw1_flower_radial")
            terminal_direction = _mul(radial, -1.0)
            chord = _distance(root, target)
            if motion_policy["mode"] == "tangent_led_v1":
                assert waypoint is not None
                waypoint_exit = _unit(
                    _sub(target, waypoint),
                    "sw1_waypoint_exit",
                )
                sw1_departure_policy = dict(motion_policy)
                sw1_departure_policy["departure_chord_fraction"] = (
                    float(motion_policy["departure_chord_fraction"])
                    * float(motion_policy["sw1_departure_fraction_multiplier"])
                )
                sw1_departure_policy["minimum_departure_length"] = float(
                    motion_policy["sw1_minimum_departure_length"]
                )
                sw1_departure_policy["minimum_departure_clearance"] = float(
                    motion_policy["sw1_minimum_departure_clearance"]
                )
                sw1_departure_policy["maximum_departure_clearance"] = float(
                    motion_policy["sw1_maximum_departure_clearance"]
                )
                first_segments = _tangent_led_segments(
                    root=root,
                    target=waypoint,
                    flow_direction=start_direction,
                    outward=outward,
                    terminal_direction=waypoint_exit,
                    policy=sw1_departure_policy,
                )
                waypoint_chord = _distance(waypoint, target)
                segments = [
                    *first_segments,
                    _hermite_segment(
                        waypoint,
                        target,
                        waypoint_exit,
                        terminal_direction,
                        waypoint_chord
                        * float(
                            motion_policy[
                                "sw1_waypoint_exit_start_arm_fraction"
                            ]
                        ),
                        waypoint_chord
                        * float(
                            motion_policy[
                                "sw1_waypoint_exit_end_arm_fraction"
                            ]
                        ),
                    ),
                ]
            else:
                segments = [
                    _hermite_segment(
                        root,
                        target,
                        start_direction,
                        terminal_direction,
                        chord * 0.31,
                        chord * 0.24,
                    )
                ]
            trough_distance = _periodic_delta(root_s, base_trough)
            candidate = _candidate_base(
                candidate_id=f"{slot.slot_id}_sw1_{candidate_index:02d}",
                slot=slot,
                source_channel="prototype_morphology_rule",
                side_id=side_id,
                root_s=root_s,
                root=root,
                target=target,
                segments=segments,
                flower_id=slot.flower_id,
                curvature_signature="C",
                features={
                    "outward_alignment": _dot(start_direction, outward),
                    "trough_arc_distance": trough_distance,
                    "flower_contact_ellipse_value": _ellipse_value(
                        target,
                        center,
                        float(flower["rx"]),
                        float(flower["ry"]),
                    ),
                    "below_flower_waypoint_margin": (
                        waypoint[1] - (center[1] + float(flower["ry"]))
                        if waypoint is not None
                        else 0.0
                    ),
                    "preferred_flow_direction": (
                        1.0 if flow_index == 0 else 0.0
                    ),
                },
                individual_score=(
                    6.0
                    - 7.0 * trough_distance
                    + (0.15 if flow_index == 0 else 0.0)
                ),
            )
            if motion_policy["mode"] == "tangent_led_v1":
                _annotate_motion_candidate(candidate, analysis, motion_policy)
            candidates.append(candidate)
    return candidates


def _sw3_support_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    latents: Mapping[str, float],
    motion_policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if slot.flower_id is None:
        raise GlobalL1FlowError("SW-3 support slot has no flower id")
    flower = _flower_by_id(analysis, slot.flower_id)
    nearest_s = float(flower["nearest_backbone_s"])
    tangent_led = motion_policy["mode"] == "tangent_led_v1"
    distances = (
        tuple(
            float(value)
            for value in motion_policy["sw3_remote_mount_distances"]
        )
        if tangent_led
        else (0.335, 0.375, 0.415, 0.455)
    )
    waypoint_variants = (
        [
            (
                float(rx_fraction),
                float(horizontal_margin),
                float(vertical_margin),
            )
            for rx_fraction in motion_policy["sw3_waypoint_rx_fractions"]
            for horizontal_margin in motion_policy[
                "sw3_waypoint_horizontal_margins"
            ]
            for vertical_margin in motion_policy[
                "sw3_waypoint_vertical_margins"
            ]
        ]
        if tangent_led
        else [(0.62, 0.035, 0.055)]
    )
    candidates: list[dict[str, Any]] = []
    index = 0
    for arc_direction in (-1.0, 1.0):
        for distance in distances:
            remote_distance = distance + float(
                latents["flow_phase"]
            ) * (
                float(motion_policy["sw3_remote_phase_scale"])
                if tangent_led
                else 0.20
            )
            root_s = (nearest_s + arc_direction * remote_distance) % 1.0
            root, tangent = _sample_at_s(analysis, root_s)
            center = _flower_center_near(flower, root[0])
            rx = float(flower["rx"])
            ry = float(flower["ry"])
            target = center[0], center[1] + ry
            horizontal_sign = -1.0 if root[0] <= center[0] else 1.0
            for (
                waypoint_rx_fraction,
                waypoint_horizontal_margin,
                waypoint_vertical_margin,
            ) in waypoint_variants:
                index += 1
                waypoint = (
                    center[0]
                    + horizontal_sign
                    * (
                        waypoint_rx_fraction * rx
                        + waypoint_horizontal_margin
                    ),
                    center[1] + ry + waypoint_vertical_margin,
                )
                toward_waypoint = _unit(
                    _sub(waypoint, root),
                    "sw3_waypoint_direction",
                )
                side_id, outward = _closest_side(
                    tangent,
                    toward_waypoint,
                )
                if tangent_led:
                    along_sign = (
                        1.0
                        if _dot(tangent, toward_waypoint) >= 0.0
                        else -1.0
                    )
                    start_direction = _mul(tangent, along_sign)
                else:
                    start_direction = _unit(
                        _add(
                            _mul(toward_waypoint, 0.92),
                            _mul(outward, 0.16),
                        ),
                        "sw3_support_start",
                    )
                first_chord = _distance(root, waypoint)
                second_chord = _distance(waypoint, target)
                tangent_at_waypoint = _unit(
                    _sub(target, waypoint),
                    "sw3_second_start",
                )
                first_segments = (
                    _tangent_led_segments(
                        root=root,
                        target=waypoint,
                        flow_direction=start_direction,
                        outward=outward,
                        terminal_direction=tangent_at_waypoint,
                        policy=motion_policy,
                    )
                    if tangent_led
                    else [
                        _hermite_segment(
                            root,
                            waypoint,
                            start_direction,
                            tangent_at_waypoint,
                            first_chord * 0.33,
                            first_chord * 0.12,
                        )
                    ]
                )
                second = _hermite_segment(
                    waypoint,
                    target,
                    tangent_at_waypoint,
                    (0.0, -1.0),
                    max(
                        (
                            float(
                                motion_policy[
                                    "sw3_second_minimum_start_arm"
                                ]
                            )
                            if tangent_led
                            else 0.035
                        ),
                        second_chord
                        * (
                            float(
                                motion_policy[
                                    "sw3_second_start_arm_fraction"
                                ]
                            )
                            if tangent_led
                            else 0.42
                        ),
                    ),
                    max(
                        (
                            float(
                                motion_policy[
                                    "sw3_second_minimum_end_arm"
                                ]
                            )
                            if tangent_led
                            else 0.025
                        ),
                        second_chord
                        * (
                            float(
                                motion_policy[
                                    "sw3_second_end_arm_fraction"
                                ]
                            )
                            if tangent_led
                            else 0.28
                        ),
                    ),
                )
                candidate = _candidate_base(
                    candidate_id=f"{slot.slot_id}_sw3_{index:02d}",
                    slot=slot,
                    source_channel="prototype_morphology_rule",
                    side_id=side_id,
                    root_s=root_s,
                    root=root,
                    target=target,
                    segments=[*first_segments, second],
                    flower_id=slot.flower_id,
                    curvature_signature="SC" if arc_direction < 0 else "CS",
                    features={
                        "outward_alignment": _dot(start_direction, outward),
                        "remote_mount_arc_distance": _periodic_delta(root_s, nearest_s),
                        "below_flower_waypoint_margin": waypoint[1] - (center[1] + ry),
                        "underside_contact_dx": abs(target[0] - center[0]),
                        "underside_contact_dy": abs(target[1] - (center[1] + ry)),
                        "waypoint_rx_fraction": waypoint_rx_fraction,
                        "waypoint_horizontal_margin": waypoint_horizontal_margin,
                        "waypoint_vertical_margin": waypoint_vertical_margin,
                    },
                    individual_score=8.0
                    - abs(_periodic_delta(root_s, nearest_s) - 0.395) * 8.0,
                )
                if tangent_led:
                    _annotate_motion_candidate(
                        candidate,
                        analysis,
                        motion_policy,
                    )
                candidates.append(candidate)
    return candidates


def _fixed_warp_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    seed: int,
    motion_policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    # The tangent-led R path must derive geometry from the current backbone,
    # flower reserves, and measured free space.  The legacy paired prior stores
    # seed-indexed cubic geometry and is therefore not a legal R candidate
    # source, even when its endpoint happens to satisfy the numeric motion
    # checks.
    if motion_policy["mode"] == "tangent_led_v1":
        return []
    if analysis["prototype_id"] != "proto_sw_1_3":
        return []
    templates = prior["paired_primary_templates"][str(seed)]
    if slot.flower_id is None:
        applicable = [
            row for row in templates if row["kind"] != "flower"
        ]
        applicable.sort(key=lambda row: float(row["mount_s"]))
        ordinary_index = int(slot.slot_id.split("_")[-1]) - 1
        if ordinary_index >= len(applicable):
            return []
        applicable = [applicable[ordinary_index]]
    else:
        applicable = [
            row
            for row in templates
            if row["kind"] == "flower" and row["target_flower_id"] == slot.flower_id
        ]
    candidates: list[dict[str, Any]] = []
    for template in applicable:
        source_segments = template["cubics"]
        root = _point(source_segments[0]["p0"], "fixed_template.p0")
        target = _point(source_segments[-1]["p3"], "fixed_template.p3")
        root_s = float(template["mount_s"])
        _, tangent = _sample_at_s(analysis, root_s)
        direction = _unit(_sub(target, root), "fixed_warp_direction")
        side_id, outward = _closest_side(tangent, direction)
        source_p1 = _point(source_segments[0]["p1"], "fixed_template.p1")
        source_arm = max(0.065, _distance(root, source_p1))
        if motion_policy["mode"] == "tangent_led_v1":
            along_sign = 1.0 if _dot(tangent, direction) >= 0.0 else -1.0
            corrected_start = _mul(tangent, along_sign)
            source_end = source_segments[-1]
            terminal_direction = _unit(
                _sub(
                    _point(source_end["p3"], "fixed_template.last.p3"),
                    _point(source_end["p2"], "fixed_template.last.p2"),
                ),
                "fixed_template_terminal_direction",
            )
            segments = _tangent_led_segments(
                root=root,
                target=target,
                flow_direction=corrected_start,
                outward=outward,
                terminal_direction=terminal_direction,
                policy=motion_policy,
            )
        else:
            corrected_start = _unit(
                _add(_mul(outward, 0.90), _mul(direction, 0.24)),
                "fixed_warp_corrected_start",
            )
            segments = [
                {
                    key: list(values)
                    for key, values in source_segment.items()
                }
                for source_segment in source_segments
            ]
            segments[0]["p1"] = _round_point(
                _add(root, _mul(corrected_start, source_arm))
            )
        candidate = _candidate_base(
                candidate_id=f'{slot.slot_id}_fixed_warp_{template["curve_id"]}',
                slot=slot,
                source_channel="fixed_warp_visual_prior",
                side_id=side_id,
                root_s=root_s,
                root=root,
                target=target,
                segments=segments,
                flower_id=slot.flower_id,
                curvature_signature="fixed_derived",
                features={
                    "outward_alignment": _dot(corrected_start, outward),
                    "source_template_mount_s": root_s,
                    "initial_handle_changed_only": (
                        0.0
                        if motion_policy["mode"] == "tangent_led_v1"
                        else 1.0
                    ),
                    "fixed_endpoint_and_terminal_preserved": (
                        1.0
                        if motion_policy["mode"] == "tangent_led_v1"
                        else 0.0
                    ),
                },
                individual_score=7.0,
            )
        if motion_policy["mode"] == "tangent_led_v1":
            _annotate_motion_candidate(candidate, analysis, motion_policy)
        candidates.append(candidate)
    return candidates


def _backbone_points(analysis: Mapping[str, Any]) -> list[Point]:
    return [_point(row["point"], "backbone.point") for row in analysis["backbone"]["samples"]]


def _point_backbone_clearance(
    point: Point,
    backbone: Sequence[Point],
) -> float:
    minimum = float("inf")
    for offset in (-1.0, 0.0, 1.0):
        shifted = [(row[0] + offset, row[1]) for row in backbone]
        for index in range(1, len(shifted)):
            minimum = min(
                minimum,
                _point_segment_distance(point, shifted[index - 1], shifted[index]),
            )
    return minimum


def _polyline_tail_after_fraction(
    points: Sequence[Point],
    fraction: float,
) -> list[Point]:
    lengths = _polyline_cumulative_lengths(points)
    if not lengths or lengths[-1] <= 1e-12:
        return list(points)
    target = lengths[-1] * fraction
    for index in range(1, len(points)):
        if lengths[index] + 1e-12 < target:
            continue
        span = lengths[index] - lengths[index - 1]
        local = (
            0.0
            if span <= 1e-12
            else (target - lengths[index - 1]) / span
        )
        return [
            _lerp(points[index - 1], points[index], local),
            *points[index:],
        ]
    return [points[-1]]


def _prepare_backbone_collision_geometry(
    backbone: Sequence[Point],
    bin_width: float,
) -> dict[str, Any]:
    segments: list[
        tuple[Point, Point, float, float, float, float]
    ] = []
    bins: dict[int, list[int]] = {}
    for offset in (-1.0, 0.0, 1.0):
        shifted = [(row[0] + offset, row[1]) for row in backbone]
        for start, end in zip(shifted, shifted[1:]):
            min_x = min(start[0], end[0])
            max_x = max(start[0], end[0])
            segment_index = len(segments)
            segments.append(
                (
                    start,
                    end,
                    min_x,
                    max_x,
                    min(start[1], end[1]),
                    max(start[1], end[1]),
                )
            )
            first_bin = math.floor(min_x / bin_width)
            last_bin = math.floor(max_x / bin_width)
            for bin_index in range(first_bin, last_bin + 1):
                bins.setdefault(bin_index, []).append(segment_index)
    return {
        "bin_width": bin_width,
        "segments": tuple(segments),
        "bins": {
            key: tuple(value)
            for key, value in bins.items()
        },
    }


def _backbone_non_root_crossing_count(
    centerline: Sequence[Point],
    backbone_collision: Mapping[str, Any],
    start_fraction: float,
) -> int:
    tail = _polyline_tail_after_fraction(centerline, start_fraction)
    bin_width = float(backbone_collision["bin_width"])
    segments = backbone_collision["segments"]
    bins = backbone_collision["bins"]
    count = 0
    for lane_start, lane_end in zip(tail, tail[1:]):
        lane_min_x = min(lane_start[0], lane_end[0])
        lane_max_x = max(lane_start[0], lane_end[0])
        lane_min_y = min(lane_start[1], lane_end[1])
        lane_max_y = max(lane_start[1], lane_end[1])
        candidate_indices: set[int] = set()
        for bin_index in range(
            math.floor(lane_min_x / bin_width),
            math.floor(lane_max_x / bin_width) + 1,
        ):
            candidate_indices.update(bins.get(bin_index, ()))
        for segment_index in candidate_indices:
            (
                backbone_start,
                backbone_end,
                backbone_min_x,
                backbone_max_x,
                backbone_min_y,
                backbone_max_y,
            ) = segments[segment_index]
            if (
                lane_max_x < backbone_min_x
                or backbone_max_x < lane_min_x
                or lane_max_y < backbone_min_y
                or backbone_max_y < lane_min_y
            ):
                continue
            if _segments_intersect(
                lane_start,
                lane_end,
                backbone_start,
                backbone_end,
            ):
                count += 1
    return count


def _candidate_motion_features(
    candidate: Mapping[str, Any],
    analysis: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, float]:
    centerline = [
        _point(point, "candidate.centerline")
        for point in candidate["centerline"]
    ]
    _, tangent = _sample_at_s(analysis, float(candidate["root_s"]))
    initial = _unit(_sub(centerline[1], centerline[0]), "candidate.initial")
    selected_flow = tangent if _dot(initial, tangent) >= 0.0 else _mul(tangent, -1.0)
    cumulative = _polyline_cumulative_lengths(centerline)
    total = cumulative[-1]
    initial_errors: list[float] = []
    initial_fraction = float(policy["initial_flow_arc_fraction"])
    for index in range(1, len(centerline)):
        midpoint_length = 0.5 * (cumulative[index - 1] + cumulative[index])
        if total > 1e-12 and midpoint_length / total > initial_fraction:
            break
        direction = _sub(centerline[index], centerline[index - 1])
        initial_errors.append(_angle_degrees(direction, selected_flow))
    y_min = float(analysis["coordinate_system"]["canvas_bounds"][1])
    y_max = float(analysis["coordinate_system"]["canvas_bounds"][3])
    outside_length = 0.0
    for start, end in zip(centerline, centerline[1:]):
        midpoint_y = 0.5 * (start[1] + end[1])
        if midpoint_y < y_min or midpoint_y > y_max:
            outside_length += _distance(start, end)
    point_25 = _point_at_arc_fraction(
        centerline,
        float(policy["clearance_measure_arc_fraction"]),
    )
    return {
        "root_tangent_error_deg": _angle_degrees(
            initial,
            tangent,
            unsigned_axis=True,
        ),
        "selected_flow_sign": 1.0 if _dot(initial, tangent) >= 0.0 else -1.0,
        "maximum_tangent_error_first_15pct": max(initial_errors, default=0.0),
        "backbone_clearance_at_25pct": _point_backbone_clearance(
            point_25,
            _backbone_points(analysis),
        ),
        "horizontal_progress_ratio": (
            abs(centerline[-1][0] - centerline[0][0]) / total
            if total > 1e-12
            else 0.0
        ),
        "out_of_bounds_length": outside_length,
    }


def _annotate_motion_candidate(
    candidate: dict[str, Any],
    analysis: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    features = _candidate_motion_features(candidate, analysis, policy)
    candidate["features"].update(
        {key: round(value, 9) for key, value in features.items()}
    )
    scoring = policy["scoring"]
    candidate["individual_score"] = round(
        float(candidate["individual_score"])
        + float(scoring["horizontal_progress_weight"])
        * features["horizontal_progress_ratio"]
        + float(scoring["clearance_at_25pct_weight"])
        * min(
            1.0,
            features["backbone_clearance_at_25pct"]
            / float(policy["minimum_backbone_clearance_at_25pct"]),
        )
        + float(scoring["initial_flow_weight"])
        * max(
            0.0,
            1.0
            - features["maximum_tangent_error_first_15pct"]
            / float(policy["maximum_initial_flow_error_deg"]),
        ),
        9,
    )
    return candidate


def _ordinary_flower_intrusion(
    centerline: Sequence[Point],
    analysis: Mapping[str, Any],
) -> bool:
    for flower in analysis["flowers"]:
        rx = float(flower["protection_rx"])
        ry = float(flower["protection_ry"])
        for point in centerline[3:]:
            center = _flower_center_near(flower, point[0])
            if _ellipse_value(point, center, rx, ry) < 1.0:
                return True
    return False


def _support_flower_intrusion(
    centerline: Sequence[Point],
    analysis: Mapping[str, Any],
    target_flower_id: str,
) -> bool:
    for flower in analysis["flowers"]:
        rx = float(flower["protection_rx"])
        ry = float(flower["protection_ry"])
        limit = int(len(centerline) * 0.72) if flower["flower_id"] == target_flower_id else len(centerline)
        for point in centerline[:limit]:
            center = _flower_center_near(flower, point[0])
            if _ellipse_value(point, center, rx, ry) < 1.0:
                return True
    return False


def _backbone_non_root_clearance(
    centerline: Sequence[Point],
    backbone: Sequence[Point],
    start_fraction: float = 0.16,
) -> float:
    start = max(4, int(len(centerline) * start_fraction))
    minimum = float("inf")
    for point in centerline[start:]:
        for offset in (-1.0, 0.0, 1.0):
            shifted = [(row[0] + offset, row[1]) for row in backbone]
            for index in range(1, len(shifted)):
                minimum = min(
                    minimum,
                    _point_segment_distance(point, shifted[index - 1], shifted[index]),
                )
    return minimum


def _candidate_rejections(
    candidate: Mapping[str, Any],
    analysis: Mapping[str, Any],
    family_id: str,
    prior: Mapping[str, Any],
    motion_policy: Mapping[str, Any],
    backbone: Sequence[Point],
    backbone_collision: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    centerline = [_point(point, "candidate.centerline") for point in candidate["centerline"]]
    root = _point(candidate["root"], "candidate.root")
    target = _point(candidate["target"], "candidate.target")
    _, tangent = _sample_at_s(analysis, float(candidate["root_s"]))
    initial = _unit(_sub(centerline[1], centerline[0]), "candidate.initial")
    if motion_policy["mode"] == "tangent_led_v1":
        features = candidate["features"]
        if float(features["root_tangent_error_deg"]) > float(
            motion_policy["maximum_root_tangent_error_deg"]
        ):
            reasons.append("root_tangent_error_exceeds_limit")
        if float(features["maximum_tangent_error_first_15pct"]) > float(
            motion_policy["maximum_initial_flow_error_deg"]
        ):
            reasons.append("initial_flow_turns_before_delay_window")
        if float(features["backbone_clearance_at_25pct"]) < float(
            motion_policy["minimum_backbone_clearance_at_25pct"]
        ):
            reasons.append("insufficient_backbone_clearance_at_25pct")
        minimum_horizontal = (
            float(motion_policy["minimum_support_horizontal_progress_ratio"])
            if candidate["role"] in {"flower_support", "terminal_flower_support"}
            else float(motion_policy["minimum_ordinary_horizontal_progress_ratio"])
        )
        if float(features["horizontal_progress_ratio"]) < minimum_horizontal:
            reasons.append("insufficient_horizontal_progress")
        if float(features["out_of_bounds_length"]) > float(
            motion_policy["out_of_bounds_length_tolerance"]
        ):
            reasons.append("curve_exits_vertical_canvas")
        crossing_count = _backbone_non_root_crossing_count(
            centerline,
            backbone_collision,
            float(
                motion_policy[
                    "non_root_crossing_exclusion_fraction"
                ]
            ),
        )
        candidate["features"]["non_root_backbone_crossing_count"] = float(
            crossing_count
        )
        if crossing_count > 0:
            reasons.append("non_root_backbone_crossing")
    else:
        outward = _normal(tangent, str(candidate["side_id"]))
        if _dot(initial, outward) < 0.72:
            reasons.append("ordinary_or_support_initial_departure_not_outward")

    canvas_height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    if not (0.0 <= target[1] <= canvas_height):
        reasons.append("target_outside_vertical_canvas")
    if not (-0.34 <= target[0] <= 1.34):
        reasons.append("target_outside_periodic_review_window")

    backbone_clearance = _backbone_non_root_clearance(
        centerline,
        backbone,
        (
            float(motion_policy["non_root_clearance_start_fraction"])
            if motion_policy["mode"] == "tangent_led_v1"
            else 0.16
        ),
    )
    minimum_non_root_clearance = (
        float(motion_policy["minimum_non_root_backbone_clearance"])
        if motion_policy["mode"] == "tangent_led_v1"
        else 0.012
    )
    if backbone_clearance < minimum_non_root_clearance:
        reasons.append("non_root_backbone_crossing_or_contact")

    role = str(candidate["role"])
    flower_id = candidate.get("flower_id")
    if flower_id is None:
        if _ordinary_flower_intrusion(centerline, analysis):
            reasons.append("ordinary_lane_enters_flower_reserve")
    else:
        if _support_flower_intrusion(centerline, analysis, str(flower_id)):
            reasons.append("support_lane_enters_flower_reserve_before_terminal_approach")

    self_clearance = min(
        _polyline_distance(centerline, centerline, -1.0),
        _polyline_distance(centerline, centerline, 1.0),
    )
    if self_clearance < 0.032:
        reasons.append("periodic_self_conflict")

    if family_id == "SW-1_valley_filling" and role == "flower_support":
        trough_distance = float(candidate["features"].get("trough_arc_distance", 1.0))
        if trough_distance > 0.14:
            reasons.append("sw1_support_not_from_trough_flank")
    if family_id == "SW-3_tangent_terminal" and role == "terminal_flower_support":
        remote = float(candidate["features"].get("remote_mount_arc_distance", -1.0))
        if not 0.30 <= remote <= 0.48:
            reasons.append("sw3_support_mount_not_remote")
        if float(candidate["features"].get("below_flower_waypoint_margin", -1.0)) < 0.035:
            reasons.append("sw3_support_does_not_route_below_flower")
        if float(candidate["features"].get("underside_contact_dx", 1.0)) > 0.01:
            reasons.append("sw3_support_wrong_horizontal_contact")
        if float(candidate["features"].get("underside_contact_dy", 1.0)) > 0.01:
            reasons.append("sw3_support_wrong_vertical_contact")

    minimum_length = float(
        prior["statistics"]["primary_geometry"]["actual_length_repeat"]["min"]
    ) * 0.72
    if float(candidate["planning_length"]) < minimum_length:
        reasons.append("lane_shorter_than_visual_prior_floor")
    return reasons


def _pair_metrics(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    root_spacing: float,
    lane_clearance: float,
    collision_cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[bool, float, dict[str, float]]:
    root_gap = _periodic_delta(float(a["root_s"]), float(b["root_s"]))
    if root_gap < root_spacing:
        return False, 0.0, {"root_gap": root_gap, "minimum_clearance": 0.0}
    def collision_geometry(
        candidate: Mapping[str, Any],
        label: str,
    ) -> dict[str, Any]:
        candidate_id = str(candidate["candidate_id"])
        if collision_cache is not None and candidate_id in collision_cache:
            return collision_cache[candidate_id]
        geometry = _prepare_polyline_collision_geometry(
            [_point(point, label) for point in candidate["centerline"]]
        )
        if collision_cache is not None:
            collision_cache[candidate_id] = geometry
        return geometry

    geometry_a = collision_geometry(a, "lane_a.centerline")
    geometry_b = collision_geometry(b, "lane_b.centerline")
    points_a = geometry_a["points"]
    points_b = geometry_b["points"]
    minimum = float("inf")
    for offset in (-1.0, 0.0, 1.0):
        minimum = min(
            minimum,
            _prepared_polyline_distance(
                geometry_a,
                geometry_b,
                offset,
                stop_below=lane_clearance,
            ),
        )
        if minimum < lane_clearance:
            break
    if minimum < lane_clearance:
        return False, 0.0, {"root_gap": root_gap, "minimum_clearance": minimum}

    direction_a = _unit(_sub(points_a[-1], points_a[-4]), "lane_a_terminal")
    direction_b = _unit(_sub(points_b[-1], points_b[-4]), "lane_b_terminal")
    alignment = abs(_dot(direction_a, direction_b))
    glide = 0.0
    if lane_clearance <= minimum <= 0.16 and alignment >= 0.72:
        glide = alignment * (1.0 - abs(minimum - 0.085) / 0.075)
    spacing_score = 1.0 - min(1.0, abs(root_gap - 0.13) / 0.13)
    pair_score = 0.9 * glide + 0.35 * spacing_score
    return True, pair_score, {
        "root_gap": root_gap,
        "minimum_clearance": minimum,
        "terminal_alignment": alignment,
        "parallel_glide": glide,
    }


def _maximum_root_count_in_window(
    roots: Sequence[float],
    window: float,
) -> int:
    values = sorted(value % 1.0 for value in roots)
    if not values:
        return 0
    extended = values + [value + 1.0 for value in values]
    maximum = 0
    for index, start in enumerate(values):
        maximum = max(
            maximum,
            sum(
                1
                for value in extended[index : index + len(values)]
                if value - start <= window + 1e-12
            ),
        )
    return maximum


def _global_score(
    lanes: Sequence[Mapping[str, Any]],
    motion_policy: Mapping[str, Any],
) -> tuple[float, dict[str, float]]:
    roots = sorted(float(lane["root_s"]) for lane in lanes)
    root_gaps = [
        roots[index] - roots[index - 1]
        for index in range(1, len(roots))
    ] + [1.0 - roots[-1] + roots[0]]
    root_gap_mean = sum(root_gaps) / len(root_gaps)
    root_gap_variance = sum((gap - root_gap_mean) ** 2 for gap in root_gaps) / len(root_gaps)
    root_coverage = 1.0 - max(root_gaps)

    target_bins = {
        (
            int(math.floor((_point(lane["target"], "lane.target")[0] % 1.0) * 4.0)),
            0 if _point(lane["target"], "lane.target")[1] < _point(lane["root"], "lane.root")[1] else 1,
        )
        for lane in lanes
    }
    target_coverage = len(target_bins) / min(len(lanes), 8)
    lengths = [float(lane["planning_length"]) for lane in lanes]
    length_mean = sum(lengths) / len(lengths)
    length_variance = sum((value - length_mean) ** 2 for value in lengths) / len(lengths)
    length_rhythm = min(1.0, math.sqrt(length_variance) / max(length_mean * 0.32, 1e-9))
    source_channels = Counter(str(lane["source_channel"]) for lane in lanes)
    fixed_prior_presence = 1.0 if source_channels["fixed_warp_visual_prior"] else 0.0
    score = (
        4.0 * root_coverage
        + 3.0 * target_coverage
        + 1.6 * length_rhythm
        + 0.8 * fixed_prior_presence
        + min(1.0, math.sqrt(root_gap_variance) / 0.055)
    )
    features = {
        "root_coverage": root_coverage,
        "target_zone_coverage": target_coverage,
        "length_rhythm": length_rhythm,
        "root_gap_variation": math.sqrt(root_gap_variance),
        "fixed_prior_channel_present": fixed_prior_presence,
    }
    if motion_policy["mode"] == "tangent_led_v1":
        horizontal_mean = sum(
            float(lane["features"]["horizontal_progress_ratio"])
            for lane in lanes
        ) / len(lanes)
        initial_flow_mean = sum(
            max(
                0.0,
                1.0
                - float(
                    lane["features"]["maximum_tangent_error_first_15pct"]
                )
                / float(motion_policy["maximum_initial_flow_error_deg"]),
            )
            for lane in lanes
        ) / len(lanes)
        motion_weight = float(
            motion_policy["scoring"]["global_motion_quality_weight"]
        )
        score += motion_weight * (horizontal_mean + initial_flow_mean)
        features.update(
            {
                "horizontal_progress_mean": horizontal_mean,
                "initial_flow_quality_mean": initial_flow_mean,
            }
        )
    return score, features


def _diverse_candidate_subset(
    pool: Sequence[Mapping[str, Any]],
    cap: int,
    root_bin_width: float,
) -> list[Mapping[str, Any]]:
    ranked = sorted(
        pool,
        key=lambda row: (
            -float(row["individual_score"]),
            str(row["candidate_id"]),
        ),
    )
    groups: dict[tuple[int, str, int], list[Mapping[str, Any]]] = {}
    for row in ranked:
        key = (
            int(math.floor((float(row["root_s"]) % 1.0) / root_bin_width)),
            str(row["side_id"]),
            int(round(float(row["features"].get("selected_flow_sign", 0.0)))),
        )
        groups.setdefault(key, []).append(row)
    group_keys = sorted(
        groups,
        key=lambda key: (
            -float(groups[key][0]["individual_score"]),
            key,
        ),
    )
    selected: list[Mapping[str, Any]] = []
    depth = 0
    while len(selected) < cap:
        added = False
        for key in group_keys:
            rows = groups[key]
            if depth < len(rows):
                selected.append(rows[depth])
                added = True
                if len(selected) >= cap:
                    break
        if not added:
            break
        depth += 1
    return selected


def _diverse_state_subset(
    states: Sequence[BeamState],
    cap: int,
    root_bin_width: float,
) -> list[BeamState]:
    ranked = sorted(
        states,
        key=lambda state: (
            -state.score,
            tuple(str(row["candidate_id"]) for row in state.lanes),
        ),
    )
    groups: dict[tuple[int, ...], list[BeamState]] = {}
    for state in ranked:
        signature = tuple(
            sorted(
                int(
                    math.floor(
                        (float(row["root_s"]) % 1.0) / root_bin_width
                    )
                )
                for row in state.lanes
            )
        )
        groups.setdefault(signature, []).append(state)
    group_keys = sorted(
        groups,
        key=lambda key: (
            -groups[key][0].score,
            key,
        ),
    )
    selected: list[BeamState] = []
    depth = 0
    while len(selected) < cap:
        added = False
        for key in group_keys:
            rows = groups[key]
            if depth < len(rows):
                selected.append(rows[depth])
                added = True
                if len(selected) >= cap:
                    break
        if not added:
            break
        depth += 1
    return selected


def _solve(
    slots: Sequence[Slot],
    candidate_pools: Mapping[str, Sequence[Mapping[str, Any]]],
    prior: Mapping[str, Any],
    motion_policy: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root_stats = prior["statistics"]["primary_root_rhythm"]["consecutive_mount_gap"]
    root_spacing = max(0.05, float(root_stats["min"]) * 0.78)
    lane_clearance = max(0.032, root_spacing * 0.58)
    if motion_policy["mode"] == "tangent_led_v1":
        beam_capacity = (
            int(motion_policy["solver_beam_capacity_per_slot_squared"])
            * len(slots) ** 2
        )
        expansion_cap = (
            int(motion_policy["solver_expansion_cap_per_slot"])
            * len(slots)
            + int(motion_policy["solver_expansion_cap_constant"])
        )
    else:
        beam_capacity = 36 * len(slots) ** 2
        expansion_cap = 4 * len(slots) + 4
    solve_slots = (
        sorted(
            slots,
            key=lambda slot: (
                len(candidate_pools[slot.slot_id]),
                slot.slot_id,
            ),
        )
        if motion_policy["mode"] == "tangent_led_v1"
        and motion_policy["solver_slot_order"] == "minimum_remaining_values"
        else list(slots)
    )
    states = [BeamState(lanes=[], score=0.0)]
    pair_cache: dict[tuple[str, str], tuple[bool, float, dict[str, float]]] = {}
    collision_cache: dict[str, dict[str, Any]] = {}

    for slot in solve_slots:
        pool = (
            _diverse_candidate_subset(
                candidate_pools[slot.slot_id],
                expansion_cap,
                float(motion_policy["solver_candidate_root_bin_width"]),
            )
            if motion_policy["mode"] == "tangent_led_v1"
            else sorted(
                candidate_pools[slot.slot_id],
                key=lambda row: (
                    -float(row["individual_score"]),
                    str(row["candidate_id"]),
                ),
            )[:expansion_cap]
        )
        if not pool:
            raise GlobalL1FlowError(f"slot {slot.slot_id} has no feasible candidates")
        expanded: list[BeamState] = []
        for state in states:
            for candidate in pool:
                if (
                    motion_policy["mode"] == "tangent_led_v1"
                    and _maximum_root_count_in_window(
                        [
                            *(float(row["root_s"]) for row in state.lanes),
                            float(candidate["root_s"]),
                        ],
                        float(motion_policy["root_density_window"]),
                    )
                    > int(motion_policy["maximum_roots_per_density_window"])
                ):
                    continue
                pair_score = 0.0
                compatible = True
                for existing in state.lanes:
                    key = tuple(sorted((str(candidate["candidate_id"]), str(existing["candidate_id"]))))
                    if key not in pair_cache:
                        pair_cache[key] = _pair_metrics(
                            candidate,
                            existing,
                            root_spacing,
                            lane_clearance,
                            collision_cache,
                        )
                    valid, score, _ = pair_cache[key]
                    if not valid:
                        compatible = False
                        break
                    pair_score += score
                if compatible:
                    expanded.append(
                        BeamState(
                            lanes=state.lanes + [dict(candidate)],
                            score=state.score
                            + float(candidate["individual_score"])
                            + pair_score,
                        )
                    )
        if not expanded:
            raise GlobalL1FlowError(
                f"single forward global solve became infeasible at slot {slot.slot_id}"
            )
        states = (
            _diverse_state_subset(
                expanded,
                beam_capacity,
                float(motion_policy["solver_candidate_root_bin_width"]),
            )
            if motion_policy["mode"] == "tangent_led_v1"
            else sorted(
                expanded,
                key=lambda state: (
                    -state.score,
                    tuple(str(row["candidate_id"]) for row in state.lanes),
                ),
            )[:beam_capacity]
        )

    ranked: list[tuple[float, BeamState, dict[str, float]]] = []
    for state in states:
        global_value, global_features = _global_score(
            state.lanes,
            motion_policy,
        )
        ranked.append((state.score + global_value, state, global_features))
    ranked.sort(
        key=lambda row: (
            -row[0],
            tuple(str(lane["candidate_id"]) for lane in row[1].lanes),
        )
    )
    total_score, selected_state, global_features = ranked[0]
    selected = sorted(selected_state.lanes, key=lambda row: float(row["root_s"]))

    pair_rows: list[dict[str, Any]] = []
    for index, lane in enumerate(selected):
        for other in selected[index + 1 :]:
            key = tuple(sorted((str(lane["candidate_id"]), str(other["candidate_id"]))))
            pair_result = pair_cache.get(key)
            if pair_result is None:
                pair_result = _pair_metrics(
                    lane,
                    other,
                    root_spacing,
                    lane_clearance,
                    collision_cache,
                )
            valid, score, metrics = pair_result
            if not valid:
                raise GlobalL1FlowError("selected global state contains a hard pair conflict")
            pair_rows.append(
                {
                    "candidate_ids": list(key),
                    "pair_score": round(score, 9),
                    **{name: round(value, 9) for name, value in metrics.items()},
                }
            )
    return selected, {
        "solver": "deterministic_seeded_global_beam_set_solver",
        "beam_capacity": beam_capacity,
        "expansion_cap_per_slot": expansion_cap,
        "root_spacing_hard": round(root_spacing, 9),
        "lane_clearance_hard": round(lane_clearance, 9),
        "terminal_state_count": len(states),
        "selected_total_score": round(total_score, 9),
        "global_features": {key: round(value, 9) for key, value in global_features.items()},
        "selected_pair_metrics": pair_rows,
        "slot_solve_order": [slot.slot_id for slot in solve_slots],
        "motion_policy": str(motion_policy["mode"]),
        "maximum_root_count_in_density_window": _maximum_root_count_in_window(
            [float(row["root_s"]) for row in selected],
            (
                float(motion_policy["root_density_window"])
                if motion_policy["mode"] == "tangent_led_v1"
                else 0.10
            ),
        ),
    }


def _validate_inputs(
    strict_p0: Mapping[str, Any],
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    seed: int,
) -> tuple[str, str]:
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise GlobalL1FlowError("stage-3B contract schema mismatch")
    if seed not in SEEDS:
        raise GlobalL1FlowError(f"seed is outside the formal launch matrix: {seed}")
    prototype_id = str(strict_p0.get("prototype_id"))
    if prototype_id not in PROTOTYPE_IDS:
        raise GlobalL1FlowError(f"unknown prototype id: {prototype_id}")
    if strict_p0.get("schema") != "dynamic_branch_strict_p0_v2":
        raise GlobalL1FlowError(f"{prototype_id} StrictP0 schema mismatch")
    if analysis.get("schema") != "dynamic_branch_prototype_analysis_v1":
        raise GlobalL1FlowError(f"{prototype_id} analysis schema mismatch")
    if morphology.get("schema") != "dynamic_branch_morphology_profile_v1":
        raise GlobalL1FlowError(f"{prototype_id} morphology schema mismatch")
    if analysis.get("prototype_id") != prototype_id or morphology.get("prototype_id") != prototype_id:
        raise GlobalL1FlowError(f"{prototype_id} input identity mismatch")
    strict_flower_ids = [row["flower_id"] for row in strict_p0["flowers"]]
    analysis_flower_ids = [row["flower_id"] for row in analysis["flowers"]]
    if strict_flower_ids != analysis_flower_ids:
        raise GlobalL1FlowError(f"{prototype_id} flower inventory mismatch")
    validate_fixed_visual_prior(prior)
    family_id = str(morphology["classification"]["flower_branch_relation"]["family_id"])
    return prototype_id, family_id


def _role_region_width(
    region: Mapping[str, Any],
    fraction: float,
) -> float:
    profile = [
        (float(row["u"]), float(row["half_width"]))
        for row in region["width_profile"]
    ]
    u = max(0.0, min(1.0, fraction))
    if u <= profile[0][0]:
        return profile[0][1]
    for (left_u, left_width), (right_u, right_width) in zip(
        profile,
        profile[1:],
    ):
        if u <= right_u:
            local = (u - left_u) / (right_u - left_u)
            return left_width + (right_width - left_width) * local
    return profile[-1][1]


def _wrap_region_stop_index(
    guide: Sequence[Point],
    flower: Mapping[str, Any],
    maximum_span_degrees: float = 175.0,
) -> int:
    center = _point(flower["center"], "R2C flower center")
    rx = float(flower["rx"])
    ry = float(flower["ry"])
    angles = [
        math.atan2(
            (point[1] - center[1]) / ry,
            (point[0] - center[0]) / rx,
        )
        for point in guide
    ]
    unwrapped = [angles[0]]
    for angle in angles[1:]:
        while angle - unwrapped[-1] > math.pi:
            angle -= 2.0 * math.pi
        while angle - unwrapped[-1] < -math.pi:
            angle += 2.0 * math.pi
        unwrapped.append(angle)
    valid = [
        index
        for index in range(1, len(unwrapped))
        if 90.0
        <= math.degrees(
            max(unwrapped[: index + 1]) - min(unwrapped[: index + 1])
        )
        <= maximum_span_degrees
    ]
    if not valid:
        raise GlobalL1FlowError(
            "frozen wrap region has no 90-175 degree connected guide prefix"
        )
    return max(valid)


def _offset_region_guide(
    region: Mapping[str, Any],
    offset_fraction: float,
    *,
    stop_index: int | None = None,
    terminal_point: Point | None = None,
) -> list[Point]:
    full_guide = [
        _point(value, "R2C role region guide")
        for value in region["guide_centerline"]
    ]
    guide = (
        full_guide
        if stop_index is None
        else full_guide[: stop_index + 1]
    )
    if len(guide) < 4:
        raise GlobalL1FlowError("R2C region guide is too short")
    result: list[Point] = []
    for index, point in enumerate(guide):
        before = guide[max(0, index - 1)]
        after = guide[min(len(guide) - 1, index + 1)]
        tangent = _unit(
            _sub(after, before),
            f"R2C region guide tangent {index}",
        )
        normal = (-tangent[1], tangent[0])
        fade = min(
            1.0,
            index / 3.0,
            (len(guide) - 1 - index) / 3.0,
        )
        full_fraction = index / max(1, len(full_guide) - 1)
        offset = (
            offset_fraction
            * _role_region_width(region, full_fraction)
            * fade
        )
        result.append(_add(point, _mul(normal, offset)))
    if terminal_point is not None:
        result.append(terminal_point)
    return result


def _region_path_segments(
    path: Sequence[Point],
    *,
    maximum_knot_gap: int = 4,
    knot_indices: Sequence[int] | None = None,
) -> list[dict[str, list[float]]]:
    if knot_indices is None:
        resolved_knot_indices = list(
            range(0, len(path), maximum_knot_gap)
        )
        if resolved_knot_indices[-1] != len(path) - 1:
            resolved_knot_indices.append(len(path) - 1)
    else:
        resolved_knot_indices = list(knot_indices)
        if (
            not resolved_knot_indices
            or resolved_knot_indices[0] != 0
            or resolved_knot_indices[-1] != len(path) - 1
            or resolved_knot_indices != sorted(set(resolved_knot_indices))
        ):
            raise GlobalL1FlowError("invalid R2C path knot indices")
    segments: list[dict[str, list[float]]] = []
    for left_index, right_index in zip(
        resolved_knot_indices,
        resolved_knot_indices[1:],
    ):
        start = path[left_index]
        end = path[right_index]
        start_before = path[max(0, left_index - 1)]
        start_after = path[min(len(path) - 1, left_index + 1)]
        end_before = path[max(0, right_index - 1)]
        end_after = path[min(len(path) - 1, right_index + 1)]
        start_tangent = _unit(
            _sub(start_after, start_before),
            "R2C start tangent",
        )
        end_tangent = _unit(
            _sub(end_after, end_before),
            "R2C end tangent",
        )
        chord = _distance(start, end)
        segments.append(
            _hermite_segment(
                start,
                end,
                start_tangent,
                end_tangent,
                chord / 3.0,
                chord / 3.0,
            )
        )
    return segments


def _region_l1_candidate(
    *,
    prototype_id: str,
    role: str,
    region: Mapping[str, Any],
    flower: Mapping[str, Any],
    offset_fraction: float,
    candidate_index: int,
) -> dict[str, Any]:
    if role not in {"flower_support", "flower_wrap", "balance"}:
        raise GlobalL1FlowError(f"unsupported R2C role: {role}")
    if role == "flower_support":
        center = _point(flower["center"], "R2C support flower center")
        terminal = (
            center[0],
            center[1] + float(flower["ry"]),
        )
        path = _offset_region_guide(
            region,
            offset_fraction,
            terminal_point=terminal,
        )
        knot_indices = None
    elif role == "flower_wrap":
        full_guide = [
            _point(value, "R2C wrap region guide")
            for value in region["guide_centerline"]
        ]
        stop_index = _wrap_region_stop_index(full_guide, flower)
        path = _offset_region_guide(
            region,
            offset_fraction,
            stop_index=stop_index,
        )
        center = _point(flower["center"], "R2C wrap flower center")
        rx = float(flower["rx"])
        ry = float(flower["ry"])
        engagement_index = next(
            (
                index
                for index, point in enumerate(path[1:], start=1)
                if math.hypot(
                    (point[0] - center[0]) / rx,
                    (point[1] - center[1]) / ry,
                )
                <= 1.80
            ),
            None,
        )
        if engagement_index is None:
            raise GlobalL1FlowError(
                "R2C wrap guide never engages the flower service band"
            )
        knot_indices = [
            0,
            engagement_index,
            *range(engagement_index + 3, len(path), 3),
        ]
        if knot_indices[-1] != len(path) - 1:
            knot_indices.append(len(path) - 1)
    else:
        path = _offset_region_guide(
            region,
            offset_fraction,
        )
        knot_indices = None
    segments = _region_path_segments(path, knot_indices=knot_indices)
    centerline = _sample_segments(segments, samples_per_segment=18)
    flower_service_start_index: int | None = None
    flower_service_centerline: list[Point] | None = None
    if role == "flower_wrap":
        center = _point(flower["center"], "R2C wrap service center")
        rx = float(flower["rx"])
        ry = float(flower["ry"])
        flower_service_start_index = next(
            (
                index
                for index, point in enumerate(centerline)
                if math.hypot(
                    (point[0] - center[0]) / rx,
                    (point[1] - center[1]) / ry,
                )
                <= 1.80
            ),
            None,
        )
        if flower_service_start_index is None:
            raise GlobalL1FlowError(
                "R2C wrap curve never enters its declared flower service phase"
            )
        flower_service_centerline = centerline[
            flower_service_start_index:
        ]
    entry = [float(value) for value in region["entry_s_range"]]
    root_s = 0.5 * (entry[0] + entry[1])
    candidate_id = (
        f"{prototype_id}__{region['service_flower_id']}__{role}"
        f"__region_candidate_{candidate_index}"
    )
    geometry_digest = canonical_digest(segments)
    return {
        "candidate_id": candidate_id,
        "curve_id": candidate_id.replace("__region_candidate_", "__L1_"),
        "slot_id": f"{role}__{region['service_flower_id']}",
        "role": role,
        "semantic_role": role,
        "level": "L1",
        "parent": "backbone",
        "parent_curve_id": None,
        "service_flower_id": str(region["service_flower_id"]),
        "flower_id": str(region["service_flower_id"]),
        "region_id": str(region["region_id"]),
        "source_region_plan_digest": str(region["region_plan_digest"]),
        "region_plan_regenerated_after_curve_generation": False,
        "root_s": round(root_s, 9),
        "root": _round_point(centerline[0]),
        "target": _round_point(centerline[-1]),
        "segments": segments,
        "centerline": [_round_point(point) for point in centerline],
        "flower_service_centerline": (
            [
                _round_point(point)
                for point in flower_service_centerline
            ]
            if flower_service_centerline is not None
            else None
        ),
        "flower_service_start_index": flower_service_start_index,
        "flower_service_phase_policy": (
            "first_preselection_centerline_sample_with_normalized_rho_lte_1_80"
            if role == "flower_wrap"
            else None
        ),
        "root_feature_id": region["source_geometry"].get(
            "origin_feature_id"
        ),
        "root_feature_kind": region["source_geometry"].get(
            "origin_feature_kind"
        ),
        "root_feature_s": region["source_geometry"].get(
            "origin_feature_s"
        ),
        "root_feature_arc_distance": region["source_geometry"].get(
            "origin_feature_arc_distance"
        ),
        "planning_length": round(_polyline_length(centerline), 9),
        "offset_fraction": round(offset_fraction, 9),
        "geometry_digest": geometry_digest,
        "selected": False,
        "generation_policy": {
            "region_guide_consumed": True,
            "variable_width_consumed": True,
            "posthoc_region_fit_used": False,
            "validation_guided_retry_used": False,
            "seed_specific_control_points_used": False,
        },
    }


def _polyline_crossing_count(
    first: Sequence[Sequence[float]],
    second: Sequence[Sequence[float]],
) -> int:
    first_points = [_point(value, "first R2C polyline") for value in first]
    second_points = [_point(value, "second R2C polyline") for value in second]

    def properly_intersects(
        first_start: Point,
        first_end: Point,
        second_start: Point,
        second_end: Point,
    ) -> bool:
        epsilon = 1e-9
        first_delta = _sub(first_end, first_start)
        second_delta = _sub(second_end, second_start)
        denominator = _cross(first_delta, second_delta)
        if abs(denominator) <= epsilon:
            return False
        offset = _sub(second_start, first_start)
        first_t = _cross(offset, second_delta) / denominator
        second_t = _cross(offset, first_delta) / denominator
        return (
            epsilon < first_t < 1.0 - epsilon
            and epsilon < second_t < 1.0 - epsilon
        )

    return sum(
        properly_intersects(
            first_points[left - 1],
            first_points[left],
            second_points[right - 1],
            second_points[right],
        )
        for left in range(1, len(first_points))
        for right in range(1, len(second_points))
    )


def _R2C_candidate_hard_rejections(
    candidate: Mapping[str, Any],
    analysis: Mapping[str, Any],
    flower: Mapping[str, Any],
) -> list[str]:
    points = [
        _point(value, "R2C candidate centerline")
        for value in candidate["centerline"]
    ]
    backbone = [
        _point(row["point"], "R2C backbone")
        for row in analysis["backbone"]["samples"]
    ]
    reasons: list[str] = []
    if _polyline_crossing_count(
        [_round_point(point) for point in points[1:]],
        [_round_point(point) for point in backbone],
    ):
        reasons.append("non_root_backbone_crossing")
    if _polyline_crossing_count(
        [_round_point(point) for point in points],
        [_round_point(point) for point in points],
    ):
        reasons.append("unit_self_crossing")
    center = _point(flower["center"], "R2C legality flower center")
    rx = float(flower["rx"])
    ry = float(flower["ry"])
    intrusion_points = (
        points[:-1]
        if candidate["role"] == "flower_support"
        else points
    )
    if any(
        math.hypot(
            (point[0] - center[0]) / rx,
            (point[1] - center[1]) / ry,
        )
        < 1.0 - 1e-9
        for point in intrusion_points
    ):
        reasons.append("flower_core_intrusion")
    x_min, y_min, x_max, y_max = [
        float(value)
        for value in analysis["coordinate_system"]["canvas_bounds"]
    ]
    if any(
        not (
            x_min <= point[0] <= x_max
            and y_min <= point[1] <= y_max
        )
        for point in points
    ):
        reasons.append("out_of_bounds")
    return reasons


def generate_sw1_region_l1_pair(
    analysis: Mapping[str, Any],
    region_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate and solve the frozen two-role R2C L1 pair exactly once."""

    validate_role_region_plan(region_plan)
    if analysis.get("prototype_id") != "proto_sw_1_1":
        raise GlobalL1FlowError("R2C frozen instance is proto_sw_1_1")
    if region_plan.get("source_analysis_digest") != analysis.get(
        "analysis_digest"
    ):
        raise GlobalL1FlowError("R2C analysis/region plan digest mismatch")
    flower_id = str(region_plan["service_flower_id"])
    flower = next(
        row
        for row in analysis["flowers"]
        if row["flower_id"] == flower_id
    )
    regions = {str(row["role"]): row for row in region_plan["regions"]}
    support_candidates = [
        _region_l1_candidate(
            prototype_id="proto_sw_1_1",
            role="flower_support",
            region=regions["support_region"],
            flower=flower,
            offset_fraction=offset,
            candidate_index=index,
        )
        for index, offset in enumerate((0.40, 0.60, 0.80), start=1)
    ]
    wrap_candidates = [
        _region_l1_candidate(
            prototype_id="proto_sw_1_1",
            role="flower_wrap",
            region=regions["wrap_region"],
            flower=flower,
            offset_fraction=offset,
            candidate_index=index,
        )
        for index, offset in enumerate((-0.80, -0.60, -0.40), start=1)
    ]
    for candidate in [*support_candidates, *wrap_candidates]:
        candidate["hard_rejections"] = _R2C_candidate_hard_rejections(
            candidate,
            analysis,
            flower,
        )
    legal_pairs: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for support in support_candidates:
        for wrap in wrap_candidates:
            if support["hard_rejections"] or wrap["hard_rejections"]:
                continue
            crossing_count = _polyline_crossing_count(
                support["centerline"],
                wrap["centerline"],
            )
            if crossing_count:
                continue
            score = (
                abs(float(support["offset_fraction"]) - 0.60)
                + abs(float(wrap["offset_fraction"]) + 0.60)
                + 0.01
                * (
                    float(support["planning_length"])
                    + float(wrap["planning_length"])
                )
            )
            legal_pairs.append((score, support, wrap))
    if not legal_pairs:
        raise GlobalL1FlowError(
            "R2C frozen support/wrap regions have no non-crossing L1 pair"
        )
    _, selected_support, selected_wrap = min(
        legal_pairs,
        key=lambda row: (
            row[0],
            row[1]["candidate_id"],
            row[2]["candidate_id"],
        ),
    )
    selected_ids = {
        str(selected_support["candidate_id"]),
        str(selected_wrap["candidate_id"]),
    }
    all_candidates = [*support_candidates, *wrap_candidates]
    for candidate in all_candidates:
        candidate["selected"] = str(candidate["candidate_id"]) in selected_ids
    selected = [selected_support, selected_wrap]
    return {
        "schema": "dynamic_branch_R2C_sw1_region_l1_pair_v2",
        "prototype_id": "proto_sw_1_1",
        "service_flower_id": flower_id,
        "source_region_plan_digest": str(
            region_plan["region_plan_digest"]
        ),
        "region_plan_regenerated_after_curve_generation": False,
        "stage_scope": {
            "selected_L1_count": 2,
            "support_L1_count": 1,
            "wrap_L1_count": 1,
            "L2_count": 0,
            "L3_count": 0,
        },
        "candidate_count_per_region": {
            str(regions["support_region"]["region_id"]): len(
                support_candidates
            ),
            str(regions["wrap_region"]["region_id"]): len(wrap_candidates),
        },
        "candidate_inventory": all_candidates,
        "selected_curves": selected,
        "solver": {
            "mode": "single_forward_region_pair_solve",
            "pair_count": len(support_candidates) * len(wrap_candidates),
            "legal_pair_count": len(legal_pairs),
            "validation_guided_retry_used": False,
            "best_of_n_render_selection_used": False,
        },
        "pair_digest": canonical_digest(
            {
                "source_region_plan_digest": region_plan[
                    "region_plan_digest"
                ],
                "selected_geometry_digests": [
                    row["geometry_digest"] for row in selected
                ],
                "candidate_geometry_digests": [
                    row["geometry_digest"] for row in all_candidates
                ],
            }
        ),
    }


def _offset_remote_support_guide(
    region: Mapping[str, Any],
    offset_fraction: float,
    terminal_point: Point,
) -> list[Point]:
    guide = [
        _point(value, "R2D remote-support guide")
        for value in region["guide_centerline"]
    ]
    if len(guide) < 12:
        raise GlobalL1FlowError("R2D remote-support guide is too short")
    result: list[Point] = []
    for index, point in enumerate(guide):
        before = guide[max(0, index - 1)]
        after = guide[min(len(guide) - 1, index + 1)]
        tangent = _unit(
            _sub(after, before),
            f"R2D remote-support guide tangent {index}",
        )
        normal = (-tangent[1], tangent[0])
        entry_fade = max(0.0, min(1.0, (index - 3) / 4.0))
        exit_fade = max(
            0.0,
            min(1.0, (len(guide) - 1 - index) / 4.0),
        )
        offset = (
            offset_fraction
            * _role_region_width(
                region,
                index / max(1, len(guide) - 1),
            )
            * min(entry_fade, exit_fade)
        )
        result.append(_add(point, _mul(normal, offset)))
    result[-1] = terminal_point
    return result


def _remote_support_candidate(
    *,
    analysis: Mapping[str, Any],
    region: Mapping[str, Any],
    flower: Mapping[str, Any],
    offset_fraction: float,
    candidate_index: int,
) -> dict[str, Any]:
    center = _point(flower["center"], "R2D flower center")
    contact = (center[0], center[1] + float(flower["ry"]))
    path = _offset_remote_support_guide(
        region,
        offset_fraction,
        contact,
    )
    segments = _region_path_segments(path, maximum_knot_gap=4)
    centerline = _sample_segments(segments, samples_per_segment=18)
    entry = [float(value) for value in region["entry_s_range"]]
    root_s = 0.5 * (entry[0] + entry[1])
    candidate_id = (
        "proto_sw_3_1__flower_1__remote_support"
        f"__region_candidate_{candidate_index}"
    )
    return {
        "candidate_id": candidate_id,
        "curve_id": (
            "support_1"
            if candidate_index == 2
            else f"support_1_candidate_{candidate_index}"
        ),
        "slot_id": "remote_flower_support__flower_1",
        "role": "remote_flower_support",
        "semantic_role": "remote_flower_support",
        "level": "L1",
        "parent": "backbone",
        "parent_curve_id": None,
        "service_flower_id": "flower_1",
        "flower_id": "flower_1",
        "region_id": str(region["region_id"]),
        "source_region_plan_digest": str(region["region_plan_digest"]),
        "region_plan_regenerated_after_curve_generation": False,
        "root_s": round(root_s, 9),
        "root": _round_point(centerline[0]),
        "target": _round_point(centerline[-1]),
        "segments": segments,
        "centerline": [_round_point(point) for point in centerline],
        "planning_length": round(_polyline_length(centerline), 9),
        "offset_fraction": round(offset_fraction, 9),
        "geometry_digest": canonical_digest(segments),
        "remote_mount_arc_distance": float(
            region["source_geometry"]["remote_mount_arc_distance"]
        ),
        "below_flower_waypoint_margin": float(
            region["source_geometry"]["below_flower_waypoint_margin"]
        ),
        "selected": False,
        "generation_policy": {
            "region_guide_consumed": True,
            "variable_width_consumed": True,
            "region_created_before_curve": True,
            "posthoc_region_fit_used": False,
            "validation_guided_retry_used": False,
            "seed_specific_control_points_used": False,
            "fixed_two_segment_template_used": False,
        },
    }


def generate_sw3_remote_support_l1(
    analysis: Mapping[str, Any],
    region_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate one R2D remote-support L1 from its frozen soft channel."""

    validate_sw3_remote_support_region_plan(region_plan)
    if analysis.get("prototype_id") != "proto_sw_3_1":
        raise GlobalL1FlowError("R2D frozen instance is proto_sw_3_1")
    if region_plan.get("source_analysis_digest") != analysis.get(
        "analysis_digest"
    ):
        raise GlobalL1FlowError("R2D analysis/region plan digest mismatch")
    flower = next(
        row
        for row in analysis["flowers"]
        if row["flower_id"] == "flower_1"
    )
    region = next(
        row
        for row in region_plan["regions"]
        if row["role"] == "remote_support_region"
    )
    candidates = [
        _remote_support_candidate(
            analysis=analysis,
            region=region,
            flower=flower,
            offset_fraction=offset,
            candidate_index=index,
        )
        for index, offset in enumerate((-0.65, 0.0, 0.65), start=1)
    ]
    for candidate in candidates:
        candidate["hard_rejections"] = _R2C_candidate_hard_rejections(
            candidate,
            analysis,
            flower,
        )
    legal = [
        candidate
        for candidate in candidates
        if not candidate["hard_rejections"]
    ]
    if not legal:
        raise GlobalL1FlowError(
            "R2D remote-support region has no legal L1 candidate"
        )
    selected = min(
        legal,
        key=lambda row: (
            abs(float(row["offset_fraction"])),
            str(row["candidate_id"]),
        ),
    )
    selected["curve_id"] = "support_1"
    selected["selected"] = True
    return {
        "schema": "dynamic_branch_R2D_remote_support_l1_v2",
        "prototype_id": "proto_sw_3_1",
        "seed": 4101,
        "service_flower_id": "flower_1",
        "source_region_plan_digest": str(
            region_plan["region_plan_digest"]
        ),
        "region_plan_regenerated_after_curve_generation": False,
        "stage_scope": {
            "selected_L1_count": 1,
            "remote_support_L1_count": 1,
            "wrap_curve_count": 0,
            "L2_count": 0,
            "L3_count": 0,
        },
        "candidate_inventory": candidates,
        "selected_remote_support": selected,
        "solver": {
            "mode": "single_forward_remote_region_selection",
            "candidate_count": len(candidates),
            "legal_candidate_count": len(legal),
            "validation_guided_retry_used": False,
            "best_of_n_render_selection_used": False,
        },
        "selection_digest": canonical_digest(
            {
                "source_region_plan_digest": region_plan[
                    "region_plan_digest"
                ],
                "candidate_geometry_digests": [
                    row["geometry_digest"] for row in candidates
                ],
                "selected_geometry_digest": selected[
                    "geometry_digest"
                ],
            }
        ),
    }


def _generate_region_balance_l1(
    *,
    analysis: Mapping[str, Any],
    region_plan: Mapping[str, Any],
    core_curves: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Generate a light L1 counterweight after core curves occupy the group."""

    flower_id = str(region_plan["service_flower_id"])
    flower = next(
        row
        for row in analysis["flowers"]
        if row["flower_id"] == flower_id
    )
    region = next(
        row
        for row in region_plan["regions"]
        if row["role"] == "balance_region"
    )
    candidates = [
        _region_l1_candidate(
            prototype_id=str(analysis["prototype_id"]),
            role="balance",
            region=region,
            flower=flower,
            offset_fraction=offset,
            candidate_index=index,
        )
        for index, offset in enumerate((-0.52, 0.0, 0.52), start=1)
    ]
    backbone = [
        row["point"] for row in analysis["backbone"]["samples"]
    ]
    for candidate in candidates:
        candidate["flower_id"] = None
        candidate["slot_id"] = f"balance__{flower_id}"
        candidate["curve_id"] = (
            f"{analysis['prototype_id']}__{flower_id}__balance"
            f"__candidate_{candidate['candidate_id'].rsplit('_', 1)[-1]}"
        )
        rejections: list[str] = []
        if _polyline_crossing_count(
            candidate["centerline"],
            candidate["centerline"],
        ):
            rejections.append("self_intersection")
        if _polyline_crossing_count(
            candidate["centerline"][1:],
            backbone,
        ):
            rejections.append("backbone_intersection")
        if any(
            _polyline_crossing_count(
                candidate["centerline"],
                core["centerline"],
            )
            for core in core_curves
        ):
            rejections.append("core_branch_intersection")
        candidate["hard_rejections"] = rejections
        candidate["generation_policy"].update(
            {
                "core_region_occupancy_consumed_first": True,
                "largest_remaining_sector_consumed": True,
                "independent_role_random_generation_used": False,
            }
        )
    legal = [
        candidate
        for candidate in candidates
        if not candidate["hard_rejections"]
    ]
    if not legal:
        raise GlobalL1FlowError(
            f"{analysis['prototype_id']} R3 balance region has no "
            "non-intersecting candidate"
        )
    selected = min(
        legal,
        key=lambda row: (
            abs(float(row["offset_fraction"])),
            str(row["candidate_id"]),
        ),
    )
    selected["curve_id"] = "balance_1"
    selected["selected"] = True
    return selected, candidates


def generate_sw1_region_l1_group(
    analysis: Mapping[str, Any],
    region_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate the SW1 support, wrap, then residual-sector balance group."""

    validate_role_region_plan(region_plan)
    pair = generate_sw1_region_l1_pair(analysis, region_plan)
    core_curves = list(pair["selected_curves"])
    balance, balance_candidates = _generate_region_balance_l1(
        analysis=analysis,
        region_plan=region_plan,
        core_curves=core_curves,
    )
    selected = [*core_curves, balance]
    return {
        "schema": "dynamic_branch_R3_sw1_flower_group_v2",
        "prototype_id": str(analysis["prototype_id"]),
        "family_id": "SW1",
        "service_flower_id": str(region_plan["service_flower_id"]),
        "source_region_plan_digest": str(
            region_plan["region_plan_digest"]
        ),
        "generation_order": [
            "flower_support",
            "flower_wrap",
            "compute_core_region_occupancy",
            "compute_largest_remaining_sector",
            "balance",
        ],
        "selected_curves": selected,
        "candidate_inventory": [
            *pair["candidate_inventory"],
            *balance_candidates,
        ],
        "stage_scope": {
            "selected_L1_count": 3,
            "support_L1_count": 1,
            "wrap_L1_count": 1,
            "balance_L1_count": 1,
            "ordinary_L1_count": 0,
            "L2_count": 0,
            "L3_count": 0,
        },
        "selection_digest": canonical_digest(
            {
                "source_region_plan_digest": region_plan[
                    "region_plan_digest"
                ],
                "selected_geometry_digests": [
                    row["geometry_digest"] for row in selected
                ],
            }
        ),
    }


def generate_sw3_region_l1_group(
    analysis: Mapping[str, Any],
    region_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate the SW3 remote support, then residual-sector balance group."""

    validate_sw3_group_region_plan(region_plan)
    remote_result = generate_sw3_remote_support_l1(
        analysis,
        region_plan,
    )
    remote = remote_result["selected_remote_support"]
    balance, balance_candidates = _generate_region_balance_l1(
        analysis=analysis,
        region_plan=region_plan,
        core_curves=[remote],
    )
    selected = [remote, balance]
    return {
        "schema": "dynamic_branch_R3_sw3_flower_group_v2",
        "prototype_id": str(analysis["prototype_id"]),
        "family_id": "SW3",
        "service_flower_id": str(region_plan["service_flower_id"]),
        "source_region_plan_digest": str(
            region_plan["region_plan_digest"]
        ),
        "generation_order": [
            "remote_flower_support",
            "compute_core_region_occupancy",
            "compute_largest_remaining_sector",
            "balance",
        ],
        "selected_curves": [remote, balance],
        "candidate_inventory": [
            *remote_result["candidate_inventory"],
            *balance_candidates,
        ],
        "stage_scope": {
            "selected_L1_count": 2,
            "remote_support_L1_count": 1,
            "balance_L1_count": 1,
            "forced_wrap_count": 0,
            "L2_count": 0,
            "L3_count": 0,
        },
        "selection_digest": canonical_digest(
            {
                "source_region_plan_digest": region_plan[
                    "region_plan_digest"
                ],
                "selected_geometry_digests": [
                    remote["geometry_digest"],
                    balance["geometry_digest"],
                ],
            }
        ),
    }


def generate_global_l1_flow_plan(
    strict_p0: Mapping[str, Any],
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate one formal L1-only layout and its complete candidate inventory."""

    prototype_id, family_id = _validate_inputs(
        strict_p0,
        analysis,
        morphology,
        prior,
        contract,
        seed,
    )
    motion_policy = _motion_policy(contract)
    latents = _global_latents(prototype_id, seed)
    count_derivation = _derive_lane_count(prototype_id, analysis, morphology, prior)
    prototype_topology = materialize_prototype_topology(
        prototype_id,
        [row["flower_id"] for row in analysis["flowers"]],
    )
    role_region_plan = None
    region_driven_sw1_pair = None
    remote_support_region_plan = None
    region_driven_sw3_support = None
    if prototype_id == "proto_sw_1_1":
        role_region_plan = build_sw1_role_region_plan(
            analysis,
            prototype_topology,
            str(analysis["flowers"][0]["flower_id"]),
        )
        validate_role_region_plan(role_region_plan)
        region_driven_sw1_pair = generate_sw1_region_l1_pair(
            analysis,
            role_region_plan,
        )
    elif prototype_id == "proto_sw_3_1":
        remote_support_region_plan = (
            build_sw3_remote_support_region_plan(
                analysis,
                prototype_topology,
                str(analysis["flowers"][0]["flower_id"]),
            )
        )
        validate_sw3_remote_support_region_plan(
            remote_support_region_plan
        )
        region_driven_sw3_support = generate_sw3_remote_support_l1(
            analysis,
            remote_support_region_plan,
        )
    slots = _make_slots(analysis, morphology, count_derivation, latents, seed)
    pools: dict[str, list[dict[str, Any]]] = {}
    inventory_rows: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    backbone = _backbone_points(analysis)
    backbone_collision = _prepare_backbone_collision_geometry(
        backbone,
        (
            float(motion_policy["backbone_crossing_spatial_bin_width"])
            if motion_policy["mode"] == "tangent_led_v1"
            else 0.05
        ),
    )

    for slot in slots:
        candidates: list[dict[str, Any]] = []
        if slot.role == "flower_support":
            candidates.extend(
                _sw1_support_candidates(
                    slot,
                    analysis,
                    latents,
                    motion_policy,
                )
            )
        elif slot.role == "terminal_flower_support":
            candidates.extend(
                _sw3_support_candidates(
                    slot,
                    analysis,
                    latents,
                    motion_policy,
                )
            )
        else:
            candidates.extend(
                _ordinary_candidates(
                    slot,
                    analysis,
                    prior,
                    latents,
                    motion_policy,
                )
            )
        candidates.extend(
            _fixed_warp_candidates(
                slot,
                analysis,
                prior,
                seed,
                motion_policy,
            )
        )

        feasible: list[dict[str, Any]] = []
        for candidate in candidates:
            reasons = _candidate_rejections(
                candidate,
                analysis,
                family_id,
                prior,
                motion_policy,
                backbone,
                backbone_collision,
            )
            inventory_row = dict(candidate)
            inventory_row["hard_rejections"] = reasons
            inventory_rows.append(inventory_row)
            rejection_counts.update(reasons)
            if not reasons:
                feasible.append(candidate)
        if not feasible:
            raise GlobalL1FlowError(
                f"{prototype_id} seed {seed} slot {slot.slot_id} has no feasible candidates"
            )
        pools[slot.slot_id] = feasible

    selected, solver = _solve(slots, pools, prior, motion_policy)
    selected_ids = {str(row["candidate_id"]) for row in selected}
    for row in inventory_rows:
        row["selected"] = str(row["candidate_id"]) in selected_ids

    role_counts = Counter(str(row["role"]) for row in selected)
    if sum(role_counts.values()) != count_derivation["selected_l1_count"]:
        raise GlobalL1FlowError("selected L1 count does not match count derivation")
    if role_counts["flower_support"] + role_counts["terminal_flower_support"] != count_derivation[
        "required_support_count"
    ]:
        raise GlobalL1FlowError("selected support count does not match morphology requirement")

    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": f"{prototype_id}__seed_{seed}__global_l1_flow_v1",
        "prototype_id": prototype_id,
        "family_id": family_id,
        "seed": seed,
        "geometry_semantics": "planning_flow_lane_not_final_branch_curve",
        "stage_scope": {
            "l1_only": True,
            "l2_present": False,
            "l3_present": False,
            "terminal_content_present": False,
            "old_stage3_layout_consumed": False,
            "old_stage4_geometry_consumed": False,
        },
        "global_latents": latents,
        "motion_policy": str(motion_policy["mode"]),
        "prototype_topology": prototype_topology,
        "role_region_plan": role_region_plan,
        "region_driven_sw1_pair": region_driven_sw1_pair,
        "remote_support_region_plan": remote_support_region_plan,
        "region_driven_sw3_support": region_driven_sw3_support,
        "count_derivation": count_derivation,
        "slots": [
            {
                "slot_id": slot.slot_id,
                "role": slot.role,
                "flower_id": slot.flower_id,
                "preferred_s": round(slot.preferred_s, 9),
                "preferred_vertical_side": slot.preferred_vertical_side,
            }
            for slot in slots
        ],
        "lanes": selected,
        "role_counts": dict(sorted(role_counts.items())),
        "solver": solver,
        "diagnostics": {
            "hard_issue_count": 0,
            "lane_count": len(selected),
            "candidate_count": len(inventory_rows),
            "feasible_candidate_count": sum(len(rows) for rows in pools.values()),
            "rejected_candidate_count": sum(
                1 for row in inventory_rows if row["hard_rejections"]
            ),
            "rejection_counts": dict(sorted(rejection_counts.items())),
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "silent_fallback_used": False,
        },
        "review": {
            "status": "l1_flow_pending_visual_review",
            "numeric_checks_cannot_auto_approve_visual_gate": True,
            "criteria": [
                "global_direction_position_and_distance",
                "prototype_specific_flower_branch_relation",
                "immediate_outward_departure",
                "root_and_target_spacing",
                "white_space_distribution",
                "non_crossing_periodic_flow",
                "fixed_visual_capability_not_degraded",
            ],
        },
        "input_digests": {
            "strict_p0_digest": analysis["strict_p0_digest"],
            "analysis_digest": analysis["analysis_digest"],
            "morphology_digest": morphology["morphology_digest"],
            "fixed_visual_prior_digest": prior["prior_digest"],
        },
    }
    plan["plan_digest"] = canonical_digest(plan)
    inventory: dict[str, Any] = {
        "schema": "dynamic_branch_global_l1_candidate_inventory_v1",
        "prototype_id": prototype_id,
        "seed": seed,
        "single_forward_global_solve": True,
        "experimental_variants": False,
        "candidate_count": len(inventory_rows),
        "selected_candidate_ids": sorted(selected_ids),
        "candidates": inventory_rows,
    }
    inventory["inventory_digest"] = canonical_digest(inventory)
    return plan, inventory


def attach_loop_growth_guide(
    lane: Mapping[str, Any],
    analysis: Mapping[str, Any],
    guide_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach support and flower-wrap guide channels to one existing L1 lane."""

    if lane.get("role") != "terminal_flower_support":
        raise GlobalL1FlowError(
            "loop-growth guide requires terminal_flower_support"
        )
    flower_id = str(lane.get("flower_id") or "")
    flower = _flower_by_id(analysis, flower_id)
    region = derive_loop_growth_region(
        analysis,
        flower_id,
        entry_distance_range=guide_contract["entry_distance_range"],
        boundary_sample_count=int(
            guide_contract["analysis_boundary_sample_count"]
        ),
        radial_probe_step=float(guide_contract["radial_probe_step"]),
        maximum_outer_rho=float(
            guide_contract["maximum_region_outer_rho"]
        ),
        minimum_backbone_clearance=float(
            guide_contract["minimum_region_backbone_clearance"]
        ),
        canvas_margin=float(guide_contract["region_canvas_margin"]),
    )
    support_points = [
        _point(point, "lane.centerline")
        for point in lane["centerline"]
    ]
    support_tangents = _polyline_tangents(support_points)
    support_width_start = float(
        guide_contract["support_half_width_start"]
    )
    support_width_end = float(
        guide_contract["support_half_width_end"]
    )
    support_width_profile = [
        {
            "fraction": round(index / 4.0, 9),
            "half_width": round(
                support_width_start
                + (support_width_end - support_width_start)
                * index
                / 4.0,
                9,
            ),
        }
        for index in range(5)
    ]

    mount_fraction = float(guide_contract["wrap_mount_fraction"])
    mount_root, _ = _point_and_tangent_at_arc_fraction(
        support_points,
        mount_fraction,
    )
    center = _flower_center_near(flower, mount_root[0])
    rx = float(flower["rx"])
    ry = float(flower["ry"])
    region_profile = list(region["available_width_profile"])
    region_count = len(region_profile)

    def region_row(angle_degrees: float) -> dict[str, float]:
        wrapped = angle_degrees % 360.0
        scaled = wrapped * region_count / 360.0
        left_index = int(math.floor(scaled)) % region_count
        right_index = (left_index + 1) % region_count
        local = scaled - math.floor(scaled)
        left = region_profile[left_index]
        right = region_profile[right_index]
        return {
            key: float(left[key])
            + (float(right[key]) - float(left[key])) * local
            for key in ("inner_rho", "maximum_outer_rho")
        }

    depth_profile = [
        (
            float(row["fraction"]),
            float(row["region_depth_fraction"]),
        )
        for row in guide_contract["region_depth_fraction_profile"]
    ]

    def depth_fraction(fraction: float) -> float:
        if fraction <= depth_profile[0][0]:
            return depth_profile[0][1]
        for (left_f, left_v), (right_f, right_v) in zip(
            depth_profile,
            depth_profile[1:],
        ):
            if left_f <= fraction <= right_f:
                local = (fraction - left_f) / (right_f - left_f)
                return left_v + (right_v - left_v) * local
        return depth_profile[-1][1]

    normalized_mount = (
        (mount_root[0] - center[0]) / rx,
        (mount_root[1] - center[1]) / ry,
    )
    start_angle_degrees = math.degrees(
        math.atan2(normalized_mount[1], normalized_mount[0])
    ) % 360.0
    wrap_span_degrees = float(guide_contract["wrap_span_deg"])
    guide_sample_count = int(guide_contract["region_guide_sample_count"])
    minimum_region_depth = float(
        guide_contract["minimum_region_radial_depth"]
    )
    direction_rows: list[dict[str, float]] = []
    for direction in (-1, 1):
        depths: list[float] = []
        for index in range(1, guide_sample_count + 1):
            fraction = index / guide_sample_count
            row = region_row(
                start_angle_degrees
                + direction * wrap_span_degrees * fraction
            )
            depths.append(
                row["maximum_outer_rho"] - row["inner_rho"]
            )
        direction_rows.append(
            {
                "direction": float(direction),
                "minimum_depth": min(depths),
                "mean_depth": sum(depths) / len(depths),
                "capacity_score": (
                    min(depths) * 1.5
                    + sum(depths) / len(depths)
                ),
            }
        )
    feasible_directions = [
        row
        for row in direction_rows
        if row["minimum_depth"] >= minimum_region_depth
    ]
    if not feasible_directions:
        raise GlobalL1FlowError(
            "flower wrap has no connected growth-region direction"
        )
    selected_direction = max(
        feasible_directions,
        key=lambda row: (
            row["capacity_score"],
            row["mean_depth"],
            row["direction"],
        ),
    )
    progress_sign = int(selected_direction["direction"])
    maximum_center_rho = float(
        guide_contract["maximum_guide_center_rho"]
    )
    minimum_center_rho = float(
        guide_contract["minimum_guide_center_rho"]
    )
    envelope_outer_rho = float(
        guide_contract["maximum_region_envelope_rho"]
    )
    wrap_points: list[Point] = [mount_root]
    wrap_rhos: list[float] = [
        math.hypot(normalized_mount[0], normalized_mount[1])
    ]
    region_inner_points: list[Point] = []
    region_outer_points: list[Point] = []
    region_capacity_trace: list[dict[str, float]] = []
    for index in range(guide_sample_count + 1):
        fraction = index / guide_sample_count
        angle_degrees = (
            start_angle_degrees
            + progress_sign * wrap_span_degrees * fraction
        )
        angle = math.radians(angle_degrees)
        row = region_row(angle_degrees)
        inner_rho = row["inner_rho"]
        outer_rho = min(
            row["maximum_outer_rho"],
            envelope_outer_rho,
        )
        region_inner_points.append(
            (
                center[0] + inner_rho * rx * math.cos(angle),
                center[1] + inner_rho * ry * math.sin(angle),
            )
        )
        region_outer_points.append(
            (
                center[0] + outer_rho * rx * math.cos(angle),
                center[1] + outer_rho * ry * math.sin(angle),
            )
        )
        if index == 0:
            center_rho = wrap_rhos[0]
        else:
            center_rho = inner_rho + depth_fraction(fraction) * max(
                0.0,
                min(row["maximum_outer_rho"], maximum_center_rho)
                - inner_rho,
            )
            center_rho = max(
                minimum_center_rho,
                min(center_rho, row["maximum_outer_rho"]),
            )
            wrap_points.append(
                (
                    center[0] + center_rho * rx * math.cos(angle),
                    center[1] + center_rho * ry * math.sin(angle),
                )
            )
            wrap_rhos.append(center_rho)
        region_capacity_trace.append(
            {
                "fraction": round(fraction, 9),
                "angle_degrees": round(angle_degrees, 9),
                "inner_rho": round(inner_rho, 9),
                "maximum_outer_rho": round(
                    row["maximum_outer_rho"],
                    9,
                ),
                "guide_center_rho": round(center_rho, 9),
                "region_depth_fraction": round(
                    depth_fraction(fraction),
                    9,
                ),
            }
        )
    wrap_tangents = _polyline_tangents(wrap_points)
    wrap_width_min = float(guide_contract["wrap_half_width_min"])
    wrap_width_max = float(guide_contract["wrap_half_width_max"])
    region_width_fraction = float(
        guide_contract["region_channel_width_fraction"]
    )
    wrap_width_profile = []
    for index, trace in enumerate(region_capacity_trace):
        radial_depth = (
            trace["maximum_outer_rho"] - trace["inner_rho"]
        ) * min(rx, ry)
        wrap_width_profile.append(
            {
                "fraction": round(index / guide_sample_count, 9),
                "half_width": round(
                    max(
                        wrap_width_min,
                        min(
                            wrap_width_max,
                            radial_depth * region_width_fraction,
                        ),
                    ),
                    9,
                ),
            }
        )
    guided = dict(lane)
    guided.update(
        {
            "service_flower_id": flower_id,
            "target_relation": (
                "remote_mount_below_flower_to_underside"
            ),
            "guide_centerline": [
                _round_point(point) for point in support_points
            ],
            "guide_tangents": [
                _round_point(tangent) for tangent in support_tangents
            ],
            "width_profile": support_width_profile,
            "exit_direction": _round_point(support_tangents[-1]),
            "guide_channel": {
                "schema": "dynamic_branch_role_guide_channel_v1",
                "semantic_role": "terminal_flower_support",
                "service_flower_id": flower_id,
                "guide_centerline": [
                    _round_point(point) for point in support_points
                ],
                "guide_tangents": [
                    _round_point(tangent)
                    for tangent in support_tangents
                ],
                "width_profile": support_width_profile,
                "exit_direction": _round_point(
                    support_tangents[-1]
                ),
            },
            "flower_wrap_channel": {
                "schema": "dynamic_branch_role_guide_channel_v1",
                "semantic_role": "flower_wrap",
                "service_flower_id": flower_id,
                "target_relation": (
                    "enter_wrap_region_then_swing_outward_and_return_guard"
                ),
                "mount_fraction": round(mount_fraction, 9),
                "guide_centerline": [
                    _round_point(point) for point in wrap_points
                ],
                "guide_tangents": [
                    _round_point(tangent)
                    for tangent in wrap_tangents
                ],
                "width_profile": wrap_width_profile,
                "exit_direction": _round_point(wrap_tangents[-1]),
                "wrap_start_angle_deg": round(
                    start_angle_degrees,
                    9,
                ),
                "wrap_span_deg": round(wrap_span_degrees, 9),
                "wrap_direction": int(progress_sign),
                "wrap_rho_profile": [
                    round(value, 9) for value in wrap_rhos
                ],
                "region_envelope": {
                    "inner_boundary": [
                        _round_point(point)
                        for point in region_inner_points
                    ],
                    "outer_boundary": [
                        _round_point(point)
                        for point in region_outer_points
                    ],
                },
                "region_capacity_trace": region_capacity_trace,
                "direction_candidates": direction_rows,
                "selected_region_capacity_score": round(
                    selected_direction["capacity_score"],
                    9,
                ),
                "path_construction": (
                    "non_equidistant_region_centerline"
                ),
            },
            "loop_growth_region": region,
        }
    )
    guide_source = {
        key: guided[key]
        for key in (
            "service_flower_id",
            "target_relation",
            "guide_centerline",
            "guide_tangents",
            "width_profile",
            "exit_direction",
            "flower_wrap_channel",
            "loop_growth_region",
        )
    }
    guided["guide_digest"] = canonical_digest(guide_source)
    return guided


def validate_global_l1_flow_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") != SCHEMA:
        raise GlobalL1FlowError("global L1 flow plan schema mismatch")
    digest = plan.get("plan_digest")
    if not isinstance(digest, str):
        raise GlobalL1FlowError("global L1 flow plan digest is missing")
    payload = dict(plan)
    payload.pop("plan_digest")
    if canonical_digest(payload) != digest:
        raise GlobalL1FlowError("global L1 flow plan digest mismatch")
    if plan["stage_scope"] != {
        "l1_only": True,
        "l2_present": False,
        "l3_present": False,
        "terminal_content_present": False,
        "old_stage3_layout_consumed": False,
        "old_stage4_geometry_consumed": False,
    }:
        raise GlobalL1FlowError("global L1 flow stage scope mismatch")
    if plan["diagnostics"]["hard_issue_count"] != 0:
        raise GlobalL1FlowError("global L1 flow plan contains hard issues")
    if plan["review"]["status"] != "l1_flow_pending_visual_review":
        raise GlobalL1FlowError("global L1 flow plan has an invalid review state")
