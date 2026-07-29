from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = REPO_ROOT / "experiments" / "branch_unit"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

import recursive_branch_unit_v2 as core  # noqa: E402


PROFILE_PATH = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "run57_reproduction"
    / "01_skeleton_analysis"
    / "proto_sw_1_3"
    / "skeleton_profile.json"
)


@pytest.fixture(scope="module")
def recursive_v2_cases():
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    p0 = core.strip_profile(profile)
    cases = {}
    for seed in core.DEV_SEEDS:
        plan = core.plan_recursive(p0, seed)
        result = core.compile_plan(plan, p0)
        cases[seed] = (plan, result)
    return p0, cases


def test_all_fixed_seeds_plan_once(recursive_v2_cases) -> None:
    _, cases = recursive_v2_cases
    assert tuple(cases) == core.DEV_SEEDS
    for seed, (plan, result) in cases.items():
        assert plan.seed == seed
        assert result.plan is plan


def test_topology_is_7_12_and_6_to_9_with_adjacent_parent_levels(
    recursive_v2_cases,
) -> None:
    _, cases = recursive_v2_cases
    for seed, (plan, result) in cases.items():
        nodes = result.by_id
        level_counts = Counter(node.level for node in result.curves)
        assert level_counts[1] == 7, seed
        assert level_counts[2] == 12, seed
        assert 6 <= level_counts[3] <= 9, seed
        assert set(level_counts) == {1, 2, 3}, seed
        assert max(level_counts) == plan.controls.max_depth == 3, seed

        for row in plan.descendants:
            assert row.curve_id in nodes, (seed, row.curve_id)
            assert row.parent_id in nodes, (seed, row.curve_id, row.parent_id)
            assert nodes[row.curve_id].level == row.level
            assert row.level == nodes[row.parent_id].level + 1


def test_all_tertiaries_belong_to_free_units_and_flower_units_have_none(
    recursive_v2_cases,
) -> None:
    _, cases = recursive_v2_cases
    flower_units = set(core.UNIT_ORDER) - set(core.FREE_UNITS)
    assert flower_units == {"primary_4_flower_1", "primary_5_flower_2"}

    for seed, (plan, _) in cases.items():
        tertiary_meta = [meta for meta in plan.node_metadata if meta.level == 3]
        assert 6 <= len(tertiary_meta) <= 9, seed
        assert {meta.unit_id for meta in tertiary_meta} <= set(core.FREE_UNITS), seed
        assert not any(meta.unit_id in flower_units for meta in tertiary_meta), seed


def test_edge_carrier_slots_and_heir_parents_match(recursive_v2_cases) -> None:
    _, cases = recursive_v2_cases
    for seed, (plan, _) in cases.items():
        metadata = plan.metadata_by_id
        carriers = {
            meta.unit_id: meta
            for meta in plan.node_metadata
            if meta.level == 2 and meta.edge_goal is not None
        }
        assert set(carriers) == set(core.FREE_UNITS), seed

        for unit_id, expected_slot in core.EDGE_CARRIER_SLOT.items():
            carrier = carriers[unit_id]
            unit_number = core.UNIT_ORDER.index(unit_id) + 1
            assert carrier.path == f"P{unit_number}/{expected_slot.upper()}"
            assert carrier.curve_id == f"secondary_{unit_number}_{expected_slot}"
            assert carrier.terminal_role == "edge_parent"
            assert carrier.is_edge_heir is False

        edge_heirs = [meta for meta in plan.node_metadata if meta.is_edge_heir]
        assert len(edge_heirs) == len(core.FREE_UNITS)
        for heir in edge_heirs:
            carrier = carriers[heir.unit_id]
            assert heir.parent_id == carrier.curve_id
            assert metadata[heir.parent_id] == carrier
            assert heir.edge_goal == carrier.edge_goal


def test_context_order_and_cyclic_neighbours_are_recorded(recursive_v2_cases) -> None:
    _, cases = recursive_v2_cases
    for seed, (plan, _) in cases.items():
        assert tuple(context.unit_id for context in plan.contexts) == core.CONTEXT_ORDER, seed
        assert len(plan.contexts) == len(core.UNIT_ORDER) == 7

        for generation_index, context in enumerate(plan.contexts):
            unit_index = core.UNIT_ORDER.index(context.unit_id)
            expected_left = core.UNIT_ORDER[(unit_index - 1) % len(core.UNIT_ORDER)]
            expected_right = core.UNIT_ORDER[(unit_index + 1) % len(core.UNIT_ORDER)]
            expected_previous = (
                None if generation_index == 0 else core.CONTEXT_ORDER[generation_index - 1]
            )
            assert context.left_unit_id == expected_left, (seed, context.unit_id)
            assert context.right_unit_id == expected_right, (seed, context.unit_id)
            assert context.previous_unit_id == expected_previous, (seed, context.unit_id)
            assert set(context.committed_neighbours) <= {expected_left, expected_right}
            assert len(context.left_visible_envelope) == 4
            assert len(context.right_visible_envelope) == 4
            assert context.context_digest

        by_unit = {context.unit_id: context for context in plan.contexts}
        assert by_unit[core.UNIT_ORDER[0]].left_unit_id == core.UNIT_ORDER[-1]
        assert by_unit[core.UNIT_ORDER[-1]].right_unit_id == core.UNIT_ORDER[0]


def test_fixed_seed_replay_is_stable(recursive_v2_cases) -> None:
    p0, cases = recursive_v2_cases
    for seed, (first_plan, first_result) in cases.items():
        second_plan = core.plan_recursive(p0, seed)
        second_result = core.compile_plan(second_plan, p0)

        assert second_plan == first_plan
        assert second_plan.digest == first_plan.digest
        assert second_result == first_result
        assert second_result.geometry_hash == first_result.geometry_hash
        assert json.dumps(
            second_result.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ) == json.dumps(
            first_result.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


def test_validator_is_read_only_without_asserting_geometry_validity(
    recursive_v2_cases,
) -> None:
    p0, cases = recursive_v2_cases
    for seed, (_, result) in cases.items():
        before_hash = result.geometry_hash
        before_json = json.dumps(
            result.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

        validation = core.validate_result(p0, result)

        assert validation["diagnostics"]["check_only"] is True, seed
        assert validation["diagnostics"]["geometry_unchanged"] is True, seed
        assert validation["diagnostics"]["geometry_hash_before_check"] == before_hash
        assert validation["diagnostics"]["geometry_hash_after_check"] == before_hash
        assert validation["valid"] is (not validation["issues"])
        assert result.geometry_hash == before_hash
        assert json.dumps(
            result.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ) == before_json


def test_generation_policy_is_one_pass_and_planning_uses_no_validation_feedback(
    recursive_v2_cases,
    monkeypatch,
) -> None:
    p0, cases = recursive_v2_cases
    expected_policy = {
        "candidate_count": 1,
        "retry_count": 0,
        "resample_count": 0,
        "repair_count": 0,
        "validation_feedback_consumed": False,
    }
    for seed, (plan, _) in cases.items():
        assert plan.as_dict()["generation_policy"] == expected_policy, seed

    def forbidden_validation(*_args, **_kwargs):
        raise AssertionError("planning consumed validation feedback")

    monkeypatch.setattr(core, "validate_result", forbidden_validation)
    probe = core.plan_recursive(p0, core.DEV_SEEDS[0])
    assert probe.as_dict()["generation_policy"] == expected_policy
