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
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from fixed_visual_prior import canonical_digest, validate_fixed_visual_prior


SCHEMA = "dynamic_branch_global_l1_flow_plan_v1"
SCHEMA_V2 = "dynamic_branch_global_l1_flow_plan_v2"
CONTRACT_SCHEMA = "dynamic_branch_stage3b_l1_flow_contract_v1"
CONTRACT_SCHEMA_V2 = "dynamic_branch_stage3b_l1_flow_contract_v2"
FEEDBACK_SCHEMA = "dynamic_branch_edit_feedback_prior_v1"
CURVE_GEOMETRY_PRIOR_SCHEMA = "dynamic_branch_editor_curve_geometry_prior_v2"
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


def _feedback_mode(contract: Mapping[str, Any]) -> bool:
    return contract.get("schema") == CONTRACT_SCHEMA_V2


def _feedback_profile(
    feedback_prior: Mapping[str, Any],
    prototype_id: str,
) -> dict[str, Any]:
    if feedback_prior.get("schema") != FEEDBACK_SCHEMA:
        raise GlobalL1FlowError("edit feedback prior schema mismatch")
    policy = feedback_prior.get("stage3b_policy")
    profiles = feedback_prior.get("prototype_profiles")
    if not isinstance(policy, Mapping) or not isinstance(profiles, Mapping):
        raise GlobalL1FlowError("edit feedback prior is incomplete")
    prototype = profiles.get(prototype_id)
    if not isinstance(prototype, Mapping):
        raise GlobalL1FlowError(
            f"edit feedback prior has no profile for {prototype_id}"
        )
    return {**dict(policy), **dict(prototype)}


def _curve_geometry_profile(
    curve_geometry_prior: Mapping[str, Any],
    prototype_id: str,
) -> Mapping[str, Any]:
    if curve_geometry_prior.get("schema") != CURVE_GEOMETRY_PRIOR_SCHEMA:
        raise GlobalL1FlowError("editor curve geometry prior schema mismatch")
    profiles = curve_geometry_prior.get("profiles")
    if not isinstance(profiles, Mapping):
        raise GlobalL1FlowError("editor curve geometry prior has no profiles")
    profile = profiles.get(prototype_id) or profiles.get("global")
    if not isinstance(profile, Mapping):
        raise GlobalL1FlowError(
            f"editor curve geometry prior has no profile for {prototype_id}"
        )
    if int(profile.get("single_cubic_l1_count", 0)) < 5:
        raise GlobalL1FlowError("editor curve geometry profile is too small")
    if int(profile.get("paired_original_edited_cubic_count", 0)) < 5:
        raise GlobalL1FlowError(
            "editor curve geometry profile lacks paired corrections"
        )
    if int(profile.get("paired_edited_descriptor_unique_count", 0)) != int(
        profile["paired_original_edited_cubic_count"]
    ):
        raise GlobalL1FlowError(
            "editor profile does not support non-repeating corrections"
        )
    return profile


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


def _rotate(vector: Point, radians: float) -> Point:
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        vector[0] * cosine - vector[1] * sine,
        vector[0] * sine + vector[1] * cosine,
    )


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


def _polyline_length(points: Sequence[Point]) -> float:
    return sum(_distance(points[index - 1], points[index]) for index in range(1, len(points)))


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


def _polyline_distance(a: Sequence[Point], b: Sequence[Point], offset_b: float = 0.0) -> float:
    a_min_x = min(point[0] for point in a)
    a_max_x = max(point[0] for point in a)
    a_min_y = min(point[1] for point in a)
    a_max_y = max(point[1] for point in a)
    b_min_x = min(point[0] + offset_b for point in b)
    b_max_x = max(point[0] + offset_b for point in b)
    b_min_y = min(point[1] for point in b)
    b_max_y = max(point[1] for point in b)
    gap_x = max(0.0, a_min_x - b_max_x, b_min_x - a_max_x)
    gap_y = max(0.0, a_min_y - b_max_y, b_min_y - a_max_y)
    box_gap = math.hypot(gap_x, gap_y)
    if box_gap > 0.18:
        return box_gap
    minimum = float("inf")
    for index in range(1, len(a)):
        a0, a1 = a[index - 1], a[index]
        for other_index in range(1, len(b)):
            b0 = b[other_index - 1][0] + offset_b, b[other_index - 1][1]
            b1 = b[other_index][0] + offset_b, b[other_index][1]
            minimum = min(minimum, _segment_distance(a0, a1, b0, b1))
            if minimum <= 0.0:
                return 0.0
    return minimum


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
) -> list[float]:
    values: list[float] = []
    for start, end in region["s_ranges"]:
        start_value = float(start)
        end_value = float(end)
        span = end_value - start_value
        for fraction in (0.10, 0.30, 0.50, 0.70, 0.90):
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
    feedback_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    family_id = morphology["classification"]["flower_branch_relation"]["family_id"]
    if feedback_profile is not None:
        selected = int(feedback_profile["preferred_l1_count"])
        if selected < 2:
            raise GlobalL1FlowError(
                f"{prototype_id} edit feedback requests fewer than two L1 lanes"
            )
        return {
            "selected_l1_count": selected,
            "required_support_count": 0,
            "ordinary_lane_count": selected,
            "primary_branch_evidence": int(
                morphology["instance_priors"]["source_observation_counts"][
                    "primary_branch_count"
                ]
            ),
            "branch_guide_equivalent_l1": None,
            "blank_region_plus_support_evidence": len(
                analysis["space_analysis"]["continuous_blank_regions"]
            ),
            "fixed_visual_capacity": int(
                prior["paired_baseline_scope"]["topology"]["L1"]
            ),
            "governing_evidence": "completed_editor_batch_l1_hierarchy",
            "fixed_count_copied": False,
            "mandatory_flower_service_count": 0,
        }
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
    feedback_profile: Mapping[str, Any] | None = None,
) -> list[Slot]:
    family_id = morphology["classification"]["flower_branch_relation"]["family_id"]
    if feedback_profile is not None:
        ordinary_count = int(count_derivation["ordinary_lane_count"])
        vertical = _vertical_preferences(morphology, ordinary_count, seed)
        roles = _slot_roles(family_id, ordinary_count)
        root_rhythm = feedback_profile.get("root_rhythm_quantiles")
        if isinstance(root_rhythm, Sequence) and len(root_rhythm) == ordinary_count:
            preferred_values = [
                (float(value) + 0.55 * float(latents["flow_phase"])) % 1.0
                for value in root_rhythm
            ]
        else:
            preferred_values = [
                (
                    (index + 0.5) / ordinary_count
                    + float(latents["flow_phase"])
                )
                % 1.0
                for index in range(ordinary_count)
            ]
        return [
            Slot(
                slot_id=f"ordinary_{index + 1}",
                role=roles[index],
                index=index,
                flower_id=None,
                preferred_s=preferred_values[index],
                preferred_vertical_side=vertical[index],
            )
            for index in range(ordinary_count)
        ]
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


def _bow_ratio(points: Sequence[Point]) -> float:
    if len(points) < 3:
        return 0.0
    start = points[0]
    end = points[-1]
    chord = _distance(start, end)
    actual = _polyline_length(points)
    if chord <= 1e-9 or actual <= 1e-9:
        return 0.0
    maximum = max(
        abs(_cross(_sub(end, start), _sub(point, start))) / chord
        for point in points[1:-1]
    )
    return maximum / actual


def _direction_turn_degrees(first: Point, second: Point) -> float:
    first_unit = _unit(first, "first_direction")
    second_unit = _unit(second, "second_direction")
    cosine = max(-1.0, min(1.0, _dot(first_unit, second_unit)))
    return math.degrees(math.acos(cosine))


def _polyline_inflection_count(points: Sequence[Point]) -> int:
    signs: list[int] = []
    for index in range(1, len(points) - 1):
        incoming = _sub(points[index], points[index - 1])
        outgoing = _sub(points[index + 1], points[index])
        turn = _cross(incoming, outgoing)
        if abs(turn) <= 1e-8:
            continue
        sign = 1 if turn > 0.0 else -1
        if not signs or signs[-1] != sign:
            signs.append(sign)
    return max(0, len(signs) - 1)


def _empirical_cdf(
    distribution: Mapping[str, Any],
    value: float,
) -> float:
    samples = [float(sample) for sample in distribution["samples"]]
    if not samples:
        raise GlobalL1FlowError("editor geometry distribution is empty")
    return bisect_right(samples, float(value)) / len(samples)


def _single_cubic_descriptors(
    segment: Mapping[str, Any],
) -> tuple[dict[str, float], float]:
    p0 = _point(segment["p0"], "descriptor.p0")
    p1 = _point(segment["p1"], "descriptor.p1")
    p2 = _point(segment["p2"], "descriptor.p2")
    p3 = _point(segment["p3"], "descriptor.p3")
    chord = _sub(p3, p0)
    chord_length = _length(chord)
    if chord_length <= 1e-9:
        raise GlobalL1FlowError("cannot describe a degenerate cubic")
    chord_direction = _mul(chord, 1.0 / chord_length)
    normal = (-chord_direction[1], chord_direction[0])
    start_handle = _sub(p1, p0)
    end_handle = _sub(p3, p2)
    start_angle = math.degrees(
        math.atan2(
            _dot(start_handle, normal),
            _dot(start_handle, chord_direction),
        )
    )
    end_angle = math.degrees(
        math.atan2(
            _dot(end_handle, normal),
            _dot(end_handle, chord_direction),
        )
    )
    orientation_sign = 1.0 if start_angle >= 0.0 else -1.0
    return (
        {
            "start_handle_chord_ratio": _length(start_handle) / chord_length,
            "end_handle_chord_ratio": _length(end_handle) / chord_length,
            "start_angle_abs_deg": abs(start_angle),
            "end_angle_normalized_deg": end_angle * orientation_sign,
        },
        orientation_sign,
    )


def _demonstration_corrected_descriptors(
    profile: Mapping[str, Any],
    original_descriptors: Mapping[str, float],
    variant_index: int,
) -> tuple[dict[str, float], dict[str, float], dict[str, float], int, float]:
    """Apply an actual editor original-to-edited correction in descriptor space."""

    names = (
        "start_handle_chord_ratio",
        "end_handle_chord_ratio",
        "start_angle_abs_deg",
        "end_angle_normalized_deg",
    )
    correction_rows = profile.get("paired_corrections")
    source_distributions = profile.get("original_descriptor_distributions")
    edited_distributions = profile.get("descriptor_distributions")
    if not isinstance(correction_rows, Sequence) or not correction_rows:
        raise GlobalL1FlowError("editor paired corrections are empty")
    if not isinstance(source_distributions, Mapping) or not isinstance(
        edited_distributions, Mapping
    ):
        raise GlobalL1FlowError("editor correction distributions are missing")

    def row_distance(row: Mapping[str, Any]) -> float:
        original = row["original_descriptors"]
        total = 0.0
        for name in names:
            distribution = source_distributions[name]
            scale = max(
                float(distribution["q90"]) - float(distribution["q10"]),
                1e-6,
            )
            total += (
                (float(original_descriptors[name]) - float(original[name]))
                / scale
            ) ** 2
        return math.sqrt(total / len(names))

    ranked = sorted(
        enumerate(correction_rows),
        key=lambda item: (row_distance(item[1]), item[0]),
    )
    demonstration_rank = int(variant_index) % min(8, len(ranked))
    row_index, row = ranked[demonstration_rank]
    distance = row_distance(row)
    delta = {name: float(row["edit_delta"][name]) for name in names}
    descriptors: dict[str, float] = {}
    quantiles: dict[str, float] = {}
    for name in names:
        distribution = edited_distributions[name]
        corrected = float(original_descriptors[name]) + delta[name]
        corrected = max(
            float(distribution["min"]),
            min(float(distribution["max"]), corrected),
        )
        descriptors[name] = corrected
        quantiles[name] = _empirical_cdf(distribution, corrected)
    return descriptors, quantiles, delta, int(row_index), distance


def _maximum_backbone_excursion(
    points: Sequence[Point],
    backbone: Sequence[Point],
) -> float:
    maximum = 0.0
    for point in points:
        nearest = float("inf")
        for offset in (-1.0, 0.0, 1.0):
            for index in range(1, len(backbone)):
                first = (backbone[index - 1][0] + offset, backbone[index - 1][1])
                second = (backbone[index][0] + offset, backbone[index][1])
                nearest = min(nearest, _point_segment_distance(point, first, second))
        maximum = max(maximum, nearest)
    return maximum


def _nearest_flower_gap(
    points: Sequence[Point],
    analysis: Mapping[str, Any],
) -> float:
    if not analysis["flowers"]:
        return 1.0
    minimum = float("inf")
    for flower in analysis["flowers"]:
        rx = float(flower["protection_rx"])
        ry = float(flower["protection_ry"])
        for point in points:
            center = _flower_center_near(flower, point[0])
            normalized = math.sqrt(max(0.0, _ellipse_value(point, center, rx, ry)))
            minimum = min(minimum, max(0.0, normalized - 1.0))
    return minimum


def _feedback_ordinary_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    latents: Mapping[str, float],
    feedback_profile: Mapping[str, Any],
    curve_geometry_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Correct old-mainline L1 geometry with paired editor demonstrations."""

    base_length = float(
        prior["statistics"]["primary_geometry"]["chord_length_repeat"]["median"]
    )
    length_strata = tuple(float(value) for value in feedback_profile["length_strata"])
    length_multiplier = float(feedback_profile["length_multiplier"])
    root_gap_median = float(
        prior["statistics"]["primary_root_rhythm"]["consecutive_mount_gap"]["median"]
    )
    canvas_height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    backbone = _backbone_points(analysis)
    candidates: list[dict[str, Any]] = []
    candidate_index = 0
    phase = float(latents["flow_phase"]) * (1.0 if slot.index % 2 == 0 else -1.0)
    bow_distribution = curve_geometry_profile["observed_geometry"]["bow_ratio"]
    bow_lower = float(bow_distribution["q10"])
    bow_upper = float(bow_distribution["q90"])

    for region in _candidate_regions(analysis):
        side_id = str(region["side_id"])
        for root_s in _region_s_values(region, phase):
            root, tangent = _sample_at_s(analysis, root_s)
            outward = _normal(tangent, side_id)
            for along_sign in (-1.0, 1.0):
                along = _mul(tangent, along_sign)
                for stratum_index, length_scale in enumerate(length_strata):
                    for descriptor_variant in range(16):
                        candidate_index += 1
                        planned = (
                            base_length
                            * length_scale
                            * length_multiplier
                            * (0.94 + 0.06 * float(latents["openness"]))
                        )
                        longitudinal = planned * (
                            0.72 + 0.10 * stratum_index
                        )
                        outward_reach = planned * (
                            0.56 + 0.035 * stratum_index
                        )
                        target = _add(
                            root,
                            _add(
                                _mul(along, longitudinal),
                                _mul(outward, outward_reach),
                            ),
                        )
                        chord = _sub(target, root)
                        chord_length = _length(chord)
                        chord_direction = _unit(
                            chord,
                            "feedback_editor_correction_chord",
                        )
                        original_start_direction = _unit(
                            _add(
                                _mul(outward, 0.91),
                                _mul(tangent, 0.18 * along_sign),
                            ),
                            "feedback_original_start_direction",
                        )
                        original_terminal_direction = _unit(
                            _add(
                                _mul(tangent, 0.78 * along_sign),
                                _mul(outward, 0.34),
                            ),
                            "feedback_original_terminal_direction",
                        )
                        original_variant = descriptor_variant % 2
                        if original_variant == 1:
                            original_terminal_direction = _unit(
                                _add(
                                    _mul(original_terminal_direction, 0.72),
                                    _mul(outward, -0.46),
                                ),
                                "feedback_original_reverse_terminal",
                            )
                        original_start_arm = chord_length * (
                            0.28 + 0.05 * float(latents["curl_energy"])
                        )
                        original_end_arm = chord_length * (
                            0.34 + 0.06 * float(latents["curl_energy"])
                        )
                        original_segment = _segment(
                            root,
                            _add(
                                root,
                                _mul(
                                    original_start_direction,
                                    original_start_arm,
                                ),
                            ),
                            _sub(
                                target,
                                _mul(
                                    original_terminal_direction,
                                    original_end_arm,
                                ),
                            ),
                            target,
                        )
                        original_descriptors, orientation_sign = (
                            _single_cubic_descriptors(original_segment)
                        )
                        (
                            descriptors,
                            descriptor_quantiles,
                            editor_delta,
                            demonstration_row_index,
                            demonstration_distance,
                        ) = _demonstration_corrected_descriptors(
                            curve_geometry_profile,
                            original_descriptors,
                            descriptor_variant // 2,
                        )
                        start_direction = _unit(
                            _rotate(
                                chord_direction,
                                math.radians(
                                    orientation_sign
                                    * float(descriptors["start_angle_abs_deg"])
                                ),
                            ),
                            "feedback_editor_corrected_start",
                        )
                        terminal_direction = _unit(
                            _rotate(
                                chord_direction,
                                math.radians(
                                    orientation_sign
                                    * float(
                                        descriptors[
                                            "end_angle_normalized_deg"
                                        ]
                                    )
                                ),
                            ),
                            "feedback_editor_corrected_terminal",
                        )
                        start_arm = chord_length * float(
                            descriptors["start_handle_chord_ratio"]
                        )
                        end_arm = chord_length * float(
                            descriptors["end_handle_chord_ratio"]
                        )
                        segments = [
                            _segment(
                                root,
                                _add(root, _mul(start_direction, start_arm)),
                                _sub(target, _mul(terminal_direction, end_arm)),
                                target,
                            )
                        ]
                        points = _sample_segments(segments)
                        if any(
                            point[1] < 0.025 or point[1] > canvas_height - 0.025
                            for point in points
                        ):
                            continue
                        if any(point[0] < -0.30 or point[0] > 1.30 for point in points):
                            continue
                        actual_length = _polyline_length(points)
                        bow_ratio = _bow_ratio(points)
                        bow_empirical_quantile = _empirical_cdf(
                            bow_distribution,
                            bow_ratio,
                        )
                        terminal_turn_degrees = _direction_turn_degrees(
                            start_direction,
                            terminal_direction,
                        )
                        inflection_count = _polyline_inflection_count(points)
                        vertical_span = max(point[1] for point in points) - min(
                            point[1] for point in points
                        )
                        excursion = _maximum_backbone_excursion(points, backbone)
                        flower_gap = _nearest_flower_gap(points, analysis)
                        root_preference = 1.0 - min(
                            1.0,
                            _periodic_delta(root_s, slot.preferred_s)
                            / max(root_gap_median * 2.2, 0.18),
                        )
                        vertical_side = "upper" if target[1] < root[1] else "lower"
                        vertical_match = (
                            1.0 if vertical_side == slot.preferred_vertical_side else 0.0
                        )
                        if bow_lower <= bow_ratio <= bow_upper:
                            bow_score = 1.0
                        else:
                            bow_score = 1.0 - min(
                                1.0,
                                min(
                                    abs(bow_ratio - bow_lower),
                                    abs(bow_ratio - bow_upper),
                                )
                                / max(bow_upper - bow_lower, 0.03),
                            )
                        compact_score = 1.0 - min(
                            1.0,
                            abs(actual_length - planned) / max(planned * 0.45, 1e-9),
                        )
                        individual_score = (
                            2.6 * root_preference
                            + 0.45 * vertical_match
                            + 0.75 * min(1.0, float(region["mean_clearance"]) / 0.30)
                            + 1.25 * abs(_dot(start_direction, tangent))
                            + 1.35 * bow_score
                            + 1.10 * compact_score
                            + (1.0 if stratum_index == 1 else 0.45 if stratum_index == 2 else 0.0)
                            - 0.35
                            * max(
                                0.0,
                                vertical_span
                                / float(feedback_profile["maximum_vertical_span"])
                                - 0.78,
                            )
                        )
                        candidates.append(
                            _candidate_base(
                                candidate_id=(
                                    f"{slot.slot_id}_feedback_{candidate_index:04d}"
                                ),
                                slot=slot,
                                source_channel=(
                                    "editor_original_to_edited_correction"
                                ),
                                side_id=side_id,
                                root_s=root_s,
                                root=root,
                                target=target,
                                segments=segments,
                                flower_id=None,
                                curvature_signature=(
                                    "editor_corrected_reverse_end"
                                    if float(
                                        descriptors["end_angle_normalized_deg"]
                                    )
                                    < 0.0
                                    else "editor_corrected_same_side_end"
                                ),
                                features={
                                    "root_preference": root_preference,
                                    "vertical_match": vertical_match,
                                    "initial_tangent_alignment": abs(
                                        _dot(start_direction, tangent)
                                    ),
                                    "initial_outward_alignment": _dot(
                                        start_direction, outward
                                    ),
                                    "bow_ratio": bow_ratio,
                                    "bow_empirical_quantile": (
                                        bow_empirical_quantile
                                    ),
                                    "vertical_span": vertical_span,
                                    "maximum_backbone_excursion": excursion,
                                    "nearest_flower_gap": flower_gap,
                                    "length_stratum": float(stratum_index),
                                    "descriptor_variant_index": float(
                                        descriptor_variant
                                    ),
                                    "original_curve_variant": float(
                                        original_variant
                                    ),
                                    "editor_demonstration_row_index": float(
                                        demonstration_row_index
                                    ),
                                    "editor_demonstration_distance": (
                                        demonstration_distance
                                    ),
                                    "descriptor_mean_quantile": sum(
                                        descriptor_quantiles.values()
                                    )
                                    / len(descriptor_quantiles),
                                    **{
                                        f"editor_{name}": value
                                        for name, value in descriptors.items()
                                    },
                                    **{
                                        f"original_{name}": value
                                        for name, value in original_descriptors.items()
                                    },
                                    **{
                                        f"editor_delta_{name}": value
                                        for name, value in editor_delta.items()
                                    },
                                    **{
                                        f"editor_{name}_quantile": value
                                        for name, value in descriptor_quantiles.items()
                                    },
                                    "terminal_turn_degrees": terminal_turn_degrees,
                                    "inflection_count": float(inflection_count),
                                    "planned_chord": _distance(root, target),
                                },
                                individual_score=individual_score,
                            )
                        )
    return candidates


def _ordinary_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    latents: Mapping[str, float],
    feedback_profile: Mapping[str, Any] | None = None,
    curve_geometry_profile: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if feedback_profile is not None:
        if curve_geometry_profile is None:
            raise GlobalL1FlowError(
                "editor-demonstrated curve geometry profile is required"
            )
        return _feedback_ordinary_candidates(
            slot,
            analysis,
            prior,
            latents,
            feedback_profile,
            curve_geometry_profile,
        )
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
        for root_s in _region_s_values(region, phase):
            root, tangent = _sample_at_s(analysis, root_s)
            outward = _normal(tangent, side_id)
            for along_sign in (-1.0, 1.0):
                for length_scale in length_scales:
                    index += 1
                    planned = (
                        base_length
                        * length_scale
                        * float(latents["openness"])
                        * (1.08 if slot.role == "frontier" else 1.0)
                    )
                    radial = min(0.36, max(0.20, planned * 0.68))
                    longitudinal = math.sqrt(max(planned * planned - radial * radial, 0.0144))
                    longitudinal *= along_sign * float(latents["sweep_amplitude"])
                    target = _add(
                        root,
                        _add(_mul(outward, radial), _mul(tangent, longitudinal)),
                    )
                    if not (0.035 <= target[1] <= canvas_height - 0.035):
                        continue
                    if not (-0.32 <= target[0] <= 1.32):
                        continue
                    start_direction = _unit(
                        _add(_mul(outward, 0.91), _mul(tangent, 0.18 * along_sign)),
                        "ordinary_start_direction",
                    )
                    terminal_direction = _unit(
                        _add(_mul(tangent, 0.78 * along_sign), _mul(outward, 0.34)),
                        "ordinary_terminal_direction",
                    )
                    chord = _distance(root, target)
                    entry_arm = chord * (0.28 + 0.05 * float(latents["curl_energy"]))
                    exit_arm = chord * (0.34 + 0.06 * float(latents["curl_energy"]))
                    if (slot.index + (1 if along_sign > 0 else 0)) % 2 == 0:
                        terminal_direction = _unit(
                            _add(_mul(terminal_direction, 0.72), _mul(outward, -0.46)),
                            "ordinary_s_terminal",
                        )
                        signature = "S"
                    else:
                        signature = "C"
                    segments = [
                        _hermite_segment(
                            root,
                            target,
                            start_direction,
                            terminal_direction,
                            entry_arm,
                            exit_arm,
                        )
                    ]
                    root_preference = 1.0 - min(
                        1.0, _periodic_delta(root_s, slot.preferred_s) / max(root_gap_median * 2.5, 0.20)
                    )
                    vertical_side = "upper" if target[1] < root[1] else "lower"
                    vertical_match = 1.0 if vertical_side == slot.preferred_vertical_side else 0.0
                    individual_score = (
                        3.0 * root_preference
                        + 1.4 * vertical_match
                        + 1.0 * float(region["mean_clearance"]) / 0.38
                        + (0.7 if signature == "S" else 0.45)
                    )
                    candidates.append(
                        _candidate_base(
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
                            },
                            individual_score=individual_score,
                        )
                    )
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
) -> list[dict[str, Any]]:
    if slot.flower_id is None:
        raise GlobalL1FlowError("SW-1 support slot has no flower id")
    flower = _flower_by_id(analysis, slot.flower_id)
    troughs = _trough_s_values(analysis)
    base_trough = min(
        troughs,
        key=lambda value: _periodic_delta(value, float(flower["nearest_backbone_s"])),
    )
    offsets = (-0.105, -0.075, -0.045, 0.045, 0.075, 0.105)
    candidates: list[dict[str, Any]] = []
    for index, offset in enumerate(offsets, start=1):
        signed_offset = offset + float(latents["flow_phase"]) * 0.35
        root_s = (base_trough + signed_offset) % 1.0
        root, tangent = _sample_at_s(analysis, root_s)
        target = _flower_boundary_toward(flower, root)
        direction = _unit(_sub(target, root), "sw1_support_direction")
        side_id, outward = _closest_side(tangent, direction)
        start_direction = _unit(
            _add(_mul(outward, 0.86), _mul(direction, 0.40)),
            "sw1_support_start",
        )
        center = _flower_center_near(flower, root[0])
        radial = _unit(_sub(target, center), "sw1_flower_radial")
        terminal_direction = _mul(radial, -1.0)
        chord = _distance(root, target)
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
        candidates.append(
            _candidate_base(
                candidate_id=f"{slot.slot_id}_sw1_{index:02d}",
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
                },
                individual_score=6.0 - 7.0 * trough_distance,
            )
        )
    return candidates


def _sw3_support_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    latents: Mapping[str, float],
) -> list[dict[str, Any]]:
    if slot.flower_id is None:
        raise GlobalL1FlowError("SW-3 support slot has no flower id")
    flower = _flower_by_id(analysis, slot.flower_id)
    nearest_s = float(flower["nearest_backbone_s"])
    distances = (0.335, 0.375, 0.415, 0.455)
    candidates: list[dict[str, Any]] = []
    index = 0
    for arc_direction in (-1.0, 1.0):
        for distance in distances:
            index += 1
            remote_distance = distance + float(latents["flow_phase"]) * 0.20
            root_s = (nearest_s + arc_direction * remote_distance) % 1.0
            root, tangent = _sample_at_s(analysis, root_s)
            center = _flower_center_near(flower, root[0])
            rx = float(flower["rx"])
            ry = float(flower["ry"])
            target = center[0], center[1] + ry
            horizontal_sign = -1.0 if root[0] <= center[0] else 1.0
            waypoint = (
                center[0] + horizontal_sign * (0.62 * rx + 0.035),
                center[1] + ry + 0.055,
            )
            toward_waypoint = _unit(_sub(waypoint, root), "sw3_waypoint_direction")
            side_id, outward = _closest_side(tangent, toward_waypoint)
            start_direction = _unit(
                _add(_mul(toward_waypoint, 0.92), _mul(outward, 0.16)),
                "sw3_support_start",
            )
            first_chord = _distance(root, waypoint)
            second_chord = _distance(waypoint, target)
            first = _hermite_segment(
                root,
                waypoint,
                start_direction,
                _unit(_sub(target, waypoint), "sw3_waypoint_exit"),
                first_chord * 0.33,
                first_chord * 0.12,
            )
            tangent_at_waypoint = _unit(_sub(target, waypoint), "sw3_second_start")
            second = _hermite_segment(
                waypoint,
                target,
                tangent_at_waypoint,
                (0.0, -1.0),
                max(0.035, second_chord * 0.42),
                max(0.025, second_chord * 0.28),
            )
            candidates.append(
                _candidate_base(
                    candidate_id=f"{slot.slot_id}_sw3_{index:02d}",
                    slot=slot,
                    source_channel="prototype_morphology_rule",
                    side_id=side_id,
                    root_s=root_s,
                    root=root,
                    target=target,
                    segments=[first, second],
                    flower_id=slot.flower_id,
                    curvature_signature="SC" if arc_direction < 0 else "CS",
                    features={
                        "outward_alignment": _dot(start_direction, outward),
                        "remote_mount_arc_distance": _periodic_delta(root_s, nearest_s),
                        "below_flower_waypoint_margin": waypoint[1] - (center[1] + ry),
                        "underside_contact_dx": abs(target[0] - center[0]),
                        "underside_contact_dy": abs(target[1] - (center[1] + ry)),
                    },
                    individual_score=8.0
                    - abs(_periodic_delta(root_s, nearest_s) - 0.395) * 8.0,
                )
            )
    return candidates


def _fixed_warp_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    seed: int,
) -> list[dict[str, Any]]:
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
        segments[0]["p1"] = _round_point(_add(root, _mul(corrected_start, source_arm)))
        candidates.append(
            _candidate_base(
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
                    "initial_handle_changed_only": 1.0,
                },
                individual_score=7.0,
            )
        )
    return candidates


def _backbone_points(analysis: Mapping[str, Any]) -> list[Point]:
    return [_point(row["point"], "backbone.point") for row in analysis["backbone"]["samples"]]


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
) -> float:
    start = max(4, int(len(centerline) * 0.16))
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
    feedback_profile: Mapping[str, Any] | None = None,
) -> list[str]:
    reasons: list[str] = []
    centerline = [_point(point, "candidate.centerline") for point in candidate["centerline"]]
    root = _point(candidate["root"], "candidate.root")
    target = _point(candidate["target"], "candidate.target")
    _, tangent = _sample_at_s(analysis, float(candidate["root_s"]))
    outward = _normal(tangent, str(candidate["side_id"]))
    initial = _unit(_sub(centerline[1], centerline[0]), "candidate.initial")
    if feedback_profile is None:
        if _dot(initial, outward) < 0.72:
            reasons.append("ordinary_or_support_initial_departure_not_outward")
    else:
        tangent_alignment = abs(_dot(initial, tangent))
        outward_alignment = _dot(initial, outward)
        if tangent_alignment < float(
            feedback_profile["minimum_initial_tangent_alignment"]
        ):
            reasons.append("feedback_lane_does_not_start_tangentially")
        if outward_alignment < float(
            feedback_profile["minimum_initial_outward_alignment"]
        ):
            reasons.append("feedback_lane_initially_turns_inward")

    canvas_height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    if not (0.0 <= target[1] <= canvas_height):
        reasons.append("target_outside_vertical_canvas")
    if not (-0.34 <= target[0] <= 1.34):
        reasons.append("target_outside_periodic_review_window")

    backbone_clearance = _backbone_non_root_clearance(
        centerline,
        _backbone_points(analysis),
    )
    if backbone_clearance < 0.012:
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

    if (
        feedback_profile is None
        and family_id == "SW-1_valley_filling"
        and role == "flower_support"
    ):
        trough_distance = float(candidate["features"].get("trough_arc_distance", 1.0))
        if trough_distance > 0.14:
            reasons.append("sw1_support_not_from_trough_flank")
    if (
        feedback_profile is None
        and family_id == "SW-3_tangent_terminal"
        and role == "terminal_flower_support"
    ):
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
) -> tuple[bool, float, dict[str, float]]:
    root_gap = _periodic_delta(float(a["root_s"]), float(b["root_s"]))
    if root_gap < root_spacing:
        return False, 0.0, {"root_gap": root_gap, "minimum_clearance": 0.0}
    points_a = [_point(point, "lane_a.centerline") for point in a["centerline"]]
    points_b = [_point(point, "lane_b.centerline") for point in b["centerline"]]
    minimum = min(
        _polyline_distance(points_a, points_b, offset)
        for offset in (-1.0, 0.0, 1.0)
    )
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


def _global_score(
    lanes: Sequence[Mapping[str, Any]],
    feedback_profile: Mapping[str, Any] | None = None,
    curve_geometry_profile: Mapping[str, Any] | None = None,
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
    if feedback_profile is not None:
        if curve_geometry_profile is None:
            raise GlobalL1FlowError(
                "global feedback scoring lacks editor curve geometry"
            )
        bow_distribution = curve_geometry_profile["observed_geometry"][
            "bow_ratio"
        ]
        bow_lower = float(bow_distribution["q10"])
        bow_upper = float(bow_distribution["q90"])
        bow_scores = [
            (
                1.0
                if bow_lower <= float(lane["features"]["bow_ratio"]) <= bow_upper
                else 1.0
                - min(
                    1.0,
                    min(
                        abs(float(lane["features"]["bow_ratio"]) - bow_lower),
                        abs(float(lane["features"]["bow_ratio"]) - bow_upper),
                    )
                    / max(bow_upper - bow_lower, 0.03),
                )
            )
            for lane in lanes
        ]
        tangent_alignment = sum(
            float(lane["features"]["initial_tangent_alignment"])
            for lane in lanes
        ) / len(lanes)
        root_rhythm_fidelity = sum(
            float(lane["features"]["root_preference"]) for lane in lanes
        ) / len(lanes)
        vertical_compactness = 1.0 - min(
            1.0,
            sum(float(lane["features"]["vertical_span"]) for lane in lanes)
            / len(lanes)
            / float(feedback_profile["maximum_vertical_span"]),
        )
        excursion_compactness = 1.0 - min(
            1.0,
            sum(
                float(lane["features"]["maximum_backbone_excursion"])
                for lane in lanes
            )
            / len(lanes)
            / float(feedback_profile["maximum_backbone_excursion"]),
        )
        length_strata_coverage = len(
            {
                int(round(float(lane["features"]["length_stratum"])))
                for lane in lanes
            }
        ) / 3.0
        target_fractions = [
            float(value)
            for value in feedback_profile["length_stratum_target_fractions"]
        ]
        actual_fractions = [
            sum(
                int(round(float(lane["features"]["length_stratum"]))) == index
                for lane in lanes
            )
            / len(lanes)
            for index in range(3)
        ]
        length_strata_mix = 1.0 - 0.5 * sum(
            abs(actual - target)
            for actual, target in zip(actual_fractions, target_fractions)
        )
        motion_signature_coverage = min(
            1.0,
            len({str(lane["curvature_signature"]) for lane in lanes}) / 2.0,
        )
        demonstration_correction_coverage = len(
            {
                int(lane["features"]["editor_demonstration_row_index"])
                for lane in lanes
            }
        ) / len(lanes)
        uniform_targets = [
            (index + 0.5) / len(lanes) for index in range(len(lanes))
        ]

        def distribution_match(feature_name: str) -> float:
            observed = sorted(
                float(lane["features"][feature_name]) for lane in lanes
            )
            return max(
                0.0,
                1.0
                - 2.0
                * sum(
                    abs(value - target)
                    for value, target in zip(observed, uniform_targets)
                )
                / len(observed),
            )

        control_descriptor_distribution_match = sum(
            distribution_match(feature_name)
            for feature_name in (
                "editor_start_handle_chord_ratio_quantile",
                "editor_end_handle_chord_ratio_quantile",
                "editor_start_angle_abs_deg_quantile",
                "editor_end_angle_normalized_deg_quantile",
            )
        ) / 4.0
        bow_distribution_match = distribution_match(
            "bow_empirical_quantile"
        )
        bow_mean = sum(
            float(lane["features"]["bow_ratio"]) for lane in lanes
        ) / len(lanes)
        bow_spread = min(
            1.0,
            math.sqrt(
                sum(
                    (float(lane["features"]["bow_ratio"]) - bow_mean) ** 2
                    for lane in lanes
                )
                / len(lanes)
            )
            / max(
                float(bow_distribution["q75"])
                - float(bow_distribution["q25"]),
                0.03,
            ),
        )
        flower_proximity = sum(
            1.0 / (1.0 + 2.0 * float(lane["features"]["nearest_flower_gap"]))
            for lane in lanes
        ) / len(lanes)
        bow_fidelity = sum(bow_scores) / len(bow_scores)
        score = (
            2.5 * root_coverage
            + 2.0 * root_rhythm_fidelity
            + 1.2 * target_coverage
            + 1.0 * length_rhythm
            + 0.7 * length_strata_coverage
            + 1.8 * length_strata_mix
            + 1.5 * bow_fidelity
            + 0.7 * bow_spread
            + 0.8 * motion_signature_coverage
            + 2.5 * demonstration_correction_coverage
            + 1.4 * control_descriptor_distribution_match
            + 2.4 * bow_distribution_match
            + 1.4 * tangent_alignment
            + 1.15 * vertical_compactness
            + 1.15 * excursion_compactness
            + 0.45 * flower_proximity
        )
        return score, {
            "root_coverage": root_coverage,
            "root_rhythm_fidelity": root_rhythm_fidelity,
            "target_zone_coverage": target_coverage,
            "length_rhythm": length_rhythm,
            "length_strata_coverage": length_strata_coverage,
            "length_strata_mix": length_strata_mix,
            "bow_fidelity": bow_fidelity,
            "bow_spread": bow_spread,
            "motion_signature_coverage": motion_signature_coverage,
            "demonstration_correction_coverage": (
                demonstration_correction_coverage
            ),
            "control_descriptor_distribution_match": (
                control_descriptor_distribution_match
            ),
            "bow_distribution_match": bow_distribution_match,
            "initial_tangent_alignment": tangent_alignment,
            "vertical_compactness": vertical_compactness,
            "backbone_excursion_compactness": excursion_compactness,
            "soft_flower_proximity": flower_proximity,
            "fixed_prior_channel_present": 0.0,
        }
    score = (
        4.0 * root_coverage
        + 3.0 * target_coverage
        + 1.6 * length_rhythm
        + 0.8 * fixed_prior_presence
        + min(1.0, math.sqrt(root_gap_variance) / 0.055)
    )
    return score, {
        "root_coverage": root_coverage,
        "target_zone_coverage": target_coverage,
        "length_rhythm": length_rhythm,
        "root_gap_variation": math.sqrt(root_gap_variance),
        "fixed_prior_channel_present": fixed_prior_presence,
    }


def _solve(
    slots: Sequence[Slot],
    candidate_pools: Mapping[str, Sequence[Mapping[str, Any]]],
    prior: Mapping[str, Any],
    feedback_profile: Mapping[str, Any] | None = None,
    curve_geometry_profile: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root_stats = prior["statistics"]["primary_root_rhythm"]["consecutive_mount_gap"]
    root_spacing = max(0.05, float(root_stats["min"]) * 0.78)
    lane_clearance = max(0.032, root_spacing * 0.58)
    beam_capacity = 36 * len(slots) ** 2
    expansion_cap = 4 * len(slots) + 4
    states = [BeamState(lanes=[], score=0.0)]
    pair_cache: dict[tuple[str, str], tuple[bool, float, dict[str, float]]] = {}

    for slot in slots:
        ranked_pool = sorted(
            candidate_pools[slot.slot_id],
            key=lambda row: (-float(row["individual_score"]), str(row["candidate_id"])),
        )
        if feedback_profile is not None:
            by_demonstration: dict[int, list[Mapping[str, Any]]] = {}
            for candidate in ranked_pool:
                row_index = int(
                    candidate["features"]["editor_demonstration_row_index"]
                )
                by_demonstration.setdefault(row_index, []).append(candidate)
            pool = []
            round_index = 0
            while len(pool) < expansion_cap:
                added = False
                for rows in by_demonstration.values():
                    if round_index < len(rows):
                        pool.append(rows[round_index])
                        added = True
                        if len(pool) >= expansion_cap:
                            break
                if not added:
                    break
                round_index += 1
        else:
            pool = ranked_pool[:expansion_cap]
        if not pool:
            raise GlobalL1FlowError(f"slot {slot.slot_id} has no feasible candidates")
        expanded: list[BeamState] = []
        for state in states:
            for candidate in pool:
                pair_score = 0.0
                compatible = True
                if feedback_profile is not None:
                    demonstration_row = int(
                        candidate["features"][
                            "editor_demonstration_row_index"
                        ]
                    )
                    reuse_count = sum(
                        int(
                            existing["features"][
                                "editor_demonstration_row_index"
                            ]
                        )
                        == demonstration_row
                        for existing in state.lanes
                    )
                    if reuse_count >= int(
                        feedback_profile[
                            "maximum_demonstration_correction_reuse_per_unit"
                        ]
                    ):
                        continue
                for existing in state.lanes:
                    key = tuple(sorted((str(candidate["candidate_id"]), str(existing["candidate_id"]))))
                    if key not in pair_cache:
                        pair_cache[key] = _pair_metrics(
                            candidate,
                            existing,
                            root_spacing,
                            lane_clearance,
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
        expanded.sort(
            key=lambda state: (
                -state.score,
                tuple(str(row["candidate_id"]) for row in state.lanes),
            )
        )
        states = expanded[:beam_capacity]

    ranked: list[tuple[float, BeamState, dict[str, float]]] = []
    for state in states:
        global_value, global_features = _global_score(
            state.lanes,
            feedback_profile,
            curve_geometry_profile,
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
            valid, score, metrics = pair_cache.get(
                key,
                _pair_metrics(lane, other, root_spacing, lane_clearance),
            )
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
        "maximum_demonstration_correction_reuse_per_unit": (
            int(
                feedback_profile[
                    "maximum_demonstration_correction_reuse_per_unit"
                ]
            )
            if feedback_profile is not None
            else None
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
    if contract.get("schema") not in {CONTRACT_SCHEMA, CONTRACT_SCHEMA_V2}:
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


def generate_global_l1_flow_plan(
    strict_p0: Mapping[str, Any],
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    seed: int,
    feedback_prior: Mapping[str, Any] | None = None,
    curve_geometry_prior: Mapping[str, Any] | None = None,
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
    feedback_profile: Mapping[str, Any] | None = None
    curve_geometry_profile: Mapping[str, Any] | None = None
    if _feedback_mode(contract):
        if feedback_prior is None or curve_geometry_prior is None:
            raise GlobalL1FlowError(
                "stage-3B v2 requires both completed editor priors"
            )
        feedback_profile = _feedback_profile(feedback_prior, prototype_id)
        curve_geometry_profile = _curve_geometry_profile(
            curve_geometry_prior,
            prototype_id,
        )
    latents = _global_latents(prototype_id, seed)
    count_derivation = _derive_lane_count(
        prototype_id,
        analysis,
        morphology,
        prior,
        feedback_profile,
    )
    slots = _make_slots(
        analysis,
        morphology,
        count_derivation,
        latents,
        seed,
        feedback_profile,
    )
    pools: dict[str, list[dict[str, Any]]] = {}
    inventory_rows: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()

    for slot in slots:
        candidates: list[dict[str, Any]] = []
        if feedback_profile is not None:
            candidates.extend(
                _ordinary_candidates(
                    slot,
                    analysis,
                    prior,
                    latents,
                    feedback_profile,
                    curve_geometry_profile,
                )
            )
        elif slot.role == "flower_support":
            candidates.extend(_sw1_support_candidates(slot, analysis, latents))
        elif slot.role == "terminal_flower_support":
            candidates.extend(_sw3_support_candidates(slot, analysis, latents))
        else:
            candidates.extend(_ordinary_candidates(slot, analysis, prior, latents))
        if feedback_profile is None:
            candidates.extend(_fixed_warp_candidates(slot, analysis, prior, seed))

        feasible: list[dict[str, Any]] = []
        for candidate in candidates:
            reasons = _candidate_rejections(
                candidate,
                analysis,
                family_id,
                prior,
                feedback_profile,
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

    selected, solver = _solve(
        slots,
        pools,
        prior,
        feedback_profile,
        curve_geometry_profile,
    )
    selected_ids = {str(row["candidate_id"]) for row in selected}
    for row in inventory_rows:
        row["selected"] = str(row["candidate_id"]) in selected_ids

    role_counts = Counter(str(row["role"]) for row in selected)
    if sum(role_counts.values()) != count_derivation["selected_l1_count"]:
        raise GlobalL1FlowError("selected L1 count does not match count derivation")
    if feedback_profile is None and (
        role_counts["flower_support"] + role_counts["terminal_flower_support"]
        != count_derivation["required_support_count"]
    ):
        raise GlobalL1FlowError("selected support count does not match morphology requirement")

    plan_schema = SCHEMA_V2 if feedback_profile is not None else SCHEMA
    plan_version = "v2" if feedback_profile is not None else "v1"
    plan: dict[str, Any] = {
        "schema": plan_schema,
        "plan_id": f"{prototype_id}__seed_{seed}__global_l1_flow_{plan_version}",
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
        "edit_feedback_policy": (
            {
                "consumed": True,
                "prior_id": str(feedback_prior["prior_id"]),
                "role_semantics": str(feedback_profile["role_semantics"]),
                "mandatory_flower_service_lanes": bool(
                    feedback_profile["mandatory_flower_service_lanes"]
                ),
                "curve_geometry_source": str(
                    feedback_profile["curve_geometry_source"]
                ),
                "curve_geometry_prior_id": str(
                    curve_geometry_prior["prior_id"]
                ),
                "fixed_curve_shape_quota": False,
                "maximum_demonstration_correction_reuse_per_unit": int(
                    feedback_profile[
                        "maximum_demonstration_correction_reuse_per_unit"
                    ]
                ),
                "fixed_svg_templates_consumed": False,
            }
            if feedback_profile is not None and feedback_prior is not None
            else {"consumed": False}
        ),
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
                "compact_medium_long_hierarchy",
                "tangent_run_outward_turn_and_settle",
                "flower_relation_is_soft_not_mandatory",
                "root_and_target_spacing",
                "white_space_distribution",
                "non_crossing_periodic_flow",
            ],
        },
        "input_digests": {
            "strict_p0_digest": analysis["strict_p0_digest"],
            "analysis_digest": analysis["analysis_digest"],
            "morphology_digest": morphology["morphology_digest"],
            "fixed_visual_prior_digest": prior["prior_digest"],
            **(
                {"edit_feedback_prior_digest": canonical_digest(feedback_prior)}
                if feedback_prior is not None
                else {}
            ),
            **(
                {
                    "editor_curve_geometry_prior_digest": canonical_digest(
                        curve_geometry_prior
                    )
                }
                if curve_geometry_prior is not None
                else {}
            ),
        },
    }
    plan["plan_digest"] = canonical_digest(plan)
    inventory: dict[str, Any] = {
        "schema": (
            "dynamic_branch_global_l1_candidate_inventory_v2"
            if feedback_profile is not None
            else "dynamic_branch_global_l1_candidate_inventory_v1"
        ),
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


def validate_global_l1_flow_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") not in {SCHEMA, SCHEMA_V2}:
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
    if plan.get("schema") == SCHEMA_V2:
        policy = plan.get("edit_feedback_policy", {})
        if policy.get("curve_geometry_source") != (
            "saved_editor_l1_original_to_edited_correction"
        ):
            raise GlobalL1FlowError(
                "V2 plan lacks saved-editor correction evidence"
            )
        if policy.get("fixed_curve_shape_quota") is not False:
            raise GlobalL1FlowError("V2 plan reintroduced a fixed shape quota")
        maximum_reuse = int(
            policy.get("maximum_demonstration_correction_reuse_per_unit", 0)
        )
        if maximum_reuse <= 0:
            raise GlobalL1FlowError(
                "V2 plan lacks a demonstration reuse limit"
            )
        demonstration_rows = [
            int(lane["features"]["editor_demonstration_row_index"])
            for lane in plan["lanes"]
        ]
        if max(Counter(demonstration_rows).values()) > maximum_reuse:
            raise GlobalL1FlowError(
                "V2 plan exceeds the editor correction reuse limit"
            )
        for lane in plan["lanes"]:
            features = lane.get("features", {})
            if not all(
                key in features
                for key in (
                    "editor_start_handle_chord_ratio",
                    "editor_end_handle_chord_ratio",
                    "editor_start_angle_abs_deg",
                    "editor_end_angle_normalized_deg",
                    "descriptor_mean_quantile",
                    "editor_demonstration_row_index",
                    "editor_demonstration_distance",
                )
            ):
                raise GlobalL1FlowError(
                    "V2 lane lacks editor-demonstrated descriptors"
                )
