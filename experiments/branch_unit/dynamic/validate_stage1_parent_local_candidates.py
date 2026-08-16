#!/usr/bin/env python3
"""Independently check Stage-1 parent-local starts on the active candidate path."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from typing import Any, Mapping

from backbone_variation_v1 import generate_and_analyze_variant, split_seed
import global_l1_flow as flow
from run_stage3b_l1_flow import _load_inputs
from strict_p0_v2 import load_materialized_strict_p0_v2


def _initial_frame(
    candidate: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> tuple[float, float]:
    points = candidate["centerline"]
    initial = (
        float(points[1][0]) - float(points[0][0]),
        float(points[1][1]) - float(points[0][1]),
    )
    length = math.hypot(*initial)
    if length <= 1e-12:
        raise RuntimeError("candidate has a degenerate initial segment")
    initial = initial[0] / length, initial[1] / length
    _, tangent = flow._sample_at_s(analysis, float(candidate["root_s"]))
    outward = flow._normal(tangent, str(candidate["side_id"]))
    return (
        abs(initial[0] * tangent[0] + initial[1] * tangent[1]),
        initial[0] * outward[0] + initial[1] * outward[1],
    )


def validate(production_seed: int, prototype_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    inputs, prior, feedback_prior, curve_prior, _contract, _provenance = (
        _load_inputs()
    )
    backbone_seed, branch_seed = split_seed(production_seed)
    report: list[dict[str, Any]] = []
    for prototype_id in prototype_ids:
        payload = inputs[prototype_id]
        strict = load_materialized_strict_p0_v2(payload["strict"])
        _, analysis, _variation = generate_and_analyze_variant(
            strict,
            backbone_seed,
        )
        feedback = flow._feedback_profile(feedback_prior, prototype_id)
        curve_profile = flow._curve_geometry_profile(curve_prior, prototype_id)
        latents = flow._global_latents(prototype_id, branch_seed)
        count = flow._derive_lane_count(
            prototype_id,
            analysis,
            payload["morphology"],
            prior,
            branch_seed,
            feedback,
        )
        slots, _root_rhythm = flow._make_slots(
            analysis,
            payload["morphology"],
            count,
            latents,
            branch_seed,
            prior,
            feedback,
        )
        family_id = str(
            payload["morphology"]["classification"]
            ["flower_branch_relation"]["family_id"]
        )
        slot_rows: list[dict[str, Any]] = []
        rejection_counts: Counter[str] = Counter()
        for slot in slots:
            candidates = flow._ordinary_candidates(
                slot,
                analysis,
                prior,
                latents,
                feedback,
                curve_profile,
                int(count["selected_l1_count"]),
            )
            start_pass: list[dict[str, Any]] = []
            tangent_values: list[float] = []
            outward_values: list[float] = []
            for candidate in candidates:
                tangent_alignment, outward_alignment = _initial_frame(
                    candidate,
                    analysis,
                )
                tangent_values.append(tangent_alignment)
                outward_values.append(outward_alignment)
                if (
                    tangent_alignment
                    >= float(feedback["minimum_initial_tangent_alignment"])
                    and outward_alignment
                    >= float(feedback["minimum_initial_outward_alignment"])
                ):
                    start_pass.append(candidate)
            feasible: list[dict[str, Any]] = []
            for candidate in start_pass:
                reasons = flow._candidate_rejections(
                    candidate,
                    analysis,
                    family_id,
                    prior,
                    feedback,
                )
                rejection_counts.update(reasons)
                if not reasons:
                    feasible.append(candidate)
            slot_rows.append(
                {
                    "slot_id": slot.slot_id,
                    "generated": len(candidates),
                    "parent_local_start_pass": len(start_pass),
                    "fully_feasible": len(feasible),
                    "maximum_tangent_alignment": round(max(tangent_values), 9),
                    "maximum_outward_alignment": round(max(outward_values), 9),
                    "feasible_geometry_exemplars": sorted(
                        {
                            int(
                                candidate["features"]
                                ["editor_geometry_exemplar_index"]
                            )
                            for candidate in feasible
                        }
                    ),
                }
            )
        report.append(
            {
                "prototype_id": prototype_id,
                "production_seed": production_seed,
                "branch_seed": branch_seed,
                "selected_l1_count_observed": int(
                    count["selected_l1_count"]
                ),
                "all_slots_parent_local_start_pass": all(
                    row["parent_local_start_pass"] > 0 for row in slot_rows
                ),
                "all_slots_fully_feasible": all(
                    row["fully_feasible"] > 0 for row in slot_rows
                ),
                "full_rejection_counts_after_start_prefilter": dict(
                    rejection_counts
                ),
                "slots": slot_rows,
            }
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-seed", type=int, default=4101)
    parser.add_argument(
        "--prototype",
        action="append",
        choices=flow.PROTOTYPE_IDS,
        dest="prototypes",
    )
    args = parser.parse_args()
    prototypes = tuple(args.prototypes or flow.PROTOTYPE_IDS)
    report = validate(args.production_seed, prototypes)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not all(
        row["all_slots_parent_local_start_pass"]
        and row["all_slots_fully_feasible"]
        for row in report
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
