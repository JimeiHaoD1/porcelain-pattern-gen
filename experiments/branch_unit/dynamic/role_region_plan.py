"""Curve-free role-region planning for dynamic BranchUnit R.

This module is an internal data layer.  It consumes only approved Stage-2
prototype analysis plus the verified R2A topology.  It does not expose a CLI,
read branch candidates, or compile branch geometry.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


SCHEMA = "dynamic_branch_role_region_plan_v2"
REGION_SCHEMA = "dynamic_branch_role_region_v2"
Point = tuple[float, float]


class RoleRegionPlanError(RuntimeError):
    """The frozen region plan cannot be derived from the approved inputs."""


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _finite(value: object, path: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise RoleRegionPlanError(f"{path} must be finite")
    return number


def _point(value: object, path: str) -> Point:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
    ):
        raise RoleRegionPlanError(f"{path} must be a two-number point")
    return _finite(value[0], f"{path}[0]"), _finite(value[1], f"{path}[1]")


def _round(value: float) -> float:
    return round(float(value), 9)


def _round_point(value: Point) -> list[float]:
    return [_round(value[0]), _round(value[1])]


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scale: float) -> Point:
    return a[0] * scale, a[1] * scale


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _length(value: Point) -> float:
    return math.hypot(value[0], value[1])


def _distance(a: Point, b: Point) -> float:
    return _length(_sub(a, b))


def _unit(value: Point, path: str) -> Point:
    length = _length(value)
    if length <= 1e-12:
        raise RoleRegionPlanError(f"{path} must be non-degenerate")
    return value[0] / length, value[1] / length


def _lerp(a: Point, b: Point, fraction: float) -> Point:
    return (
        a[0] + (b[0] - a[0]) * fraction,
        a[1] + (b[1] - a[1]) * fraction,
    )


def _interpolate_scalar(rows: Sequence[tuple[float, float]], u: float) -> float:
    if u <= rows[0][0]:
        return rows[0][1]
    for index in range(1, len(rows)):
        left_u, left_value = rows[index - 1]
        right_u, right_value = rows[index]
        if u <= right_u:
            fraction = (u - left_u) / (right_u - left_u)
            return left_value + (right_value - left_value) * fraction
    return rows[-1][1]


def _sample_catmull_rom(
    anchors: Sequence[Point],
    samples_per_span: int = 8,
) -> list[Point]:
    """Sample a smooth, morphology-driven guide through dynamic anchors."""

    if len(anchors) < 4:
        raise RoleRegionPlanError("a region guide needs at least four anchors")
    points: list[Point] = []
    extended = [anchors[0], *anchors, anchors[-1]]
    for span in range(1, len(extended) - 2):
        p0, p1, p2, p3 = extended[span - 1 : span + 3]
        start = 0 if span == 1 else 1
        for sample in range(start, samples_per_span + 1):
            t = sample / samples_per_span
            t2 = t * t
            t3 = t2 * t
            points.append(
                (
                    0.5
                    * (
                        2.0 * p1[0]
                        + (-p0[0] + p2[0]) * t
                        + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0])
                        * t2
                        + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0])
                        * t3
                    ),
                    0.5
                    * (
                        2.0 * p1[1]
                        + (-p0[1] + p2[1]) * t
                        + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1])
                        * t2
                        + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1])
                        * t3
                    ),
                )
            )
    return points


def _guide_tangents(points: Sequence[Point]) -> list[Point]:
    tangents: list[Point] = []
    for index in range(len(points)):
        before = points[max(0, index - 1)]
        after = points[min(len(points) - 1, index + 1)]
        tangents.append(_unit(_sub(after, before), f"guide tangent {index}"))
    return tangents


def _soft_channel_boundary(
    guide: Sequence[Point],
    tangents: Sequence[Point],
    width_profile: Sequence[tuple[float, float]],
) -> list[Point]:
    left: list[Point] = []
    right: list[Point] = []
    denominator = max(1, len(guide) - 1)
    for index, (point, tangent) in enumerate(zip(guide, tangents)):
        u = index / denominator
        half_width = _interpolate_scalar(width_profile, u)
        normal = (-tangent[1], tangent[0])
        left.append(_add(point, _mul(normal, half_width)))
        right.append(_sub(point, _mul(normal, half_width)))
    return [*left, *reversed(right), left[0]]


def _enforce_flower_clearance(
    guide: Sequence[Point],
    width_profile: Sequence[tuple[float, float]],
    flower: Mapping[str, Any],
) -> list[Point]:
    """Keep the future soft channel outside the frozen flower protection zone."""

    center = _point(flower["center"], "clearance flower center")
    rx = float(flower["protection_rx"])
    ry = float(flower["protection_ry"])
    conservative_radius = min(rx, ry)
    denominator = max(1, len(guide) - 1)
    cleared: list[Point] = []
    for index, point in enumerate(guide):
        u = index / denominator
        half_width = _interpolate_scalar(width_profile, u)
        normalized = (
            (point[0] - center[0]) / rx,
            (point[1] - center[1]) / ry,
        )
        rho = _length(normalized)
        required_rho = 1.06 + 1.08 * half_width / conservative_radius
        if rho < required_rho:
            if rho <= 1e-12:
                raise RoleRegionPlanError(
                    "role guide cannot pass through the flower center"
                )
            scale = required_rho / rho
            point = (
                center[0] + normalized[0] * rx * scale,
                center[1] + normalized[1] * ry * scale,
            )
        cleared.append(point)
    return cleared


def _angle_degrees(vector: Point) -> float:
    return math.degrees(math.atan2(vector[1], vector[0]))


def _backbone_at_s(
    samples: Sequence[Mapping[str, Any]],
    target_s: float,
) -> tuple[Point, Point]:
    s = max(0.0, min(1.0, target_s))
    for index in range(1, len(samples)):
        left = samples[index - 1]
        right = samples[index]
        if s <= float(right["s"]):
            span = float(right["s"]) - float(left["s"])
            fraction = 0.0 if span <= 1e-12 else (s - float(left["s"])) / span
            point = _lerp(
                _point(left["point"], "backbone point"),
                _point(right["point"], "backbone point"),
                fraction,
            )
            tangent = _unit(
                _lerp(
                    _point(left["tangent"], "backbone tangent"),
                    _point(right["tangent"], "backbone tangent"),
                    fraction,
                ),
                "interpolated backbone tangent",
            )
            return point, tangent
    last = samples[-1]
    return (
        _point(last["point"], "backbone final point"),
        _unit(_point(last["tangent"], "backbone final tangent"), "final tangent"),
    )


def _oriented_tangent(tangent: Point, toward: Point) -> Point:
    return tangent if _dot(tangent, toward) >= 0.0 else _mul(tangent, -1.0)


def _entry_range(center: float, half_span: float) -> list[float]:
    return [_round(max(0.0, center - half_span)), _round(min(1.0, center + half_span))]


def _nearby_probe_ids(
    analysis: Mapping[str, Any],
    entry_range: Sequence[float],
) -> list[str]:
    low, high = float(entry_range[0]), float(entry_range[1])
    return [
        str(row["probe_id"])
        for row in analysis["space_analysis"]["probes"]
        if low <= float(row["s"]) <= high
    ]


def _role_region(
    *,
    prototype_id: str,
    family_id: str,
    role: str,
    region_id: str,
    service_flower_id: str,
    entry_s_range: Sequence[float],
    anchors: Sequence[Point],
    width_profile: Sequence[tuple[float, float]],
    target_relation: str,
    target_sector: str,
    capacity: Mapping[str, int],
    priority: int,
    overlap_roles: Sequence[str],
    forbidden_ids: Sequence[str],
    analysis: Mapping[str, Any],
    source_region_ids: Sequence[str],
    protection_flower: Mapping[str, Any],
) -> dict[str, Any]:
    guide = _sample_catmull_rom(anchors)
    guide = _enforce_flower_clearance(
        guide,
        width_profile,
        protection_flower,
    )
    tangents = _guide_tangents(guide)
    boundary = _soft_channel_boundary(guide, tangents, width_profile)
    entry_angle = _angle_degrees(tangents[0])
    return {
        "schema": REGION_SCHEMA,
        "region_id": region_id,
        "unit_id": prototype_id,
        "role": role,
        "geometry_kind": "morphology_derived_variable_width_soft_channel",
        "service_flower_id": service_flower_id,
        "family_id": family_id,
        "entry_s_range": [_round(float(value)) for value in entry_s_range],
        "entry_direction_range_deg": [
            _round(entry_angle - 12.0),
            _round(entry_angle + 12.0),
        ],
        "guide_centerline": [_round_point(value) for value in guide],
        "guide_centerline_digest": canonical_digest(
            [_round_point(value) for value in guide]
        ),
        "guide_tangents": [_round_point(value) for value in tangents],
        "width_profile": [
            {"u": _round(u), "half_width": _round(width)}
            for u, width in width_profile
        ],
        "boundary": [_round_point(value) for value in boundary],
        "target_relation": target_relation,
        "target_sector": target_sector,
        "exit_direction": _round_point(tangents[-1]),
        "capacity": dict(capacity),
        "priority": priority,
        "soft_overlap_allowed_with": list(overlap_roles),
        "forbidden_overlap_ids": list(forbidden_ids),
        "source_geometry": {
            "backbone_s_ranges": [
                [_round(float(value)) for value in entry_s_range]
            ],
            "space_probe_ids": _nearby_probe_ids(analysis, entry_s_range),
            "protection_zone_ids": list(forbidden_ids),
            "source_region_ids": list(source_region_ids),
            "topology_contract_digest": None,
        },
        "created_before_branch_geometry": True,
        "region_plan_digest": None,
    }


def _flower_forbidden_region(
    *,
    prototype_id: str,
    family_id: str,
    flower: Mapping[str, Any],
) -> dict[str, Any]:
    center = _point(flower["center"], "flower center")
    rx = float(flower["protection_rx"])
    ry = float(flower["protection_ry"])
    boundary = [
        (
            center[0] + rx * math.cos(2.0 * math.pi * index / 64),
            center[1] + ry * math.sin(2.0 * math.pi * index / 64),
        )
        for index in range(64)
    ]
    boundary.append(boundary[0])
    return {
        "schema": REGION_SCHEMA,
        "region_id": f"{prototype_id}__{flower['flower_id']}__flower_forbidden",
        "unit_id": prototype_id,
        "role": "flower_forbidden_region",
        "geometry_kind": "morphology_derived_hard_ellipse",
        "service_flower_id": str(flower["flower_id"]),
        "family_id": family_id,
        "boundary": [_round_point(value) for value in boundary],
        "source_geometry": {
            "flower_center": _round_point(center),
            "flower_rx": _round(float(flower["rx"])),
            "flower_ry": _round(float(flower["ry"])),
            "protection_padding": _round(float(flower["protection_padding"])),
        },
        "created_before_branch_geometry": True,
        "region_plan_digest": None,
    }


def _backbone_protection_region(
    *,
    prototype_id: str,
    family_id: str,
    analysis: Mapping[str, Any],
    reference_flower: Mapping[str, Any],
) -> dict[str, Any]:
    samples = analysis["backbone"]["samples"]
    points = [_point(row["point"], "backbone point") for row in samples]
    tangents = [
        _unit(_point(row["tangent"], "backbone tangent"), "backbone tangent")
        for row in samples
    ]
    base_width = min(
        float(reference_flower["rx"]),
        float(reference_flower["ry"]),
    ) * 0.11
    widths = [
        base_width
        * (
            0.88
            + 0.16
            * abs(float(row["tangent"][0]))
        )
        for row in samples
    ]
    left = [
        _add(point, _mul((-tangent[1], tangent[0]), width))
        for point, tangent, width in zip(points, tangents, widths)
    ]
    right = [
        _sub(point, _mul((-tangent[1], tangent[0]), width))
        for point, tangent, width in zip(points, tangents, widths)
    ]
    boundary = [*left, *reversed(right), left[0]]
    return {
        "schema": REGION_SCHEMA,
        "region_id": f"{prototype_id}__backbone_protection_1",
        "unit_id": prototype_id,
        "role": "backbone_protection_region",
        "geometry_kind": "backbone_derived_variable_width_closed_band",
        "service_flower_id": str(reference_flower["flower_id"]),
        "family_id": family_id,
        "boundary": [_round_point(value) for value in boundary],
        "source_geometry": {
            "backbone_sample_count": len(points),
            "width_basis": "reference_flower_minor_radius_and_local_tangent",
        },
        "created_before_branch_geometry": True,
        "region_plan_digest": None,
    }


def _validate_inputs(
    analysis: Mapping[str, Any],
    topology: Mapping[str, Any],
    service_flower_id: str,
) -> tuple[str, Mapping[str, Any]]:
    if analysis.get("schema") != "dynamic_branch_prototype_analysis_v1":
        raise RoleRegionPlanError("R2B requires approved Stage-2 analysis")
    if analysis.get("prototype_id") != "proto_sw_1_1":
        raise RoleRegionPlanError("R2B frozen instance is proto_sw_1_1")
    contract = analysis.get("analysis_contract", {})
    boundary = analysis.get("stage_boundary", {})
    forbidden_flags = (
        bool(contract.get("curve_geometry_present")),
        bool(contract.get("old_branches_consumed")),
        bool(contract.get("old_growth_regions_consumed")),
        bool(contract.get("old_region_graph_consumed")),
        bool(contract.get("planner_decisions_present")),
        bool(boundary.get("curve_compilation_present")),
        bool(boundary.get("dynamic_branch_plan_present")),
        bool(boundary.get("stage_3_candidate_slots_started")),
    )
    if any(forbidden_flags):
        raise RoleRegionPlanError("R2B input contains forbidden post-region state")
    if topology.get("schema") != "dynamic_branch_R_prototype_topology_v2":
        raise RoleRegionPlanError("R2B requires verified R2A topology")
    if topology.get("family") != "SW1":
        raise RoleRegionPlanError("R2B frozen instance requires SW1 topology")
    roles = {
        str(row["role"])
        for row in topology.get("slots", [])
        if row.get("service_flower_id") == service_flower_id
    }
    if not {"flower_support", "flower_wrap", "balance"}.issubset(roles):
        raise RoleRegionPlanError("R2B target flower lacks frozen SW1 role slots")
    flower = next(
        (
            row
            for row in analysis.get("flowers", [])
            if row.get("flower_id") == service_flower_id
        ),
        None,
    )
    if flower is None:
        raise RoleRegionPlanError(f"unknown service flower: {service_flower_id}")
    return str(analysis["prototype_id"]), flower


def _balance_source(
    analysis: Mapping[str, Any],
    core_guides: Sequence[Sequence[Point]],
    service_flower: Mapping[str, Any],
    excluded_s_ranges: Sequence[Sequence[float]],
) -> Mapping[str, Any]:
    center = _point(service_flower["center"], "service flower center")
    bounds = [
        float(value)
        for value in analysis["coordinate_system"]["canvas_bounds"]
    ]

    def overlaps(entry: Mapping[str, Any]) -> bool:
        candidate_range = entry["s_ranges"][0]
        return any(
            max(float(candidate_range[0]), float(other[0]))
            <= min(float(candidate_range[1]), float(other[1]))
            for other in excluded_s_ranges
        )

    def inside_effective_unit(entry: Mapping[str, Any]) -> bool:
        root = _point(entry["best_root"], "balance probe root")
        target = _point(entry["best_target"], "balance probe target")
        return all(
            (
                bounds[0] <= root[0] <= bounds[2],
                bounds[1] <= root[1] <= bounds[3],
                bounds[0] <= target[0] <= bounds[2],
                bounds[1] <= target[1] <= bounds[3],
            )
        )

    candidates = [
        row
        for row in analysis["candidate_l1_attachment_regions"]
        if not overlaps(row) and inside_effective_unit(row)
    ]
    if not candidates:
        raise RoleRegionPlanError("no residual attachment interval for balance")

    def score(row: Mapping[str, Any]) -> tuple[float, float, str]:
        target = _point(row["best_target"], "balance probe target")
        root = _point(row["best_root"], "balance probe root")
        core_clearance = min(
            _distance(target, point)
            for guide in core_guides
            for point in guide
        )
        flower_clearance = _distance(target, center)
        horizontal = abs(target[0] - root[0])
        return (
            core_clearance + 0.45 * flower_clearance + 0.35 * horizontal,
            float(row["mean_clearance"]),
            str(row["region_id"]),
        )

    return max(candidates, key=score)


def build_sw1_role_region_plan(
    analysis: Mapping[str, Any],
    topology: Mapping[str, Any],
    service_flower_id: str,
) -> dict[str, Any]:
    """Create the frozen R2B region plan before any branch candidate geometry."""

    prototype_id, flower = _validate_inputs(
        analysis,
        topology,
        service_flower_id,
    )
    family_id = "SW1"
    backbone = analysis["backbone"]["samples"]
    center = _point(flower["center"], "service flower center")
    protection_rx = float(flower["protection_rx"])
    protection_ry = float(flower["protection_ry"])
    minor_radius = min(float(flower["rx"]), float(flower["ry"]))
    canvas = [
        float(value)
        for value in analysis["coordinate_system"]["canvas_bounds"]
    ]

    support_context = flower["support_context_s_ranges"][0]
    support_span = float(support_context[1]) - float(support_context[0])
    support_s = float(support_context[0]) + 0.18 * support_span
    support_entry = _entry_range(support_s, max(0.014, 0.18 * support_span))
    support_root, support_tangent = _backbone_at_s(backbone, support_s)
    support_half_width = minor_radius * 0.16
    support_target = (
        center[0],
        center[1] + protection_ry + 1.35 * support_half_width,
    )
    support_tangent = _oriented_tangent(
        support_tangent,
        _sub(support_target, support_root),
    )
    support_chord = _distance(support_root, support_target)
    support_anchors = [
        support_root,
        _add(support_root, _mul(support_tangent, 0.18 * support_chord)),
        (
            center[0] + 0.72 * protection_rx,
            center[1] + 0.73 * protection_ry,
        ),
        support_target,
    ]
    support_widths = [
        (0.0, support_half_width * 0.58),
        (0.25, support_half_width * 0.92),
        (0.50, support_half_width * 1.16),
        (0.75, support_half_width * 1.00),
        (1.0, support_half_width * 0.54),
    ]

    trough_features = [
        row
        for row in analysis["backbone"]["extrema"]
        if row["kind"] == "trough"
    ]
    if not trough_features:
        raise RoleRegionPlanError(
            "SW1 wrap planning requires a Stage-2 detected trough"
        )

    def trough_separation(feature: Mapping[str, Any]) -> tuple[float, float, str]:
        feature_s = float(feature["s"])
        separation = abs(feature_s - support_s)
        periodic_separation = min(separation, 1.0 - separation)
        return (
            periodic_separation,
            float(feature["prominence"]),
            str(feature["feature_id"]),
        )

    wrap_origin_feature = max(trough_features, key=trough_separation)
    wrap_s = float(wrap_origin_feature["s"])
    wrap_entry = _entry_range(wrap_s, max(0.018, 0.22 * support_span))
    if not (
        wrap_entry[1] < support_entry[0]
        or support_entry[1] < wrap_entry[0]
    ):
        raise RoleRegionPlanError("support and wrap entry intervals overlap")
    wrap_root, wrap_tangent = _backbone_at_s(backbone, wrap_s)
    wrap_half_width = minor_radius * 0.145
    wrap_lower_right = (
        center[0] + protection_rx + 1.30 * wrap_half_width,
        center[1] + protection_ry + 1.05 * wrap_half_width,
    )
    wrap_lower = (
        center[0] + 0.08 * protection_rx,
        center[1] + protection_ry + 1.12 * wrap_half_width,
    )
    wrap_left_lower = (
        center[0] - protection_rx - 1.25 * wrap_half_width,
        center[1] + 0.38 * protection_ry,
    )
    wrap_tangent = _oriented_tangent(
        wrap_tangent,
        _sub(wrap_lower_right, wrap_root),
    )
    wrap_chord = _distance(wrap_root, wrap_lower_right)
    wrap_exit = (
        center[0] - protection_rx - 1.05 * wrap_half_width,
        center[1] - 0.10 * protection_ry,
    )
    wrap_anchors = [
        wrap_root,
        _add(wrap_root, _mul(wrap_tangent, max(0.05, 0.22 * wrap_chord))),
        wrap_lower_right,
        wrap_lower,
        wrap_left_lower,
        wrap_exit,
    ]
    wrap_widths = [
        (0.0, wrap_half_width * 0.55),
        (0.25, wrap_half_width * 0.88),
        (0.50, wrap_half_width * 1.05),
        (0.75, wrap_half_width * 0.90),
        (1.0, wrap_half_width * 0.52),
    ]

    forbidden_id = f"{prototype_id}__{service_flower_id}__flower_forbidden"
    backbone_id = f"{prototype_id}__backbone_protection_1"
    support = _role_region(
        prototype_id=prototype_id,
        family_id=family_id,
        role="support_region",
        region_id=f"{prototype_id}__{service_flower_id}__support",
        service_flower_id=service_flower_id,
        entry_s_range=support_entry,
        anchors=support_anchors,
        width_profile=support_widths,
        target_relation="support_flower_lower_sector",
        target_sector="flower_lower_outer_sector",
        capacity={"maximum_l1_count": 1, "maximum_l2_count": 0},
        priority=20,
        overlap_roles=["wrap_region"],
        forbidden_ids=[forbidden_id, backbone_id],
        analysis=analysis,
        source_region_ids=[],
        protection_flower=flower,
    )
    wrap = _role_region(
        prototype_id=prototype_id,
        family_id=family_id,
        role="wrap_region",
        region_id=f"{prototype_id}__{service_flower_id}__wrap",
        service_flower_id=service_flower_id,
        entry_s_range=wrap_entry,
        anchors=wrap_anchors,
        width_profile=wrap_widths,
        target_relation="enclose_flower_outer_edge_then_return",
        target_sector="flower_side_lower_outer_perimeter",
        capacity={"maximum_l1_count": 1, "maximum_l2_count": 0},
        priority=20,
        overlap_roles=["support_region"],
        forbidden_ids=[forbidden_id, backbone_id],
        analysis=analysis,
        source_region_ids=[str(support["region_id"])],
        protection_flower=flower,
    )
    wrap["source_geometry"].update(
        {
            "origin_feature_id": str(
                wrap_origin_feature["feature_id"]
            ),
            "origin_feature_kind": str(wrap_origin_feature["kind"]),
            "origin_feature_s": _round(wrap_s),
            "origin_feature_arc_distance": 0.0,
            "origin_policy": (
                "most_separated_stage2_detected_trough_from_support_entry"
            ),
        }
    )

    support_guide = [
        _point(value, "support guide") for value in support["guide_centerline"]
    ]
    wrap_guide = [
        _point(value, "wrap guide") for value in wrap["guide_centerline"]
    ]
    balance_source = _balance_source(
        analysis,
        [support_guide, wrap_guide],
        flower,
        [support_entry, wrap_entry],
    )
    balance_entry = [
        _round(float(value))
        for value in balance_source["s_ranges"][0]
    ]
    balance_root = _point(balance_source["best_root"], "balance root")
    balance_target = _point(balance_source["best_target"], "balance target")
    balance_tangent = _unit(
        _point(balance_source["best_direction"], "balance direction"),
        "balance direction",
    )
    balance_tangent = _oriented_tangent(
        balance_tangent,
        _sub(balance_target, balance_root),
    )
    balance_chord = _distance(balance_root, balance_target)
    balance_half_width = minor_radius * 0.13
    balance_mid = _lerp(balance_root, balance_target, 0.58)
    balance_anchors = [
        balance_root,
        _add(balance_root, _mul(balance_tangent, 0.19 * balance_chord)),
        _add(
            balance_mid,
            (
                0.0,
                -0.08
                * math.copysign(
                    min(protection_rx, protection_ry),
                    balance_target[1] - center[1],
                ),
            ),
        ),
        balance_target,
    ]
    balance_widths = [
        (0.0, balance_half_width * 0.55),
        (0.25, balance_half_width * 0.90),
        (0.50, balance_half_width * 1.05),
        (0.75, balance_half_width * 0.82),
        (1.0, balance_half_width * 0.48),
    ]
    balance = _role_region(
        prototype_id=prototype_id,
        family_id=family_id,
        role="balance_region",
        region_id=f"{prototype_id}__{service_flower_id}__balance",
        service_flower_id=service_flower_id,
        entry_s_range=balance_entry,
        anchors=balance_anchors,
        width_profile=balance_widths,
        target_relation="counterweight_without_flower_connection",
        target_sector="largest_residual_opposite_sector",
        capacity={"maximum_l1_count": 1, "maximum_l2_count": 0},
        priority=30,
        overlap_roles=["support_region", "wrap_region"],
        forbidden_ids=[forbidden_id, backbone_id],
        analysis=analysis,
        source_region_ids=[
            str(balance_source["region_id"]),
            str(support["region_id"]),
            str(wrap["region_id"]),
        ],
        protection_flower=flower,
    )

    topology_digest = str(topology["topology_contract_digest"])
    for region in (support, wrap, balance):
        region["source_geometry"]["topology_contract_digest"] = topology_digest

    regions = [
        _flower_forbidden_region(
            prototype_id=prototype_id,
            family_id=family_id,
            flower=flower,
        ),
        _backbone_protection_region(
            prototype_id=prototype_id,
            family_id=family_id,
            analysis=analysis,
            reference_flower=flower,
        ),
        support,
        wrap,
        balance,
    ]
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": f"{prototype_id}__{service_flower_id}__role_regions_v2",
        "prototype_id": prototype_id,
        "family_id": family_id,
        "service_flower_id": service_flower_id,
        "topology_contract_digest": topology_digest,
        "source_analysis_digest": str(analysis["analysis_digest"]),
        "unit_bounds": [_round(value) for value in canvas],
        "periodic_seam": {
            "axis": "x",
            "repeat_x_range": [
                _round(float(value))
                for value in analysis["coordinate_system"]["repeat_x_range"]
            ],
            "left_guard_visible": True,
            "right_guard_visible": True,
        },
        "generation_order": [
            "local_coordinate_frame",
            "hard_constraint_regions",
            "role_entry_intervals",
            "guide_centerlines",
            "variable_width_soft_channels",
            "SW1_support_wrap_interlock",
            "balance_from_remaining_space",
            "freeze_before_branch_geometry",
        ],
        "input_provenance": {
            "stage2_analysis_only": True,
            "R2A_topology_only": True,
            "branch_geometry_used_as_input": False,
            "selected_candidate_used_as_input": False,
            "stage5_selection_used_as_input": False,
            "seed_used_as_geometry_input": False,
        },
        "stage_scope": {
            "new_branch_curve_count": 0,
            "role_region_count": 3,
            "hard_constraint_region_count": 2,
            "region_plan_created_before_branch_geometry": True,
        },
        "regions": regions,
        "region_plan_digest": None,
    }
    digest_source = json.loads(json.dumps(plan))
    digest_source["region_plan_digest"] = None
    for region in digest_source["regions"]:
        region["region_plan_digest"] = None
    region_plan_digest = canonical_digest(digest_source)
    plan["region_plan_digest"] = region_plan_digest
    for region in plan["regions"]:
        region["region_plan_digest"] = region_plan_digest
    return plan


def build_sw3_remote_support_region_plan(
    analysis: Mapping[str, Any],
    topology: Mapping[str, Any],
    service_flower_id: str,
) -> dict[str, Any]:
    """Create the curve-free R2D remote-support channel before candidates."""

    if analysis.get("schema") != "dynamic_branch_prototype_analysis_v1":
        raise RoleRegionPlanError("R2D requires approved Stage-2 analysis")
    if analysis.get("prototype_id") != "proto_sw_3_1":
        raise RoleRegionPlanError("R2D frozen instance is proto_sw_3_1")
    contract = analysis.get("analysis_contract", {})
    boundary = analysis.get("stage_boundary", {})
    if any(
        (
            bool(contract.get("curve_geometry_present")),
            bool(contract.get("old_branches_consumed")),
            bool(contract.get("old_growth_regions_consumed")),
            bool(contract.get("old_region_graph_consumed")),
            bool(contract.get("planner_decisions_present")),
            bool(boundary.get("curve_compilation_present")),
            bool(boundary.get("dynamic_branch_plan_present")),
            bool(boundary.get("stage_3_candidate_slots_started")),
        )
    ):
        raise RoleRegionPlanError(
            "R2D input contains forbidden post-region state"
        )
    if topology.get("schema") != "dynamic_branch_R_prototype_topology_v2":
        raise RoleRegionPlanError("R2D requires verified R2A topology")
    if topology.get("family") != "SW3":
        raise RoleRegionPlanError("R2D frozen instance requires SW3 topology")
    matching_slots = [
        row
        for row in topology.get("slots", [])
        if row.get("role") == "remote_flower_support"
        and row.get("service_flower_id") == service_flower_id
        and row.get("level") == "L1"
        and row.get("parent") == "backbone"
        and row.get("parent_curve_id") is None
    ]
    if len(matching_slots) != 1:
        raise RoleRegionPlanError(
            "R2D target flower lacks one frozen remote-support L1 slot"
        )
    flower = next(
        (
            row
            for row in analysis.get("flowers", [])
            if row.get("flower_id") == service_flower_id
        ),
        None,
    )
    if flower is None:
        raise RoleRegionPlanError(
            f"unknown R2D service flower: {service_flower_id}"
        )

    prototype_id = str(analysis["prototype_id"])
    family_id = "SW3"
    backbone = analysis["backbone"]["samples"]
    center = _point(flower["center"], "R2D flower center")
    rx = float(flower["rx"])
    ry = float(flower["ry"])
    protection_rx = float(flower["protection_rx"])
    protection_ry = float(flower["protection_ry"])
    nearest_s = float(flower["nearest_backbone_s"])
    remote_distance = 0.5 * (0.30 + 0.48)
    root_options: list[tuple[float, float, Point, Point]] = []
    for direction in (-1.0, 1.0):
        root_s = (nearest_s + direction * remote_distance) % 1.0
        root, tangent = _backbone_at_s(backbone, root_s)
        root_options.append(
            (
                abs(root[0] - center[0]),
                direction,
                root,
                tangent,
            )
        )
    _, root_direction, root, tangent = max(
        root_options,
        key=lambda row: (row[0], row[1]),
    )
    root_s = (nearest_s + root_direction * remote_distance) % 1.0
    entry = _entry_range(root_s, 0.024)
    half_width = min(rx, ry) * 0.12
    contact = (center[0], center[1] + ry)
    lower_margin = max(0.045, 0.18 * min(rx, ry))
    lower_left = (
        center[0] - 0.72 * protection_rx,
        contact[1] + 0.95 * lower_margin,
    )
    lower_mid = (
        center[0] - 0.34 * protection_rx,
        contact[1] + 0.72 * lower_margin,
    )
    guide_target = (
        center[0] - 0.12 * protection_rx,
        contact[1] + 0.32 * lower_margin,
    )
    tangent = _oriented_tangent(tangent, _sub(lower_left, root))
    flower_side_normal = (tangent[1], -tangent[0])
    departure_angle = math.radians(38.0)
    departure_direction = _unit(
        _add(
            _mul(tangent, math.cos(departure_angle)),
            _mul(flower_side_normal, math.sin(departure_angle)),
        ),
        "R2D remote-support departure direction",
    )
    first_chord = _distance(root, lower_left)
    anchors = [
        root,
        _add(
            root,
            _mul(
                departure_direction,
                0.22 * first_chord,
            ),
        ),
        _add(
            _add(
                root,
                _mul(
                    departure_direction,
                    0.42 * first_chord,
                ),
            ),
            _mul(flower_side_normal, 0.18 * first_chord),
        ),
        lower_left,
        lower_mid,
        guide_target,
        contact,
    ]
    widths = [
        (0.0, half_width * 0.52),
        (0.25, half_width * 0.86),
        (0.50, half_width * 1.08),
        (0.75, half_width * 0.88),
        (1.0, half_width * 0.50),
    ]
    forbidden_id = (
        f"{prototype_id}__{service_flower_id}__flower_forbidden"
    )
    backbone_id = f"{prototype_id}__backbone_protection_1"
    remote = _role_region(
        prototype_id=prototype_id,
        family_id=family_id,
        role="remote_support_region",
        region_id=(
            f"{prototype_id}__{service_flower_id}__remote_support"
        ),
        service_flower_id=service_flower_id,
        entry_s_range=entry,
        anchors=anchors,
        width_profile=widths,
        target_relation="remote_mount_below_flower_to_underside",
        target_sector="flower_lower_remote_approach",
        capacity={"maximum_l1_count": 1, "maximum_l2_count": 0},
        priority=20,
        overlap_roles=[],
        forbidden_ids=[forbidden_id, backbone_id],
        analysis=analysis,
        source_region_ids=[],
        protection_flower=flower,
    )
    remote["source_geometry"].update(
        {
            "nearest_backbone_s": _round(nearest_s),
            "remote_root_s": _round(root_s),
            "remote_mount_arc_distance": _round(remote_distance),
            "remote_direction": _round(root_direction),
            "root_selection_policy": (
                "maximum_horizontal_separation_at_frozen_remote_band_midpoint"
            ),
            "below_flower_waypoint": _round_point(lower_left),
            "below_flower_waypoint_margin": _round(
                lower_left[1] - contact[1]
            ),
            "topology_contract_digest": str(
                topology["topology_contract_digest"]
            ),
        }
    )
    regions = [
        _flower_forbidden_region(
            prototype_id=prototype_id,
            family_id=family_id,
            flower=flower,
        ),
        _backbone_protection_region(
            prototype_id=prototype_id,
            family_id=family_id,
            analysis=analysis,
            reference_flower=flower,
        ),
        remote,
    ]
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": (
            f"{prototype_id}__{service_flower_id}"
            "__remote_support_regions_v2"
        ),
        "prototype_id": prototype_id,
        "family_id": family_id,
        "service_flower_id": service_flower_id,
        "topology_contract_digest": str(
            topology["topology_contract_digest"]
        ),
        "source_analysis_digest": str(analysis["analysis_digest"]),
        "unit_bounds": [
            _round(float(value))
            for value in analysis["coordinate_system"]["canvas_bounds"]
        ],
        "periodic_seam": {
            "axis": "x",
            "repeat_x_range": [
                _round(float(value))
                for value in analysis["coordinate_system"][
                    "repeat_x_range"
                ]
            ],
            "left_guard_visible": True,
            "right_guard_visible": True,
        },
        "generation_order": [
            "local_coordinate_frame",
            "hard_constraint_regions",
            "remote_entry_interval",
            "remote_support_guide_centerline",
            "variable_width_soft_channel",
            "freeze_before_branch_geometry",
        ],
        "input_provenance": {
            "stage2_analysis_only": True,
            "R2A_topology_only": True,
            "branch_geometry_used_as_input": False,
            "selected_candidate_used_as_input": False,
            "stage5_selection_used_as_input": False,
            "seed_used_as_geometry_input": False,
        },
        "stage_scope": {
            "new_branch_curve_count": 0,
            "role_region_count": 1,
            "hard_constraint_region_count": 2,
            "region_plan_created_before_branch_geometry": True,
        },
        "regions": regions,
        "region_plan_digest": None,
    }
    digest_source = json.loads(json.dumps(plan))
    for region in digest_source["regions"]:
        region["region_plan_digest"] = None
    region_plan_digest = canonical_digest(digest_source)
    plan["region_plan_digest"] = region_plan_digest
    for region in plan["regions"]:
        region["region_plan_digest"] = region_plan_digest
    return plan


def validate_sw3_remote_support_region_plan(
    plan: Mapping[str, Any],
) -> None:
    if plan.get("schema") != SCHEMA:
        raise RoleRegionPlanError("R2D role region plan schema mismatch")
    if plan.get("prototype_id") != "proto_sw_3_1":
        raise RoleRegionPlanError("R2D role region prototype mismatch")
    if plan.get("family_id") != "SW3":
        raise RoleRegionPlanError("R2D role region family mismatch")
    if plan.get("stage_scope", {}).get("new_branch_curve_count") != 0:
        raise RoleRegionPlanError("R2D region plan must be curve-free")
    regions = plan.get("regions")
    if not isinstance(regions, list):
        raise RoleRegionPlanError("R2D role regions are missing")
    roles = [str(row.get("role")) for row in regions]
    for role in (
        "remote_support_region",
        "flower_forbidden_region",
        "backbone_protection_region",
    ):
        if roles.count(role) != 1:
            raise RoleRegionPlanError(f"R2D requires exactly one {role}")
    digest_source = json.loads(json.dumps(plan))
    stored_digest = digest_source["region_plan_digest"]
    digest_source["region_plan_digest"] = None
    for region in digest_source["regions"]:
        if region.get("region_plan_digest") != stored_digest:
            raise RoleRegionPlanError(
                "R2D region/plan digest reference mismatch"
            )
        region["region_plan_digest"] = None
    if canonical_digest(digest_source) != stored_digest:
        raise RoleRegionPlanError("R2D role region plan digest mismatch")


def build_sw3_group_region_plan(
    analysis: Mapping[str, Any],
    topology: Mapping[str, Any],
    service_flower_id: str,
) -> dict[str, Any]:
    """Plan the R3 SW3 balance channel after the remote-support channel."""

    plan = build_sw3_remote_support_region_plan(
        analysis,
        topology,
        service_flower_id,
    )
    flower = next(
        row
        for row in analysis["flowers"]
        if row["flower_id"] == service_flower_id
    )
    remote = next(
        row
        for row in plan["regions"]
        if row["role"] == "remote_support_region"
    )
    center = _point(flower["center"], "R3 SW3 flower center")
    protection_rx = float(flower["protection_rx"])
    protection_ry = float(flower["protection_ry"])
    minor_radius = min(float(flower["rx"]), float(flower["ry"]))
    backbone = analysis["backbone"]["samples"]
    nearest_s = float(flower["nearest_backbone_s"])

    # The remote support occupies the lower flower-side sector.  The balance
    # root and target are derived from the opposite residual sector, not from
    # a seed-specific point or a pre-existing branch.
    balance_s = (nearest_s + 0.175) % 1.0
    balance_root, balance_tangent = _backbone_at_s(backbone, balance_s)
    bounds = [
        float(value)
        for value in analysis["coordinate_system"]["canvas_bounds"]
    ]
    balance_target = (
        min(
            bounds[2] - 0.08,
            max(bounds[0] + 0.08, center[0] - 1.50 * protection_rx),
        ),
        min(
            bounds[3] - 0.08,
            max(bounds[1] + 0.08, center[1] - 0.64 * protection_ry),
        ),
    )
    balance_tangent = _oriented_tangent(
        balance_tangent,
        _sub(balance_target, balance_root),
    )
    balance_chord = _distance(balance_root, balance_target)
    normal_options = [
        (-balance_tangent[1], balance_tangent[0]),
        (balance_tangent[1], -balance_tangent[0]),
    ]
    balance_normal = max(
        normal_options,
        key=lambda normal: _distance(
            _add(
                _lerp(balance_root, balance_target, 0.52),
                _mul(normal, 0.14 * balance_chord),
            ),
            center,
        ),
    )
    balance_anchors = [
        balance_root,
        _add(
            _add(
                balance_root,
                _mul(balance_tangent, 0.20 * balance_chord),
            ),
            _mul(balance_normal, 0.05 * balance_chord),
        ),
        _add(
            _lerp(balance_root, balance_target, 0.54),
            _mul(balance_normal, 0.14 * balance_chord),
        ),
        balance_target,
    ]
    balance_half_width = minor_radius * 0.13
    balance = _role_region(
        prototype_id=str(analysis["prototype_id"]),
        family_id="SW3",
        role="balance_region",
        region_id=(
            f"{analysis['prototype_id']}__{service_flower_id}__balance"
        ),
        service_flower_id=service_flower_id,
        entry_s_range=_entry_range(balance_s, 0.022),
        anchors=balance_anchors,
        width_profile=[
            (0.0, balance_half_width * 0.54),
            (0.25, balance_half_width * 0.88),
            (0.50, balance_half_width * 1.00),
            (0.75, balance_half_width * 0.78),
            (1.0, balance_half_width * 0.46),
        ],
        target_relation="counterweight_without_flower_connection",
        target_sector="largest_residual_opposite_sector",
        capacity={"maximum_l1_count": 1, "maximum_l2_count": 0},
        priority=30,
        overlap_roles=[],
        forbidden_ids=[
            f"{analysis['prototype_id']}__{service_flower_id}"
            "__flower_forbidden",
            f"{analysis['prototype_id']}__backbone_protection_1",
        ],
        analysis=analysis,
        source_region_ids=[str(remote["region_id"])],
        protection_flower=flower,
    )
    balance["source_geometry"].update(
        {
            "core_region_occupancy_computed_first": True,
            "largest_remaining_sector": "upper_opposite_to_remote_support",
            "balance_root_s": _round(balance_s),
            "balance_target_policy": (
                "flower_frame_opposite_sector_after_remote_occupancy"
            ),
            "topology_contract_digest": str(
                topology["topology_contract_digest"]
            ),
        }
    )
    plan["plan_id"] = (
        f"{analysis['prototype_id']}__{service_flower_id}"
        "__family_group_regions_v2"
    )
    plan["generation_order"] = [
        "local_coordinate_frame",
        "hard_constraint_regions",
        "remote_support_region",
        "compute_core_region_occupancy",
        "compute_largest_remaining_sector",
        "balance_region",
        "freeze_before_branch_geometry",
    ]
    plan["stage_scope"] = {
        "new_branch_curve_count": 0,
        "role_region_count": 2,
        "hard_constraint_region_count": 2,
        "region_plan_created_before_branch_geometry": True,
    }
    plan["regions"].append(balance)
    plan["region_plan_digest"] = None
    digest_source = json.loads(json.dumps(plan))
    for region in digest_source["regions"]:
        region["region_plan_digest"] = None
    region_plan_digest = canonical_digest(digest_source)
    plan["region_plan_digest"] = region_plan_digest
    for region in plan["regions"]:
        region["region_plan_digest"] = region_plan_digest
    return plan


def validate_sw3_group_region_plan(plan: Mapping[str, Any]) -> None:
    validate_sw3_remote_support_region_plan(plan)
    roles = [str(row.get("role")) for row in plan["regions"]]
    if roles.count("balance_region") != 1:
        raise RoleRegionPlanError("R3 SW3 requires exactly one balance region")
    if plan.get("stage_scope", {}).get("role_region_count") not in {2, 3}:
        raise RoleRegionPlanError("R3 SW3 region count mismatch")
    order = list(plan.get("generation_order", []))
    core_step = (
        "remote_support_region"
        if "remote_support_region" in order
        else "core_flower_group"
    )
    if order.index(core_step) > order.index("balance_region"):
        raise RoleRegionPlanError(
            "R3 SW3 balance must be planned after remote support"
        )


def build_sw3_global_unit_region_plan(
    analysis: Mapping[str, Any],
    topology: Mapping[str, Any],
    service_flower_id: str,
) -> dict[str, Any]:
    """Add an R4 seam-directed settle channel after the full core group."""

    plan = build_sw3_group_region_plan(
        analysis,
        topology,
        service_flower_id,
    )
    flower = next(
        row
        for row in analysis["flowers"]
        if row["flower_id"] == service_flower_id
    )
    center = _point(flower["center"], "R4 flower center")
    backbone = analysis["backbone"]["samples"]
    bounds = [
        float(value)
        for value in analysis["coordinate_system"]["canvas_bounds"]
    ]
    nearest_s = float(flower["nearest_backbone_s"])
    settle_s = (nearest_s - 0.275) % 1.0
    settle_root, settle_tangent = _backbone_at_s(backbone, settle_s)
    settle_target = (
        bounds[2] - 0.010,
        min(
            bounds[3] - 0.075,
            max(
                center[1] + float(flower["protection_ry"]) + 0.07,
                settle_root[1] - 0.030,
            ),
        ),
    )
    settle_tangent = _oriented_tangent(
        settle_tangent,
        _sub(settle_target, settle_root),
    )
    settle_chord = _distance(settle_root, settle_target)
    normal_options = [
        (-settle_tangent[1], settle_tangent[0]),
        (settle_tangent[1], -settle_tangent[0]),
    ]
    settle_normal = max(
        normal_options,
        key=lambda normal: _distance(
            _add(
                _lerp(settle_root, settle_target, 0.48),
                _mul(normal, 0.10 * settle_chord),
            ),
            center,
        ),
    )
    settle_anchors = [
        settle_root,
        _add(
            _add(
                settle_root,
                _mul(settle_tangent, 0.22 * settle_chord),
            ),
            _mul(settle_normal, 0.04 * settle_chord),
        ),
        _add(
            _lerp(settle_root, settle_target, 0.54),
            _mul(settle_normal, 0.10 * settle_chord),
        ),
        settle_target,
    ]
    half_width = min(float(flower["rx"]), float(flower["ry"])) * 0.105
    settle = _role_region(
        prototype_id=str(analysis["prototype_id"]),
        family_id="SW3",
        role="settle_region",
        region_id=f"{analysis['prototype_id']}__unit_settle",
        service_flower_id=service_flower_id,
        entry_s_range=_entry_range(settle_s, 0.020),
        anchors=settle_anchors,
        width_profile=[
            (0.0, half_width * 0.54),
            (0.30, half_width * 0.88),
            (0.60, half_width * 0.74),
            (1.0, half_width * 0.38),
        ],
        target_relation="reduce_density_and_rejoin_seam_direction",
        target_sector="right_seam_lower_entry",
        capacity={"maximum_l1_count": 1, "maximum_l2_count": 0},
        priority=40,
        overlap_roles=[],
        forbidden_ids=[
            f"{analysis['prototype_id']}__{service_flower_id}"
            "__flower_forbidden",
            f"{analysis['prototype_id']}__backbone_protection_1",
        ],
        analysis=analysis,
        source_region_ids=[
            str(row["region_id"])
            for row in plan["regions"]
            if row["role"]
            in {"remote_support_region", "balance_region"}
        ],
        protection_flower=flower,
    )
    settle["source_geometry"].update(
        {
            "core_and_balance_occupancy_computed_first": True,
            "settle_root_s": _round(settle_s),
            "terminal_policy": "right_seam_horizontal_continuation",
            "topology_contract_digest": str(
                topology["topology_contract_digest"]
            ),
        }
    )
    plan["plan_id"] = (
        f"{analysis['prototype_id']}__global_unit_regions_v2"
    )
    plan["generation_order"] = [
        "core_flower_group",
        "compute_remaining_capacity",
        "balance_region",
        "reserve_seam_entry",
        "settle_region",
        "freeze_before_branch_geometry",
    ]
    plan["stage_scope"] = {
        "new_branch_curve_count": 0,
        "role_region_count": 3,
        "hard_constraint_region_count": 2,
        "region_plan_created_before_branch_geometry": True,
    }
    plan["regions"].append(settle)
    plan["region_plan_digest"] = None
    digest_source = json.loads(json.dumps(plan))
    for region in digest_source["regions"]:
        region["region_plan_digest"] = None
    region_plan_digest = canonical_digest(digest_source)
    plan["region_plan_digest"] = region_plan_digest
    for region in plan["regions"]:
        region["region_plan_digest"] = region_plan_digest
    return plan


def validate_sw3_global_unit_region_plan(
    plan: Mapping[str, Any],
) -> None:
    validate_sw3_remote_support_region_plan(plan)
    roles = [str(row.get("role")) for row in plan["regions"]]
    if roles.count("balance_region") != 1:
        raise RoleRegionPlanError("R4 requires exactly one balance region")
    if roles.count("settle_region") != 1:
        raise RoleRegionPlanError("R4 requires exactly one settle region")
    if plan.get("stage_scope", {}).get("role_region_count") != 3:
        raise RoleRegionPlanError("R4 role region count mismatch")
    order = list(plan.get("generation_order", []))
    if order.index("balance_region") > order.index("settle_region"):
        raise RoleRegionPlanError("R4 settle must be planned after balance")


def validate_role_region_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") != SCHEMA:
        raise RoleRegionPlanError("role region plan schema mismatch")
    if plan.get("prototype_id") != "proto_sw_1_1":
        raise RoleRegionPlanError("role region plan prototype mismatch")
    if plan.get("family_id") != "SW1":
        raise RoleRegionPlanError("role region plan family mismatch")
    if plan.get("stage_scope", {}).get("new_branch_curve_count") != 0:
        raise RoleRegionPlanError("R2B must not contain branch curves")
    regions = plan.get("regions")
    if not isinstance(regions, list):
        raise RoleRegionPlanError("role region plan regions are missing")
    roles = [str(row.get("role")) for row in regions]
    for role in (
        "support_region",
        "wrap_region",
        "balance_region",
        "flower_forbidden_region",
        "backbone_protection_region",
    ):
        if roles.count(role) != 1:
            raise RoleRegionPlanError(f"R2B requires exactly one {role}")
    digest_source = json.loads(json.dumps(plan))
    stored_digest = digest_source["region_plan_digest"]
    digest_source["region_plan_digest"] = None
    for region in digest_source["regions"]:
        if region.get("region_plan_digest") != stored_digest:
            raise RoleRegionPlanError("region/plan digest reference mismatch")
        region["region_plan_digest"] = None
    if canonical_digest(digest_source) != stored_digest:
        raise RoleRegionPlanError("role region plan digest mismatch")
