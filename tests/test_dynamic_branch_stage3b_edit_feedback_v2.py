from __future__ import annotations

import copy
import json
import statistics
import sys
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import global_l1_flow as planner  # noqa: E402


STAGE1 = ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
STAGE2 = ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE25 = ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
STAGE3A = ROOT / "artifacts" / "runs" / "dynamic_branch_stage3a_fixed_visual_prior_v1"
CONTRACT = DYNAMIC_DIR / "STAGE3B_L1_FLOW_CONTRACT_V2.json"
FEEDBACK = DYNAMIC_DIR / "EDIT_FEEDBACK_PRIOR_V1.json"
CURVE_GEOMETRY = DYNAMIC_DIR / "EDITOR_CURVE_GEOMETRY_PRIOR_V2.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _inputs() -> tuple[dict, dict, dict, dict, dict, dict, dict]:
    prototype_id = "proto_sw_1_3"
    return (
        _read(STAGE1 / prototype_id / "strict_p0_v2.json"),
        _read(STAGE2 / prototype_id / "prototype_analysis.json"),
        _read(STAGE25 / prototype_id / "morphology_profile.json"),
        _read(STAGE3A / "fixed_visual_prior.json"),
        _read(CONTRACT),
        _read(FEEDBACK),
        _read(CURVE_GEOMETRY),
    )


@lru_cache(maxsize=1)
def _plan() -> tuple[dict, dict]:
    strict, analysis, morphology, prior, contract, feedback, curve_geometry = _inputs()
    return planner.generate_global_l1_flow_plan(
        strict,
        analysis,
        morphology,
        prior,
        contract,
        4101,
        feedback,
        curve_geometry,
    )


def test_feedback_v2_is_the_active_l1_production_path() -> None:
    plan, inventory = _plan()
    planner.validate_global_l1_flow_plan(plan)
    assert plan["schema"] == planner.SCHEMA_V2
    assert plan["edit_feedback_policy"]["consumed"] is True
    assert plan["edit_feedback_policy"]["prior_id"] == (
        "old_mainline_editor_batch_20260806"
    )
    assert plan["edit_feedback_policy"]["role_semantics"] == (
        "weak_compatibility_label_only"
    )
    assert plan["edit_feedback_policy"]["mandatory_flower_service_lanes"] is False
    assert plan["edit_feedback_policy"]["fixed_svg_templates_consumed"] is False
    assert plan["edit_feedback_policy"]["curve_geometry_source"] == (
        "saved_editor_l1_original_to_edited_correction"
    )
    assert plan["edit_feedback_policy"]["fixed_curve_shape_quota"] is False
    assert plan["count_derivation"]["selected_l1_count"] == 7
    assert plan["count_derivation"]["required_support_count"] == 0
    assert all(lane["flower_id"] is None for lane in plan["lanes"])
    assert all(
        lane["source_channel"] == "editor_original_to_edited_correction"
        for lane in plan["lanes"]
    )
    assert all(
        all(
            name in lane["features"]
            for name in (
                "editor_start_handle_chord_ratio",
                "editor_end_handle_chord_ratio",
                "editor_start_angle_abs_deg",
                "editor_end_angle_normalized_deg",
                "editor_demonstration_row_index",
                "editor_demonstration_distance",
            )
        )
        for lane in plan["lanes"]
    )
    assert all(
        {
            "initial_tangent_alignment",
            "initial_outward_alignment",
            "bow_ratio",
            "vertical_span",
            "maximum_backbone_excursion",
            "nearest_flower_gap",
            "length_stratum",
        }
        <= set(lane["features"])
        for lane in plan["lanes"]
    )
    assert inventory["schema"] == "dynamic_branch_global_l1_candidate_inventory_v2"


def test_feedback_v2_selected_lanes_are_mechanically_non_intersecting() -> None:
    plan, _ = _plan()
    root_spacing = float(plan["solver"]["root_spacing_hard"])
    lane_clearance = float(plan["solver"]["lane_clearance_hard"])
    for index, lane in enumerate(plan["lanes"]):
        for other in plan["lanes"][index + 1 :]:
            valid, _, metrics = planner._pair_metrics(
                lane,
                other,
                root_spacing,
                lane_clearance,
            )
            assert valid, metrics


def test_feedback_geometry_counterfactual_changes_formal_output() -> None:
    strict, analysis, morphology, prior, contract, feedback, curve_geometry = _inputs()
    original, _ = _plan()
    perturbed = copy.deepcopy(feedback)
    perturbed["prototype_profiles"]["proto_sw_1_3"]["length_multiplier"] = 0.82
    changed, _ = planner.generate_global_l1_flow_plan(
        strict,
        analysis,
        morphology,
        prior,
        contract,
        4101,
        perturbed,
        curve_geometry,
    )
    original_median = statistics.median(
        float(lane["planning_length"]) for lane in original["lanes"]
    )
    changed_median = statistics.median(
        float(lane["planning_length"]) for lane in changed["lanes"]
    )
    assert changed["plan_digest"] != original["plan_digest"]
    assert changed_median < original_median


def test_editor_original_to_edited_correction_is_consumed() -> None:
    strict, analysis, morphology, prior, contract, feedback, curve_geometry = _inputs()
    original, _ = _plan()
    reduced_edits = copy.deepcopy(curve_geometry)
    profile = reduced_edits["profiles"]["proto_sw_1_3"]
    for row in profile["paired_corrections"]:
        row["edit_delta"] = {
            name: 0.5 * float(value)
            for name, value in row["edit_delta"].items()
        }
    with pytest.raises(
        planner.GlobalL1FlowError,
        match="single forward global solve became infeasible",
    ):
        planner.generate_global_l1_flow_plan(
            strict,
            analysis,
            morphology,
            prior,
            contract,
            4101,
            feedback,
            reduced_edits,
        )
    assert original["plan_digest"]
