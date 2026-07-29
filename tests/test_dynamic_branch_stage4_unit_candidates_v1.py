from __future__ import annotations

import hashlib
import json
import math
import sys
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import branch_unit_grammar_v1 as grammar  # noqa: E402


STAGE2 = ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE3A = (
    ROOT / "artifacts" / "runs" / "dynamic_branch_stage3a_fixed_visual_prior_v1"
)
STAGE3B = (
    ROOT / "artifacts" / "runs" / "dynamic_branch_stage3b_global_l1_flow_v1"
)
STAGE4 = (
    ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_unit_candidates_v1"
)
CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V1.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _contract() -> dict:
    return _read(CONTRACT_PATH)


@lru_cache(maxsize=1)
def _prior() -> dict:
    return _read(STAGE3A / "fixed_visual_prior.json")


@lru_cache(maxsize=None)
def _analysis(prototype_id: str) -> dict:
    return _read(STAGE2 / prototype_id / "prototype_analysis.json")


@lru_cache(maxsize=None)
def _plan(prototype_id: str, seed: int) -> dict:
    return _read(
        STAGE3B
        / prototype_id
        / f"seed_{seed}"
        / "global_l1_flow_plan.json"
    )


@lru_cache(maxsize=None)
def _inventory(prototype_id: str, seed: int) -> dict:
    return grammar.generate_unit_candidate_inventory(
        _plan(prototype_id, seed),
        _analysis(prototype_id),
        _prior(),
        _contract(),
    )


def test_stage3b_approval_binds_the_complete_immutable_launch_matrix() -> None:
    approval = _read(STAGE3B / "stage3b_approval.json")
    assert approval["schema"] == "dynamic_branch_stage3b_approval_v1"
    assert approval["status"] == "l1_flow_approved_for_unit_generation"
    assert approval["stage4_unlocked"] is True
    assert approval["approved_task_count"] == 15
    assert approval["stage3b_manifest_sha256"] == _sha256(
        STAGE3B / "manifest.json"
    )
    assert len(approval["approved_tasks"]) == 15
    for row in approval["approved_tasks"]:
        path = STAGE3B / row["plan_path"]
        assert path.is_file()
        assert _sha256(path) == row["plan_sha256"]
        plan = _read(path)
        assert plan["plan_digest"] == row["plan_digest"]
        assert len(plan["lanes"]) == row["lane_count"]


def test_stage4_contract_is_complete_unit_candidate_generation_only() -> None:
    contract = _contract()
    assert contract["schema"] == grammar.CONTRACT_SCHEMA
    assert set(contract["grammar"]) == {
        "Y-C",
        "Y-2C",
        "Frontier-Y-C",
        "FlowerSupport-C",
        "TerminalSupport-C",
    }
    assert contract["required_inputs"]["approved_l1_geometry_is_immutable"] is True
    assert contract["required_inputs"]["old_stage3_layout_consumed"] is False
    assert contract["required_inputs"]["old_stage4_geometry_consumed"] is False
    assert contract["candidate_coverage"]["global_candidate_selection_in_stage4"] is False
    assert contract["output"]["whole_composition_selection_present"] is False
    assert contract["scope"]["leaves_present"] is False
    assert contract["scope"]["buds_present"] is False
    assert contract["scope"]["curl_heads_present"] is False
    for key in (
        "validation_guided_retry_allowed",
        "validation_guided_resample_allowed",
        "automatic_repair_allowed",
        "automatic_deletion_allowed",
        "silent_fallback_allowed",
    ):
        assert contract["sampling"][key] is False


def test_candidate_inventory_preserves_l1_and_materializes_complete_units() -> None:
    prototype_id = "proto_sw_1_3"
    seed = 4101
    plan = _plan(prototype_id, seed)
    inventory = _inventory(prototype_id, seed)
    grammar.validate_unit_candidate_inventory(inventory, _contract())
    assert inventory["lane_count"] == len(plan["lanes"]) == 7
    assert inventory["coverage"]["lanes_without_feasible_candidate"] == []
    assert all(
        row["feasible_candidate_count"] >= 1 for row in inventory["lanes"]
    )
    assert inventory["review"]["status"] == (
        "unit_candidate_pool_pending_visual_review"
    )
    lane_by_id = {lane["slot_id"]: lane for lane in plan["lanes"]}
    grammar_by_role = {
        "primary_sweep": {"Y-C", "Y-2C"},
        "balance": {"Y-C", "Y-2C"},
        "frontier": {"Frontier-Y-C"},
        "flower_support": {"FlowerSupport-C"},
        "terminal_flower_support": {"TerminalSupport-C"},
    }
    for candidate in inventory["candidates"]:
        lane = lane_by_id[candidate["source_lane_id"]]
        assert candidate["grammar_id"] in grammar_by_role[candidate["role"]]
        l1 = next(curve for curve in candidate["curves"] if curve["level"] == "L1")
        assert l1["cubic_segments"] == lane["segments"]
        assert candidate["hierarchy"]["l2_count"] >= 1
        assert len(candidate["parent_graph"]) == len(candidate["curves"])
        assert candidate["random_provenance"][
            "validation_guided_retry_count"
        ] == 0
        assert candidate["random_provenance"][
            "validation_guided_resample_count"
        ] == 0
        assert candidate["random_provenance"]["automatic_repair_count"] == 0
        assert candidate["random_provenance"]["automatic_deletion_count"] == 0
        assert candidate["random_provenance"]["silent_fallback_count"] == 0


def test_feasible_candidates_have_exact_attachment_opening_and_smooth_s_joins() -> None:
    inventory = _inventory("proto_sw_2_3", 4101)
    contract = _contract()
    lower, upper = contract["geometry"]["entry_opening_degrees_range"]
    for candidate in inventory["candidates"]:
        if not candidate["intrinsic_diagnostics"]["valid"]:
            continue
        curve_by_id = {
            curve["curve_id"]: curve for curve in candidate["curves"]
        }
        for curve in candidate["curves"]:
            if curve["level"] == "L1":
                continue
            assert curve["parent_curve_id"] in curve_by_id
            assert lower - 0.5 <= curve["entry_opening_degrees"] <= upper + 0.5
            assert candidate["intrinsic_diagnostics"]["metrics"][
                "maximum_attachment_error"
            ] <= 2e-6
            if len(curve["cubic_segments"]) == 2:
                first, second = curve["cubic_segments"]
                incoming = grammar._unit(
                    grammar._sub(
                        grammar._point(first["p3"]),
                        grammar._point(first["p2"]),
                    )
                )
                outgoing = grammar._unit(
                    grammar._sub(
                        grammar._point(second["p1"]),
                        grammar._point(second["p0"]),
                    )
                )
                assert grammar._angle_degrees(incoming, outgoing) < 0.01


def test_c_and_s_arcs_are_gentle_and_ordinary_l2_is_not_short() -> None:
    inventory = _inventory("proto_sw_1_3", 4101)
    for candidate in inventory["candidates"]:
        curve_by_id = {
            curve["curve_id"]: curve for curve in candidate["curves"]
        }
        for curve in candidate["curves"]:
            if curve["level"] != "L2":
                continue
            parent = curve_by_id[curve["parent_curve_id"]]
            if candidate["role"] in {"primary_sweep", "balance"}:
                assert curve["actual_length"] / parent["actual_length"] >= 0.34
            first = curve["cubic_segments"][0]
            last = curve["cubic_segments"][-1]
            entry = grammar._unit(
                grammar._sub(
                    grammar._point(first["p1"]),
                    grammar._point(first["p0"]),
                )
            )
            exit_direction = grammar._unit(
                grammar._sub(
                    grammar._point(last["p3"]),
                    grammar._point(last["p2"]),
                )
            )
            internal_turn = grammar._angle_degrees(entry, exit_direction)
            if curve["shape_signature"] == "C":
                assert internal_turn <= 18.1
            elif curve["shape_signature"] == "S":
                assert internal_turn <= 48.1
                segment_turns = []
                for segment in curve["cubic_segments"]:
                    segment_entry = grammar._unit(
                        grammar._sub(
                            grammar._point(segment["p1"]),
                            grammar._point(segment["p0"]),
                        )
                    )
                    segment_exit = grammar._unit(
                        grammar._sub(
                            grammar._point(segment["p3"]),
                            grammar._point(segment["p2"]),
                        )
                    )
                    segment_turns.append(
                        grammar._angle_degrees(
                            segment_entry,
                            segment_exit,
                        )
                    )
                assert len(segment_turns) == 2
                assert min(segment_turns) >= 18.9
                assert max(segment_turns) - min(segment_turns) <= 0.01


def test_stage4_is_deterministic_and_preserves_invalid_candidates() -> None:
    first = _inventory("proto_sw_3_2", 4102)
    repeated = grammar.generate_unit_candidate_inventory(
        _plan("proto_sw_3_2", 4102),
        _analysis("proto_sw_3_2"),
        _prior(),
        _contract(),
    )
    assert first["inventory_digest"] == repeated["inventory_digest"]
    assert first["invalid_candidate_count"] > 0
    assert any(
        candidate["intrinsic_diagnostics"]["issues"]
        for candidate in first["candidates"]
    )
    assert first["generation_policy"] == {
        "generated_once": True,
        "validation_guided_retry_used": False,
        "validation_guided_resample_used": False,
        "automatic_repair_used": False,
        "automatic_deletion_used": False,
        "silent_fallback_used": False,
        "best_of_n_selection_used": False,
    }


def test_formal_stage4_package_contains_all_15_candidate_pools_and_atlases() -> None:
    manifest = _read(STAGE4 / "manifest.json")
    assert manifest["schema"] == "dynamic_branch_stage4_unit_candidate_manifest_v1"
    assert manifest["task_count"] == manifest["success_count"] == 15
    assert manifest["failure_count"] == 0
    assert manifest["total_lane_count"] == 90
    assert manifest["total_candidate_count"] == 405
    assert manifest["total_feasible_candidate_count"] > 0
    assert manifest["coverage"] == {
        "all_approved_l1_lanes_consumed": True,
        "every_lane_has_feasible_complete_unit_candidate": True,
        "lanes_without_feasible_candidate": [],
    }
    assert manifest["scope"]["global_unit_selection_present"] is False
    assert manifest["scope"]["whole_composition_output_present"] is False
    assert manifest["review_gate"] == {
        "status": "unit_candidate_pool_pending_visual_review",
        "numeric_checks_cannot_auto_approve_visual_gate": True,
        "stage5_unlocked": False,
    }
    for name, digest in manifest["contact_sheets"].items():
        path = STAGE4 / name
        assert path.is_file()
        assert _sha256(path) == digest
    for row in manifest["tasks"]:
        assert row["lanes_without_feasible_candidate"] == []
        assert row["feasible_candidate_count"] >= row["lane_count"]
        assert row["state"] == "unit_candidate_pool_pending_visual_review"
        for file_row in row["files"].values():
            path = STAGE4 / file_row["path"]
            assert path.is_file()
            assert _sha256(path) == file_row["sha256"]
        if row["prototype_id"] == "proto_sw_1_3":
            assert "fixed_stage4_visual_pair.png" in row["files"]
