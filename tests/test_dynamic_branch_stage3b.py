from __future__ import annotations

import json
import hashlib
import sys
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import fixed_visual_prior as prior_module  # noqa: E402
import global_l1_flow as planner  # noqa: E402


BASELINE = ROOT / "artifacts" / "frozen_baselines" / "fixed_depth_7_12_2_v23"
STAGE1 = ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
STAGE2 = ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE25 = (
    ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
)
PRIOR_CONTRACT = DYNAMIC_DIR / "FIXED_VISUAL_PRIOR_CONTRACT_V1.json"
FLOW_CONTRACT = DYNAMIC_DIR / "STAGE3B_L1_FLOW_CONTRACT_V1.json"
FORMAL_OUTPUT = (
    ROOT / "artifacts" / "runs" / "dynamic_branch_stage3b_global_l1_flow_v1"
)
EXPECTED_COUNTS = {
    "proto_sw_1_1": 7,
    "proto_sw_1_3": 7,
    "proto_sw_2_3": 6,
    "proto_sw_3_1": 4,
    "proto_sw_3_2": 6,
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _prior() -> dict:
    return prior_module.build_fixed_visual_prior(BASELINE, PRIOR_CONTRACT)


@lru_cache(maxsize=None)
def _inputs(prototype_id: str) -> tuple[dict, dict, dict, dict, dict]:
    return (
        _read(STAGE1 / prototype_id / "strict_p0_v2.json"),
        _read(STAGE2 / prototype_id / "prototype_analysis.json"),
        _read(STAGE25 / prototype_id / "morphology_profile.json"),
        _prior(),
        _read(FLOW_CONTRACT),
    )


@lru_cache(maxsize=None)
def _plan(prototype_id: str, seed: int) -> tuple[dict, dict]:
    return planner.generate_global_l1_flow_plan(*_inputs(prototype_id), seed)


@pytest.mark.parametrize("prototype_id", planner.PROTOTYPE_IDS)
def test_stage3b_emits_one_strict_global_l1_layout(prototype_id: str) -> None:
    plan, inventory = _plan(prototype_id, 4101)
    planner.validate_global_l1_flow_plan(plan)
    assert len(plan["lanes"]) == EXPECTED_COUNTS[prototype_id]
    assert plan["count_derivation"]["selected_l1_count"] == EXPECTED_COUNTS[
        prototype_id
    ]
    assert plan["geometry_semantics"] == "planning_flow_lane_not_final_branch_curve"
    assert plan["diagnostics"]["hard_issue_count"] == 0
    assert plan["diagnostics"]["automatic_repair_used"] is False
    assert plan["diagnostics"]["automatic_deletion_used"] is False
    assert plan["diagnostics"]["validation_guided_retry_used"] is False
    assert plan["diagnostics"]["validation_guided_resample_used"] is False
    assert plan["diagnostics"]["silent_fallback_used"] is False
    assert plan["review"]["status"] == "l1_flow_pending_visual_review"
    assert inventory["single_forward_global_solve"] is True
    assert inventory["experimental_variants"] is False
    assert sum(bool(row["selected"]) for row in inventory["candidates"]) == len(
        plan["lanes"]
    )


def test_stage3b_preserves_prototype_specific_flower_relations() -> None:
    sw1, _ = _plan("proto_sw_1_1", 4101)
    sw2, _ = _plan("proto_sw_2_3", 4101)
    sw3, _ = _plan("proto_sw_3_2", 4101)

    sw1_supports = [
        lane for lane in sw1["lanes"] if lane["role"] == "flower_support"
    ]
    assert len(sw1_supports) == 2
    assert all(
        lane["features"]["trough_arc_distance"] <= 0.14
        for lane in sw1_supports
    )

    assert all(lane["flower_id"] is None for lane in sw2["lanes"])
    assert "flower_support" not in sw2["role_counts"]
    assert "terminal_flower_support" not in sw2["role_counts"]

    sw3_supports = [
        lane
        for lane in sw3["lanes"]
        if lane["role"] == "terminal_flower_support"
    ]
    assert len(sw3_supports) == 2
    assert all(
        0.30 <= lane["features"]["remote_mount_arc_distance"] <= 0.48
        for lane in sw3_supports
    )
    assert all(
        lane["features"]["below_flower_waypoint_margin"] >= 0.035
        for lane in sw3_supports
    )
    assert all(
        lane["features"]["underside_contact_dx"] <= 0.01
        and lane["features"]["underside_contact_dy"] <= 0.01
        for lane in sw3_supports
    )


def test_stage3b_selected_set_is_periodically_clear() -> None:
    plan, _ = _plan("proto_sw_2_3", 4101)
    root_limit = plan["solver"]["root_spacing_hard"]
    lane_limit = plan["solver"]["lane_clearance_hard"]
    for row in plan["solver"]["selected_pair_metrics"]:
        assert row["root_gap"] >= root_limit
        assert row["minimum_clearance"] >= lane_limit


def test_stage3b_is_seed_deterministic_and_seed_sensitive() -> None:
    first, _ = _plan("proto_sw_3_1", 4102)
    repeated = planner.generate_global_l1_flow_plan(
        *_inputs("proto_sw_3_1"),
        4102,
    )[0]
    other, _ = _plan("proto_sw_3_1", 4103)
    assert first["plan_digest"] == repeated["plan_digest"]
    assert first["plan_digest"] != other["plan_digest"]


def test_stage3b_formal_fifteen_task_package_is_complete() -> None:
    manifest = _read(FORMAL_OUTPUT / "manifest.json")
    assert manifest["schema"] == "dynamic_branch_stage3b_l1_flow_manifest_v1"
    assert manifest["task_count"] == 15
    assert manifest["success_count"] == 15
    assert manifest["failure_count"] == 0
    assert manifest["review_gate"]["status"] == "l1_flow_pending_visual_review"
    assert manifest["generation_policy"] == {
        "one_forward_global_solve_per_task": True,
        "experimental_variants_created": False,
        "automatic_repair_used": False,
        "automatic_deletion_used": False,
        "validation_guided_retry_used": False,
        "validation_guided_resample_used": False,
        "silent_fallback_used": False,
    }
    for task in manifest["tasks"]:
        assert task["hard_issue_count"] == 0
        assert task["state"] == "l1_flow_pending_visual_review"
        for row in task["files"].values():
            path = FORMAL_OUTPUT / row["path"]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        plan = _read(
            FORMAL_OUTPUT
            / task["prototype_id"]
            / f'seed_{task["seed"]}'
            / "global_l1_flow_plan.json"
        )
        planner.validate_global_l1_flow_plan(plan)
