from __future__ import annotations

import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import stage5_global_unit_selection as stage5  # noqa: E402


STAGE4 = (
    ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_unit_candidates_v1"
)
STAGE5 = (
    ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage5_global_unit_selection_v1"
)
CONTRACT_PATH = DYNAMIC_DIR / "STAGE5_GLOBAL_SELECTION_CONTRACT_V1.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _contract() -> dict:
    return _read(CONTRACT_PATH)


@lru_cache(maxsize=None)
def _inventory(prototype_id: str, seed: int) -> dict:
    return _read(
        STAGE4
        / prototype_id
        / f"seed_{seed}"
        / "unit_candidate_inventory.json"
    )


@lru_cache(maxsize=None)
def _computed(prototype_id: str, seed: int) -> tuple[dict, dict]:
    inventory = _inventory(prototype_id, seed)
    graph = stage5.build_conflict_graph(inventory, _contract())
    selection = stage5.select_global_units(
        inventory,
        graph,
        _contract(),
    )
    return graph, selection


def test_stage4_approval_binds_all_fifteen_immutable_candidate_pools() -> None:
    approval = _read(STAGE4 / "stage4_approval.json")
    assert approval["schema"] == (
        "dynamic_branch_stage4_unit_candidate_approval_v1"
    )
    assert approval["status"] == (
        "unit_candidate_pool_approved_for_global_selection"
    )
    assert approval["stage5_unlocked"] is True
    assert approval["approved_task_count"] == 15
    assert approval["stage4_manifest_sha256"] == _sha256(
        STAGE4 / "manifest.json"
    )
    for row in approval["approved_tasks"]:
        path = STAGE4 / row["inventory_path"]
        assert _sha256(path) == row["inventory_sha256"]
        inventory = _read(path)
        assert inventory["inventory_digest"] == row["inventory_digest"]


def test_stage5_contract_forbids_curve_mutation_and_visual_best_of_n() -> None:
    contract = _contract()
    assert contract["schema"] == stage5.CONTRACT_SCHEMA
    assert contract["scope"]["new_curve_generation_present"] is False
    assert contract["scope"]["curve_mutation_present"] is False
    assert contract["scope"]["candidate_deletion_present"] is False
    assert contract["selection"]["best_of_n_visual_ranking_used"] is False
    assert contract["selection"]["composite_visual_score_used"] is False
    assert contract["selection"]["automatic_repair_used"] is False
    assert contract["selection"]["automatic_deletion_used"] is False
    assert contract["hard_constraints"]["cross_unit_curve_crossing_allowed"] is False
    assert contract["hard_constraints"]["periodic_repeat_crossing_allowed"] is False


def test_feasible_selection_covers_every_lane_without_conflict_edges() -> None:
    graph, selection = _computed("proto_sw_1_3", 4101)
    assert selection["feasible"] is True
    assert selection["selected_candidate_count"] == selection["lane_count"]
    selected_ids = set(selection["selected_candidate_ids"])
    assert len(selected_ids) == selection["lane_count"]
    assert all(
        not {
            edge["first_candidate_id"],
            edge["second_candidate_id"],
        }
        <= selected_ids
        for edge in graph["edges"]
    )
    assert selection["solver_trace"]["automatic_repair_used"] is False
    assert selection["solver_trace"]["automatic_deletion_used"] is False


def test_periodic_blocker_is_preserved_without_partial_selection() -> None:
    graph, selection = _computed("proto_sw_3_1", 4103)
    assert graph["edge_count"] == 12
    assert selection["feasible"] is False
    assert selection["status"] == "global_unit_selection_infeasible"
    assert selection["selected_candidate_count"] == 0
    assert selection["selected_candidates"] == []
    assert selection["blocking_lane_pairs"] == [
        {
            "first_lane_id": "ordinary_1",
            "second_lane_id": "ordinary_3",
            "first_candidate_count": 6,
            "second_candidate_count": 2,
            "reason": "every_candidate_pair_crosses",
        }
    ]


def test_formal_stage5_package_matches_deterministic_recomputation() -> None:
    manifest = _read(STAGE5 / "manifest.json")
    assert manifest["schema"] == (
        "dynamic_branch_stage5_global_selection_manifest_v1"
    )
    assert manifest["task_count"] == manifest["processed_task_count"] == 15
    assert manifest["processing_failure_count"] == 0
    assert manifest["complete_composition_count"] == 14
    assert manifest["unresolved_composition_count"] == 1
    assert manifest["blocking_pair_counts"] == {
        "proto_sw_3_1:ordinary_1×ordinary_3": 1
    }
    contact = STAGE5 / manifest["contact_sheet"]["path"]
    assert contact.is_file()
    assert _sha256(contact) == manifest["contact_sheet"]["sha256"]

    for row in manifest["tasks"]:
        prototype_id = row["prototype_id"]
        seed = row["seed"]
        graph, selection = _computed(prototype_id, seed)
        assert row["conflict_graph_digest"] == graph["conflict_graph_digest"]
        assert row["selection_digest"] == selection["selection_digest"]
        for file_row in row["files"].values():
            path = STAGE5 / file_row["path"]
            assert path.is_file()
            assert _sha256(path) == file_row["sha256"]
