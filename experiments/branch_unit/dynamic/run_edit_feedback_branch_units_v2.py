#!/usr/bin/env python3
"""Render old-mainline BranchUnit hierarchy pilots from stage-3B V2 plans."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from branch_unit_grammar_v1 import (
    generate_unit_candidate_inventory,
    validate_unit_candidate_inventory,
)
from flower_mounting_v1 import validate_flower_mount_plan
from render_stage4_unit_atlas import render_contact_sheet, render_lane_context_atlas
from render_stage5_global_selection import render_global_selection
from stage5_global_unit_selection import (
    build_conflict_graph,
    select_global_units,
    validate_global_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
INPUT_REPO_ROOT = Path(
    os.environ.get("CHANZHI_FROZEN_INPUT_ROOT", str(REPO_ROOT))
).resolve()
STAGE3A_PRIOR = (
    INPUT_REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage3a_fixed_visual_prior_v1"
    / "fixed_visual_prior.json"
)
MORPHOLOGY_CONTRACT = DYNAMIC_DIR / "MORPHOLOGY_CONTRACT.json"
STAGE4_CONTRACT = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json"
STAGE5_CONTRACT = DYNAMIC_DIR / "STAGE5_GLOBAL_SELECTION_CONTRACT_V2.json"
EDITOR_L2_PRIOR = DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json"


class EditFeedbackBranchUnitRunError(RuntimeError):
    """The review-only old-mainline hierarchy run is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EditFeedbackBranchUnitRunError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run(stage3b_root: Path, output: Path) -> None:
    if output.exists():
        raise EditFeedbackBranchUnitRunError(f"output already exists: {output}")
    manifest_path = stage3b_root / "manifest.json"
    required = (
        manifest_path,
        STAGE3A_PRIOR,
        MORPHOLOGY_CONTRACT,
        STAGE4_CONTRACT,
        STAGE5_CONTRACT,
        EDITOR_L2_PRIOR,
    )
    for path in required:
        if not path.is_file():
            raise EditFeedbackBranchUnitRunError(f"missing input: {path}")
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != "dynamic_branch_stage3b_l1_flow_manifest_v2":
        raise EditFeedbackBranchUnitRunError("stage-3B V2 manifest is required")

    stage4_contract = _read_json(STAGE4_CONTRACT)
    stage5_contract = _read_json(STAGE5_CONTRACT)
    morphology_contract = _read_json(MORPHOLOGY_CONTRACT)
    editor_l2_prior = _read_json(EDITOR_L2_PRIOR)
    prior = _read_json(STAGE3A_PRIOR)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="edit_feedback_branch_units_v2_",
        dir=str(output.parent),
    ) as directory:
        temporary = Path(directory)
        final_previews: list[Path] = []
        atlas_previews: list[Path] = []
        task_rows: list[dict[str, Any]] = []
        for task in manifest["tasks"]:
            prototype_id = str(task["prototype_id"])
            seed = int(task["seed"])
            plan_path = stage3b_root / str(task["files"]["global_l1_flow_plan.json"]["path"])
            if not plan_path.is_file():
                raise EditFeedbackBranchUnitRunError(
                    f"stage-3B plan is missing: {prototype_id} seed {seed}"
                )
            analysis_entry = task["files"].get("prototype_analysis_variant.json")
            if not isinstance(analysis_entry, dict) or "path" not in analysis_entry:
                raise EditFeedbackBranchUnitRunError(
                    f"task manifest has no variant analysis: {prototype_id} seed {seed}"
                )
            analysis_path = stage3b_root / str(analysis_entry["path"])
            if not analysis_path.is_file():
                raise EditFeedbackBranchUnitRunError(
                    f"variant analysis is missing: {prototype_id} seed {seed}"
                )
            plan = _read_json(plan_path)
            analysis = _read_json(analysis_path)
            flower_mount_plan = plan.get("flower_mount_plan")
            if not isinstance(flower_mount_plan, dict):
                raise EditFeedbackBranchUnitRunError(
                    f"stage-3B plan lacks flower-first geometry: {prototype_id} seed {seed}"
                )
            prototype_strategy = plan.get("prototype_strategy")
            if not isinstance(prototype_strategy, dict):
                raise EditFeedbackBranchUnitRunError(
                    f"stage-3B plan lacks frozen prototype strategy: {prototype_id} seed {seed}"
                )
            validate_flower_mount_plan(
                flower_mount_plan,
                analysis,
                morphology_contract,
                prototype_strategy=prototype_strategy,
            )
            inventory = generate_unit_candidate_inventory(
                plan,
                analysis,
                prior,
                stage4_contract,
                editor_l2_prior,
            )
            validate_unit_candidate_inventory(inventory, stage4_contract)
            conflict_graph = build_conflict_graph(
                inventory,
                stage5_contract,
                editor_l2_prior,
            )
            selection = select_global_units(
                inventory,
                conflict_graph,
                stage5_contract,
            )
            validate_global_selection(selection, conflict_graph)
            if not selection["feasible"]:
                raise EditFeedbackBranchUnitRunError(
                    f"no exact legal hierarchy mix: {prototype_id} seed {seed}"
                )
            case = temporary / prototype_id / f"seed_{seed}"
            case.mkdir(parents=True)
            inventory_path = case / "unit_candidate_inventory.json"
            graph_path = case / "candidate_conflict_graph.json"
            selection_path = case / "global_unit_selection.json"
            flower_mount_path = case / "flower_mount_plan.json"
            atlas_path = case / "unit_candidate_context_atlas.png"
            final_path = case / "global_unit_selection.png"
            triple_path = case / "global_unit_selection_triple_repeat.png"
            _write_json(inventory_path, inventory)
            _write_json(graph_path, conflict_graph)
            _write_json(selection_path, selection)
            _write_json(flower_mount_path, flower_mount_plan)
            render_lane_context_atlas(analysis, plan, inventory, atlas_path)
            render_global_selection(
                analysis,
                inventory,
                conflict_graph,
                selection,
                final_path,
                triple_repeat=False,
                flower_mount_plan=flower_mount_plan,
            )
            render_global_selection(
                analysis,
                inventory,
                conflict_graph,
                selection,
                triple_path,
                triple_repeat=True,
                flower_mount_plan=flower_mount_plan,
            )
            atlas_previews.append(atlas_path)
            final_previews.append(final_path)
            task_rows.append(
                {
                    "prototype_id": prototype_id,
                    "seed": seed,
                    "production_seed": task.get("production_seed"),
                    "backbone_seed": task.get("backbone_seed"),
                    "flower_seed": task.get("flower_seed"),
                    "branch_seed": task.get("branch_seed", seed),
                    "unit_seed": task.get("unit_seed", seed),
                    "flower_layout": task.get("flower_layout"),
                    "prototype_strategy": prototype_strategy,
                    "prototype_analysis_variant_path": str(
                        analysis_path.relative_to(stage3b_root)
                    ).replace("\\", "/"),
                    "lane_count": selection["lane_count"],
                    "candidate_count": inventory["candidate_count"],
                    "feasible_candidate_count": inventory["feasible_candidate_count"],
                    "conflict_edge_count": conflict_graph["edge_count"],
                    "flower_mount_count": len(flower_mount_plan["mounts"]),
                    "flower_morphology_family": flower_mount_plan[
                        "morphology_family"
                    ],
                    "flower_binding": flower_mount_plan["flower_binding"],
                    "flower_mount_mechanical_checks": flower_mount_plan[
                        "mechanical_checks"
                    ],
                    "hierarchy_mix_target_counts": selection["solver_trace"][
                        "hierarchy_mix_target_counts"
                    ],
                    "hierarchy_mix_selected_counts": selection["solver_trace"][
                        "hierarchy_mix_selected_counts"
                    ],
                    "selection_digest": selection["selection_digest"],
                    "files": {
                        path.name: {
                            "path": str(path.relative_to(temporary)).replace("\\", "/"),
                        }
                        for path in (
                            inventory_path,
                            graph_path,
                            selection_path,
                            flower_mount_path,
                            atlas_path,
                            final_path,
                            triple_path,
                        )
                    },
                }
            )

        final_sheet = temporary / "branch_unit_composition_contact_sheet.png"
        atlas_sheet = temporary / "branch_unit_candidate_contact_sheet.png"
        render_contact_sheet(final_previews, final_sheet, columns=3)
        render_contact_sheet(atlas_previews, atlas_sheet, columns=3)
        result_manifest = {
            "schema": "dynamic_branch_edit_feedback_hierarchy_review_manifest_v2",
            "source_stage3b_manifest": str(manifest_path),
            "morphology_contract": str(MORPHOLOGY_CONTRACT),
            "stage4_contract": str(STAGE4_CONTRACT),
            "stage5_contract": str(STAGE5_CONTRACT),
            "editor_l2_placement_prior": str(EDITOR_L2_PRIOR),
            "task_count": len(task_rows),
            "generation_policy": {
                "old_mainline_only": True,
                "role_labels_are_weak_metadata": True,
                "region_planning_used": False,
                "l1_geometry_mutated_after_stage3b": False,
                "exact_edit_feedback_hierarchy_mix_enforced": True,
                "editor_l2_placement_prior_consumed": True,
                "editor_clearance_used_in_global_selection": True,
                "flower_mounting_rebuilt_after_stage5_selection": False,
                "flower_mounting_loaded_from_stage3b_upstream": True,
                "branch_geometry_mutated_by_flower_mounting": False,
                "flower_mounting_rendered_in_formal_outputs": True,
                "family_conditioned_flower_binding": True,
                "frozen_prototype_strategy_consumed_by_stage4_and_stage5": True,
                "sw2_axis_integration_has_no_support_curve": True,
                "sw2_axis_penetration_recomputed_from_geometry": True,
                "best_of_n_visual_ranking_used": False,
            },
            "review_gate": {
                "status": "branch_units_preserved_flower_mounting_pending_visual_review",
                "numeric_checks_cannot_auto_approve_visual_gate": True,
                "formal_stage4_or_stage5_approval_created": False,
            },
            "contact_sheets": {
                "final": final_sheet.name,
                "candidate_atlas": atlas_sheet.name,
            },
            "tasks": task_rows,
        }
        _write_json(temporary / "manifest.json", result_manifest)
        temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage3b-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.stage3b_root.resolve(), args.output.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
