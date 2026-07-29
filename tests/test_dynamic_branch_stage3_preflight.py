from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import run_stage3_preflight as preflight  # noqa: E402


STAGE1_ROOT = ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
STAGE2_ROOT = ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE25_ROOT = (
    ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
)
CONTRACT_PATH = DYNAMIC_DIR / "STAGE3_PLAN_CONTRACT.json"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_stage3_contract_freezes_branchunit_only_symbolic_scope() -> None:
    contract = _contract()
    assert contract["task_matrix"]["expected_task_count"] == 15
    assert contract["task_matrix"]["raw_candidate_count_per_prototype_seed"] == 1
    assert contract["output"]["curve_geometry_present"] is False
    assert contract["output"]["schema"] == "dynamic_branch_plan_v3"
    assert (
        contract["structural_primitive"][
            "independent_curve_as_primary_primitive_allowed"
        ]
        is False
    )
    assert contract["candidate_and_failure_policy"][
        "validation_guided_retry_allowed"
    ] is False
    assert contract["candidate_and_failure_policy"][
        "automatic_repair_allowed"
    ] is False
    assert "adding_leaves_buds_or_curl_heads" in contract[
        "prohibited_implementation_shortcuts"
    ]
    layout = contract["initial_layout_constraints"]
    assert layout["role_density_field_consumed_by_global_selection"] is True
    assert layout["one_selected_root_per_density_bin"] is True
    assert layout["opposite_side_same_root_exception_allowed"] is False
    assert layout["symbolic_intent_polyline_crossing_allowed"] is False
    assert (
        layout["symbolic_intent_polyline_clearance_is_hard_constraint"]
        is True
    )
    assert layout["minimum_symbolic_intent_clearance"] > 0
    assert layout["directional_preview_is_branch_shape_simulation"] is False
    assert layout["parent_tangent_departure_segment_in_preview_allowed"] is False
    assert layout["immediate_outward_departure_required"] is True
    assert layout["minimum_outward_normal_alignment"] > 0.8
    assert (
        layout["sw3_remote_terminal_support"]["near_flower_stub_allowed"]
        is False
    )
    assert (
        layout["sw3_remote_terminal_support"]["route_below_flower_required"]
        is True
    )
    assert (
        layout["sw3_remote_terminal_support"]["underside_contact_required"]
        is True
    )


def test_approved_inputs_build_exactly_fifteen_ready_tasks() -> None:
    readiness, task_matrix, provenance = preflight.build_readiness(
        STAGE1_ROOT,
        STAGE2_ROOT,
        STAGE25_ROOT,
    )
    assert readiness["ready"] is True
    assert readiness["blockers"] == []
    assert readiness["analysis_review_gate"] == "analysis_approved"
    assert readiness["morphology_review_gate"] == "morphology_approved"
    assert task_matrix["task_count"] == 15
    assert len({row["task_id"] for row in task_matrix["tasks"]}) == 15
    assert {row["seed"] for row in task_matrix["tasks"]} == {4101, 4102, 4103}
    assert all(row["state"] == "ready_not_generated" for row in task_matrix["tasks"])
    assert all(row["raw_candidate_index"] == 1 for row in task_matrix["tasks"])
    assert all(row["curve_geometry_allowed"] is False for row in task_matrix["tasks"])
    assert all(
        row["validation_guided_retry_allowed"] is False
        for row in task_matrix["tasks"]
    )
    for prototype_id in preflight.PROTOTYPE_IDS:
        rows = [
            row
            for row in task_matrix["tasks"]
            if row["prototype_id"] == prototype_id
        ]
        assert len(rows) == 3
        assert len({row["family_id"] for row in rows}) == 1
    assert set(provenance) == {
        "implementation_contract_sha256",
        "stage3_plan_contract_sha256",
        "stage1_manifest_sha256",
        "stage2_manifest_sha256",
        "stage25_manifest_sha256",
    }


def test_preflight_runner_materializes_readiness_without_starting_plans(
    tmp_path: Path,
) -> None:
    output = tmp_path / "stage3_preflight"
    manifest = preflight.run(
        STAGE1_ROOT,
        STAGE2_ROOT,
        STAGE25_ROOT,
        output,
    )
    assert manifest["ready"] is True
    assert manifest["task_count"] == 15
    assert manifest["stage_scope"]["not_started"] == [
        "candidate_slot_selection",
        "branch_unit_plan_generation",
        "dynamic_branch_plan_rendering",
        "curve_compilation",
    ]
    assert {path.name for path in output.iterdir()} == {
        "stage3_readiness.json",
        "stage3_task_matrix.json",
        "manifest.json",
    }
    matrix = json.loads(
        (output / "stage3_task_matrix.json").read_text(encoding="utf-8")
    )
    assert matrix["stage_boundary"] == {
        "plan_generation_started": False,
        "curve_compilation_started": False,
        "leaves_buds_or_curl_heads_started": False,
    }


def test_preflight_rejects_unapproved_morphology_gate(tmp_path: Path) -> None:
    stage25_copy = tmp_path / "stage25"
    stage25_copy.mkdir()
    manifest = json.loads(
        (STAGE25_ROOT / "manifest.json").read_text(encoding="utf-8")
    )
    manifest["review_gate"]["status"] = "morphology_pending_review"
    manifest["review_gate"]["stage_3_unlocked"] = False
    (stage25_copy / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        preflight.Stage3PreflightError,
        match="stage 2.5 review gate is morphology_pending_review",
    ):
        preflight.build_readiness(
            STAGE1_ROOT,
            STAGE2_ROOT,
            stage25_copy,
        )
