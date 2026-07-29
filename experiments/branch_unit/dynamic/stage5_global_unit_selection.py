#!/usr/bin/env python3
"""Build cross-Unit conflicts and select one immutable Unit per approved lane."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Mapping, Sequence

from branch_unit_grammar_v1 import _curve_crosses


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
