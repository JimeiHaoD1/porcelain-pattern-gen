#!/usr/bin/env python3
"""Compile long, visibly intertwined complete BranchUnits from v4 macro plans."""

from __future__ import annotations

import itertools
import math
from typing import Any, Mapping, Sequence

import dynamic_branch_unit_curve_v2 as v2


Point = v2.Point
EPSILON = v2.EPSILON
SCHEMA = "dynamic_branch_intertwined_unit_curve_candidate_v3"
CONTRACT_SCHEMA = "dynamic_branch_stage4_intertwined_unit_contract_v3"


class IntertwinedCompilationFailure(RuntimeError):
    """Fatal v3 input or compilation error."""


def _signed_angle(first: Point, second: Point) -> float:
    first = v2._unit(first)
    second = v2._unit(second)
    return math.degrees(
        math.atan2(v2._cross(first, second), v2._dot(first, second))
    )


def _rotate_toward(
    reference: Point,
    target: Point,
    opening_degrees: float,
) -> Point:
    turn = _signed_angle(reference, target)
    sign = 1.0 if turn >= 0.0 else -1.0
    return v2._unit(v2._rotate(reference, sign * opening_degrees))


def _elevated_quadratic(
    start: Point,
    control: Point,
    end: Point,
) -> dict[str, list[float]]:
    return v2._cubic(
        start,
        v2._add(start, v2._mul(v2._sub(control, start), 2.0 / 3.0)),
        v2._add(end, v2._mul(v2._sub(control, end), 2.0 / 3.0)),
        end,
    )


def _two_cubic_sweep(
    root: Point,
    tip: Point,
    entry_tangent: Point,
    exit_tangent: Point,
    *,
    start_arm_ratio: float,
    end_arm_ratio: float,
    arm_length_basis: float | None = None,
    midpoint_bow_ratio: float = 0.0,
    midpoint_bow_sign: int = 1,
    reinforce_existing_bow: bool = False,
) -> list[dict[str, list[float]]]:
    chord = v2._distance(root, tip)
    arm_basis = max(
        chord,
        0.0 if arm_length_basis is None else float(arm_length_basis),
    )
    first_control = v2._add(
        root,
        v2._mul(entry_tangent, arm_basis * start_arm_ratio),
    )
    second_control = v2._sub(
        tip,
        v2._mul(exit_tangent, arm_basis * end_arm_ratio),
    )
    midpoint = v2._mul(v2._add(first_control, second_control), 0.5)
    if abs(midpoint_bow_ratio) > EPSILON:
        chord_direction = v2._unit(v2._sub(tip, root))
        chord_normal = (-chord_direction[1], chord_direction[0])
        offset_sign = 1 if midpoint_bow_sign >= 0 else -1
        existing_side = v2._cross(
            chord_direction,
            v2._sub(midpoint, root),
        )
        if reinforce_existing_bow and abs(existing_side) > EPSILON:
            offset_sign = 1 if existing_side >= 0.0 else -1
        midpoint = v2._add(
            midpoint,
            v2._mul(
                chord_normal,
                arm_basis
                * abs(midpoint_bow_ratio)
                * offset_sign,
            ),
        )
    return [
        _elevated_quadratic(root, first_control, midpoint),
        _elevated_quadratic(midpoint, second_control, tip),
    ]


def _safe_sw1_tip(
    analysis: Mapping[str, Any],
    root: Point,
    direction: Point,
    desired_length: float,
    fallback_tip: Point,
) -> Point:
    height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    safe = 0.0
    for index in range(1, 81):
        length = desired_length * index / 80.0
        point = v2._add(root, v2._mul(direction, length))
        if (
            point[0] < -0.16
            or point[0] > 1.16
            or point[1] < 0.035
            or point[1] > height - 0.035
            or any(
                v2._inside_flower(point, flower, padding=1.02)
                for flower in analysis["flowers"]
            )
        ):
            break
        safe = length
    fallback_length = v2._distance(root, fallback_tip)
    if safe <= fallback_length:
        return fallback_tip
    return v2._add(root, v2._mul(direction, safe))


def _primary_record(
    unit: Mapping[str, Any],
    cubics: Sequence[Mapping[str, Sequence[float]]],
    source_points: Sequence[Point],
    *,
    shape_mode: str,
    entry_opening: float,
    exit_release: float,
    macro_tip: Point,
    final_tip: Point,
    shape_scale: float,
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
        "source_stage3_path_points": [
            v2._point_json(point) for point in source_points
        ],
        "flower_relation_intents": list(unit["flower_relation_intents"]),
        "compiler_trace": {
            "compiler": "long_intertwined_primary_sweep_v3",
            "shape_mode": shape_mode,
            "entry_opening_degrees": v2._round(entry_opening),
            "exit_release_degrees": v2._round(exit_release),
            "macro_tip": v2._point_json(macro_tip),
            "final_tip": v2._point_json(final_tip),
            "shape_scale": v2._round(shape_scale),
            "macro_direction_preserved": True,
            "narrow_occupancy_bow_cap_used": False,
        },
    }
    curve["shape_metrics"] = v2._shape_metrics(curve)
    return curve


def _precision_context_penalty(
    curve: Mapping[str, Any],
    *,
    analysis: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[float, dict[str, float]]:
    points = v2._curve_points(curve, 72)
    level = int(curve["hierarchy_level"])
    trace = {
        "precision_shape": 0.0,
        "precision_flower": 0.0,
        "precision_backbone": 0.0,
        "precision_bounds": 0.0,
    }
    if _shape_issue(curve, contract) is not None:
        trace["precision_shape"] += 180.0
    target_flower_ids = v2._target_flower_ids(curve)
    for flower in analysis["flowers"]:
        flower_id = str(flower["flower_id"])
        if level == 1 and flower_id in target_flower_ids:
            checked = points[:-8]
            intrusion_count = sum(
                v2._inside_flower(
                    point,
                    flower,
                    protection=False,
                )
                for point in checked
            )
        else:
            intrusion_count = sum(
                v2._inside_flower(point, flower)
                for point in points
            )
        if intrusion_count:
            trace["precision_flower"] += (
                3200.0 + intrusion_count * 24.0
            )
    backbone = [
        v2._point(row["point"])
        for row in analysis["backbone"]["samples"]
    ]
    checked_backbone = points[8:] if level == 1 else points
    if v2._polyline_crosses(checked_backbone, backbone):
        trace["precision_backbone"] += 3600.0
    height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    outside_count = sum(
        point[0] < -0.24
        or point[0] > 1.24
        or point[1] < -0.04
        or point[1] > height + 0.04
        for point in points
    )
    if outside_count:
        trace["precision_bounds"] += 1800.0 + outside_count * 20.0
    return sum(trace.values()), trace


def _sw3_intertwined_primary(
    unit: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    bow_sign: int,
    shape_scale: float,
) -> dict[str, Any]:
    path_points = [
        v2._point(point)
        for point in unit["directional_layout_intent"]["path_points"]
    ]
    if len(path_points) != 3:
        raise IntertwinedCompilationFailure(
            f'{unit["branch_unit_id"]} SW3 support needs a three-point route'
        )
    root, waypoint, tip = path_points
    first_vector = v2._sub(waypoint, root)
    second_vector = v2._sub(tip, waypoint)
    first_direction = v2._unit(first_vector)
    second_direction = v2._unit(second_vector)
    parent = v2._oriented_parent_tangent(
        v2._point(
            unit["root_tangent_intent"]["parent_tangent_reference"]
        ),
        first_direction,
    )
    opening = 44.0 + 10.0 * v2._u01(
        int(plan["seed"]),
        unit["branch_unit_id"],
        "sw3_entry_opening_v3",
    )
    entry = _rotate_toward(parent, first_direction, opening)
    joined = v2._unit(v2._add(first_direction, second_direction))
    side = 1 if bow_sign >= 0 else -1
    radius = float(unit["occupancy_envelope"]["radius"])
    first_length = v2._distance(root, waypoint)
    second_length = v2._distance(waypoint, tip)
    first_bias = (
        side
        * min(radius * 2.00, first_length * 0.32)
        * shape_scale
    )
    second_bias = (
        -side
        * min(radius * 1.20, second_length * 0.22)
        * shape_scale
    )
    first_normal = (-first_direction[1], first_direction[0])
    second_normal = (-second_direction[1], second_direction[0])
    first = v2._cubic(
        root,
        v2._add(
            v2._add(root, v2._mul(entry, first_length * 0.32)),
            v2._mul(first_normal, first_bias),
        ),
        v2._add(
            v2._sub(waypoint, v2._mul(joined, first_length * 0.29)),
            v2._mul(first_normal, first_bias * 0.45),
        ),
        waypoint,
    )
    exit_tangent = v2._unit(
        v2._add(
            second_direction,
            v2._mul(
                second_normal,
                second_bias / max(second_length, EPSILON),
            ),
        )
    )
    second = v2._cubic(
        waypoint,
        v2._add(
            v2._add(waypoint, v2._mul(joined, second_length * 0.34)),
            v2._mul(second_normal, second_bias * 0.45),
        ),
        v2._sub(tip, v2._mul(exit_tangent, second_length * 0.31)),
        tip,
    )
    curve = v2._primary_record(
        unit,
        [first, second],
        path_points,
        bow_sign=side,
        shape_mode="sw3_long_below_flower_sweep_v3",
        bow_amplitude=abs(first_bias) + abs(second_bias),
        entry_direction=entry,
    )
    curve["compiler_trace"].update(
        {
            "compiler": "sw3_long_below_flower_sweep_v3",
            "entry_opening_degrees": v2._round(opening),
            "shape_scale": v2._round(shape_scale),
            "far_root_and_under_flower_waypoint_preserved": True,
            "flower_underside_tip_preserved": True,
        }
    )
    return curve


def _compile_primary(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    unit: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    bow_sign: int,
    shape_scale: float = 1.0,
) -> dict[str, Any]:
    if str(unit["structural_role"]) == "terminal_flower_support":
        return _sw3_intertwined_primary(
            unit,
            plan,
            bow_sign=bow_sign,
            shape_scale=shape_scale,
        )
    points = [
        v2._point(point)
        for point in unit["directional_layout_intent"]["path_points"]
    ]
    if len(points) != 2:
        raise IntertwinedCompilationFailure(
            f'{unit["branch_unit_id"]} ordinary primary needs two macro points'
        )
    root, macro_tip = points
    macro_direction = v2._unit(v2._sub(macro_tip, root))
    tip = macro_tip
    family_id = str(unit["family_id"])
    density = str(plan["instance_priors"]["density_class"])
    role = str(unit["structural_role"])
    if family_id == "SW-1_valley_filling" and role == "primary_sweep":
        minimums = contract["primary_curve_compilation"][
            "sw1_minimum_primary_chord_by_density"
        ]
        minimum = float(minimums.get(density, v2._distance(root, macro_tip)))
        desired = max(v2._distance(root, macro_tip), minimum)
        desired *= 0.96 + 0.08 * v2._u01(
            int(plan["seed"]),
            unit["branch_unit_id"],
            "long_primary_length",
        )
        tip = _safe_sw1_tip(
            analysis,
            root,
            macro_direction,
            desired,
            macro_tip,
        )
    direction = v2._unit(v2._sub(tip, root))
    parent = v2._oriented_parent_tangent(
        v2._point(
            unit["root_tangent_intent"]["parent_tangent_reference"]
        ),
        direction,
    )
    primary_policy = contract["primary_curve_compilation"]
    opening_low, opening_high = (
        float(value)
        for value in primary_policy["entry_opening_degrees"]
    )
    opening = opening_low + (opening_high - opening_low) * v2._u01(
        int(plan["seed"]),
        unit["branch_unit_id"],
        "primary_opening",
    )
    entry = v2._unit(v2._rotate(parent, (1 if bow_sign >= 0 else -1) * opening))
    unit_number = int(str(unit["branch_unit_id"])[2:])
    shape_mode = (
        "C"
        if "flower_support" in role or unit_number % 2
        else "S"
    )
    release_low, release_high = (
        float(value)
        for value in primary_policy["exit_release_degrees"]
    )
    release = release_low + (release_high - release_low) * v2._u01(
        int(plan["seed"]),
        unit["branch_unit_id"],
        "primary_release",
    )
    release_sign = (1 if bow_sign >= 0 else -1) * (
        1 if shape_mode == "C" else -1
    )
    exit_tangent = v2._unit(
        v2._rotate(direction, release_sign * release)
    )
    start_low, start_high = (
        float(value)
        for value in primary_policy["start_arm_ratio"]
    )
    end_low, end_high = (
        float(value)
        for value in primary_policy["end_arm_ratio"]
    )
    start_ratio = start_low + (start_high - start_low) * v2._u01(
        int(plan["seed"]),
        unit["branch_unit_id"],
        "primary_start_arm",
    )
    end_ratio = end_low + (end_high - end_low) * v2._u01(
        int(plan["seed"]),
        unit["branch_unit_id"],
        "primary_end_arm",
    )
    cubics = _two_cubic_sweep(
        root,
        tip,
        entry,
        exit_tangent,
        start_arm_ratio=start_ratio,
        end_arm_ratio=end_ratio,
        arm_length_basis=(
            float(
                primary_policy[
                    "flower_support_minimum_handle_length_basis"
                ]
            )
            * shape_scale
            if "flower_support" in role
            else None
        ),
        midpoint_bow_ratio=(
            0.09 * shape_scale
            if "flower_support" in role
            else (0.075 if shape_mode == "C" else 0.07)
        ),
        midpoint_bow_sign=bow_sign,
        reinforce_existing_bow=True,
    )
    return _primary_record(
        unit,
        cubics,
        points,
        shape_mode=shape_mode,
        entry_opening=opening,
        exit_release=release,
        macro_tip=macro_tip,
        final_tip=tip,
        shape_scale=shape_scale,
    )


def _primary_set(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    options: list[list[dict[str, Any]]] = []
    for unit in plan["branch_units"]:
        role = str(unit["structural_role"])
        shape_scales = (
            (1.0, 0.78)
            if "flower_support" in role
            else (1.0,)
        )
        options.append(
            [
                _compile_primary(
                    analysis,
                    plan,
                    unit,
                    contract,
                    bow_sign=sign,
                    shape_scale=shape_scale,
                )
                for sign in (-1, 1)
                for shape_scale in shape_scales
            ]
        )
    best_score = float("inf")
    best_indices: tuple[int, ...] | None = None
    evaluated = 0
    for indices in itertools.product(
        *(range(len(rows)) for rows in options)
    ):
        curves = [
            options[index][choice]
            for index, choice in enumerate(indices)
        ]
        score = 0.0
        for curve in curves:
            local, _ = v2._curve_context_penalty(
                curve,
                analysis=analysis,
                all_primaries=curves,
                parent_curve=None,
            )
            score += local
            precise, _ = _precision_context_penalty(
                curve,
                analysis=analysis,
                contract=contract,
            )
            score += precise
        for first, second in itertools.combinations(curves, 2):
            score += v2._curve_pair_penalty(first, second)
        evaluated += 1
        if score < best_score - EPSILON:
            best_score = score
            best_indices = tuple(indices)
    if best_indices is None:
        raise IntertwinedCompilationFailure(
            "no primary sweep set could be selected"
        )
    selected = [
        options[index][choice]
        for index, choice in enumerate(best_indices)
    ]
    return selected, {
        "candidate_set_count": evaluated,
        "selected_variant_indices": list(best_indices),
        "selected_score": v2._round(best_score),
        "single_forward_global_selection": True,
    }


def _mount_fractions(count: int) -> list[float]:
    rows = {
        "0": [],
        "1": [0.60],
        "2": [0.34, 0.66],
        "3": [0.26, 0.50, 0.74],
    }
    if str(count) not in rows:
        raise IntertwinedCompilationFailure(
            f"unsupported L2 count {count}"
        )
    return list(rows[str(count)])


def _actual_child_count(
    unit: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> int:
    envelope = unit["child_rhythm_envelope"]
    minimum = int(envelope["minimum_child_count"])
    maximum = int(envelope["maximum_child_count"])
    if maximum < minimum:
        raise IntertwinedCompilationFailure(
            f'{unit["branch_unit_id"]} has an inverted child envelope'
        )
    span = maximum - minimum + 1
    density = str(plan["instance_priors"]["density_class"])
    exponent = 1.8 if density == "dense" else 1.35
    token = v2._u01(
        int(plan["seed"]),
        unit["branch_unit_id"],
        "v3_child_count",
    ) ** exponent
    return minimum + min(span - 1, int(token * span))


def _length_class(unit: Mapping[str, Any], index: int) -> str:
    sequence = list(unit["child_rhythm_envelope"]["length_sequence"])
    return str(sequence[index % len(sequence)]) if sequence else "medium"


def _l2_chord_length(
    plan: Mapping[str, Any],
    unit: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    index: int,
) -> tuple[str, float]:
    density = str(plan["instance_priors"]["density_class"])
    length_class = _length_class(unit, index)
    ranges = contract["dependent_curve_compilation"][
        "absolute_l2_chord_ranges_by_density"
    ][density]
    low, high = (float(value) for value in ranges[length_class])
    token = v2._u01(
        int(plan["seed"]),
        unit["branch_unit_id"],
        "v3_child_length",
        index,
    )
    return length_class, low + (high - low) * token


def _compile_child(
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    curve_id: str,
    unit_id: str,
    level: int,
    parent_curve: Mapping[str, Any],
    mount_fraction: float,
    chord_length: float,
    turn_sign: int,
    shape_mode: str,
    travel_direction: Point,
    flow_role: str,
) -> dict[str, Any]:
    parent_points = v2._curve_points(parent_curve, 96)
    root, parent_tangent = v2._sample_polyline(
        parent_points,
        mount_fraction,
    )
    policy = contract["dependent_curve_compilation"]
    opening_low, opening_high = (
        float(value) for value in policy["entry_opening_degrees"]
    )
    opening = opening_low + (opening_high - opening_low) * v2._u01(
        int(plan["seed"]),
        curve_id,
        "opening",
    )
    requested_sign = 1 if turn_sign >= 0 else -1
    travel = v2._unit(travel_direction)
    travel_turn = _signed_angle(parent_tangent, travel)
    sign = 1 if travel_turn >= 0.0 else -1
    entry = _rotate_toward(parent_tangent, travel, opening)
    tip = v2._add(root, v2._mul(travel, chord_length))
    release_low, release_high = (
        float(value)
        for value in policy["exit_release_degrees"]
    )
    release = release_low + (release_high - release_low) * v2._u01(
        int(plan["seed"]),
        curve_id,
        "release",
    )
    release_sign = sign if shape_mode == "C" else -sign
    exit_tangent = v2._unit(
        v2._rotate(travel, release_sign * release)
    )
    start_ratio = 0.28 + 0.12 * v2._u01(
        int(plan["seed"]),
        curve_id,
        "start_arm",
    )
    end_ratio = 0.30 + 0.14 * v2._u01(
        int(plan["seed"]),
        curve_id,
        "end_arm",
    )
    cubics = _two_cubic_sweep(
        root,
        tip,
        entry,
        exit_tangent,
        start_arm_ratio=start_ratio,
        end_arm_ratio=end_ratio,
        midpoint_bow_ratio=(0.065 if level == 2 else 0.075),
        midpoint_bow_sign=sign,
        reinforce_existing_bow=True,
    )
    curve = {
        "curve_id": curve_id,
        "branch_curve_id": curve_id,
        "branch_unit_id": unit_id,
        "hierarchy_level": level,
        "level": f"L{level}",
        "parent_curve_id": parent_curve["curve_id"],
        "parent_kind": "branch_curve",
        "mount_fraction": v2._round(mount_fraction),
        "structural_role": (
            "secondary_branch" if level == 2 else "tertiary_branch"
        ),
        "semantic_function": "intertwined_unit_child_rhythm",
        "width": float(
            policy["hierarchy_widths"][f"L{level}"]
        ),
        "cubic_segments": cubics,
        "flower_relation_intents": [],
        "compiler_trace": {
            "compiler": "parent_local_open_fork_sweep_v3",
            "actual_parent_curve_id": parent_curve["curve_id"],
            "mount_fraction_is_parent_arc_length_fraction": True,
            "parent_local_reference_tangent": v2._point_json(
                parent_tangent
            ),
            "entry_opening_degrees": v2._round(opening),
            "travel_direction_is_unit_shared_flow": True,
            "travel_turn_from_parent_degrees": v2._round(travel_turn),
            "exit_release_degrees": v2._round(release),
            "turn_sign": sign,
            "requested_variant_sign": requested_sign,
            "shape_mode": shape_mode,
            "flow_role": flow_role,
            "target_chord_length": v2._round(chord_length),
            "exact_parent_tangent_continuity_used": False,
        },
    }
    curve["shape_metrics"] = v2._shape_metrics(curve)
    return curve


def _curve_flow_direction(curve: Mapping[str, Any]) -> Point:
    root = v2._point(curve["cubic_segments"][0]["p0"])
    tip = v2._point(curve["cubic_segments"][-1]["p3"])
    chord = v2._unit(v2._sub(tip, root))
    exit_direction = v2._unit(
        v2._sub(
            v2._point(curve["cubic_segments"][-1]["p3"]),
            v2._point(curve["cubic_segments"][-1]["p2"]),
        )
    )
    return v2._unit(
        v2._add(v2._mul(chord, 0.72), v2._mul(exit_direction, 0.28))
    )


def _flower_for_unit(
    analysis: Mapping[str, Any],
    unit: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    target_ids = {
        str(relation["flower_id"])
        for relation in unit.get("flower_relation_intents", [])
        if relation.get("flower_id")
    }
    return next(
        (
            flower
            for flower in analysis["flowers"]
            if str(flower["flower_id"]) in target_ids
        ),
        None,
    )


def _dependent_flow_direction(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    unit: Mapping[str, Any],
    parent_curve: Mapping[str, Any],
    *,
    mount_fraction: float,
    child_index: int,
    child_count: int,
    turn_sign: int,
    level: int,
) -> tuple[Point, str]:
    parent_points = v2._curve_points(parent_curve, 96)
    root, _ = v2._sample_polyline(parent_points, mount_fraction)
    shared_flow = _curve_flow_direction(parent_curve)
    sign = 1 if turn_sign >= 0 else -1
    flower = _flower_for_unit(analysis, unit)
    if level == 2 and flower is not None:
        radial = v2._unit(v2._sub(root, v2._point(flower["center"])))
        tangent = v2._unit(v2._rotate(radial, sign * 90.0))
        if v2._dot(tangent, shared_flow) < -0.20:
            tangent = v2._mul(tangent, -1.0)
        outward = radial
        direction = v2._unit(
            v2._add(v2._mul(tangent, 0.84), v2._mul(outward, 0.36))
        )
        return direction, "flower_tangential_wrap"
    if level == 3:
        angle = 20.0 + 8.0 * v2._u01(
            int(plan["seed"]),
            unit["branch_unit_id"],
            "tertiary_shared_flow_angle",
        )
        return (
            v2._unit(v2._rotate(shared_flow, sign * angle)),
            "tertiary_flow_echo",
        )
    role_rows = {
        1: (18.0, 28.0, "same_flow_companion"),
        2: (38.0, 54.0, "counter_envelope"),
        3: (10.0, 20.0, "terminal_flow_echo"),
    }
    low, high, flow_role = role_rows[child_index]
    angle = low + (high - low) * v2._u01(
        int(plan["seed"]),
        unit["branch_unit_id"],
        "dependent_shared_flow_angle",
        child_index,
        child_count,
    )
    return (
        v2._unit(v2._rotate(shared_flow, sign * angle)),
        flow_role,
    )


def _unit_variants(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
    unit: Mapping[str, Any],
    primary: Mapping[str, Any],
    all_primaries: Sequence[Mapping[str, Any]],
    l3_enabled_unit_ids: set[str],
) -> list[v2.UnitVariant]:
    unit_id = str(unit["branch_unit_id"])
    child_count = _actual_child_count(unit, plan)
    mounts = _mount_fractions(child_count)
    primary_turn = 1 if _signed_angle(
        v2._point(
            unit["root_tangent_intent"]["parent_tangent_reference"]
        ),
        v2._sub(
            v2._point(primary["cubic_segments"][-1]["p3"]),
            v2._point(primary["cubic_segments"][0]["p0"]),
        ),
    ) >= 0 else -1
    patterns = v2._pattern_signs(child_count, -primary_turn)
    variants: list[v2.UnitVariant] = []
    for pattern_index, signs in enumerate(patterns):
        curves: list[dict[str, Any]] = [dict(primary)]
        child_specs: list[dict[str, Any]] = []
        local_score = 0.0
        trace_rows: list[dict[str, Any]] = []
        for child_index, (mount, sign) in enumerate(
            zip(mounts, signs),
            start=1,
        ):
            length_class, chord_length = _l2_chord_length(
                plan,
                unit,
                contract,
                index=child_index - 1,
            )
            shape_mode = (
                "C"
                if v2._u01(
                    int(plan["seed"]),
                    unit_id,
                    "child_mode_v3",
                    child_index,
                )
                < 0.58
                else "S"
            )
            travel_direction, flow_role = _dependent_flow_direction(
                analysis,
                plan,
                unit,
                primary,
                mount_fraction=mount,
                child_index=child_index,
                child_count=child_count,
                turn_sign=sign,
                level=2,
            )
            child = _compile_child(
                plan,
                contract,
                curve_id=f"{unit_id}.L2.{child_index}",
                unit_id=unit_id,
                level=2,
                parent_curve=primary,
                mount_fraction=mount,
                chord_length=chord_length,
                turn_sign=sign,
                shape_mode=shape_mode,
                travel_direction=travel_direction,
                flow_role=flow_role,
            )
            context_score, context_trace = v2._curve_context_penalty(
                child,
                analysis=analysis,
                all_primaries=all_primaries,
                parent_curve=primary,
            )
            precision_score, precision_trace = (
                _precision_context_penalty(
                    child,
                    analysis=analysis,
                    contract=contract,
                )
            )
            context_score += precision_score
            context_trace = {
                **context_trace,
                **precision_trace,
            }
            local_score += context_score
            curves.append(child)
            child_specs.append(
                {
                    "curve_id": child["curve_id"],
                    "level": "L2",
                    "parent_curve_id": primary["curve_id"],
                    "mount_fraction": mount,
                    "length_class": length_class,
                    "target_chord_length": v2._round(chord_length),
                    "turn_sign": sign,
                    "shape_mode": shape_mode,
                    "flow_role": flow_role,
                }
            )
            trace_rows.append(
                {
                    "curve_id": child["curve_id"],
                    "context_score": v2._round(context_score),
                    "context": {
                        key: v2._round(value)
                        for key, value in context_trace.items()
                    },
                }
            )
        for first, second in itertools.combinations(curves, 2):
            registered = (
                first.get("parent_curve_id") == second.get("curve_id")
                or second.get("parent_curve_id") == first.get("curve_id")
            )
            local_score += v2._curve_pair_penalty(
                first,
                second,
                registered_parent_contact=registered,
            )
        l3_specs: list[dict[str, Any]] = []
        density = str(plan["instance_priors"]["density_class"])
        if unit_id in l3_enabled_unit_ids and child_count >= 2:
            parent_index = min(
                child_count - 1,
                int(
                    v2._u01(
                        int(plan["seed"]),
                        unit_id,
                        "v3_l3_parent",
                    )
                    * child_count
                ),
            )
            parent_child = curves[1 + parent_index]
            ratios = contract["dependent_curve_compilation"][
                "l3_to_parent_chord_ratio"
            ]
            ratio = float(ratios[0]) + (
                float(ratios[1]) - float(ratios[0])
            ) * v2._u01(
                int(plan["seed"]),
                unit_id,
                "v3_l3_length",
            )
            chord_length = (
                float(
                    parent_child["compiler_trace"][
                        "target_chord_length"
                    ]
                )
                * ratio
            )
            options: list[
                tuple[float, dict[str, Any], int, dict[str, float]]
            ] = []
            for sign in (-1, 1):
                travel_direction, flow_role = _dependent_flow_direction(
                    analysis,
                    plan,
                    unit,
                    parent_child,
                    mount_fraction=0.62,
                    child_index=1,
                    child_count=1,
                    turn_sign=sign,
                    level=3,
                )
                tertiary = _compile_child(
                    plan,
                    contract,
                    curve_id=f"{unit_id}.L3.1",
                    unit_id=unit_id,
                    level=3,
                    parent_curve=parent_child,
                    mount_fraction=0.62,
                    chord_length=chord_length,
                    turn_sign=sign,
                    shape_mode="C",
                    travel_direction=travel_direction,
                    flow_role=flow_role,
                )
                context_score, context_trace = v2._curve_context_penalty(
                    tertiary,
                    analysis=analysis,
                    all_primaries=all_primaries,
                    parent_curve=parent_child,
                )
                precision_score, precision_trace = (
                    _precision_context_penalty(
                        tertiary,
                        analysis=analysis,
                        contract=contract,
                    )
                )
                context_score += precision_score
                context_trace = {
                    **context_trace,
                    **precision_trace,
                }
                score = context_score
                for existing in curves:
                    score += v2._curve_pair_penalty(
                        existing,
                        tertiary,
                        registered_parent_contact=(
                            existing["curve_id"]
                            == parent_child["curve_id"]
                        ),
                    )
                options.append(
                    (score, tertiary, sign, context_trace)
                )
            score, tertiary, sign, context_trace = min(
                options,
                key=lambda row: (row[0], row[2]),
            )
            local_score += score
            curves.append(tertiary)
            l3_specs.append(
                {
                    "curve_id": tertiary["curve_id"],
                    "level": "L3",
                    "parent_curve_id": parent_child["curve_id"],
                    "mount_fraction": 0.62,
                    "target_chord_length": v2._round(chord_length),
                    "turn_sign": sign,
                    "shape_mode": "C",
                    "flow_role": flow_role,
                }
            )
            trace_rows.append(
                {
                    "curve_id": tertiary["curve_id"],
                    "context_score": v2._round(
                        sum(context_trace.values())
                    ),
                    "orientation_candidate_count": 2,
                }
            )
        rhythm = str(
            unit["child_rhythm_envelope"]["rhythm_policy"]
        )
        if "balanced" in rhythm:
            local_score += abs(sum(signs)) * 0.8
        if "asymmetric" in rhythm and child_count > 1:
            local_score += (
                child_count - abs(sum(signs))
            ) * 0.25
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
                "minimum": int(
                    unit["child_rhythm_envelope"][
                        "minimum_child_count"
                    ]
                ),
                "maximum": int(
                    unit["child_rhythm_envelope"][
                        "maximum_child_count"
                    ]
                ),
            },
            "topology_selected_before_final_diagnostics": True,
        }
        variants.append(
            v2.UnitVariant(
                unit_id=unit_id,
                pattern_id=f"{unit_id}.pattern_{pattern_index + 1}",
                curves=tuple(curves),
                topology=topology,
                local_score=local_score,
                local_score_trace={
                    "dependent_context_rows": trace_rows,
                },
            )
        )
    return variants


def _l3_unit_ids(
    plan: Mapping[str, Any],
) -> set[str]:
    density = str(plan["instance_priors"]["density_class"])
    quota = 2 if density == "dense" else 1
    eligible = [
        unit
        for unit in plan["branch_units"]
        if int(
            unit["child_rhythm_envelope"]["maximum_child_count"]
        )
        >= 2
        and str(unit["structural_role"]) != "terminal_flower_support"
    ]
    ranked = sorted(
        eligible,
        key=lambda unit: (
            -v2._u01(
                int(plan["seed"]),
                unit["branch_unit_id"],
                "v3_global_l3_rhythm_rank",
            ),
            str(unit["branch_unit_id"]),
        ),
    )
    return {
        str(unit["branch_unit_id"])
        for unit in ranked[:quota]
    }


def _validate_inputs(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    if analysis.get("schema") != "dynamic_branch_prototype_analysis_v1":
        raise IntertwinedCompilationFailure(
            "prototype analysis schema mismatch"
        )
    if plan.get("schema") != "dynamic_branch_plan_v4":
        raise IntertwinedCompilationFailure(
            "stage-3 v4 plan schema mismatch"
        )
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise IntertwinedCompilationFailure(
            "stage-4 v3 contract schema mismatch"
        )
    if plan.get("prototype_id") != analysis.get("prototype_id"):
        raise IntertwinedCompilationFailure(
            "plan and analysis prototype ids differ"
        )


def compile_dynamic_branch_units_v3(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_inputs(analysis, plan, contract)
    selected_primaries, primary_trace = _primary_set(
        analysis,
        plan,
        contract,
    )
    primary_by_unit = {
        curve["branch_unit_id"]: curve
        for curve in selected_primaries
    }
    l3_enabled_unit_ids = _l3_unit_ids(plan)
    variant_rows = [
        _unit_variants(
            analysis,
            plan,
            contract,
            unit,
            primary_by_unit[str(unit["branch_unit_id"])],
            selected_primaries,
            l3_enabled_unit_ids,
        )
        for unit in plan["branch_units"]
    ]
    selected_units, unit_trace = v2._global_unit_set(variant_rows)
    branch_units: list[dict[str, Any]] = []
    branch_curves: list[dict[str, Any]] = []
    for variant in selected_units:
        topology = dict(variant.topology)
        topology["curve_ids"] = [
            curve["curve_id"] for curve in variant.curves
        ]
        topology["selected_pattern_id"] = variant.pattern_id
        topology["selected_local_score"] = v2._round(
            variant.local_score
        )
        topology["selection_trace"] = dict(
            variant.local_score_trace
        )
        branch_units.append(topology)
        branch_curves.extend(dict(curve) for curve in variant.curves)
    topology_payload = {
        "branch_units": branch_units,
        "compile_order": ["L1", "L2", "L3"],
    }
    candidate: dict[str, Any] = {
        "schema": SCHEMA,
        "stage4_version": "v3_intertwined",
        "curve_contract_id": contract["contract_id"],
        "candidate_id": f'{plan["plan_id"]}__stage4_v3_raw_1',
        "task_id": plan["task_id"],
        "prototype_id": plan["prototype_id"],
        "seed": int(plan["seed"]),
        "classification": dict(plan["classification"]),
        "instance_priors": dict(plan["instance_priors"]),
        "coordinate_system": dict(plan["coordinate_system"]),
        "branch_units": branch_units,
        "branch_curves": branch_curves,
        "unit_topology_digest": v2._canonical_digest(
            topology_payload
        ),
        "selection_trace": {
            "primary_set": primary_trace,
            "complete_unit_set": unit_trace,
            "unit_candidate_counts": [
                len(variants) for variants in variant_rows
            ],
            "single_forward_generation": True,
            "validation_guided_retry_used": False,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
        },
        "stage_boundary": dict(contract["stage_boundary"]),
        "review": {
            "status": contract["review"]["initial_state"],
            "criteria": list(contract["review"]["criteria"]),
            "numeric_checks_cannot_auto_approve": True,
        },
        "input_refs": {
            "stage3_plan_digest": plan["plan_digest"],
            "prototype_analysis_digest": analysis["analysis_digest"],
        },
    }
    digest_source = dict(candidate)
    candidate["candidate_digest"] = v2._canonical_digest(
        digest_source
    )
    return candidate


def _shape_issue(
    curve: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> str | None:
    metrics = curve["shape_metrics"]
    thresholds = contract["diagnostics"]["shape_thresholds"]
    level = str(curve["level"])
    if float(metrics["maximum_deviation_ratio"]) < float(
        thresholds[f"{level}_minimum_deviation_ratio"]
    ):
        return "near-straight maximum chord deviation"
    if float(metrics["arc_ratio"]) < float(
        thresholds[f"{level}_minimum_arc_ratio"]
    ):
        return "near-straight arc/chord ratio"
    if float(metrics["maximum_deviation_ratio"]) > float(
        thresholds["maximum_deviation_ratio"]
    ):
        return "over-bent maximum chord deviation"
    return None


def diagnose_dynamic_branch_units_v3(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_inputs(analysis, plan, contract)
    curves = list(candidate["branch_curves"])
    curve_by_id = {
        str(curve["curve_id"]): curve for curve in curves
    }
    plan_units = {
        str(unit["branch_unit_id"]): unit
        for unit in plan["branch_units"]
    }
    issues: list[dict[str, Any]] = []
    near_straight: list[str] = []
    root_error_max = 0.0
    opening_error_max = 0.0
    backbone = [
        v2._point(row["point"])
        for row in analysis["backbone"]["samples"]
    ]
    backbone_crossings: list[str] = []
    wrong_flowers: list[dict[str, str]] = []
    for curve in curves:
        curve_id = str(curve["curve_id"])
        level = int(curve["hierarchy_level"])
        shape_reason = _shape_issue(curve, contract)
        if shape_reason:
            near_straight.append(curve_id)
            issues.append(
                {
                    "label": "curve_issue",
                    "curve_id": curve_id,
                    "detail": shape_reason,
                }
            )
        points = v2._curve_points(curve, 64)
        if level == 1:
            unit = plan_units[str(curve["branch_unit_id"])]
            expected_root = v2._point(
                unit["parent_ref"]["mount_point"]
            )
            error = v2._distance(points[0], expected_root)
            root_error_max = max(root_error_max, error)
            if error > 1e-7:
                issues.append(
                    {
                        "label": "attachment_issue",
                        "curve_id": curve_id,
                        "detail": "L1 root differs from macro plan",
                    }
                )
            checked_backbone = points[7:]
        else:
            parent = curve_by_id[str(curve["parent_curve_id"])]
            parent_points = v2._curve_points(parent, 96)
            expected_root, parent_tangent = v2._sample_polyline(
                parent_points,
                float(curve["mount_fraction"]),
            )
            error = v2._distance(points[0], expected_root)
            root_error_max = max(root_error_max, error)
            actual_entry = v2._unit(
                v2._sub(
                    v2._point(curve["cubic_segments"][0]["p1"]),
                    v2._point(curve["cubic_segments"][0]["p0"]),
                )
            )
            actual_opening = abs(
                _signed_angle(parent_tangent, actual_entry)
            )
            planned_opening = float(
                curve["compiler_trace"]["entry_opening_degrees"]
            )
            opening_error = abs(actual_opening - planned_opening)
            opening_error_max = max(
                opening_error_max,
                opening_error,
            )
            if error > 2e-5 or opening_error > 1.2:
                issues.append(
                    {
                        "label": "attachment_issue",
                        "curve_id": curve_id,
                        "detail": "child root or visible fork angle is invalid",
                    }
                )
            checked_backbone = points
        if v2._polyline_crosses(checked_backbone, backbone):
            backbone_crossings.append(curve_id)
            issues.append(
                {
                    "label": "collision_issue",
                    "curve_id": curve_id,
                    "detail": "curve crosses backbone outside registered root",
                }
            )
        target_flowers = v2._target_flower_ids(curve)
        for flower in analysis["flowers"]:
            flower_id = str(flower["flower_id"])
            if level == 1 and flower_id in target_flowers:
                checked = points[:-8]
                intrusion = any(
                    v2._inside_flower(
                        point,
                        flower,
                        protection=False,
                    )
                    for point in checked
                )
            else:
                intrusion = any(
                    v2._inside_flower(point, flower)
                    for point in points
                )
            if intrusion:
                wrong_flowers.append(
                    {
                        "curve_id": curve_id,
                        "flower_id": flower_id,
                    }
                )
                issues.append(
                    {
                        "label": "flower_relation_issue",
                        "curve_id": curve_id,
                        "flower_id": flower_id,
                        "detail": "curve enters a flower reserve",
                    }
                )
    crossing_pairs: list[list[str]] = []
    for first, second in itertools.combinations(curves, 2):
        first_points = v2._curve_points(first, 48)
        second_points = v2._curve_points(second, 48)
        if second.get("parent_curve_id") == first.get("curve_id"):
            second_points = second_points[7:]
        elif first.get("parent_curve_id") == second.get("curve_id"):
            first_points = first_points[7:]
        if v2._polyline_crosses(first_points, second_points):
            pair = [
                str(first["curve_id"]),
                str(second["curve_id"]),
            ]
            crossing_pairs.append(pair)
            issues.append(
                {
                    "label": "collision_issue",
                    "curve_ids": pair,
                    "detail": "unregistered branch curves cross",
                }
            )
    repeat_crossings: list[list[str]] = []
    for offset in (-1.0, 1.0):
        for first in curves:
            first_points = v2._curve_points(first, 36)
            for second in curves:
                shifted = [
                    (point[0] + offset, point[1])
                    for point in v2._curve_points(second, 36)
                ]
                if v2._polyline_crosses(first_points, shifted):
                    pair = [
                        str(first["curve_id"]),
                        f'{second["curve_id"]}@{offset:+.0f}',
                    ]
                    repeat_crossings.append(pair)
                    issues.append(
                        {
                            "label": "repeat_issue",
                            "curve_ids": pair,
                            "detail": "curve crosses periodic neighbor",
                        }
                    )
    level_counts = {
        level: sum(curve["level"] == level for curve in curves)
        for level in ("L1", "L2", "L3")
    }
    return {
        "schema": "dynamic_branch_intertwined_unit_diagnostics_v3",
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
        "near_straight_curve_count": len(near_straight),
        "near_straight_curve_ids": near_straight,
        "curve_curve_crossing_count": len(crossing_pairs),
        "curve_curve_crossing_pairs": crossing_pairs,
        "repeat_crossing_count": len(repeat_crossings),
        "repeat_crossing_pairs": repeat_crossings,
        "non_root_backbone_crossing_count": len(
            backbone_crossings
        ),
        "non_root_backbone_crossing_ids": backbone_crossings,
        "wrong_flower_entry_count": len(wrong_flowers),
        "wrong_flower_entries": wrong_flowers,
        "maximum_child_root_error": v2._round(root_error_max),
        "maximum_child_entry_opening_error_degrees": v2._round(
            opening_error_max
        ),
        "issue_count": len(issues),
        "issue_labels": sorted(
            {str(issue["label"]) for issue in issues}
        ),
        "issues": issues,
        "read_only_diagnostics": True,
        "candidate_modified": False,
        "numeric_checks_cannot_auto_approve_visual_gate": True,
    }
