#!/usr/bin/env python3
"""Stage-3 symbolic BranchUnit planning without curve compilation."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "dynamic_branch_plan_v3"
POLICY_ID = "branchunit_directional_layout_free_space_and_below_flower_v3"
ANALYSIS_SCHEMA = "dynamic_branch_prototype_analysis_v1"
MORPHOLOGY_SCHEMA = "dynamic_branch_morphology_profile_v1"
PLAN_CONTRACT_SCHEMA = "dynamic_branch_stage3_plan_contract_v1"
REVIEW_STATES = (
    "plan_pending_review",
    "plan_approved_for_curve_compilation",
    "plan_needs_revision",
    "plan_rejected",
    "planning_failed",
)
FAMILY_IDS = (
    "SW-1_valley_filling",
    "SW-2_axis_penetrating",
    "SW-3_tangent_terminal",
)
Point = tuple[float, float]

DENSITY_OPTIONAL_COUNTS = {
    "dense": 4,
    "sparse": 2,
    "primary_sweep_led": 4,
    "light": 2,
    "moderate": 3,
}
DENSITY_WEIGHTS = {
    "dense": 0.92,
    "sparse": 0.42,
    "primary_sweep_led": 0.68,
    "light": 0.36,
    "moderate": 0.60,
}
SWEEP_LENGTHS = {
    "dense": (0.18, "short_medium"),
    "sparse": (0.31, "long"),
    "primary_sweep_led": (0.30, "long"),
    "light": (0.23, "medium"),
    "moderate": (0.27, "medium_long"),
}


class PlanningFailure(RuntimeError):
    """A preserved single-forward planning failure, never an auto-retry signal."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any]):
        self.code = code
        self.message = message
        self.details = dict(details)
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "dynamic_branch_planning_failure_v1",
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retry_attempted": False,
            "resample_attempted": False,
            "automatic_repair_attempted": False,
            "automatic_deletion_attempted": False,
        }


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_random(seed: int, *parts: object) -> random.Random:
    payload = "|".join([str(seed), *(str(part) for part in parts)])
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _round(value: float, digits: int = 9) -> float:
    rounded = round(float(value), digits)
    return 0.0 if rounded == -0.0 else rounded


def _round_point(point: Sequence[float]) -> list[float]:
    return [_round(float(point[0])), _round(float(point[1]))]


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scale: float) -> Point:
    return a[0] * scale, a[1] * scale


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _length(a: Point) -> float:
    return math.hypot(a[0], a[1])


def _distance(a: Point, b: Point) -> float:
    return _length(_sub(a, b))


def _unit(a: Point) -> Point:
    length = _length(a)
    if length <= 1e-12:
        return 1.0, 0.0
    return a[0] / length, a[1] / length


def _circular_s_distance(a: float, b: float) -> float:
    delta = abs(float(a) - float(b)) % 1.0
    return min(delta, 1.0 - delta)


def _signed_circular_s_delta(value: float, reference: float) -> float:
    delta = (float(value) - float(reference)) % 1.0
    return delta - 1.0 if delta > 0.5 else delta


def _angle_degrees(a: Point, b: Point) -> float:
    cosine = max(-1.0, min(1.0, _dot(_unit(a), _unit(b))))
    return math.degrees(math.acos(cosine))


def _normal(a: Point) -> Point:
    return -a[1], a[0]


def _periodic_point_near(point: Sequence[float], reference: Sequence[float]) -> Point:
    x = float(point[0])
    return x + round(float(reference[0]) - x), float(point[1])


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    segment = _sub(end, start)
    length_sq = _dot(segment, segment)
    if length_sq <= 1e-12:
        return _distance(point, start)
    t = max(0.0, min(1.0, _dot(_sub(point, start), segment) / length_sq))
    projection = _add(start, _mul(segment, t))
    return _distance(point, projection)


def _segment_distance(a0: Point, a1: Point, b0: Point, b1: Point) -> float:
    def orientation(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (
            q[1] - p[1]
        ) * (r[0] - p[0])

    def on_segment(p: Point, q: Point, r: Point) -> bool:
        return (
            min(p[0], r[0]) - 1e-12 <= q[0] <= max(p[0], r[0]) + 1e-12
            and min(p[1], r[1]) - 1e-12
            <= q[1]
            <= max(p[1], r[1]) + 1e-12
        )

    o1 = orientation(a0, a1, b0)
    o2 = orientation(a0, a1, b1)
    o3 = orientation(b0, b1, a0)
    o4 = orientation(b0, b1, a1)
    proper_intersection = (
        (o1 > 1e-12 and o2 < -1e-12 or o1 < -1e-12 and o2 > 1e-12)
        and (o3 > 1e-12 and o4 < -1e-12 or o3 < -1e-12 and o4 > 1e-12)
    )
    endpoint_intersection = (
        abs(o1) <= 1e-12
        and on_segment(a0, b0, a1)
        or abs(o2) <= 1e-12
        and on_segment(a0, b1, a1)
        or abs(o3) <= 1e-12
        and on_segment(b0, a0, b1)
        or abs(o4) <= 1e-12
        and on_segment(b0, a1, b1)
    )
    if proper_intersection or endpoint_intersection:
        return 0.0
    return min(
        _point_segment_distance(a0, b0, b1),
        _point_segment_distance(a1, b0, b1),
        _point_segment_distance(b0, a0, a1),
        _point_segment_distance(b1, a0, a1),
    )


def _polyline_point(points: Sequence[Point], fraction: float) -> Point:
    if len(points) < 2:
        return points[0]
    lengths = [
        _distance(start, end)
        for start, end in zip(points, points[1:])
    ]
    total = sum(lengths)
    if total <= 1e-12:
        return points[0]
    target = max(0.0, min(1.0, fraction)) * total
    traversed = 0.0
    for segment_length, start, end in zip(lengths, points, points[1:]):
        if traversed + segment_length >= target:
            local = (
                0.0
                if segment_length <= 1e-12
                else (target - traversed) / segment_length
            )
            return (
                start[0] + (end[0] - start[0]) * local,
                start[1] + (end[1] - start[1]) * local,
            )
        traversed += segment_length
    return points[-1]


def _point_backbone_clearance(
    analysis: Mapping[str, Any],
    point: Point,
) -> float:
    samples = [
        tuple(float(value) for value in row["point"])
        for row in analysis["backbone"]["samples"]
    ]
    return min(
        _point_segment_distance(
            point,
            (start[0] + shift, start[1]),
            (end[0] + shift, end[1]),
        )
        for shift in (-1.0, 0.0, 1.0)
        for start, end in zip(samples, samples[1:])
    )


def _direction_path_parent_clearance(
    analysis: Mapping[str, Any],
    points: Sequence[Point],
    *,
    start_fraction: float,
) -> float:
    fractions = [
        start_fraction + (1.0 - start_fraction) * index / 5.0
        for index in range(6)
    ]
    return min(
        _point_backbone_clearance(
            analysis,
            _polyline_point(points, fraction),
        )
        for fraction in fractions
    )


def _ellipse_boundary_toward(
    flower: Mapping[str, Any],
    point: Sequence[float],
    *,
    outside_scale: float = 1.03,
) -> Point:
    center = tuple(float(value) for value in flower["center"])
    vector = (float(point[0]) - center[0], float(point[1]) - center[1])
    denominator = math.sqrt(
        (vector[0] / float(flower["protection_rx"])) ** 2
        + (vector[1] / float(flower["protection_ry"])) ** 2
    )
    if denominator <= 1e-12:
        return center
    return (
        center[0] + vector[0] / denominator * outside_scale,
        center[1] + vector[1] / denominator * outside_scale,
    )


def _segment_enters_flower(
    start: Point,
    end: Point,
    flower: Mapping[str, Any],
    *,
    radius: float,
) -> bool:
    center = tuple(float(value) for value in flower["center"])
    rx = float(flower["protection_rx"]) + radius
    ry = float(flower["protection_ry"]) + radius
    for index in range(1, 13):
        t = index / 13.0
        point = (
            start[0] + (end[0] - start[0]) * t,
            start[1] + (end[1] - start[1]) * t,
        )
        dx = point[0] - center[0]
        dx -= round(dx)
        dy = point[1] - center[1]
        if (dx / rx) ** 2 + (dy / ry) ** 2 < 1.0:
            return True
    return False


def _sample_at_s(analysis: Mapping[str, Any], s: float) -> Mapping[str, Any]:
    wrapped = s % 1.0
    return min(
        analysis["backbone"]["samples"],
        key=lambda row: _circular_s_distance(float(row["s"]), wrapped),
    )


def _s_in_ranges(s: float, ranges: Sequence[Sequence[float]]) -> bool:
    return any(
        float(start) - 1e-9 <= s <= float(end) + 1e-9
        for start, end in ranges
    )


def _validate_inputs(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    plan_contract: Mapping[str, Any],
    seed: int,
) -> tuple[str, str]:
    if analysis.get("schema") != ANALYSIS_SCHEMA:
        raise PlanningFailure(
            "invalid_analysis_schema",
            "stage-2 analysis schema mismatch",
            {"actual": analysis.get("schema"), "expected": ANALYSIS_SCHEMA},
        )
    if morphology.get("schema") != MORPHOLOGY_SCHEMA:
        raise PlanningFailure(
            "invalid_morphology_schema",
            "stage-2.5 morphology schema mismatch",
            {"actual": morphology.get("schema"), "expected": MORPHOLOGY_SCHEMA},
        )
    if plan_contract.get("schema") != PLAN_CONTRACT_SCHEMA:
        raise PlanningFailure(
            "invalid_plan_contract_schema",
            "stage-3 contract schema mismatch",
            {"actual": plan_contract.get("schema"), "expected": PLAN_CONTRACT_SCHEMA},
        )
    if plan_contract.get("output", {}).get("schema") != SCHEMA:
        raise PlanningFailure(
            "invalid_plan_output_schema",
            "stage-3 contract output schema does not match the planner",
            {
                "actual": plan_contract.get("output", {}).get("schema"),
                "expected": SCHEMA,
            },
        )
    prototype_id = str(analysis.get("prototype_id", ""))
    if not prototype_id or morphology.get("prototype_id") != prototype_id:
        raise PlanningFailure(
            "input_identity_mismatch",
            "analysis and morphology prototype ids differ",
            {
                "analysis_prototype_id": prototype_id,
                "morphology_prototype_id": morphology.get("prototype_id"),
            },
        )
    if morphology.get("source_stage2_analysis_digest") != analysis.get(
        "analysis_digest"
    ):
        raise PlanningFailure(
            "input_digest_mismatch",
            "morphology is not bound to this analysis",
            {"prototype_id": prototype_id},
        )
    family_id = str(
        morphology["classification"]["flower_branch_relation"]["family_id"]
    )
    if family_id not in FAMILY_IDS:
        raise PlanningFailure(
            "unknown_morphology_family",
            "unsupported flower/branch morphology family",
            {"prototype_id": prototype_id, "family_id": family_id},
        )
    if seed not in plan_contract["task_matrix"]["seeds"]:
        raise PlanningFailure(
            "unregistered_seed",
            "seed is not preregistered for stage 3",
            {"prototype_id": prototype_id, "seed": seed},
        )
    return prototype_id, family_id


def _density_style(morphology: Mapping[str, Any]) -> tuple[str, int, float]:
    density_class = str(morphology["instance_priors"]["density_class"])
    if density_class not in DENSITY_OPTIONAL_COUNTS:
        raise PlanningFailure(
            "unknown_density_class",
            "instance density class has no planning policy",
            {"density_class": density_class},
        )
    return (
        density_class,
        DENSITY_OPTIONAL_COUNTS[density_class],
        DENSITY_WEIGHTS[density_class],
    )


def _layout_policy(
    morphology: Mapping[str, Any],
    plan_contract: Mapping[str, Any],
) -> dict[str, Any]:
    density_class = str(morphology["instance_priors"]["density_class"])
    constraints = plan_contract.get("initial_layout_constraints")
    if not isinstance(constraints, Mapping):
        raise PlanningFailure(
            "initial_layout_constraints_missing",
            "stage 3 v3 requires explicit directional layout constraints",
            {"density_class": density_class},
        )
    minimum_spacing = constraints[
        "minimum_periodic_root_spacing_by_density_class"
    ].get(density_class)
    maximum_angle = constraints[
        "maximum_local_direction_difference_degrees_by_density_class"
    ].get(density_class)
    if minimum_spacing is None or maximum_angle is None:
        raise PlanningFailure(
            "density_layout_policy_missing",
            "density class has no initial layout policy",
            {"density_class": density_class},
        )
    if constraints["symbolic_intent_polyline_crossing_allowed"] is not False:
        raise PlanningFailure(
            "symbolic_crossing_policy_violation",
            "stage 3 cannot permit crossed symbolic BranchUnit intents",
            {"density_class": density_class},
        )
    if (
        constraints["symbolic_intent_polyline_clearance_is_hard_constraint"]
        is not True
    ):
        raise PlanningFailure(
            "symbolic_clearance_policy_violation",
            "symbolic intent clearance must be a hard global constraint",
            {"density_class": density_class},
        )
    if constraints["directional_preview_is_branch_shape_simulation"] is not False:
        raise PlanningFailure(
            "directional_preview_scope_violation",
            "stage 3 preview cannot simulate branch shape",
            {"density_class": density_class},
        )
    if constraints["parent_tangent_departure_segment_in_preview_allowed"] is not False:
        raise PlanningFailure(
            "parent_tangent_preview_segment_policy_violation",
            "stage 3 directions must not first run along the parent backbone",
            {"density_class": density_class},
        )
    return {
        "density_class": density_class,
        "minimum_periodic_root_spacing": float(minimum_spacing),
        "direction_neighborhood_s": float(
            constraints["direction_neighborhood_s"]
        ),
        "maximum_local_direction_difference_degrees": float(maximum_angle),
        "one_selected_root_per_density_bin": bool(
            constraints["one_selected_root_per_density_bin"]
        ),
        "opposite_side_same_root_exception_allowed": bool(
            constraints["opposite_side_same_root_exception_allowed"]
        ),
        "role_density_field_consumed_by_global_selection": bool(
            constraints["role_density_field_consumed_by_global_selection"]
        ),
        "symbolic_intent_polyline_crossing_allowed": bool(
            constraints["symbolic_intent_polyline_crossing_allowed"]
        ),
        "symbolic_intent_polyline_clearance_is_hard_constraint": bool(
            constraints[
                "symbolic_intent_polyline_clearance_is_hard_constraint"
            ]
        ),
        "minimum_symbolic_intent_clearance": float(
            constraints["minimum_symbolic_intent_clearance"]
        ),
        "occupancy_radius_clearance_factor": float(
            constraints["occupancy_radius_clearance_factor"]
        ),
        "directional_preview_is_branch_shape_simulation": False,
        "parent_tangent_departure_segment_in_preview_allowed": False,
        "immediate_outward_departure_required": bool(
            constraints["immediate_outward_departure_required"]
        ),
        "minimum_outward_normal_alignment": float(
            constraints["minimum_outward_normal_alignment"]
        ),
        "minimum_parent_clearance_after_initial_departure": float(
            constraints["minimum_parent_clearance_after_initial_departure"]
        ),
        "parent_clearance_measurement_start_fraction": float(
            constraints["parent_clearance_measurement_start_fraction"]
        ),
    }


def _role_density_field(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    family_id: str,
) -> dict[str, Any]:
    density_class, _, density_weight = _density_style(morphology)
    probes = analysis["space_analysis"]["probes"]
    flowers = analysis["flowers"]
    bins: list[dict[str, Any]] = []
    for index in range(8):
        start_s = index / 8.0
        end_s = (index + 1) / 8.0
        rows = [
            row
            for row in probes
            if start_s - 1e-9 <= float(row["s"]) <= end_s + 1e-9
        ]
        candidate_rows = [row for row in rows if row["candidate_for_l1"]]
        mean_clearance = (
            sum(float(row["clearance"]) for row in candidate_rows)
            / len(candidate_rows)
            if candidate_rows
            else 0.0
        )
        center_s = (start_s + end_s) * 0.5
        nearest_flower_distance = min(
            (
                _circular_s_distance(center_s, float(flower["nearest_backbone_s"]))
                for flower in flowers
            ),
            default=0.5,
        )
        flower_influence = max(0.0, 1.0 - nearest_flower_distance / 0.22)
        availability = min(1.0, mean_clearance / 0.38)
        target = min(
            1.0,
            density_weight * (0.55 + 0.45 * availability)
            + (0.16 * flower_influence if family_id != "SW-2_axis_penetrating" else 0.0),
        )
        if family_id == "SW-1_valley_filling" and flower_influence > 0.45:
            preferred_role = "flower_support_or_valley_fill"
        elif family_id == "SW-3_tangent_terminal" and flower_influence > 0.45:
            preferred_role = "terminal_flower_support"
        else:
            preferred_role = "primary_sweep"
        bins.append(
            {
                "bin_id": f"density_bin_{index + 1}",
                "s_range": [_round(start_s), _round(end_s)],
                "target_density": _round(target, 6),
                "available_l1_probe_count": len(candidate_rows),
                "mean_available_clearance": _round(mean_clearance),
                "flower_influence": _round(flower_influence, 6),
                "preferred_role": preferred_role,
                "planner_selected_slot_count": 0,
            }
        )
    return {
        "schema": "dynamic_branch_role_density_field_v1",
        "density_class": density_class,
        "family_id": family_id,
        "bin_count": len(bins),
        "bins": bins,
        "counts_are_soft_instance_priors": True,
        "source_branch_counts_used_as_fixed_targets": False,
    }


def _child_rhythm(
    morphology: Mapping[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    density_class = str(morphology["instance_priors"]["density_class"])
    rhythm = str(morphology["instance_priors"]["side_rhythm"])
    if role in {"flower_support", "terminal_flower_support"}:
        minimum, maximum = (0, 1) if density_class in {"sparse", "light"} else (1, 2)
    elif density_class == "dense":
        minimum, maximum = 2, 4
    elif density_class in {"sparse", "light"}:
        minimum, maximum = 1, 2
    else:
        minimum, maximum = 1, 3
    return {
        "minimum_child_count": minimum,
        "maximum_child_count": maximum,
        "rhythm_policy": rhythm,
        "length_sequence": (
            ["short", "medium", "short"]
            if density_class == "dense"
            else ["medium", "short"]
        ),
        "child_geometry_deferred_to_stage_4": True,
    }


def _vertical_side_from_direction(direction: Point) -> str:
    return "lower" if direction[1] >= 0.0 else "upper"


def _remote_terminal_support_samples(
    analysis: Mapping[str, Any],
    flower: Mapping[str, Any],
    plan_contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    policy = plan_contract["initial_layout_constraints"][
        "sw3_remote_terminal_support"
    ]
    minimum_arc = float(
        policy["minimum_arc_distance_from_nearest_flower_mount"]
    )
    maximum_arc = float(
        policy["maximum_arc_distance_from_nearest_flower_mount"]
    )
    preferred_arc = float(policy["preferred_arc_distance"])
    minimum_reach = float(policy["minimum_root_to_flower_boundary_reach"])
    below_margin = float(policy["minimum_below_flower_corridor_margin"])
    per_direction = int(policy["candidates_per_arc_direction"])
    minimum_outward_alignment = float(
        plan_contract["initial_layout_constraints"][
            "minimum_outward_normal_alignment"
        ]
    )
    minimum_parent_clearance = float(
        plan_contract["initial_layout_constraints"][
            "minimum_parent_clearance_after_initial_departure"
        ]
    )
    flower_center = tuple(float(value) for value in flower["center"])
    nearest_s = float(flower["nearest_backbone_s"])
    radius = 0.034
    by_direction: dict[str, list[dict[str, Any]]] = {
        "forward_arc": [],
        "reverse_arc": [],
    }
    seen_root_s: set[float] = set()
    for sample in analysis["backbone"]["samples"]:
        root_s = float(sample["s"]) % 1.0
        root_key = round(root_s, 7)
        if root_key in seen_root_s:
            continue
        seen_root_s.add(root_key)
        signed_arc = _signed_circular_s_delta(root_s, nearest_s)
        arc_distance = abs(signed_arc)
        if not minimum_arc <= arc_distance <= maximum_arc:
            continue
        root = _periodic_point_near(sample["point"], flower_center)
        if root[1] <= flower_center[1]:
            continue
        contact = (
            flower_center[0],
            flower_center[1] + float(flower["ry"]) * 1.03,
        )
        horizontal_offset = max(
            0.055,
            min(0.10, float(flower["protection_rx"]) * 0.35),
        )
        root_is_left = root[0] <= contact[0]
        under_approach = (
            contact[0] - horizontal_offset
            if root_is_left
            else contact[0] + horizontal_offset,
            flower_center[1]
            + float(flower["protection_ry"])
            + below_margin,
        )
        path_points = (root, under_approach, contact)
        initial_direction = _unit(_sub(under_approach, root))
        tangent = tuple(float(value) for value in sample["tangent"])
        normal = _normal(tangent)
        side_id = (
            "left_normal"
            if _dot(normal, initial_direction) >= 0.0
            else "right_normal"
        )
        outward_normal = normal if side_id == "left_normal" else _mul(normal, -1.0)
        outward_alignment = _dot(outward_normal, initial_direction)
        reach = sum(
            _distance(start, end)
            for start, end in zip(path_points, path_points[1:])
        )
        if reach < minimum_reach:
            continue
        if _segment_enters_flower(
            root,
            under_approach,
            flower,
            radius=radius,
        ):
            continue
        if any(
            other["flower_id"] != flower["flower_id"]
            and any(
                _segment_enters_flower(start, end, other, radius=radius)
                for start, end in zip(path_points, path_points[1:])
            )
            for other in analysis["flowers"]
        ):
            continue
        parent_clearance = _direction_path_parent_clearance(
            analysis,
            path_points,
            start_fraction=float(
                plan_contract["initial_layout_constraints"][
                    "parent_clearance_measurement_start_fraction"
                ]
            ),
        )
        if (
            outward_alignment < minimum_outward_alignment
            or parent_clearance < minimum_parent_clearance
        ):
            continue
        arc_direction = "forward_arc" if signed_arc > 0.0 else "reverse_arc"
        score = (
            reach * 1.35
            + outward_alignment * 0.7
            + parent_clearance * 0.8
            - abs(arc_distance - preferred_arc) * 0.45
        )
        by_direction[arc_direction].append(
            {
                "root_s": root_s,
                "root": root,
                "target": contact,
                "to_target": initial_direction,
                "parent_tangent": tangent,
                "direction_path_points": path_points,
                "under_approach_waypoint": under_approach,
                "outward_normal_alignment": outward_alignment,
                "parent_clearance_after_initial_departure": parent_clearance,
                "reach": reach,
                "arc_distance": arc_distance,
                "arc_direction": arc_direction,
                "side_id": side_id,
                "remote_score": score,
            }
        )
    selected: list[dict[str, Any]] = []
    for rows in by_direction.values():
        rows.sort(
            key=lambda row: (
                -float(row["remote_score"]),
                float(row["root_s"]),
            )
        )
        selected.extend(rows[:per_direction])
    selected.sort(key=lambda row: float(row["root_s"]))
    return selected


def _support_candidates(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    family_id: str,
    seed: int,
    plan_contract: Mapping[str, Any],
) -> list[list[dict[str, Any]]]:
    if family_id == "SW-2_axis_penetrating":
        return []
    groups: list[list[dict[str, Any]]] = []
    relation_emphasis = str(
        morphology["instance_priors"]["flower_relation_emphasis"]
    )
    for flower in analysis["flowers"]:
        flower_id = str(flower["flower_id"])
        candidates: list[dict[str, Any]] = []
        flower_center = tuple(float(value) for value in flower["center"])
        if family_id == "SW-1_valley_filling":
            s_ranges = flower["support_context_s_ranges"]
            s_values: list[float] = []
            for start, end in s_ranges:
                s_values.extend(
                    [
                        float(start),
                        (float(start) + float(end)) * 0.5,
                        float(end),
                    ]
                )
            root_rows: list[dict[str, Any]] = []
            for root_s in sorted({round(value % 1.0, 7) for value in s_values}):
                sample = _sample_at_s(analysis, root_s)
                root = _periodic_point_near(sample["point"], flower_center)
                tangent = tuple(float(value) for value in sample["tangent"])
                target = _ellipse_boundary_toward(flower, root)
                to_target = _unit(_sub(target, root))
                root_rows.append(
                    {
                        "root_s": root_s,
                        "root": root,
                        "target": target,
                        "to_target": to_target,
                        "parent_tangent": tangent,
                        "direction_path_points": (root, target),
                        "outward_normal_alignment": abs(
                            _dot(_normal(tangent), to_target)
                        ),
                        "parent_clearance_after_initial_departure": (
                            _direction_path_parent_clearance(
                                analysis,
                                (root, target),
                                start_fraction=float(
                                    plan_contract[
                                        "initial_layout_constraints"
                                    ][
                                        "parent_clearance_measurement_start_fraction"
                                    ]
                                ),
                            )
                        ),
                        "reach": _distance(root, target),
                        "arc_distance": _circular_s_distance(
                            root_s,
                            float(flower["nearest_backbone_s"]),
                        ),
                        "arc_direction": "near_flower_context",
                        "side_id": str(flower["normal_side"]),
                        "remote_score": 0.0,
                    }
                )
        else:
            s_ranges = []
            root_rows = _remote_terminal_support_samples(
                analysis,
                flower,
                plan_contract,
            )
        for variant, root_row in enumerate(root_rows, start=1):
            root_s = float(root_row["root_s"])
            root = tuple(float(value) for value in root_row["root"])
            target = tuple(float(value) for value in root_row["target"])
            to_target = tuple(float(value) for value in root_row["to_target"])
            parent_tangent = tuple(
                float(value) for value in root_row["parent_tangent"]
            )
            direction_path_points = tuple(
                tuple(float(value) for value in point)
                for point in root_row["direction_path_points"]
            )
            length_hint = float(root_row["reach"])
            if family_id == "SW-1_valley_filling":
                role = "flower_support"
                sweep_kind = "valley_flank_support"
                terminal_kind = "flower_support_transition"
                relation_kind = (
                    "support_and_wrap"
                    if "wrap" in relation_emphasis
                    else "support"
                )
                base_score = 1.4 - abs(root_s - float(flower["nearest_backbone_s"]))
            else:
                role = "terminal_flower_support"
                sweep_kind = "remote_below_flower_terminal_support"
                terminal_kind = "flower_terminal"
                relation_kind = "terminal_flower"
                base_score = 1.2 + float(root_row["remote_score"])
            radius = 0.034
            invalid_other_flower = any(
                other["flower_id"] != flower_id
                and any(
                    _segment_enters_flower(
                        start,
                        end,
                        other,
                        radius=radius,
                    )
                    for start, end in zip(
                        direction_path_points,
                        direction_path_points[1:],
                    )
                )
                for other in analysis["flowers"]
            )
            if invalid_other_flower:
                continue
            candidate_id = f"support_{flower_id}_{variant}"
            seed_preference = _stable_random(
                seed,
                analysis["prototype_id"],
                candidate_id,
            ).uniform(-0.16, 0.16)
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "required_group": f"flower_relation:{flower_id}",
                    "role": role,
                    "semantic_function": relation_kind,
                    "root_s": root_s,
                    "root": root,
                    "side_id": str(root_row["side_id"]),
                    "vertical_side": str(flower["vertical_relation"]).replace(
                        "_backbone", ""
                    ),
                    "parent_tangent": parent_tangent,
                    "sweep_direction": to_target,
                    "end_hint": target,
                    "direction_path_points": direction_path_points,
                    "outward_normal_alignment": float(
                        root_row["outward_normal_alignment"]
                    ),
                    "parent_clearance_after_initial_departure": float(
                        root_row["parent_clearance_after_initial_departure"]
                    ),
                    "length_hint": length_hint,
                    "length_class": (
                        "flower_reach"
                        if family_id == "SW-1_valley_filling"
                        else "long_terminal_flower_reach"
                    ),
                    "occupancy_radius": radius,
                    "root_interval_ref": (
                        {
                            "kind": "flower_support_context",
                            "flower_id": flower_id,
                            "s_ranges": s_ranges,
                        }
                        if family_id == "SW-1_valley_filling"
                        else {
                            "kind": "remote_terminal_support_corridor",
                            "flower_id": flower_id,
                            "source_mount_s": _round(root_s),
                            "nearest_flower_mount_s": _round(
                                flower["nearest_backbone_s"]
                            ),
                            "arc_distance_from_nearest_flower_mount": _round(
                                root_row["arc_distance"]
                            ),
                            "arc_direction": root_row["arc_direction"],
                            "near_flower_stub_allowed": False,
                            "route_below_flower": True,
                            "contact_side": "underside",
                        }
                    ),
                    "flower_relation_intents": [
                        {
                            "flower_id": flower_id,
                            "relation": relation_kind,
                            "approach": (
                                "nearest_protection_boundary"
                                if family_id == "SW-1_valley_filling"
                                else "below_flower_corridor_to_underside"
                            ),
                            "flower_core_entry_allowed": False,
                            "origin_policy": (
                                "near_flower_support_context"
                                if family_id == "SW-1_valley_filling"
                                else "remote_parent_mount_long_terminal_reach"
                            ),
                            "root_to_flower_boundary_reach": _round(length_hint),
                            **(
                                {
                                    "route_policy": "below_flower_corridor",
                                    "contact_policy": "underside_flower_boundary",
                                    "under_approach_waypoint": _round_point(
                                        root_row["under_approach_waypoint"]
                                    ),
                                    "contact_point": _round_point(target),
                                }
                                if family_id == "SW-3_tangent_terminal"
                                else {}
                            ),
                        }
                    ],
                    "reserve_zone_refs": [f"flower_reserve:{flower_id}"],
                    "terminal_kind": terminal_kind,
                    "sweep_kind": sweep_kind,
                    "child_rhythm": _child_rhythm(morphology, role=role),
                    "base_score": base_score,
                    "seed_preference": seed_preference,
                    "source_interval_capacity": (
                        "flower_relation_required"
                        if family_id == "SW-1_valley_filling"
                        else "remote_terminal_corridor_required"
                    ),
                }
            )
        if not candidates:
            raise PlanningFailure(
                "required_flower_relation_unavailable",
                "no valid symbolic support candidate exists for a required flower",
                {
                    "prototype_id": analysis["prototype_id"],
                    "family_id": family_id,
                    "flower_id": flower_id,
                    "seed": seed,
                },
            )
        groups.append(candidates)
    return groups


def _probe_rows_for_region(
    analysis: Mapping[str, Any],
    region: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    probes = analysis["space_analysis"]["probes"]
    ordered: list[Mapping[str, Any]] = []
    seen_periodic_s: set[float] = set()
    for start, end in region["s_ranges"]:
        rows = sorted(
            (
                row
                for row in probes
                if row["side_id"] == region["side_id"]
                and row["candidate_for_l1"] is True
                and float(start) - 1e-9 <= float(row["s"]) <= float(end) + 1e-9
            ),
            key=lambda row: float(row["s"]),
        )
        for row in rows:
            periodic_s = round(float(row["s"]) % 1.0, 7)
            if periodic_s in seen_periodic_s:
                continue
            seen_periodic_s.add(periodic_s)
            ordered.append(row)
    return ordered


def _quantile_rows(
    rows: Sequence[Mapping[str, Any]],
    count: int = 3,
) -> list[Mapping[str, Any]]:
    if not rows:
        return []
    if len(rows) <= count:
        return list(rows)
    indices = {
        round((position + 1) * (len(rows) - 1) / (count + 1))
        for position in range(count)
    }
    return [rows[index] for index in sorted(indices)]


def _optional_candidates(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    family_id: str,
    seed: int,
    plan_contract: Mapping[str, Any],
    *,
    root_sample_count_override: int | None = None,
) -> list[dict[str, Any]]:
    density_class, _, _ = _density_style(morphology)
    base_length, length_class = SWEEP_LENGTHS[density_class]
    constraints = plan_contract["initial_layout_constraints"]
    minimum_outward_alignment = float(
        constraints["minimum_outward_normal_alignment"]
    )
    minimum_parent_clearance = float(
        constraints["minimum_parent_clearance_after_initial_departure"]
    )
    parent_clearance_start = float(
        constraints["parent_clearance_measurement_start_fraction"]
    )
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    if root_sample_count_override is not None:
        root_sample_count = max(1, int(root_sample_count_override))
    elif family_id == "SW-2_axis_penetrating":
        root_sample_count = 10
    elif family_id == "SW-3_tangent_terminal":
        root_sample_count = 5
    else:
        root_sample_count = 2
    for region in analysis["candidate_l1_attachment_regions"]:
        for root_variant, probe in enumerate(
            _quantile_rows(
                _probe_rows_for_region(analysis, region),
                count=root_sample_count,
            ),
            start=1,
        ):
            sample_index = int(probe["sample_index"])
            key = str(probe["side_id"]), sample_index
            if key in seen:
                continue
            seen.add(key)
            root = tuple(float(value) for value in probe["root"])
            tangent = tuple(
                float(value)
                for value in analysis["backbone"]["samples"][sample_index]["tangent"]
            )
            normal = tuple(float(value) for value in probe["direction"])
            for direction_variant, tangent_sign in (("forward", 1.0), ("reverse", -1.0)):
                candidate_id = (
                    f"sweep_{region['region_id']}_{root_variant}_"
                    f"{direction_variant}_{probe['probe_id']}"
                )
                rng = _stable_random(seed, analysis["prototype_id"], candidate_id)
                tangent_reference = _mul(tangent, tangent_sign)
                if family_id == "SW-2_axis_penetrating":
                    tangent_weight, normal_weight = 0.28, 0.96
                    semantic_function = "axis_flank_primary_sweep"
                elif family_id == "SW-1_valley_filling":
                    tangent_weight, normal_weight = 0.30, 0.95
                    semantic_function = "valley_space_primary_sweep"
                else:
                    tangent_weight, normal_weight = 0.30, 0.95
                    semantic_function = "subordinate_primary_sweep"
                sweep_direction = _unit(
                    _add(
                        _mul(tangent_reference, tangent_weight),
                        _mul(normal, normal_weight),
                    )
                )
                outward_alignment = _dot(normal, sweep_direction)
                if outward_alignment < minimum_outward_alignment:
                    continue
                clearance = float(probe["clearance"])
                length_hint = min(
                    clearance * 0.88,
                    base_length * rng.uniform(0.88, 1.12),
                )
                if length_hint < 0.115:
                    continue
                end_hint = _add(root, _mul(sweep_direction, length_hint))
                direction_path_points = (root, end_hint)
                parent_clearance = _direction_path_parent_clearance(
                    analysis,
                    direction_path_points,
                    start_fraction=parent_clearance_start,
                )
                if parent_clearance < minimum_parent_clearance:
                    continue
                radius = 0.036 if density_class in {"dense", "moderate"} else 0.041
                if any(
                    _segment_enters_flower(
                        root,
                        end_hint,
                        flower,
                        radius=radius,
                    )
                    for flower in analysis["flowers"]
                ):
                    continue
                base_score = (
                    0.9
                    + clearance * 1.7
                    + 0.12 * int(region["maximum_child_level_supported"])
                )
                candidates.append(
                    {
                        "candidate_id": candidate_id,
                        "required_group": None,
                        "role": "primary_sweep",
                        "semantic_function": semantic_function,
                        "root_s": float(probe["s"]),
                        "root": root,
                        "side_id": str(probe["side_id"]),
                        "vertical_side": str(probe["vertical_side"]),
                        "parent_tangent": tangent,
                        "sweep_direction": sweep_direction,
                        "end_hint": end_hint,
                        "direction_path_points": direction_path_points,
                        "outward_normal_alignment": outward_alignment,
                        "parent_clearance_after_initial_departure": parent_clearance,
                        "length_hint": length_hint,
                        "length_class": length_class,
                        "occupancy_radius": radius,
                        "root_interval_ref": {
                            "kind": "candidate_l1_attachment_interval",
                            "region_id": region["region_id"],
                            "side_id": region["side_id"],
                            "s_ranges": region["s_ranges"],
                        },
                        "flower_relation_intents": [],
                        "reserve_zone_refs": [
                            f"flower_reserve:{flower['flower_id']}"
                            for flower in analysis["flowers"]
                        ],
                        "terminal_kind": "open_symbolic_tip",
                        "sweep_kind": "primary_sweep",
                        "child_rhythm": _child_rhythm(
                            morphology,
                            role="primary_sweep",
                        ),
                        "base_score": base_score,
                        "seed_preference": rng.uniform(-0.24, 0.24),
                        "source_interval_capacity": region["capacity_class"],
                    }
                )
    return candidates


def _density_bin_index(root_s: float, bin_count: int = 8) -> int:
    return min(bin_count - 1, int((float(root_s) % 1.0) * bin_count))


def _candidate_intent_polyline(
    candidate: Mapping[str, Any],
) -> tuple[Point, ...]:
    explicit_points = candidate.get("direction_path_points")
    if explicit_points:
        return tuple(
            tuple(float(value) for value in point)
            for point in explicit_points
        )
    root = tuple(float(value) for value in candidate["root"])
    end_hint = tuple(float(value) for value in candidate["end_hint"])
    return root, end_hint


def _symbolic_intent_clearance(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
) -> float:
    a_points = _candidate_intent_polyline(a)
    b_points = _candidate_intent_polyline(b)
    return min(
        _segment_distance(a0, a1, b0, b1)
        for b_shift in (-1.0, 0.0, 1.0)
        for shifted_b_points in (
            tuple((point[0] + b_shift, point[1]) for point in b_points),
        )
        for a0, a1 in zip(a_points, a_points[1:])
        for b0, b1 in zip(shifted_b_points, shifted_b_points[1:])
    )


def _candidates_conflict(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    layout_policy: Mapping[str, Any],
) -> bool:
    root_distance = _circular_s_distance(float(a["root_s"]), float(b["root_s"]))
    if root_distance < float(layout_policy["minimum_periodic_root_spacing"]):
        return True
    if (
        layout_policy["one_selected_root_per_density_bin"]
        and _density_bin_index(float(a["root_s"]))
        == _density_bin_index(float(b["root_s"]))
    ):
        return True
    if root_distance < float(layout_policy["direction_neighborhood_s"]):
        direction_difference = _angle_degrees(
            tuple(float(value) for value in a["sweep_direction"]),
            tuple(float(value) for value in b["sweep_direction"]),
        )
        if direction_difference > float(
            layout_policy["maximum_local_direction_difference_degrees"]
        ):
            return True
    clearance = _symbolic_intent_clearance(a, b)
    required = max(
        float(layout_policy["minimum_symbolic_intent_clearance"]),
        float(layout_policy["occupancy_radius_clearance_factor"])
        * (
            float(a["occupancy_radius"])
            + float(b["occupancy_radius"])
        ),
    )
    if clearance < required:
        return True
    return False


def _set_score(
    candidates: Sequence[Mapping[str, Any]],
    morphology: Mapping[str, Any],
    role_density_field: Mapping[str, Any],
    layout_policy: Mapping[str, Any],
) -> tuple[float, dict[str, float]]:
    roots = [float(candidate["root_s"]) for candidate in candidates]
    base = sum(
        float(candidate["base_score"]) + float(candidate["seed_preference"])
        for candidate in candidates
    )
    if len(roots) > 1:
        nearest = [
            min(
                _circular_s_distance(root, other)
                for other_index, other in enumerate(roots)
                if other_index != root_index
            )
            for root_index, root in enumerate(roots)
        ]
        spacing = sum(nearest) / len(nearest)
    else:
        spacing = 0.5
    minimum_spacing = min(nearest) if len(roots) > 1 else 0.5
    coverage = len({min(3, int((root % 1.0) * 4)) for root in roots}) / 4.0
    density_bins = role_density_field["bins"]
    density_fit = sum(
        float(density_bins[_density_bin_index(root)]["target_density"])
        for root in roots
    ) / max(1, len(roots))
    local_direction_differences = [
        _angle_degrees(
            tuple(float(value) for value in a["sweep_direction"]),
            tuple(float(value) for value in b["sweep_direction"]),
        )
        for a, b in itertools.combinations(candidates, 2)
        if _circular_s_distance(float(a["root_s"]), float(b["root_s"]))
        < float(layout_policy["direction_neighborhood_s"])
    ]
    if local_direction_differences:
        direction_coherence = max(
            0.0,
            1.0
            - sum(local_direction_differences)
            / len(local_direction_differences)
            / float(layout_policy["maximum_local_direction_difference_degrees"]),
        )
    else:
        direction_coherence = 1.0
    pairwise_intent_clearances = [
        _symbolic_intent_clearance(a, b)
        for a, b in itertools.combinations(candidates, 2)
    ]
    minimum_intent_clearance = min(
        pairwise_intent_clearances,
        default=1.0,
    )
    upper = sum(candidate["vertical_side"] == "upper" for candidate in candidates)
    lower = sum(candidate["vertical_side"] == "lower" for candidate in candidates)
    rhythm = str(morphology["instance_priors"]["side_rhythm"])
    difference = abs(upper - lower)
    if "balanced" in rhythm or "alternation" in rhythm:
        side_rhythm = max(-1.0, 1.0 - difference / max(1, len(candidates)))
    elif "asymmetric" in rhythm:
        side_rhythm = min(1.0, difference / max(1, len(candidates)))
    elif "upper_side_emphasis" in rhythm:
        side_rhythm = (upper - lower) / max(1, len(candidates))
    else:
        side_rhythm = 0.0
    total = (
        base
        + spacing * 1.8
        + minimum_spacing * 2.0
        + coverage * 0.8
        + density_fit * 1.15
        + direction_coherence * 0.75
        + side_rhythm * 0.45
    )
    return total, {
        "candidate_quality": _round(base, 6),
        "root_spacing": _round(spacing, 6),
        "minimum_root_spacing": _round(minimum_spacing, 6),
        "repeat_coverage": _round(coverage, 6),
        "role_density_fit": _round(density_fit, 6),
        "local_direction_coherence": _round(direction_coherence, 6),
        "maximum_local_direction_difference": _round(
            max(local_direction_differences, default=0.0),
            6,
        ),
        "minimum_symbolic_intent_clearance": _round(
            minimum_intent_clearance,
            6,
        ),
        "symbolic_intent_crossing_count": 0.0,
        "side_rhythm": _round(side_rhythm, 6),
        "total": _round(total, 6),
    }


def _global_select(
    required_groups: Sequence[Sequence[Mapping[str, Any]]],
    optional_candidates: Sequence[Mapping[str, Any]],
    optional_count: int,
    morphology: Mapping[str, Any],
    role_density_field: Mapping[str, Any],
    layout_policy: Mapping[str, Any],
    *,
    prototype_id: str,
    family_id: str,
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(optional_candidates) < optional_count:
        raise PlanningFailure(
            "insufficient_complete_branchunit_candidates",
            "not enough complete optional BranchUnit candidates for the density prior",
            {
                "prototype_id": prototype_id,
                "family_id": family_id,
                "seed": seed,
                "required_optional_count": optional_count,
                "available_optional_count": len(optional_candidates),
            },
        )
    required_products: Iterable[tuple[Mapping[str, Any], ...]]
    required_products = (
        itertools.product(*required_groups) if required_groups else [tuple()]
    )
    best_set: list[dict[str, Any]] | None = None
    best_score = -math.inf
    best_components: dict[str, float] = {}
    evaluated_set_count = 0
    valid_set_count = 0
    conflict_cache: dict[tuple[str, str], bool] = {}

    def conflicts(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
        a_id = str(a["candidate_id"])
        b_id = str(b["candidate_id"])
        key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
        if key not in conflict_cache:
            conflict_cache[key] = _candidates_conflict(a, b, layout_policy)
        return conflict_cache[key]

    for required_choice in required_products:
        if any(
            conflicts(a, b)
            for a, b in itertools.combinations(required_choice, 2)
        ):
            continue
        compatible_optional = [
            candidate
            for candidate in optional_candidates
            if not any(
                conflicts(candidate, required)
                for required in required_choice
            )
        ]
        for optional_choice in itertools.combinations(
            compatible_optional,
            optional_count,
        ):
            evaluated_set_count += 1
            combined = [*required_choice, *optional_choice]
            if any(
                conflicts(a, b)
                for a, b in itertools.combinations(combined, 2)
            ):
                continue
            valid_set_count += 1
            score, components = _set_score(
                combined,
                morphology,
                role_density_field,
                layout_policy,
            )
            lexical = tuple(str(candidate["candidate_id"]) for candidate in combined)
            best_lexical = (
                tuple(str(candidate["candidate_id"]) for candidate in best_set)
                if best_set
                else tuple()
            )
            if score > best_score + 1e-12 or (
                abs(score - best_score) <= 1e-12 and lexical < best_lexical
            ):
                best_score = score
                best_components = components
                best_set = [dict(candidate) for candidate in combined]
    if best_set is None:
        raise PlanningFailure(
            "no_globally_compatible_branchunit_set",
            "complete candidates exist but no exact global set satisfies unit clearance",
            {
                "prototype_id": prototype_id,
                "family_id": family_id,
                "seed": seed,
                "required_group_count": len(required_groups),
                "optional_candidate_count": len(optional_candidates),
                "required_optional_count": optional_count,
                "evaluated_set_count": evaluated_set_count,
                "valid_set_count": valid_set_count,
            },
        )
    return best_set, {
        "selection_method": "exhaustive_complete_branchunit_set_scoring",
        "single_forward_plan": True,
        "validation_guided_retry": False,
        "initial_layout_policy": dict(layout_policy),
        "role_density_field_consumed": True,
        "required_group_count": len(required_groups),
        "required_candidate_count": sum(len(group) for group in required_groups),
        "optional_candidate_count": len(optional_candidates),
        "target_optional_unit_count": optional_count,
        "evaluated_set_count": evaluated_set_count,
        "valid_set_count": valid_set_count,
        "selected_candidate_ids": [
            candidate["candidate_id"] for candidate in best_set
        ],
        "objective": best_components,
    }


def _serialize_branch_unit(
    candidate: Mapping[str, Any],
    *,
    branch_unit_id: str,
    prototype_id: str,
    family_id: str,
    seed: int,
    analysis_digest: str,
    morphology_digest: str,
) -> dict[str, Any]:
    root = tuple(float(value) for value in candidate["root"])
    end_hint = tuple(float(value) for value in candidate["end_hint"])
    tangent = tuple(float(value) for value in candidate["parent_tangent"])
    direction = tuple(float(value) for value in candidate["sweep_direction"])
    path_points = _candidate_intent_polyline(candidate)
    return {
        "branch_unit_id": branch_unit_id,
        "parent_ref": {
            "kind": "backbone",
            "prototype_id": prototype_id,
            "mount_s": _round(candidate["root_s"]),
            "mount_point": _round_point(root),
        },
        "family_id": family_id,
        "structural_role": candidate["role"],
        "semantic_function": candidate["semantic_function"],
        "root_interval_ref": candidate["root_interval_ref"],
        "root_tangent_intent": {
            "parent_tangent_reference": _round_point(tangent),
            "parent_tangent_is_reference_only": True,
            "must_start_along_parent_tangent": False,
            "direct_outward_departure_required": True,
            "curve_compilation_deferred": True,
        },
        "primary_sweep_intent": {
            "kind": candidate["sweep_kind"],
            "eventual_direction": _round_point(direction),
            "length_class": candidate["length_class"],
            "length_hint": _round(candidate["length_hint"]),
            "end_hint": _round_point(end_hint),
            "end_hint_is_symbolic_not_curve_geometry": True,
            "directional_path_points": [
                _round_point(point) for point in path_points
            ],
        },
        "directional_layout_intent": {
            "type": "directional_polyline_not_branch_geometry",
            "path_points": [_round_point(point) for point in path_points],
            "segment_count": len(path_points) - 1,
            "immediate_outward_departure": True,
            "outward_normal_alignment": _round(
                candidate["outward_normal_alignment"],
                6,
            ),
            "parent_clearance_after_initial_departure": _round(
                candidate["parent_clearance_after_initial_departure"],
                6,
            ),
            "position_distance_direction_only": True,
            "branch_shape_simulation": False,
        },
        "flower_relation_intents": candidate["flower_relation_intents"],
        "child_rhythm_envelope": candidate["child_rhythm"],
        "occupancy_envelope": {
            "type": "symbolic_directional_corridor_polyline",
            "start": _round_point(root),
            "end_hint": _round_point(end_hint),
            "path_points": [_round_point(point) for point in path_points],
            "radius": _round(candidate["occupancy_radius"]),
            "used_for_stage3_unit_clearance_only": True,
        },
        "reserve_zone_refs": candidate["reserve_zone_refs"],
        "terminal_intent": {
            "kind": candidate["terminal_kind"],
            "leaves_present": False,
            "buds_present": False,
            "curl_head_present": False,
            "geometry_deferred_to_stage_4": True,
        },
        "provenance": {
            "candidate_id": candidate["candidate_id"],
            "source_interval_capacity": candidate["source_interval_capacity"],
            "analysis_digest": analysis_digest,
            "morphology_digest": morphology_digest,
            "seed": seed,
            "prototype_specific_topology_rule_used": False,
            "legacy_branch_geometry_used": False,
        },
    }


def generate_dynamic_branch_plan(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    plan_contract: Mapping[str, Any],
    *,
    seed: int,
    raw_candidate_index: int = 1,
) -> dict[str, Any]:
    """Generate exactly one deterministic symbolic plan for one task."""

    prototype_id, family_id = _validate_inputs(
        analysis,
        morphology,
        plan_contract,
        seed,
    )
    if raw_candidate_index != 1:
        raise PlanningFailure(
            "raw_candidate_index_violation",
            "stage 3 permits exactly one raw candidate per prototype and seed",
            {
                "prototype_id": prototype_id,
                "seed": seed,
                "raw_candidate_index": raw_candidate_index,
            },
        )
    density_class, optional_count, _ = _density_style(morphology)
    layout_policy = _layout_policy(morphology, plan_contract)
    role_density_field = _role_density_field(analysis, morphology, family_id)
    required_groups = _support_candidates(
        analysis,
        morphology,
        family_id,
        seed,
        plan_contract,
    )
    optional_candidates = _optional_candidates(
        analysis,
        morphology,
        family_id,
        seed,
        plan_contract,
    )
    selected, selection = _global_select(
        required_groups,
        optional_candidates,
        optional_count,
        morphology,
        role_density_field,
        layout_policy,
        prototype_id=prototype_id,
        family_id=family_id,
        seed=seed,
    )
    selected.sort(
        key=lambda candidate: (
            float(candidate["root_s"]),
            str(candidate["candidate_id"]),
        )
    )
    analysis_digest = str(analysis["analysis_digest"])
    morphology_digest = str(morphology["morphology_digest"])
    branch_units = [
        _serialize_branch_unit(
            candidate,
            branch_unit_id=f"BU{index:02d}",
            prototype_id=prototype_id,
            family_id=family_id,
            seed=seed,
            analysis_digest=analysis_digest,
            morphology_digest=morphology_digest,
        )
        for index, candidate in enumerate(selected, start=1)
    ]
    required_flower_relations = {
        relation["flower_id"]
        for unit in branch_units
        for relation in unit["flower_relation_intents"]
    }
    if family_id != "SW-2_axis_penetrating" and required_flower_relations != {
        flower["flower_id"] for flower in analysis["flowers"]
    }:
        raise PlanningFailure(
            "flower_relation_coverage_failure",
            "selected set does not cover every required flower relation",
            {
                "prototype_id": prototype_id,
                "family_id": family_id,
                "seed": seed,
                "covered_flower_ids": sorted(required_flower_relations),
            },
        )
    if family_id == "SW-2_axis_penetrating" and not any(
        unit["structural_role"] == "primary_sweep" for unit in branch_units
    ):
        raise PlanningFailure(
            "axis_primary_sweep_missing",
            "axis-penetrating family requires a primary sweep",
            {"prototype_id": prototype_id, "seed": seed},
        )
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "policy_id": POLICY_ID,
        "plan_contract_id": plan_contract["contract_id"],
        "plan_id": f"{prototype_id}__seed_{seed}__raw_1",
        "task_id": f"{prototype_id}__seed_{seed}__raw_1",
        "prototype_id": prototype_id,
        "seed": seed,
        "raw_candidate_index": raw_candidate_index,
        "coordinate_system": analysis["coordinate_system"],
        "input_refs": {
            "strict_p0_digest": analysis["strict_p0_digest"],
            "prototype_analysis_digest": analysis_digest,
            "morphology_digest": morphology_digest,
        },
        "classification": morphology["classification"],
        "instance_priors": {
            "density_class": density_class,
            "primary_sweep_class": morphology["instance_priors"][
                "primary_sweep_class"
            ],
            "side_rhythm": morphology["instance_priors"]["side_rhythm"],
            "flower_relation_emphasis": morphology["instance_priors"][
                "flower_relation_emphasis"
            ],
            "source_observation_counts_used_as_fixed_targets": False,
        },
        "family_invariants": plan_contract["family_invariants"][family_id],
        "role_density_field": role_density_field,
        "initial_layout_policy": {
            **layout_policy,
            "constraints_applied_before_curve_compilation": True,
            "root_spacing_is_hard_constraint": True,
            "local_direction_difference_is_hard_constraint": True,
            "density_bin_capacity_is_hard_constraint": True,
            "symbolic_intent_crossing_is_hard_failure": True,
            "parent_backbone_hugging_is_hard_failure": True,
        },
        "branch_units": branch_units,
        "global_selection": selection,
        "planning_contract": {
            "complete_branchunit_is_primary_primitive": True,
            "prototype_id_specific_topology_used": False,
            "legacy_branch_geometry_used": False,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
            "raw_plan_count_for_task": 1,
        },
        "stage_boundary": {
            "candidate_slots_are_symbolic": True,
            "dynamic_branch_plan_present": True,
            "directional_layout_only": True,
            "branch_shape_simulation_present": False,
            "curve_geometry_present": False,
            "leaves_present": False,
            "buds_present": False,
            "curl_heads_present": False,
            "editor_integration_present": False,
        },
        "review": {
            "status": "plan_pending_review",
            "allowed_states": list(REVIEW_STATES),
            "visual_gate_required": True,
            "criteria": plan_contract["review"]["criteria"],
            "stage_4_unlocked": False,
        },
    }
    core["plan_digest"] = _canonical_digest(core)
    return core
