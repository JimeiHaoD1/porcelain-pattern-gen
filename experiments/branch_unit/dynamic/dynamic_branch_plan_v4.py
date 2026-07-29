#!/usr/bin/env python3
"""Revise stage-3 macro plans for long, trough-rooted dynamic BranchUnits.

The approved v3 direction diagrams remain preserved as evidence.  This module
rebuilds the candidate set from the same approved analysis and morphology, but
corrects the macro growth abstraction before curve compilation:

* SW-1 flower support originates in the detected trough band;
* dense and sparse SW-1 instances receive enough complete units;
* ordinary SW-1 sweeps use long-space reach rather than short normal probes;
* child-count envelopes favour distributed two-child units instead of claws.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import dynamic_branch_plan as base


SCHEMA = "dynamic_branch_plan_v4"
POLICY_ID = "branchunit_long_sweep_trough_support_layout_v4"


def _safe_ray_length(
    analysis: Mapping[str, Any],
    root: base.Point,
    direction: base.Point,
    desired: float,
    *,
    radius: float,
) -> float:
    """Return the longest forward-planned ray length inside bounds/reserves."""

    height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    lower = 0.0
    upper = max(0.0, desired)
    for index in range(1, 81):
        length = desired * index / 80.0
        point = base._add(root, base._mul(direction, length))
        if (
            point[0] < -0.24
            or point[0] > 1.24
            or point[1] < 0.035
            or point[1] > height - 0.035
            or any(
                base._segment_enters_flower(
                    root,
                    point,
                    flower,
                    radius=radius,
                )
                for flower in analysis["flowers"]
            )
        ):
            upper = length
            break
        lower = length
    del upper
    return lower


def _segment_has_flower_corridor(
    start: base.Point,
    end: base.Point,
    flower: Mapping[str, Any],
    *,
    radius: float,
) -> bool:
    center = tuple(float(value) for value in flower["center"])
    rx = float(flower["protection_rx"]) + radius
    ry = float(flower["protection_ry"]) + radius
    for index in range(1, 33):
        fraction = index / 32.0
        point = (
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        )
        dx = point[0] - center[0]
        dx -= round(dx)
        dy = point[1] - center[1]
        if (dx / rx) ** 2 + (dy / ry) ** 2 < 1.0:
            return False
    return True


def _sw1_child_rhythm(
    morphology: Mapping[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    density = str(morphology["instance_priors"]["density_class"])
    if role == "flower_support":
        minimum, maximum = (2, 2) if density == "dense" else (1, 2)
        sequence = ["long", "medium"]
    elif density == "dense":
        minimum, maximum = 2, 3
        sequence = ["long", "medium", "short"]
    else:
        minimum, maximum = 1, 2
        sequence = ["long", "medium"]
    return {
        "minimum_child_count": minimum,
        "maximum_child_count": maximum,
        "rhythm_policy": str(morphology["instance_priors"]["side_rhythm"]),
        "length_sequence": sequence,
        "child_geometry_deferred_to_stage_4": True,
    }


def _sw1_trough_support_candidates(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    seed: int,
    layout_policy: Mapping[str, Any],
) -> list[list[dict[str, Any]]]:
    troughs = [
        feature
        for feature in analysis["backbone"]["extrema"]
        if feature["kind"] == "trough"
    ]
    if not troughs:
        raise base.PlanningFailure(
            "sw1_trough_missing",
            "SW-1 support planning requires a detected backbone trough",
            {"prototype_id": analysis["prototype_id"]},
        )
    trough = max(troughs, key=lambda feature: float(feature["prominence"]))
    trough_s = float(trough["s"])
    minimum_spacing = float(layout_policy["minimum_periodic_root_spacing"])
    flowers = list(analysis["flowers"])
    if len(flowers) == 1:
        nominal_offsets = [0.0]
    else:
        half_gap = max(0.042, minimum_spacing * 0.56)
        nominal_offsets = [
            -half_gap
            + 2.0 * half_gap * index / (len(flowers) - 1)
            for index in range(len(flowers))
        ]
    groups: list[list[dict[str, Any]]] = []
    for flower_index, (flower, nominal_offset) in enumerate(
        zip(flowers, nominal_offsets),
        start=1,
    ):
        flower_id = str(flower["flower_id"])
        flower_center = tuple(float(value) for value in flower["center"])
        candidates: list[dict[str, Any]] = []
        for variant, jitter in enumerate((-0.008, 0.0, 0.008), start=1):
            root_s = (trough_s + nominal_offset + jitter) % 1.0
            sample = base._sample_at_s(analysis, root_s)
            root = base._periodic_point_near(sample["point"], flower_center)
            tangent = tuple(float(value) for value in sample["tangent"])
            target = base._ellipse_boundary_toward(flower, root)
            direction = base._unit(base._sub(target, root))
            normal = base._normal(tangent)
            side_id = (
                "left_normal"
                if base._dot(normal, direction) >= 0.0
                else "right_normal"
            )
            invalid_other_flower = any(
                other["flower_id"] != flower_id
                and base._segment_enters_flower(
                    root,
                    target,
                    other,
                    radius=0.028,
                )
                for other in flowers
            )
            if invalid_other_flower:
                continue
            length_hint = base._distance(root, target)
            candidate_id = (
                f"trough_support_{flower_id}_{flower_index}_{variant}"
            )
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "required_group": f"flower_relation:{flower_id}",
                    "role": "flower_support",
                    "semantic_function": (
                        "support_and_wrap"
                        if "wrap"
                        in str(
                            morphology["instance_priors"][
                                "flower_relation_emphasis"
                            ]
                        )
                        else "support"
                    ),
                    "root_s": root_s,
                    "root": root,
                    "side_id": side_id,
                    "vertical_side": "lower",
                    "parent_tangent": tangent,
                    "sweep_direction": direction,
                    "end_hint": target,
                    "direction_path_points": (root, target),
                    "outward_normal_alignment": abs(
                        base._dot(normal, direction)
                    ),
                    "parent_clearance_after_initial_departure": (
                        base._direction_path_parent_clearance(
                            analysis,
                            (root, target),
                            start_fraction=0.30,
                        )
                    ),
                    "length_hint": length_hint,
                    "length_class": "long_trough_flower_reach",
                    "occupancy_radius": 0.050,
                    "root_interval_ref": {
                        "kind": "sw1_trough_support_band",
                        "feature_id": trough["feature_id"],
                        "trough_s": base._round(trough_s),
                        "nominal_offset": base._round(nominal_offset),
                        "flower_id": flower_id,
                    },
                    "flower_relation_intents": [
                        {
                            "flower_id": flower_id,
                            "relation": "support_and_wrap",
                            "approach": "long_trough_sweep_to_flower_collar",
                            "flower_core_entry_allowed": False,
                            "origin_policy": "wave_trough_support",
                            "root_to_flower_boundary_reach": base._round(
                                length_hint
                            ),
                            "contact_point": base._round_point(target),
                        }
                    ],
                    "reserve_zone_refs": [
                        f"flower_reserve:{flower_id}"
                    ],
                    "terminal_kind": "flower_support_transition",
                    "sweep_kind": "trough_rooted_flower_support",
                    "child_rhythm": _sw1_child_rhythm(
                        morphology,
                        role="flower_support",
                    ),
                    "base_score": 2.4
                    - abs(jitter) * 8.0
                    + length_hint * 0.5,
                    "seed_preference": base._stable_random(
                        seed,
                        analysis["prototype_id"],
                        candidate_id,
                    ).uniform(-0.05, 0.05),
                    "source_interval_capacity": "trough_support_required",
                }
            )
        if not candidates:
            raise base.PlanningFailure(
                "sw1_trough_support_unavailable",
                "no trough-rooted support corridor is available",
                {
                    "prototype_id": analysis["prototype_id"],
                    "flower_id": flower_id,
                },
            )
        groups.append(candidates)
    return groups


def _long_sw1_optional_candidates(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    seed: int,
) -> list[dict[str, Any]]:
    density = str(morphology["instance_priors"]["density_class"])
    base_length = 0.46 if density == "dense" else 0.50
    revised: list[dict[str, Any]] = []
    for candidate in candidates:
        row = dict(candidate)
        root = tuple(float(value) for value in row["root"])
        macro_direction = tuple(
            float(value) for value in row["sweep_direction"]
        )
        tangent = tuple(
            float(value) for value in row["parent_tangent"]
        )
        if base._dot(tangent, macro_direction) < 0.0:
            tangent = base._mul(tangent, -1.0)
        direction = base._unit(
            base._add(
                base._mul(macro_direction, 0.72),
                base._mul(tangent, 0.58),
            )
        )
        desired = base_length * base._stable_random(
            seed,
            analysis["prototype_id"],
            row["candidate_id"],
            "long_sweep",
        ).uniform(0.90, 1.10)
        safe = _safe_ray_length(
            analysis,
            root,
            direction,
            desired,
            radius=float(row["occupancy_radius"]),
        )
        existing = float(row["length_hint"])
        if safe < max(0.115, existing * 0.72):
            revised.append(row)
            continue
        length_hint = max(existing, safe)
        end_hint = base._add(root, base._mul(direction, length_hint))
        corridor_radius = max(
            0.046,
            float(row["occupancy_radius"]),
        )
        if any(
            not _segment_has_flower_corridor(
                root,
                end_hint,
                flower,
                radius=corridor_radius,
            )
            for flower in analysis["flowers"]
        ):
            continue
        row.update(
            {
                "sweep_direction": direction,
                "end_hint": end_hint,
                "direction_path_points": (root, end_hint),
                "length_hint": length_hint,
                "length_class": (
                    "long_dense_sweep"
                    if density == "dense"
                    else "long_sparse_sweep"
                ),
                "occupancy_radius": 0.050,
                "child_rhythm": _sw1_child_rhythm(
                    morphology,
                    role="primary_sweep",
                ),
                "base_score": float(row["base_score"])
                + length_hint * 0.65,
                "shared_flow_reweighting": {
                    "macro_direction_weight": 0.72,
                    "oriented_parent_tangent_weight": 0.58,
                    "purpose": (
                        "depart_from_backbone_then_join_family_flow"
                    ),
                },
            }
        )
        revised.append(row)
    return revised


def _optional_count(
    family_id: str,
    density_class: str,
    default: int,
) -> int:
    if family_id != "SW-1_valley_filling":
        return default
    if density_class == "sparse":
        return 3
    return default


def generate_dynamic_branch_plan_v4(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    plan_contract: Mapping[str, Any],
    *,
    seed: int,
    raw_candidate_index: int = 1,
) -> dict[str, Any]:
    """Generate one revised macro plan without compiling branch curves."""

    prototype_id, family_id = base._validate_inputs(
        analysis,
        morphology,
        plan_contract,
        seed,
    )
    if raw_candidate_index != 1:
        raise base.PlanningFailure(
            "raw_candidate_index_violation",
            "stage 3 v4 permits exactly one raw candidate per task",
            {
                "prototype_id": prototype_id,
                "seed": seed,
                "raw_candidate_index": raw_candidate_index,
            },
        )
    density_class, default_optional_count, _ = base._density_style(
        morphology
    )
    optional_count = _optional_count(
        family_id,
        density_class,
        default_optional_count,
    )
    layout_policy = base._layout_policy(morphology, plan_contract)
    role_density_field = base._role_density_field(
        analysis,
        morphology,
        family_id,
    )
    if family_id == "SW-1_valley_filling":
        required_groups = _sw1_trough_support_candidates(
            analysis,
            morphology,
            seed,
            layout_policy,
        )
    else:
        required_groups = base._support_candidates(
            analysis,
            morphology,
            family_id,
            seed,
            plan_contract,
        )
    optional_candidates = base._optional_candidates(
        analysis,
        morphology,
        family_id,
        seed,
        plan_contract,
        root_sample_count_override=(
            5 if family_id == "SW-1_valley_filling" else None
        ),
    )
    if family_id == "SW-1_valley_filling":
        optional_candidates = _long_sw1_optional_candidates(
            analysis,
            morphology,
            [
            {
                **candidate,
                "child_rhythm": _sw1_child_rhythm(
                    morphology,
                    role="primary_sweep",
                ),
            }
            for candidate in optional_candidates
            ],
            seed,
        )
    selected, selection = base._global_select(
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
        base._serialize_branch_unit(
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
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "policy_id": POLICY_ID,
        "supersedes_policy_id": base.POLICY_ID,
        "plan_contract_id": plan_contract["contract_id"],
        "plan_id": f"{prototype_id}__seed_{seed}__raw_1__plan_v4",
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
        "family_invariants": (
            [
                "flower_support_present_per_flower",
                "flower_support_originates_in_detected_trough_band",
                "long_primary_sweeps_organize_valley_space",
                "flower_breathing_ring_preserved",
            ]
            if family_id == "SW-1_valley_filling"
            else plan_contract["family_invariants"][family_id]
        ),
        "role_density_field": role_density_field,
        "initial_layout_policy": {
            **layout_policy,
            "constraints_applied_before_curve_compilation": True,
            "sw1_trough_support_is_family_hard_constraint": (
                family_id == "SW-1_valley_filling"
            ),
            "long_sweep_reach_is_macro_layout_not_curve_shape": True,
        },
        "branch_units": branch_units,
        "global_selection": {
            **selection,
            "target_optional_unit_count": optional_count,
        },
        "planning_contract": {
            "complete_branchunit_is_primary_primitive": True,
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
            "visual_gate_required": True,
            "stage_4_unlocked": False,
            "criteria": [
                "sw1_flower_support_roots_are_in_the_detected_trough_band",
                "sw1_1_uses_long_dense_sweeps",
                "sw1_3_has_few_long_sweeps_but_not_missing_substructure",
                "macro_intents_do_not_cross",
            ],
        },
    }
    core["plan_digest"] = base._canonical_digest(core)
    return core
