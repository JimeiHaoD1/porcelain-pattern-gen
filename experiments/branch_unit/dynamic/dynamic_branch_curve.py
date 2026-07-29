#!/usr/bin/env python3
"""Compile stage-3 directional BranchUnit plans into cubic Bezier skeletons."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from typing import Any, Mapping, Sequence


SCHEMA = "dynamic_branch_curve_candidate_v1"
PLAN_SCHEMA = "dynamic_branch_plan_v3"
CONTRACT_SCHEMA = "dynamic_branch_stage4_curve_contract_v1"
Point = tuple[float, float]


class CurveCompilationFailure(RuntimeError):
    """A fatal input/geometry failure preserved without retry."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any]):
        self.code = code
        self.message = message
        self.details = dict(details)
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "dynamic_branch_curve_compilation_failure_v1",
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


def _round(value: float, digits: int = 9) -> float:
    rounded = round(float(value), digits)
    return 0.0 if rounded == -0.0 else rounded


def _point(value: Sequence[float]) -> Point:
    point = float(value[0]), float(value[1])
    if not all(math.isfinite(component) for component in point):
        raise CurveCompilationFailure(
            "non_finite_geometry",
            "curve compilation input contains a non-finite coordinate",
            {"point": list(value)},
        )
    return point


def _round_point(value: Sequence[float]) -> list[float]:
    return [_round(float(value[0])), _round(float(value[1]))]


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
        raise CurveCompilationFailure(
            "invalid_coordinate",
            "directional path contains a zero-length segment",
            {"vector": list(a)},
        )
    return a[0] / length, a[1] / length


def _angle_degrees(a: Point, b: Point) -> float:
    cosine = max(-1.0, min(1.0, _dot(_unit(a), _unit(b))))
    return math.degrees(math.acos(cosine))


def cubic_point(cubic: Mapping[str, Sequence[float]], t: float) -> Point:
    """Evaluate one cubic Bezier at t."""

    p0, p1, p2, p3 = (_point(cubic[key]) for key in ("p0", "p1", "p2", "p3"))
    u = 1.0 - t
    return (
        u**3 * p0[0]
        + 3.0 * u * u * t * p1[0]
        + 3.0 * u * t * t * p2[0]
        + t**3 * p3[0],
        u**3 * p0[1]
        + 3.0 * u * u * t * p1[1]
        + 3.0 * u * t * t * p2[1]
        + t**3 * p3[1],
    )


def sample_cubics(
    cubics: Sequence[Mapping[str, Sequence[float]]],
    *,
    samples_per_cubic: int = 64,
) -> list[Point]:
    """Sample joined cubics without duplicating join points."""

    points: list[Point] = []
    for cubic_index, cubic in enumerate(cubics):
        sampled = [
            cubic_point(cubic, index / samples_per_cubic)
            for index in range(samples_per_cubic + 1)
        ]
        points.extend(sampled if cubic_index == 0 else sampled[1:])
    return points


def _cubic(
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


def _oriented_parent_tangent(reference: Point, first_direction: Point) -> Point:
    tangent = _unit(reference)
    return tangent if _dot(tangent, first_direction) >= 0.0 else _mul(tangent, -1.0)


def _interior_tangent(incoming: Point, outgoing: Point) -> Point:
    combined = _add(incoming, outgoing)
    return _unit(combined) if _length(combined) > 1e-8 else outgoing


def _compile_path(
    path_points: Sequence[Point],
    parent_tangent: Point,
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, list[float]]], dict[str, Any]]:
    policy = contract["curve_representation"]
    directions = [
        _unit(_sub(end, start))
        for start, end in zip(path_points, path_points[1:])
    ]
    lengths = [
        _distance(start, end)
        for start, end in zip(path_points, path_points[1:])
    ]
    oriented_parent = _oriented_parent_tangent(
        parent_tangent,
        directions[0],
    )
    vertex_tangents: list[Point] = [oriented_parent]
    vertex_tangents.extend(
        _interior_tangent(directions[index - 1], directions[index])
        for index in range(1, len(directions))
    )
    vertex_tangents.append(directions[-1])
    minimum_root_handle = float(policy["minimum_root_handle_length"])
    maximum_root_handle = float(policy["maximum_root_handle_length"])
    root_fraction = float(policy["root_handle_fraction_of_first_segment"])
    interior_fraction = float(policy["interior_handle_fraction"])
    terminal_fraction = float(policy["terminal_handle_fraction"])
    root_handle = min(
        maximum_root_handle,
        max(minimum_root_handle, lengths[0] * root_fraction),
    )
    cubics: list[dict[str, list[float]]] = []
    handles: list[dict[str, float]] = []
    for index, (start, end, segment_length) in enumerate(
        zip(path_points, path_points[1:], lengths)
    ):
        if index == 0:
            start_handle = root_handle
        else:
            start_handle = min(
                segment_length * interior_fraction,
                lengths[index - 1] * interior_fraction,
            )
        if index == len(lengths) - 1:
            end_handle = segment_length * terminal_fraction
        else:
            end_handle = min(
                segment_length * interior_fraction,
                lengths[index + 1] * interior_fraction,
            )
        p1 = _add(start, _mul(vertex_tangents[index], start_handle))
        p2 = _sub(end, _mul(vertex_tangents[index + 1], end_handle))
        cubics.append(_cubic(start, p1, p2, end))
        handles.append(
            {
                "start_handle_length": _round(start_handle),
                "end_handle_length": _round(end_handle),
            }
        )
    return cubics, {
        "oriented_parent_tangent": _round_point(oriented_parent),
        "root_handle_length": _round(root_handle),
        "root_tangent_is_derivative_only": True,
        "straight_parent_tangent_prefix_present": False,
        "vertex_tangents": [
            _round_point(tangent) for tangent in vertex_tangents
        ],
        "segment_handles": handles,
        "join_continuity": "G1" if len(cubics) == 2 else "single_cubic",
    }


def _validate_inputs(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise CurveCompilationFailure(
            "invalid_schema",
            "stage-4 curve contract schema mismatch",
            {"actual": contract.get("schema"), "expected": CONTRACT_SCHEMA},
        )
    if plan.get("schema") != PLAN_SCHEMA:
        raise CurveCompilationFailure(
            "invalid_schema",
            "stage-3 plan schema mismatch",
            {"actual": plan.get("schema"), "expected": PLAN_SCHEMA},
        )
    if analysis.get("prototype_id") != plan.get("prototype_id"):
        raise CurveCompilationFailure(
            "invalid_parent_graph",
            "analysis and plan prototype ids differ",
            {
                "analysis_prototype_id": analysis.get("prototype_id"),
                "plan_prototype_id": plan.get("prototype_id"),
            },
        )
    if analysis.get("analysis_digest") != plan.get("input_refs", {}).get(
        "prototype_analysis_digest"
    ):
        raise CurveCompilationFailure(
            "invalid_parent_graph",
            "plan is not bound to the supplied prototype analysis",
            {"prototype_id": plan.get("prototype_id")},
        )
    if plan.get("stage_boundary", {}).get("directional_layout_only") is not True:
        raise CurveCompilationFailure(
            "invalid_schema",
            "plan is not a stage-3 directional layout",
            {"prototype_id": plan.get("prototype_id")},
        )


def compile_dynamic_branch_curve(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile one immutable raw Bezier candidate with no repair or retry."""

    _validate_inputs(analysis, plan, contract)
    maximum_segments = int(
        contract["curve_representation"]["maximum_cubic_segments_per_branch"]
    )
    branch_curves: list[dict[str, Any]] = []
    for unit in plan["branch_units"]:
        directional = unit["directional_layout_intent"]
        path_points = tuple(_point(point) for point in directional["path_points"])
        if len(path_points) not in (2, 3):
            raise CurveCompilationFailure(
                "invalid_schema",
                "stage-4 supports one- or two-segment directional paths",
                {
                    "branch_unit_id": unit["branch_unit_id"],
                    "path_point_count": len(path_points),
                },
            )
        parent_tangent = _point(
            unit["root_tangent_intent"]["parent_tangent_reference"]
        )
        cubics, trace = _compile_path(path_points, parent_tangent, contract)
        if len(cubics) > maximum_segments:
            raise CurveCompilationFailure(
                "invalid_schema",
                "compiled branch exceeds the cubic segment limit",
                {
                    "branch_unit_id": unit["branch_unit_id"],
                    "cubic_segment_count": len(cubics),
                },
            )
        branch_curves.append(
            {
                "branch_curve_id": f'curve_{unit["branch_unit_id"]}',
                "branch_unit_id": unit["branch_unit_id"],
                "hierarchy_level": 1,
                "parent_kind": "backbone",
                "parent_ref": unit["parent_ref"],
                "family_id": unit["family_id"],
                "structural_role": unit["structural_role"],
                "semantic_function": unit["semantic_function"],
                "source_directional_layout_intent": directional,
                "source_occupancy_radius": unit["occupancy_envelope"]["radius"],
                "cubic_segments": cubics,
                "compiler_trace": trace,
                "flower_relation_intents": unit["flower_relation_intents"],
                "terminal_intent": unit["terminal_intent"],
                "provenance": {
                    "source_plan_digest": plan["plan_digest"],
                    "source_candidate_id": unit["provenance"]["candidate_id"],
                    "compiler": "directional_corridor_cubic_v1",
                    "validation_guided_retry_used": False,
                    "automatic_repair_used": False,
                    "automatic_deletion_used": False,
                },
            }
        )
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "curve_contract_id": contract["contract_id"],
        "candidate_id": f'{plan["plan_id"]}__stage4_curve_1',
        "task_id": plan["task_id"],
        "prototype_id": plan["prototype_id"],
        "seed": plan["seed"],
        "raw_curve_candidate_index": 1,
        "coordinate_system": plan["coordinate_system"],
        "input_refs": {
            "strict_p0_digest": plan["input_refs"]["strict_p0_digest"],
            "prototype_analysis_digest": plan["input_refs"][
                "prototype_analysis_digest"
            ],
            "morphology_digest": plan["input_refs"]["morphology_digest"],
            "stage3_plan_digest": plan["plan_digest"],
        },
        "classification": plan["classification"],
        "instance_priors": plan["instance_priors"],
        "branch_curves": branch_curves,
        "compilation_policy": {
            "single_forward_compilation": True,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
            "stage3_unit_count_preserved": len(branch_curves)
            == len(plan["branch_units"]),
            "stage3_unit_ids_preserved": [
                curve["branch_unit_id"] for curve in branch_curves
            ]
            == [unit["branch_unit_id"] for unit in plan["branch_units"]],
        },
        "stage_boundary": dict(contract["stage_boundary"]),
        "review": {
            "status": contract["review"]["initial_state"],
            "allowed_states": list(contract["review"]["allowed_states"]),
            "criteria": list(contract["review"]["criteria"]),
            "numeric_checks_cannot_auto_approve": True,
        },
    }
    core["candidate_digest"] = _canonical_digest(core)
    return core


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    segment = _sub(end, start)
    length_sq = _dot(segment, segment)
    if length_sq <= 1e-12:
        return _distance(point, start)
    t = max(0.0, min(1.0, _dot(_sub(point, start), segment) / length_sq))
    return _distance(point, _add(start, _mul(segment, t)))


def _segments_intersect(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    def orientation(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (
            q[1] - p[1]
        ) * (r[0] - p[0])

    def on_segment(p: Point, q: Point, r: Point) -> bool:
        return (
            min(p[0], r[0]) - 1e-10 <= q[0] <= max(p[0], r[0]) + 1e-10
            and min(p[1], r[1]) - 1e-10
            <= q[1]
            <= max(p[1], r[1]) + 1e-10
        )

    o1, o2 = orientation(a0, a1, b0), orientation(a0, a1, b1)
    o3, o4 = orientation(b0, b1, a0), orientation(b0, b1, a1)
    if (
        (o1 > 1e-10 and o2 < -1e-10 or o1 < -1e-10 and o2 > 1e-10)
        and (o3 > 1e-10 and o4 < -1e-10 or o3 < -1e-10 and o4 > 1e-10)
    ):
        return True
    return (
        abs(o1) <= 1e-10
        and on_segment(a0, b0, a1)
        or abs(o2) <= 1e-10
        and on_segment(a0, b1, a1)
        or abs(o3) <= 1e-10
        and on_segment(b0, a0, b1)
        or abs(o4) <= 1e-10
        and on_segment(b0, a1, b1)
    )


def _polyline_crosses(a: Sequence[Point], b: Sequence[Point]) -> bool:
    return any(
        _segments_intersect(a0, a1, b0, b1)
        for a0, a1 in zip(a, a[1:])
        for b0, b1 in zip(b, b[1:])
    )


def _point_polyline_distance(point: Point, polyline: Sequence[Point]) -> float:
    return min(
        _point_segment_distance(point, start, end)
        for start, end in zip(polyline, polyline[1:])
    )


def _polyline_point_at_fraction(
    points: Sequence[Point],
    fraction: float,
) -> Point:
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


def _inside_ellipse(
    point: Point,
    flower: Mapping[str, Any],
    *,
    protection: bool,
) -> bool:
    center = _point(flower["center"])
    rx = float(flower["protection_rx"] if protection else flower["rx"])
    ry = float(flower["protection_ry"] if protection else flower["ry"])
    dx = point[0] - center[0]
    dx -= round(dx)
    dy = point[1] - center[1]
    return (dx / rx) ** 2 + (dy / ry) ** 2 < 1.0 - 1e-7


def diagnose_curve_candidate(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Read-only compiler diagnostics; never changes the raw candidate."""

    plan_units = {
        unit["branch_unit_id"]: unit for unit in plan["branch_units"]
    }
    flower_by_id = {
        flower["flower_id"]: flower for flower in analysis["flowers"]
    }
    backbone = [
        _point(row["point"])
        for row in analysis["backbone"]["samples"]
    ]
    issues: list[dict[str, Any]] = []
    sampled_by_id: dict[str, list[Point]] = {}
    maximum_corridor_escape = 0.0
    maximum_root_tangent_error = 0.0
    minimum_primary_parent_clearance = math.inf
    for curve in candidate["branch_curves"]:
        unit_id = str(curve["branch_unit_id"])
        unit = plan_units[unit_id]
        cubics = curve["cubic_segments"]
        samples = sample_cubics(cubics, samples_per_cubic=72)
        sampled_by_id[unit_id] = samples
        source_path = [
            _point(point)
            for point in unit["directional_layout_intent"]["path_points"]
        ]
        if _distance(samples[0], source_path[0]) > 1e-8:
            issues.append(
                {
                    "label": "attachment_issue",
                    "branch_unit_id": unit_id,
                    "detail": "curve root differs from stage3 mount point",
                }
            )
        if _distance(samples[-1], source_path[-1]) > 1e-8:
            issues.append(
                {
                    "label": "curve_issue",
                    "branch_unit_id": unit_id,
                    "detail": "curve tip differs from stage3 directional endpoint",
                }
            )
        if len(cubics) == 2:
            first_end = _point(cubics[0]["p3"])
            second_start = _point(cubics[1]["p0"])
            if (
                _distance(first_end, source_path[1]) > 1e-8
                or _distance(second_start, source_path[1]) > 1e-8
            ):
                issues.append(
                    {
                        "label": "curve_issue",
                        "branch_unit_id": unit_id,
                        "detail": "two-cubic join does not preserve the stage3 waypoint",
                    }
                )
            end_tangent = _sub(
                _point(cubics[0]["p3"]),
                _point(cubics[0]["p2"]),
            )
            start_tangent = _sub(
                _point(cubics[1]["p1"]),
                _point(cubics[1]["p0"]),
            )
            if _angle_degrees(end_tangent, start_tangent) > 1e-5:
                issues.append(
                    {
                        "label": "curve_issue",
                        "branch_unit_id": unit_id,
                        "detail": "two-cubic join is not G1 continuous",
                    }
                )
        actual_root_tangent = _sub(
            _point(cubics[0]["p1"]),
            _point(cubics[0]["p0"]),
        )
        expected_root_tangent = _point(
            curve["compiler_trace"]["oriented_parent_tangent"]
        )
        tangent_error = _angle_degrees(
            actual_root_tangent,
            expected_root_tangent,
        )
        maximum_root_tangent_error = max(
            maximum_root_tangent_error,
            tangent_error,
        )
        if tangent_error > 1e-5:
            issues.append(
                {
                    "label": "attachment_issue",
                    "branch_unit_id": unit_id,
                    "detail": "root derivative does not match oriented parent tangent",
                }
            )
        corridor_escape = max(
            min(
                _point_polyline_distance(
                    (sample[0] + shift, sample[1]),
                    source_path,
                )
                for shift in (-1.0, 0.0, 1.0)
            )
            for sample in samples
        )
        maximum_corridor_escape = max(
            maximum_corridor_escape,
            corridor_escape,
        )
        if corridor_escape > float(curve["source_occupancy_radius"]) + 1e-6:
            issues.append(
                {
                    "label": "curve_issue",
                    "branch_unit_id": unit_id,
                    "detail": "curve escaped the stage3 directional corridor",
                    "measured": _round(corridor_escape),
                    "allowed": curve["source_occupancy_radius"],
                }
            )
        if curve["structural_role"] == "primary_sweep":
            start_fraction = float(
                plan["initial_layout_policy"][
                    "parent_clearance_measurement_start_fraction"
                ]
            )
            sample = _polyline_point_at_fraction(samples, start_fraction)
            parent_clearance = min(
                _point_polyline_distance(
                    sample,
                    [(point[0] + shift, point[1]) for point in backbone],
                )
                for shift in (-1.0, 0.0, 1.0)
            )
            minimum_primary_parent_clearance = min(
                minimum_primary_parent_clearance,
                parent_clearance,
            )
            required_parent_clearance = float(
                plan["initial_layout_policy"][
                    "minimum_parent_clearance_after_initial_departure"
                ]
            )
            if parent_clearance + 1e-6 < required_parent_clearance:
                issues.append(
                    {
                        "label": "attachment_issue",
                        "branch_unit_id": unit_id,
                        "detail": "compiled primary curve still hugs the parent backbone after initial departure",
                        "measured": _round(parent_clearance),
                        "required": _round(required_parent_clearance),
                    }
                )
        target_ids = {
            relation["flower_id"]
            for relation in curve["flower_relation_intents"]
        }
        for flower_id, flower in flower_by_id.items():
            if flower_id in target_ids:
                if any(
                    _inside_ellipse(point, flower, protection=False)
                    for point in samples[:-1]
                ):
                    issues.append(
                        {
                            "label": "flower_relation_issue",
                            "branch_unit_id": unit_id,
                            "flower_id": flower_id,
                            "detail": "support curve entered the target flower core before its endpoint",
                        }
                    )
            elif any(
                _inside_ellipse(point, flower, protection=True)
                for point in samples[1:]
            ):
                issues.append(
                    {
                        "label": "flower_relation_issue",
                        "branch_unit_id": unit_id,
                        "flower_id": flower_id,
                        "detail": "curve entered a non-target flower protection region",
                    }
                )
        if curve["structural_role"] == "terminal_flower_support":
            relation = curve["flower_relation_intents"][0]
            flower = flower_by_id[relation["flower_id"]]
            first_cubic_samples = sample_cubics(
                [cubics[0]],
                samples_per_cubic=72,
            )
            if any(
                _inside_ellipse(point, flower, protection=True)
                for point in first_cubic_samples[:-1]
            ):
                issues.append(
                    {
                        "label": "flower_relation_issue",
                        "branch_unit_id": unit_id,
                        "flower_id": relation["flower_id"],
                        "detail": "SW3 route entered the flower reserve before the below-flower waypoint",
                    }
                )

    crossing_pairs: list[list[str]] = []
    for first, second in itertools.combinations(
        candidate["branch_curves"],
        2,
    ):
        first_points = sampled_by_id[first["branch_unit_id"]]
        second_points = sampled_by_id[second["branch_unit_id"]]
        if any(
            _polyline_crosses(
                first_points,
                [(point[0] + shift, point[1]) for point in second_points],
            )
            for shift in (-1.0, 0.0, 1.0)
        ):
            pair = [first["branch_unit_id"], second["branch_unit_id"]]
            crossing_pairs.append(pair)
            issues.append(
                {
                    "label": "collision_issue",
                    "branch_unit_ids": pair,
                    "detail": "compiled Bezier branch curves cross",
                }
            )

    backbone_crossing_units: list[str] = []
    for curve in candidate["branch_curves"]:
        unit_id = str(curve["branch_unit_id"])
        points = sampled_by_id[unit_id]
        skip = max(5, round((len(points) - 1) * 0.15))
        post_root_points = points[skip:]
        crosses_backbone = any(
            _polyline_crosses(
                post_root_points,
                [(point[0] + shift, point[1]) for point in backbone],
            )
            for shift in (-1.0, 0.0, 1.0)
        )
        if crosses_backbone:
            backbone_crossing_units.append(unit_id)
            issues.append(
                {
                    "label": "collision_issue",
                    "branch_unit_id": unit_id,
                    "detail": "compiled branch crosses the parent backbone away from its root",
                }
            )

    labels = sorted({str(issue["label"]) for issue in issues})
    return {
        "schema": "dynamic_branch_curve_compile_diagnostics_v1",
        "candidate_id": candidate["candidate_id"],
        "candidate_digest": candidate["candidate_digest"],
        "prototype_id": candidate["prototype_id"],
        "seed": candidate["seed"],
        "read_only": True,
        "candidate_modified": False,
        "retry_attempted": False,
        "automatic_repair_attempted": False,
        "automatic_deletion_attempted": False,
        "curve_count": len(candidate["branch_curves"]),
        "cubic_segment_count": sum(
            len(curve["cubic_segments"])
            for curve in candidate["branch_curves"]
        ),
        "maximum_stage3_corridor_escape": _round(maximum_corridor_escape),
        "maximum_root_tangent_error_degrees": _round(
            maximum_root_tangent_error,
            8,
        ),
        "minimum_primary_parent_clearance_after_initial_departure": (
            None
            if math.isinf(minimum_primary_parent_clearance)
            else _round(minimum_primary_parent_clearance)
        ),
        "curve_curve_crossing_count": len(crossing_pairs),
        "curve_curve_crossing_pairs": crossing_pairs,
        "non_root_backbone_crossing_count": len(backbone_crossing_units),
        "non_root_backbone_crossing_units": backbone_crossing_units,
        "issue_count": len(issues),
        "issue_labels": labels,
        "issues": issues,
        "visual_review_still_required": True,
        "numeric_checks_auto_approved_candidate": False,
    }
