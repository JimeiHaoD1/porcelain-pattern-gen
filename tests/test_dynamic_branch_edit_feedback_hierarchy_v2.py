from __future__ import annotations

import copy
import json
import sys
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import branch_unit_grammar_v1 as grammar  # noqa: E402
import global_l1_flow as planner  # noqa: E402
import stage5_global_unit_selection as stage5  # noqa: E402


STAGE1 = ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
STAGE2 = ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE25 = ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
STAGE3A = ROOT / "artifacts" / "runs" / "dynamic_branch_stage3a_fixed_visual_prior_v1"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _pipeline() -> tuple[dict, dict, dict, dict, dict]:
    prototype_id = "proto_sw_1_3"
    analysis = _read(STAGE2 / prototype_id / "prototype_analysis.json")
    prior = _read(STAGE3A / "fixed_visual_prior.json")
    stage3b_contract = _read(DYNAMIC_DIR / "STAGE3B_L1_FLOW_CONTRACT_V2.json")
    feedback = _read(DYNAMIC_DIR / "EDIT_FEEDBACK_PRIOR_V1.json")
    curve_geometry = _read(
        DYNAMIC_DIR / "EDITOR_CURVE_GEOMETRY_PRIOR_V2.json"
    )
    editor_l2 = _read(DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json")
    plan, _ = planner.generate_global_l1_flow_plan(
        _read(STAGE1 / prototype_id / "strict_p0_v2.json"),
        analysis,
        _read(STAGE25 / prototype_id / "morphology_profile.json"),
        prior,
        stage3b_contract,
        4101,
        feedback,
        curve_geometry,
    )
    stage4_contract = _read(DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json")
    inventory = grammar.generate_unit_candidate_inventory(
        plan,
        analysis,
        prior,
        stage4_contract,
        editor_l2,
    )
    grammar.validate_unit_candidate_inventory(inventory, stage4_contract)
    stage5_contract = _read(DYNAMIC_DIR / "STAGE5_GLOBAL_SELECTION_CONTRACT_V2.json")
    graph = stage5.build_conflict_graph(
        inventory,
        stage5_contract,
        editor_l2,
    )
    selection = stage5.select_global_units(
        inventory,
        graph,
        stage5_contract,
    )
    stage5.validate_global_selection(selection, graph)
    return plan, inventory, graph, selection, stage5_contract


def test_v2_l1_curvature_and_sparse_hierarchy_reach_the_formal_selection() -> None:
    plan, inventory, graph, selection, _ = _pipeline()
    assert plan["edit_feedback_policy"]["fixed_curve_shape_quota"] is False
    assert all(
        lane["source_channel"] == "editor_original_to_edited_correction"
        for lane in plan["lanes"]
    )
    assert inventory["schema"] == "dynamic_branch_stage4_unit_candidate_inventory_v2"
    assert inventory["editor_l2_placement_prior"]["consumed"] is True
    assert selection["schema"] == stage5.SCHEMA_V2
    assert selection["feasible"] is True
    assert selection["solver_trace"]["hierarchy_mix_target_counts"] == {
        "l1_only": 2,
        "single_child": 3,
        "paired_child": 2,
    }
    assert selection["solver_trace"]["hierarchy_mix_selected_counts"] == {
        "l1_only": 2,
        "single_child": 3,
        "paired_child": 2,
    }
    assert sum(
        candidate["hierarchy"]["l2_count"]
        for candidate in selection["selected_candidates"]
    ) == 7
    assert graph["editor_l2_placement_prior_id"] == (
        "saved_editor_l2_placement_20260809"
    )
    assert graph["minimum_descendant_clearance"] > 0.0
    for candidate in selection["selected_candidates"]:
        if candidate["hierarchy"]["l2_count"] < 2:
            continue
        metrics = candidate["intrinsic_diagnostics"]["metrics"]
        assert metrics["minimum_sibling_curve_clearance"] >= metrics[
            "required_sibling_curve_clearance"
        ]
    selected_ids = set(selection["selected_candidate_ids"])
    assert all(
        not {
            edge["first_candidate_id"],
            edge["second_candidate_id"],
        }
        <= selected_ids
        for edge in graph["edges"]
    )


def test_every_lane_offers_l1_only_single_and_paired_without_role_rules() -> None:
    plan, inventory, _, _, _ = _pipeline()
    assert inventory["role_policy"] == "weak_compatibility_metadata_only"
    classes_by_lane: dict[str, set[str]] = {}
    for candidate in inventory["candidates"]:
        classes_by_lane.setdefault(candidate["source_lane_id"], set()).add(
            candidate["visual_features"]["hierarchy_density_class"]
        )
    assert set(classes_by_lane) == {lane["slot_id"] for lane in plan["lanes"]}
    assert all(
        classes == {"l1_only", "single_child", "paired_child"}
        for classes in classes_by_lane.values()
    )
    lane_by_id = {lane["slot_id"]: lane for lane in plan["lanes"]}
    for candidate in inventory["candidates"]:
        l1 = next(curve for curve in candidate["curves"] if curve["level"] == "L1")
        assert l1["cubic_segments"] == lane_by_id[candidate["source_lane_id"]][
            "segments"
        ]


def test_editor_l2_mount_prior_changes_formal_candidate_geometry() -> None:
    plan, original, _, _, _ = _pipeline()
    prototype_id = "proto_sw_1_3"
    changed_prior = _read(DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json")
    profile = changed_prior["profiles"][prototype_id]
    for name in (
        "single_child_mount_fraction",
        "paired_child_mount_center",
    ):
        profile[name]["samples"] = [
            max(0.12, float(value) - 0.08)
            for value in profile[name]["samples"]
        ]
    changed = grammar.generate_unit_candidate_inventory(
        plan,
        _read(STAGE2 / prototype_id / "prototype_analysis.json"),
        _read(STAGE3A / "fixed_visual_prior.json"),
        _read(DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json"),
        changed_prior,
    )
    original_mounts = {
        candidate["candidate_id"]: candidate["visual_features"][
            "mount_sequence"
        ]
        for candidate in original["candidates"]
    }
    changed_mounts = {
        candidate["candidate_id"]: candidate["visual_features"][
            "mount_sequence"
        ]
        for candidate in changed["candidates"]
    }
    assert changed["inventory_digest"] != original["inventory_digest"]
    assert changed_mounts != original_mounts
    original_l1 = {
        candidate["candidate_id"]: candidate["curves"][0]["cubic_segments"]
        for candidate in original["candidates"]
    }
    changed_l1 = {
        candidate["candidate_id"]: candidate["curves"][0]["cubic_segments"]
        for candidate in changed["candidates"]
    }
    assert changed_l1 == original_l1


def test_hierarchy_mix_counterfactual_changes_the_selected_structure() -> None:
    _, inventory, graph, original, contract = _pipeline()
    changed_contract = copy.deepcopy(contract)
    changed_contract["hierarchy_mix"]["class_fraction_targets"] = {
        "l1_only": 0.14,
        "single_child": 0.72,
        "paired_child": 0.14,
    }
    changed = stage5.select_global_units(inventory, graph, changed_contract)
    stage5.validate_global_selection(changed, graph)
    assert changed["solver_trace"]["hierarchy_mix_selected_counts"] == {
        "l1_only": 1,
        "single_child": 5,
        "paired_child": 1,
    }
    assert changed["selected_candidate_ids"] != original["selected_candidate_ids"]
