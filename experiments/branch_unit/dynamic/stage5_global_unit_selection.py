#!/usr/bin/env python3
"""Build cross-Unit conflicts and select one immutable Unit per approved lane."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Mapping, Sequence

from branch_unit_grammar_v1 import (
    _add,
    _cubic,
    _curve_crosses,
    _distance,
    _mul,
    _point,
    _sample_segments,
    _sub,
    _unit,
)


SCHEMA = "dynamic_branch_stage5_global_unit_selection_v1"
CONFLICT_SCHEMA = "dynamic_branch_stage5_candidate_conflict_graph_v1"
CONTRACT_SCHEMA = "dynamic_branch_stage5_global_selection_contract_v1"


class Stage5SelectionError(RuntimeError):
    """The immutable candidate pool cannot be processed under the contract."""


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _curve_bounds(
    curve: Mapping[str, Any],
    shift_x: float = 0.0,
) -> tuple[float, float, float, float]:
    points = curve["centerline"]
    return (
        min(float(point[0]) for point in points) + shift_x,
        min(float(point[1]) for point in points),
        max(float(point[0]) for point in points) + shift_x,
        max(float(point[1]) for point in points),
    )


def _bounds_overlap(
    first: Sequence[float],
    second: Sequence[float],
) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _shift_curve(
    curve: Mapping[str, Any],
    shift_x: float,
) -> dict[str, Any]:
    return {
        "centerline": [
            [float(point[0]) + shift_x, float(point[1])]
            for point in curve["centerline"]
        ]
    }


def candidate_pair_crossings(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    repeat_shifts: Sequence[float],
) -> list[dict[str, Any]]:
    crossings: list[dict[str, Any]] = []
    for first_curve in first["curves"]:
        for second_curve in second["curves"]:
            if (
                first_curve["level"] == "L1"
                and second_curve["level"] == "L1"
            ):
                continue
            first_bounds = _curve_bounds(first_curve)
            for shift_x in repeat_shifts:
                second_bounds = _curve_bounds(second_curve, float(shift_x))
                if not _bounds_overlap(first_bounds, second_bounds):
                    continue
                if _curve_crosses(
                    first_curve,
                    _shift_curve(second_curve, float(shift_x)),
                    None,
                ):
                    crossings.append(
                        {
                            "first_curve_id": first_curve["curve_id"],
                            "first_level": first_curve["level"],
                            "second_curve_id": second_curve["curve_id"],
                            "second_level": second_curve["level"],
                            "second_repeat_shift_x": float(shift_x),
                        }
                    )
    return crossings


def build_conflict_graph(
    inventory: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    repeat_shifts = [
        float(value)
        for value in contract["hard_constraints"]["repeat_shifts_checked"]
    ]
    candidates = inventory["candidates"]
    nodes = [
        {
            "candidate_id": candidate["candidate_id"],
            "source_lane_id": candidate["source_lane_id"],
            "role": candidate["role"],
            "grammar_id": candidate["grammar_id"],
            "parameter_stratum": candidate["parameter_stratum"],
            "eligible": bool(candidate["intrinsic_diagnostics"]["valid"]),
            "intrinsic_issue_codes": [
                issue["code"]
                for issue in candidate["intrinsic_diagnostics"]["issues"]
            ],
        }
        for candidate in candidates
    ]
    eligible = [
        candidate
        for candidate in candidates
        if candidate["intrinsic_diagnostics"]["valid"]
    ]
    edges: list[dict[str, Any]] = []
    for index, first in enumerate(eligible):
        for second in eligible[index + 1 :]:
            if first["source_lane_id"] == second["source_lane_id"]:
                continue
            crossings = candidate_pair_crossings(
                first,
                second,
                repeat_shifts,
            )
            if crossings:
                edges.append(
                    {
                        "first_candidate_id": first["candidate_id"],
                        "first_lane_id": first["source_lane_id"],
                        "second_candidate_id": second["candidate_id"],
                        "second_lane_id": second["source_lane_id"],
                        "reason": "cross_unit_curve_crossing",
                        "crossings": crossings,
                    }
                )
    graph: dict[str, Any] = {
        "schema": CONFLICT_SCHEMA,
        "contract_id": contract["contract_id"],
        "prototype_id": inventory["prototype_id"],
        "seed": inventory["seed"],
        "source_inventory_id": inventory["inventory_id"],
        "source_inventory_digest": inventory["inventory_digest"],
        "node_count": len(nodes),
        "eligible_node_count": len(eligible),
        "ineligible_node_count": len(nodes) - len(eligible),
        "edge_count": len(edges),
        "repeat_shifts_checked": repeat_shifts,
        "nodes": nodes,
        "edges": edges,
    }
    graph["conflict_graph_digest"] = canonical_digest(graph)
    return graph


def _blocking_lane_pairs(
    eligible_by_lane: Mapping[str, Sequence[Mapping[str, Any]]],
    conflict_ids: Mapping[str, set[str]],
) -> list[dict[str, Any]]:
    lanes = sorted(eligible_by_lane)
    rows: list[dict[str, Any]] = []
    for index, first_lane in enumerate(lanes):
        for second_lane in lanes[index + 1 :]:
            first_candidates = eligible_by_lane[first_lane]
            second_candidates = eligible_by_lane[second_lane]
            if all(
                second["candidate_id"]
                in conflict_ids[first["candidate_id"]]
                for first in first_candidates
                for second in second_candidates
            ):
                rows.append(
                    {
                        "first_lane_id": first_lane,
                        "second_lane_id": second_lane,
                        "first_candidate_count": len(first_candidates),
                        "second_candidate_count": len(second_candidates),
                        "reason": "every_candidate_pair_crosses",
                    }
                )
    return rows


def select_global_units(
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    eligible_by_lane: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for candidate in inventory["candidates"]:
        if candidate["intrinsic_diagnostics"]["valid"]:
            eligible_by_lane[str(candidate["source_lane_id"])].append(candidate)

    lane_ids = [str(row["source_lane_id"]) for row in inventory["lanes"]]
    if set(lane_ids) != set(eligible_by_lane):
        raise Stage5SelectionError("one or more lanes have no eligible Unit")
    lane_order = sorted(
        lane_ids,
        key=lambda lane_id: (len(eligible_by_lane[lane_id]), lane_id),
    )

    conflict_ids: dict[str, set[str]] = defaultdict(set)
    for edge in conflict_graph["edges"]:
        first_id = str(edge["first_candidate_id"])
        second_id = str(edge["second_candidate_id"])
        conflict_ids[first_id].add(second_id)
        conflict_ids[second_id].add(first_id)

    priorities = contract["deterministic_order"]["role_stratum_priority"]

    def candidate_order(candidate: Mapping[str, Any]) -> tuple[int, int, str]:
        role_priority = priorities[str(candidate["role"])]
        return (
            role_priority.index(str(candidate["parameter_stratum"])),
            len(conflict_ids[str(candidate["candidate_id"])]),
            str(candidate["candidate_id"]),
        )

    for lane_id in lane_order:
        eligible_by_lane[lane_id].sort(key=candidate_order)

    selected: list[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    search_node_count = 0
    backtrack_count = 0

    def search(lane_index: int) -> bool:
        nonlocal search_node_count, backtrack_count
        if lane_index == len(lane_order):
            return True
        lane_id = lane_order[lane_index]
        for candidate in eligible_by_lane[lane_id]:
            search_node_count += 1
            candidate_id = str(candidate["candidate_id"])
            if selected_ids & conflict_ids[candidate_id]:
                continue
            selected.append(candidate)
            selected_ids.add(candidate_id)
            if search(lane_index + 1):
                return True
            selected.pop()
            selected_ids.remove(candidate_id)
            backtrack_count += 1
        return False

    feasible = search(0)
    selected_candidates = list(selected) if feasible else []
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "contract_id": contract["contract_id"],
        "selection_id": (
            f"{inventory['inventory_id']}__global_unit_selection_v1"
        ),
        "prototype_id": inventory["prototype_id"],
        "family_id": inventory["family_id"],
        "seed": inventory["seed"],
        "source_inventory_id": inventory["inventory_id"],
        "source_inventory_digest": inventory["inventory_digest"],
        "source_conflict_graph_digest": conflict_graph[
            "conflict_graph_digest"
        ],
        "status": (
            contract["output"]["review_state"]
            if feasible
            else "global_unit_selection_infeasible"
        ),
        "feasible": feasible,
        "lane_count": len(lane_ids),
        "selected_candidate_count": len(selected_candidates),
        "selected_candidate_ids": [
            candidate["candidate_id"] for candidate in selected_candidates
        ],
        "selected_candidates": selected_candidates,
        "blocking_lane_pairs": (
            []
            if feasible
            else _blocking_lane_pairs(eligible_by_lane, conflict_ids)
        ),
        "solver_trace": {
            "method": contract["selection"]["solver"],
            "lane_order": lane_order,
            "candidate_order": contract["deterministic_order"][
                "candidate_order"
            ],
            "search_node_count": search_node_count,
            "backtrack_count": backtrack_count,
            "stopped_at_first_complete_legal_assignment": feasible,
            "best_of_n_visual_ranking_used": False,
            "composite_visual_score_used": False,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
            "silent_fallback_used": False,
        },
        "review": {
            "numeric_checks_cannot_auto_approve_visual_gate": True,
            "criteria": [
                "whole_composition_vine_flow",
                "cross_unit_non_crossing",
                "hierarchy_and_density_rhythm",
                "flower_support_relation",
                "repeat_continuity",
            ],
        },
    }
    result["selection_digest"] = canonical_digest(result)
    validate_global_selection(result, conflict_graph)
    return result


def validate_global_selection(
    selection: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
) -> None:
    if selection.get("schema") != SCHEMA:
        raise Stage5SelectionError("selection schema mismatch")
    if selection.get("source_conflict_graph_digest") != conflict_graph.get(
        "conflict_graph_digest"
    ):
        raise Stage5SelectionError("selection/conflict graph mismatch")
    selected = selection.get("selected_candidates")
    if not isinstance(selected, list):
        raise Stage5SelectionError("selected candidate array is missing")
    if selection.get("feasible"):
        if len(selected) != selection.get("lane_count"):
            raise Stage5SelectionError(
                "feasible composition does not cover every lane"
            )
        lane_ids = [candidate["source_lane_id"] for candidate in selected]
        if len(set(lane_ids)) != len(lane_ids):
            raise Stage5SelectionError(
                "feasible composition selects a lane more than once"
            )
        if any(
            not candidate["intrinsic_diagnostics"]["valid"]
            for candidate in selected
        ):
            raise Stage5SelectionError(
                "feasible composition contains an invalid Unit"
            )
        selected_ids = {
            candidate["candidate_id"] for candidate in selected
        }
        for edge in conflict_graph["edges"]:
            if {
                edge["first_candidate_id"],
                edge["second_candidate_id"],
            } <= selected_ids:
                raise Stage5SelectionError(
                    "feasible composition contains a conflict edge"
                )
    elif selected:
        raise Stage5SelectionError(
            "infeasible result must not publish a partial selection"
        )


Point = tuple[float, float]
R6_SCORE_WEIGHTS = {
    "role_completeness_score": 0.20,
    "region_path_score": 0.16,
    "hierarchy_score": 0.10,
    "density_balance_score": 0.15,
    "horizontal_rhythm_score": 0.14,
    "flower_group_score": 0.17,
    "settle_continuity_score": 0.08,
}


def _R6_round_point(point: Point) -> list[float]:
    return [round(point[0], 9), round(point[1], 9)]


def _R6_backbone_at_s(
    samples: Sequence[Mapping[str, Any]],
    value: float,
) -> tuple[Point, Point]:
    target = value % 1.0
    rows = sorted(samples, key=lambda row: float(row["s"]))
    for index in range(1, len(rows)):
        left = rows[index - 1]
        right = rows[index]
        left_s = float(left["s"])
        right_s = float(right["s"])
        if left_s <= target <= right_s:
            span = max(1e-12, right_s - left_s)
            fraction = (target - left_s) / span
            left_point = _point(left["point"], "R6 backbone left")
            right_point = _point(right["point"], "R6 backbone right")
            point = _add(
                left_point,
                _mul(_sub(right_point, left_point), fraction),
            )
            return point, _unit(
                _sub(right_point, left_point),
                "R6 backbone tangent",
            )
    first = _point(rows[0]["point"], "R6 backbone first")
    second = _point(rows[1]["point"], "R6 backbone second")
    return first, _unit(_sub(second, first), "R6 backbone seam tangent")


def _R6_oriented_tangent(tangent: Point, target_vector: Point) -> Point:
    if tangent[0] * target_vector[0] + tangent[1] * target_vector[1] < 0:
        return -tangent[0], -tangent[1]
    return tangent


def _R6_curve_from_anchors(
    *,
    curve_id: str,
    role: str,
    anchors: Sequence[Point],
    root_s: float,
    service_flower_id: str | None,
) -> dict[str, Any]:
    if len(anchors) < 4:
        raise Stage5SelectionError("R6 curve needs at least four anchors")
    tangents: list[Point] = []
    for index in range(len(anchors)):
        before = anchors[max(0, index - 1)]
        after = anchors[min(len(anchors) - 1, index + 1)]
        tangents.append(
            _unit(_sub(after, before), f"{curve_id}.tangent.{index}")
        )
    segments: list[dict[str, list[float]]] = []
    for index in range(1, len(anchors)):
        start = anchors[index - 1]
        end = anchors[index]
        chord = _distance(start, end)
        segments.append(
            _cubic(
                start,
                _add(start, _mul(tangents[index - 1], 0.30 * chord)),
                _sub(end, _mul(tangents[index], 0.30 * chord)),
                end,
            )
        )
    centerline = _sample_segments(segments, 26)
    geometry_digest = canonical_digest(segments)
    return {
        "curve_id": curve_id,
        "role": role,
        "semantic_role": role,
        "level": "L1",
        "hierarchy_level": 1,
        "parent": "backbone",
        "parent_curve_id": None,
        "service_flower_id": service_flower_id,
        "root_s": round(root_s % 1.0, 9),
        "root": _R6_round_point(centerline[0]),
        "target": _R6_round_point(centerline[-1]),
        "segments": segments,
        "centerline": [
            _R6_round_point(point) for point in centerline
        ],
        "geometry_digest": geometry_digest,
    }


def _R6_support_curve(
    analysis: Mapping[str, Any],
    flower: Mapping[str, Any],
    seed_phase: float,
    variant_phase: float,
) -> dict[str, Any]:
    backbone = analysis["backbone"]["samples"]
    nearest_s = float(flower["nearest_backbone_s"])
    center = _point(flower["center"], "R6 SW1 flower center")
    target = (center[0], center[1] + float(flower["ry"]))
    root_s = nearest_s - 0.035 - 0.010 * variant_phase
    root, tangent = _R6_backbone_at_s(backbone, root_s)
    troughs = [
        row
        for row in analysis["backbone"]["extrema"]
        if row["kind"] == "trough"
    ]
    if troughs:
        trough_s = float(troughs[0]["s"])
        trough_root, trough_tangent = _R6_backbone_at_s(
            backbone,
            trough_s,
        )
        if _distance(trough_root, target) < _distance(root, target):
            root_s = trough_s
            root = trough_root
            tangent = trough_tangent
            tangent = _unit(
                _sub(target, root),
                "R6 trough support departure",
            )
    chord = _distance(root, target)
    tangent = _R6_oriented_tangent(tangent, _sub(target, root))
    side = 1.0 if root[0] >= center[0] else -1.0
    anchors = [
        root,
        _add(
            root,
            _mul(tangent, max(0.025, 0.18 * chord)),
        ),
        (
            center[0] + side * (0.42 + 0.04 * seed_phase)
            * float(flower["rx"]),
            center[1] + 0.70 * float(flower["ry"]),
        ),
        target,
    ]
    return _R6_curve_from_anchors(
        curve_id=(
            f"{analysis['prototype_id']}__{flower['flower_id']}"
            "__support"
        ),
        role="flower_support",
        anchors=anchors,
        root_s=root_s,
        service_flower_id=str(flower["flower_id"]),
    )


def _R6_wrap_curve(
    analysis: Mapping[str, Any],
    flower: Mapping[str, Any],
    seed_phase: float,
    variant_phase: float,
) -> dict[str, Any]:
    troughs = [
        row
        for row in analysis["backbone"]["extrema"]
        if row["kind"] == "trough"
    ]
    if not troughs:
        raise Stage5SelectionError("R6 SW1 wrap needs a detected trough")
    nearest_s = float(flower["nearest_backbone_s"])
    support_probe_s = nearest_s - 0.035 - 0.010 * variant_phase
    support_probe, _ = _R6_backbone_at_s(
        analysis["backbone"]["samples"],
        support_probe_s,
    )
    center = _point(flower["center"], "R6 SW1 wrap center")
    target_bottom = (
        center[0],
        center[1] + float(flower["ry"]),
    )
    trough = max(
        troughs,
        key=lambda row: min(
            abs(float(row["s"]) - nearest_s),
            1.0 - abs(float(row["s"]) - nearest_s),
        ),
    )
    trough_root, _ = _R6_backbone_at_s(
        analysis["backbone"]["samples"],
        float(trough["s"]),
    )
    support_uses_trough = (
        _distance(trough_root, target_bottom)
        < _distance(support_probe, target_bottom)
    )
    source = trough
    if support_uses_trough:
        peaks = [
            row
            for row in analysis["backbone"]["extrema"]
            if row["kind"] == "peak"
        ]
        if peaks:
            source = peaks[0]
    root_s = float(source["s"])
    root, tangent = _R6_backbone_at_s(
        analysis["backbone"]["samples"],
        root_s,
    )
    rx = float(flower["protection_rx"])
    ry = float(flower["protection_ry"])
    side = 1.0 if root[0] >= center[0] else -1.0
    if abs(root[0] - center[0]) < 0.10:
        side = 1.0 if variant_phase >= 0.0 else -1.0
    margin = 0.035 + 0.008 * abs(seed_phase)
    if support_uses_trough:
        upper_side = (
            center[0] + side * (rx + margin),
            center[1] - ry - 0.035,
        )
        upper_mid = (
            center[0] + side * 0.08 * rx,
            center[1] - ry - 0.045,
        )
        opposite_upper = (
            center[0] - side * (rx + margin),
            center[1] - 0.42 * ry,
        )
        exit_point = (
            center[0] - side * (rx + 0.025),
            center[1] + (0.12 + 0.04 * variant_phase) * ry,
        )
        departure = (
            root[0] - side * 0.09,
            root[1] - 0.075,
        )
        anchors = [
            root,
            departure,
            upper_side,
            upper_mid,
            opposite_upper,
            exit_point,
        ]
    else:
        lower_side = (
            center[0] + side * (rx + margin),
            center[1] + ry + 0.035,
        )
        lower_mid = (
            center[0] + side * 0.08 * rx,
            center[1] + ry + 0.045,
        )
        opposite_lower = (
            center[0] - side * (rx + margin),
            center[1] + 0.42 * ry,
        )
        exit_point = (
            center[0] - side * (rx + 0.025),
            center[1] - (0.12 + 0.04 * variant_phase) * ry,
        )
        tangent = _R6_oriented_tangent(
            tangent,
            _sub(lower_side, root),
        )
        chord = _distance(root, lower_side)
        anchors = [
            root,
            _add(
                root,
                _mul(tangent, max(0.035, 0.18 * chord)),
            ),
            lower_side,
            lower_mid,
            opposite_lower,
            exit_point,
        ]
    return _R6_curve_from_anchors(
        curve_id=(
            f"{analysis['prototype_id']}__{flower['flower_id']}"
            "__wrap"
        ),
        role="flower_wrap",
        anchors=anchors,
        root_s=root_s,
        service_flower_id=str(flower["flower_id"]),
    )


def _R6_balance_curve(
    analysis: Mapping[str, Any],
    service_flower: Mapping[str, Any],
    seed_phase: float,
    variant_phase: float,
) -> dict[str, Any]:
    peaks = [
        row
        for row in analysis["backbone"]["extrema"]
        if row["kind"] == "peak"
    ]
    source = (
        peaks[0]
        if peaks
        else min(
            analysis["backbone"]["samples"],
            key=lambda row: float(row["point"][1]),
        )
    )
    root_s = float(source["s"])
    root, tangent = _R6_backbone_at_s(
        analysis["backbone"]["samples"],
        root_s,
    )
    flower_center = _point(
        service_flower["center"],
        "R6 balance flower center",
    )
    direction = -1.0 if root[0] >= flower_center[0] else 1.0
    target = (
        root[0] + direction * (0.20 + 0.025 * variant_phase),
        max(
            0.09,
            root[1] - 0.12 - 0.018 * seed_phase,
        ),
    )
    tangent = _R6_oriented_tangent(tangent, _sub(target, root))
    chord = _distance(root, target)
    normal = (-tangent[1], tangent[0])
    if normal[1] > 0:
        normal = (-normal[0], -normal[1])
    anchors = [
        root,
        _add(root, _mul(tangent, 0.20 * chord)),
        _add(
            _add(root, _mul(_sub(target, root), 0.58)),
            _mul(normal, 0.12 * chord),
        ),
        target,
    ]
    return _R6_curve_from_anchors(
        curve_id=f"{analysis['prototype_id']}__balance",
        role="balance",
        anchors=anchors,
        root_s=root_s,
        service_flower_id=str(service_flower["flower_id"]),
    )


def _R6_remote_support_curve(
    analysis: Mapping[str, Any],
    flower: Mapping[str, Any],
    seed_phase: float,
    variant_phase: float,
) -> dict[str, Any]:
    center = _point(flower["center"], "R6 SW3 flower center")
    nearest_s = float(flower["nearest_backbone_s"])
    direction = -1.0 if center[0] < 0.5 else 1.0
    single_flower = len(analysis["flowers"]) == 1
    root_s = nearest_s + direction * (
        (0.39 if single_flower else 0.32)
        + 0.012 * variant_phase
    )
    root, tangent = _R6_backbone_at_s(
        analysis["backbone"]["samples"],
        root_s,
    )
    target = (center[0], center[1] + float(flower["ry"]))
    tangent = _R6_oriented_tangent(tangent, _sub(target, root))
    chord = _distance(root, target)
    approach_side = -1.0 if root[0] < target[0] else 1.0
    if single_flower and target[1] >= root[1]:
        protection_rx = float(flower["protection_rx"])
        lower_left = (
            center[0] - 0.72 * protection_rx,
            target[1] + 0.045,
        )
        lower_mid = (
            center[0] - 0.34 * protection_rx,
            target[1] + 0.032,
        )
        anchors = [
            root,
            (root[0] + 0.060, root[1] + 0.008),
            lower_left,
            lower_mid,
            (
                center[0] - 0.12 * protection_rx,
                target[1] + 0.014,
            ),
            target,
        ]
    else:
        if target[1] < root[1]:
            tangent = _unit(
                _sub(target, root),
                "R6 upward remote departure",
            )
        vertical_sign = 1.0 if target[1] >= root[1] else -1.0
        anchors = [
            root,
            _add(root, _mul(tangent, max(0.035, 0.18 * chord))),
            (
                0.55 * root[0] + 0.45 * target[0],
                0.55 * root[1]
                + 0.45 * target[1]
                + vertical_sign * 0.045,
            ),
            (
                target[0] + approach_side * 0.14 * float(flower["rx"]),
                target[1] + 0.025,
            ),
            target,
        ]
    return _R6_curve_from_anchors(
        curve_id=(
            f"{analysis['prototype_id']}__{flower['flower_id']}"
            "__remote_support"
        ),
        role="remote_flower_support",
        anchors=anchors,
        root_s=root_s,
        service_flower_id=str(flower["flower_id"]),
    )


def _R6_axis_echoes(
    analysis: Mapping[str, Any],
    seed_phase: float,
    variant_phase: float,
) -> list[dict[str, Any]]:
    troughs = [
        row
        for row in analysis["backbone"]["extrema"]
        if row["kind"] == "trough"
    ]
    curves: list[dict[str, Any]] = []
    for index, feature in enumerate(troughs[:2], start=1):
        root_s = float(feature["s"])
        root, tangent = _R6_backbone_at_s(
            analysis["backbone"]["samples"],
            root_s,
        )
        direction = -1.0 if root[0] < 0.5 else 1.0
        target = (
            root[0] + direction * (
                0.18 + 0.015 * variant_phase
            ),
            root[1] + 0.16 + 0.010 * seed_phase,
        )
        tangent = _R6_oriented_tangent(tangent, _sub(target, root))
        chord = _distance(root, target)
        anchors = [
            root,
            _add(root, _mul(tangent, 0.20 * chord)),
            (
                0.52 * root[0] + 0.48 * target[0],
                0.52 * root[1] + 0.48 * target[1] - 0.04,
            ),
            target,
        ]
        curves.append(
            _R6_curve_from_anchors(
                curve_id=(
                    f"{analysis['prototype_id']}__axis_echo_{index}"
                ),
                role="axis_flow",
                anchors=anchors,
                root_s=root_s,
                service_flower_id=None,
            )
        )
    return curves


def _R6_settle_curve(
    analysis: Mapping[str, Any],
    seed_phase: float,
    variant_phase: float,
) -> dict[str, Any] | None:
    if analysis["prototype_id"] == "proto_sw_3_2":
        return None
    root_s = 0.70 + 0.015 * variant_phase
    root, tangent = _R6_backbone_at_s(
        analysis["backbone"]["samples"],
        root_s,
    )
    if root[1] < 0.65:
        return None
    if root[0] > 0.90:
        return None
    bounds = [
        float(value)
        for value in analysis["coordinate_system"]["canvas_bounds"]
    ]
    target = (
        bounds[2] - 0.012,
        min(bounds[3] - 0.06, root[1] - 0.02 * seed_phase),
    )
    tangent = _R6_oriented_tangent(tangent, _sub(target, root))
    chord = _distance(root, target)
    normal = (-tangent[1], tangent[0])
    if normal[1] < 0:
        normal = (-normal[0], -normal[1])
    anchors = [
        root,
        _add(root, _mul(tangent, 0.20 * chord)),
        _add(
            _add(root, _mul(_sub(target, root), 0.58)),
            _mul(normal, 0.07 * chord),
        ),
        target,
    ]
    return _R6_curve_from_anchors(
        curve_id=f"{analysis['prototype_id']}__settle",
        role="settle",
        anchors=anchors,
        root_s=root_s,
        service_flower_id=None,
    )


def _R6_generated_layout(
    analysis: Mapping[str, Any],
    family_id: str,
    seed: int,
    variant_index: int,
) -> dict[str, Any]:
    seed_phase = float(seed - 4102)
    variant_phase = float(variant_index - 2)
    curves: list[dict[str, Any]] = []
    flowers = list(analysis["flowers"])
    if family_id == "SW1":
        service = flowers[0]
        curves.extend(
            [
                _R6_support_curve(
                    analysis,
                    service,
                    seed_phase,
                    variant_phase,
                ),
                _R6_wrap_curve(
                    analysis,
                    service,
                    seed_phase,
                    variant_phase,
                ),
                _R6_balance_curve(
                    analysis,
                    service,
                    seed_phase,
                    variant_phase,
                ),
            ]
        )
    elif family_id == "SW3":
        for flower in flowers:
            curves.append(
                _R6_remote_support_curve(
                    analysis,
                    flower,
                    seed_phase,
                    variant_phase,
                )
            )
        curves.append(
            _R6_balance_curve(
                analysis,
                flowers[0],
                seed_phase,
                variant_phase,
            )
        )
    elif family_id == "SW2":
        curves.extend(
            _R6_axis_echoes(
                analysis,
                seed_phase,
                variant_phase,
            )
        )
    else:
        raise Stage5SelectionError(f"unknown R6 family: {family_id}")
    settle = _R6_settle_curve(
        analysis,
        seed_phase,
        variant_phase,
    )
    if settle is not None:
        curves.append(settle)
    return {
        "candidate_id": (
            f"{analysis['prototype_id']}__seed_{seed}"
            f"__layout_variant_{variant_index}"
        ),
        "prototype_id": str(analysis["prototype_id"]),
        "family_id": family_id,
        "seed": seed,
        "variant_index": variant_index,
        "curves": curves,
        "generation_policy": {
            "first_legal_stop_used": False,
            "failed_candidates_retained": True,
            "seed_specific_fixed_coordinates_used": False,
            "stage5_deletion_used": False,
            "material_reference_policy": (
                "SW1_support_wrap_continuous_handoff"
            ),
        },
    }


def R6_layout_intersections(
    analysis: Mapping[str, Any],
    layout: Mapping[str, Any],
) -> dict[str, int]:
    curves = list(layout["curves"])
    backbone = {
        "curve_id": "backbone",
        "centerline": [
            row["point"] for row in analysis["backbone"]["samples"]
        ],
    }
    self_count = sum(
        int(_curve_crosses(curve, curve, None))
        for curve in curves
    )
    backbone_count = sum(
        int(
            _curve_crosses(
                curve,
                backbone,
                _point(curve["root"], "R6 root"),
            )
        )
        for curve in curves
    )
    pair_count = sum(
        int(_curve_crosses(curves[left], curves[right], None))
        for left in range(len(curves))
        for right in range(left + 1, len(curves))
    )
    periodic_count = 0
    for curve in curves:
        for shift in (-1.0, 1.0):
            shifted_backbone = _shift_curve(backbone, shift)
            periodic_count += int(
                _curve_crosses(curve, shifted_backbone, None)
            )
    for left in range(len(curves)):
        for right in range(len(curves)):
            for shift in (-1.0, 1.0):
                periodic_count += int(
                    _curve_crosses(
                        curves[left],
                        _shift_curve(curves[right], shift),
                        None,
                    )
                )
    return {
        "self_intersection_count": self_count,
        "backbone_intersection_count": backbone_count,
        "branch_pair_intersection_count": pair_count,
        "periodic_intersection_count": periodic_count,
    }


def _R6_score_layout(
    analysis: Mapping[str, Any],
    layout: Mapping[str, Any],
    intersections: Mapping[str, int],
) -> dict[str, Any]:
    curves = list(layout["curves"])
    family_id = str(layout["family_id"])
    roles = [str(curve["role"]) for curve in curves]
    expected = (
        {"flower_support", "flower_wrap", "balance"}
        if family_id == "SW1"
        else {"remote_flower_support", "balance"}
        if family_id == "SW3"
        else {"axis_flow"}
    )
    role_raw = len(expected.intersection(roles)) / max(1, len(expected))
    targets = [
        _point(curve["target"], "R6 score target") for curve in curves
    ]
    roots = [_point(curve["root"], "R6 score root") for curve in curves]
    horizontal_progress = sum(
        abs(target[0] - root[0])
        for root, target in zip(roots, targets)
    ) / max(1, len(curves))
    region_raw = max(0.0, min(1.0, horizontal_progress / 0.30))
    hierarchy_raw = 1.0
    upper = sum(point[1] < 0.58 for point in targets)
    lower = sum(point[1] >= 0.58 for point in targets)
    density_raw = 1.0 - abs(upper - lower) / max(1, len(targets))
    xs = [point[0] for point in targets]
    horizontal_raw = (
        max(0.0, min(1.0, (max(xs) - min(xs)) / 0.65))
        if len(xs) >= 2
        else 0.55
    )
    flower_roles = [
        curve
        for curve in curves
        if curve["role"]
        in {
            "flower_support",
            "flower_wrap",
            "remote_flower_support",
        }
    ]
    flower_raw = min(
        1.0,
        len(flower_roles)
        / max(1, len(analysis["flowers"])),
    )
    settle_curves = [
        curve for curve in curves if curve["role"] == "settle"
    ]
    settle_raw = (
        max(
            0.0,
            min(
                1.0,
                max(float(curve["target"][0]) for curve in settle_curves),
            ),
        )
        if settle_curves
        else 0.45
    )
    if any(intersections.values()):
        role_raw = 0.0
        region_raw = 0.0
        hierarchy_raw = 0.0
        density_raw = 0.0
        horizontal_raw = 0.0
        flower_raw = 0.0
        settle_raw = 0.0
    raw_values = {
        "role_completeness_score": role_raw,
        "region_path_score": region_raw,
        "hierarchy_score": hierarchy_raw,
        "density_balance_score": density_raw,
        "horizontal_rhythm_score": horizontal_raw,
        "flower_group_score": flower_raw,
        "settle_continuity_score": settle_raw,
    }
    components = {}
    total = 0.0
    for name, weight in R6_SCORE_WEIGHTS.items():
        normalized = max(0.0, min(1.0, float(raw_values[name])))
        weighted = normalized * weight
        components[name] = {
            "raw_value": round(float(raw_values[name]), 9),
            "normalized_value": round(normalized, 9),
            "weight": weight,
            "weighted_value": round(weighted, 9),
        }
        total += weighted
    return {
        "components": components,
        "composite_score": round(total, 9),
    }


def generate_and_select_R6_layout(
    analysis: Mapping[str, Any],
    family_id: str,
    seed: int,
) -> dict[str, Any]:
    """Generate every R6 whole-layout variant and select the best legal one."""

    candidates = [
        _R6_generated_layout(
            analysis,
            family_id,
            seed,
            variant_index,
        )
        for variant_index in range(5)
    ]
    for candidate in candidates:
        intersections = R6_layout_intersections(analysis, candidate)
        candidate["intersection_report"] = intersections
        candidate["legal"] = not any(intersections.values())
        candidate["score"] = _R6_score_layout(
            analysis,
            candidate,
            intersections,
        )
    legal = [candidate for candidate in candidates if candidate["legal"]]
    if not legal:
        raise Stage5SelectionError(
            f"{analysis['prototype_id']} seed {seed} has no legal R6 layout"
        )
    selected = max(
        legal,
        key=lambda candidate: (
            float(candidate["score"]["composite_score"]),
            -int(candidate["variant_index"]),
        ),
    )
    selected["selected"] = True
    return {
        "schema": "dynamic_branch_R6_scored_layout_selection_v2",
        "prototype_id": str(analysis["prototype_id"]),
        "family_id": family_id,
        "seed": seed,
        "candidate_count": len(candidates),
        "legal_candidate_count": len(legal),
        "selected_candidate_id": str(selected["candidate_id"]),
        "selected_layout": selected,
        "candidate_inventory": candidates,
        "solver": {
            "mode": "enumerate_all_legal_then_maximize_composite_score",
            "stopped_at_first_complete_legal_assignment": False,
            "composite_visual_score_used": True,
            "failed_candidates_retained": True,
            "stage5_deletion_used": False,
        },
        "selection_digest": canonical_digest(
            {
                "prototype_id": analysis["prototype_id"],
                "seed": seed,
                "selected_candidate_id": selected["candidate_id"],
                "selected_geometry_digests": [
                    curve["geometry_digest"]
                    for curve in selected["curves"]
                ],
                "candidate_scores": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "legal": candidate["legal"],
                        "score": candidate["score"],
                    }
                    for candidate in candidates
                ],
            }
        ),
    }
