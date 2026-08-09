#!/usr/bin/env python3
"""Build cross-Unit conflicts and select one immutable Unit per approved lane."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Mapping, Sequence

from branch_unit_grammar_v1 import _curve_crosses


SCHEMA_V1 = "dynamic_branch_stage5_global_unit_selection_v1"
SCHEMA_V2 = "dynamic_branch_stage5_global_unit_selection_v2"
CONFLICT_SCHEMA_V1 = "dynamic_branch_stage5_candidate_conflict_graph_v1"
CONFLICT_SCHEMA_V2 = "dynamic_branch_stage5_candidate_conflict_graph_v2"
CONTRACT_SCHEMA_V1 = "dynamic_branch_stage5_global_selection_contract_v1"
CONTRACT_SCHEMA_V2 = "dynamic_branch_stage5_global_selection_contract_v2"
EDITOR_L2_PRIOR_SCHEMA = "dynamic_branch_editor_l2_placement_prior_v1"
SCHEMA = SCHEMA_V1
CONFLICT_SCHEMA = CONFLICT_SCHEMA_V1
CONTRACT_SCHEMA = CONTRACT_SCHEMA_V1


class Stage5SelectionError(RuntimeError):
    """The immutable candidate pool cannot be processed under the contract."""


def _editor_l2_profile(
    editor_l2_prior: Mapping[str, Any],
    prototype_id: str,
) -> Mapping[str, Any]:
    if editor_l2_prior.get("schema") != EDITOR_L2_PRIOR_SCHEMA:
        raise Stage5SelectionError("editor L2 placement prior schema mismatch")
    profiles = editor_l2_prior.get("profiles")
    if not isinstance(profiles, Mapping):
        raise Stage5SelectionError("editor L2 placement prior has no profiles")
    profile = profiles.get(prototype_id) or profiles.get("global")
    if not isinstance(profile, Mapping):
        raise Stage5SelectionError(
            f"editor L2 placement prior has no profile for {prototype_id}"
        )
    return profile


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


def candidate_pair_minimum_clearance(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    repeat_shifts: Sequence[float],
) -> float:
    """Measure descendant clearance without treating the two immutable L1s."""

    minimum = float("inf")
    for first_curve in first["curves"]:
        for second_curve in second["curves"]:
            if (
                first_curve["level"] == "L1"
                and second_curve["level"] == "L1"
            ):
                continue
            first_points = [
                (float(point[0]), float(point[1]))
                for point in first_curve["centerline"]
            ]
            for shift_x in repeat_shifts:
                second_points = [
                    (float(point[0]) + float(shift_x), float(point[1]))
                    for point in second_curve["centerline"]
                ]
                minimum = min(
                    minimum,
                    min(
                        ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                        for a in first_points
                        for b in second_points
                    ),
                )
    return minimum


def build_conflict_graph(
    inventory: Mapping[str, Any],
    contract: Mapping[str, Any],
    editor_l2_prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    repeat_shifts = [
        float(value)
        for value in contract["hard_constraints"]["repeat_shifts_checked"]
    ]
    contract_schema = str(contract.get("schema"))
    minimum_clearance: float | None = None
    editor_l2_prior_id: str | None = None
    if contract_schema == CONTRACT_SCHEMA_V2:
        if editor_l2_prior is None:
            raise Stage5SelectionError(
                "stage-5 V2 requires the editor L2 placement prior"
            )
        profile = _editor_l2_profile(
            editor_l2_prior,
            str(inventory["prototype_id"]),
        )
        minimum_clearance = float(
            profile["nonparent_curve_clearance_unit_ratio"]["q10"]
        )
        editor_l2_prior_id = str(editor_l2_prior["prior_id"])
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
            pair_clearance = candidate_pair_minimum_clearance(
                first,
                second,
                repeat_shifts,
            )
            crowded = (
                minimum_clearance is not None
                and pair_clearance < minimum_clearance
            )
            if crossings or crowded:
                edge = {
                    "first_candidate_id": first["candidate_id"],
                    "first_lane_id": first["source_lane_id"],
                    "second_candidate_id": second["candidate_id"],
                    "second_lane_id": second["source_lane_id"],
                    "reason": (
                        "crossing_and_editor_clearance_violation"
                        if crossings and crowded
                        else "cross_unit_curve_crossing"
                        if crossings
                        else "editor_l2_clearance_violation"
                    ),
                    "crossings": crossings,
                }
                if contract_schema == CONTRACT_SCHEMA_V2:
                    edge.update(
                        {
                            "minimum_descendant_clearance": round(
                                pair_clearance, 9
                            ),
                            "required_descendant_clearance": round(
                                float(minimum_clearance), 9
                            ),
                        }
                    )
                edges.append(edge)
    graph_schema = (
        CONFLICT_SCHEMA_V2
        if contract_schema == CONTRACT_SCHEMA_V2
        else CONFLICT_SCHEMA_V1
    )
    graph: dict[str, Any] = {
        "schema": graph_schema,
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
    if contract_schema == CONTRACT_SCHEMA_V2:
        graph.update(
            {
                "editor_l2_placement_prior_id": editor_l2_prior_id,
                "minimum_descendant_clearance": round(
                    float(minimum_clearance), 9
                ),
            }
        )
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


def _derive_hierarchy_mix_counts(
    lane_count: int,
    fractions: Mapping[str, Any],
) -> dict[str, int]:
    """Convert edit-derived fractions to exact per-composition counts."""

    class_order = ("l1_only", "single_child", "paired_child")
    if set(fractions) != set(class_order):
        raise Stage5SelectionError("hierarchy mix classes are incomplete")
    total = sum(float(fractions[name]) for name in class_order)
    if total <= 0.0:
        raise Stage5SelectionError("hierarchy mix fractions must be positive")
    raw = {
        name: lane_count * float(fractions[name]) / total
        for name in class_order
    }
    counts = {name: int(raw[name]) for name in class_order}
    remainder = lane_count - sum(counts.values())
    ranked = sorted(
        class_order,
        key=lambda name: (-(raw[name] - counts[name]), class_order.index(name)),
    )
    for name in ranked[:remainder]:
        counts[name] += 1
    return counts


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

    contract_schema = str(contract.get("schema"))
    is_v2 = contract_schema == CONTRACT_SCHEMA_V2
    if contract_schema not in {CONTRACT_SCHEMA_V1, CONTRACT_SCHEMA_V2}:
        raise Stage5SelectionError("stage-5 contract schema mismatch")

    hierarchy_targets: dict[str, int] | None = None
    if is_v2:
        hierarchy_targets = _derive_hierarchy_mix_counts(
            len(lane_ids),
            contract["hierarchy_mix"]["class_fraction_targets"],
        )
        class_cycle = list(contract["deterministic_order"]["class_cycle"])
        stratum_priorities = contract["deterministic_order"][
            "within_class_stratum_priority"
        ]

        def v2_candidate_order(
            candidate: Mapping[str, Any],
            lane_index: int,
        ) -> tuple[int, int, int, str]:
            density_class = str(
                candidate["visual_features"]["hierarchy_density_class"]
            )
            desired_class_order = (
                class_cycle[lane_index % len(class_cycle) :]
                + class_cycle[: lane_index % len(class_cycle)]
            )
            strata = list(stratum_priorities[density_class])
            # Repeated visits to the same hierarchy class rotate through its
            # strata instead of cloning one child grammar across the unit.
            offset = (lane_index // len(class_cycle)) % len(strata)
            rotated_strata = strata[offset:] + strata[:offset]
            return (
                desired_class_order.index(density_class),
                rotated_strata.index(str(candidate["parameter_stratum"])),
                len(conflict_ids[str(candidate["candidate_id"])]),
                str(candidate["candidate_id"]),
            )

        for lane_index, lane_id in enumerate(lane_order):
            eligible_by_lane[lane_id].sort(
                key=lambda candidate, index=lane_index: v2_candidate_order(
                    candidate,
                    index,
                )
            )
    else:
        priorities = contract["deterministic_order"]["role_stratum_priority"]

        def v1_candidate_order(
            candidate: Mapping[str, Any],
        ) -> tuple[int, int, str]:
            role_priority = priorities[str(candidate["role"])]
            return (
                role_priority.index(str(candidate["parameter_stratum"])),
                len(conflict_ids[str(candidate["candidate_id"])]),
                str(candidate["candidate_id"]),
            )

        for lane_id in lane_order:
            eligible_by_lane[lane_id].sort(key=v1_candidate_order)

    selected: list[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    selected_hierarchy_counts: dict[str, int] = defaultdict(int)
    search_node_count = 0
    backtrack_count = 0

    def search(lane_index: int) -> bool:
        nonlocal search_node_count, backtrack_count
        if lane_index == len(lane_order):
            return (
                not is_v2
                or dict(selected_hierarchy_counts) == hierarchy_targets
            )
        if is_v2 and hierarchy_targets is not None:
            remaining_lanes = lane_order[lane_index:]
            for density_class, target in hierarchy_targets.items():
                deficit = target - selected_hierarchy_counts[density_class]
                if deficit < 0:
                    return False
                available_lane_count = sum(
                    any(
                        str(
                            candidate["visual_features"][
                                "hierarchy_density_class"
                            ]
                        )
                        == density_class
                        for candidate in eligible_by_lane[remaining_lane]
                    )
                    for remaining_lane in remaining_lanes
                )
                if deficit > available_lane_count:
                    return False
        lane_id = lane_order[lane_index]
        for candidate in eligible_by_lane[lane_id]:
            search_node_count += 1
            candidate_id = str(candidate["candidate_id"])
            if selected_ids & conflict_ids[candidate_id]:
                continue
            density_class = None
            if is_v2 and hierarchy_targets is not None:
                density_class = str(
                    candidate["visual_features"]["hierarchy_density_class"]
                )
                if (
                    selected_hierarchy_counts[density_class]
                    >= hierarchy_targets[density_class]
                ):
                    continue
            selected.append(candidate)
            selected_ids.add(candidate_id)
            if density_class is not None:
                selected_hierarchy_counts[density_class] += 1
            if search(lane_index + 1):
                return True
            selected.pop()
            selected_ids.remove(candidate_id)
            if density_class is not None:
                selected_hierarchy_counts[density_class] -= 1
            backtrack_count += 1
        return False

    feasible = search(0)
    selected_candidates = list(selected) if feasible else []
    result: dict[str, Any] = {
        "schema": SCHEMA_V2 if is_v2 else SCHEMA_V1,
        "contract_id": contract["contract_id"],
        "selection_id": (
            f"{inventory['inventory_id']}__global_unit_selection_"
            f"{'v2' if is_v2 else 'v1'}"
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
    if is_v2:
        result["solver_trace"].update(
            {
                "edit_feedback_structural_mix_enforced": True,
                "hierarchy_mix_target_counts": hierarchy_targets,
                "hierarchy_mix_selected_counts": dict(
                    selected_hierarchy_counts
                ),
            }
        )
    result["selection_digest"] = canonical_digest(result)
    validate_global_selection(result, conflict_graph)
    return result


def validate_global_selection(
    selection: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
) -> None:
    if selection.get("schema") not in {SCHEMA_V1, SCHEMA_V2}:
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
        if selection.get("schema") == SCHEMA_V2:
            target_counts = selection.get("solver_trace", {}).get(
                "hierarchy_mix_target_counts"
            )
            actual_counts: dict[str, int] = defaultdict(int)
            for candidate in selected:
                actual_counts[
                    str(
                        candidate["visual_features"][
                            "hierarchy_density_class"
                        ]
                    )
                ] += 1
            if dict(actual_counts) != target_counts:
                raise Stage5SelectionError(
                    "V2 composition does not match its frozen hierarchy mix"
                )
    elif selected:
        raise Stage5SelectionError(
            "infeasible result must not publish a partial selection"
        )
