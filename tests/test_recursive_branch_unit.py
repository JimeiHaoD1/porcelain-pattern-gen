from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = REPO_ROOT / "experiments" / "branch_unit"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

import recursive_branch_unit as core  # noqa: E402


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
def recursive_cases():
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    p0 = core.strip_profile(profile)
    cases = {}
    for seed in core.DEV_SEEDS:
        plan = core.plan_recursive(p0, seed)
        result = core.compile_plan(plan, p0)
        cases[seed] = (plan, result)
    return p0, cases


def _root_primary_id(plan: core.RecursivePlan, curve_id: str) -> str:
    primary_ids = {row.curve_id for row in plan.primaries}
    child_by_id = {row.curve_id: row for row in plan.descendants}
    current = curve_id
    visited: set[str] = set()
    while current not in primary_ids:
        assert current not in visited, f"cycle while tracing {curve_id}: {visited}"
        visited.add(current)
        assert current in child_by_id, f"orphan descendant {current}"
        current = child_by_id[current].parent_id
    return current


def test_recursive_topology_range_and_parent_graph(recursive_cases) -> None:
    _, cases = recursive_cases
    for seed, (plan, result) in cases.items():
        nodes = result.by_id
        level_counts = Counter(node.level for node in result.curves)
        assert level_counts[1] == 7, seed
        assert level_counts[2] == 12, seed
        assert 6 <= level_counts[3] <= 9, seed
        assert set(level_counts) == {1, 2, 3}, seed
        assert max(level_counts) <= plan.controls.max_depth == 3, seed

        primary_ids = {row.curve_id for row in plan.primaries}
        assert primary_ids == set(core.UNIT_ORDER), seed
        assert set(nodes) == primary_ids | {row.curve_id for row in plan.descendants}

        secondary_counts = Counter(
            row.parent_id for row in plan.descendants if row.level == 2
        )
        assert secondary_counts == Counter(core.SECONDARY_BUDGETS), seed

        for row in plan.descendants:
            assert row.curve_id in nodes, (seed, row.curve_id)
            assert row.parent_id in nodes, (seed, row.curve_id, row.parent_id)
            assert nodes[row.curve_id].level == row.level
            assert row.level == nodes[row.parent_id].level + 1
            assert _root_primary_id(plan, row.curve_id) in primary_ids


def test_tertiary_minimums_and_branching_caps(recursive_cases) -> None:
    _, cases = recursive_cases
    for seed, (plan, result) in cases.items():
        nodes = result.by_id
        metadata = plan.metadata_by_id
        tertiary_rows = [row for row in plan.descendants if row.level == 3]

        tertiary_per_secondary = Counter(row.parent_id for row in tertiary_rows)
        assert all(nodes[parent_id].level == 2 for parent_id in tertiary_per_secondary)
        assert all(
            count <= plan.controls.max_tertiary_per_secondary == 1
            for count in tertiary_per_secondary.values()
        ), seed

        tertiary_per_unit = Counter(metadata[row.curve_id].unit_id for row in tertiary_rows)
        assert all(tertiary_per_unit[unit_id] >= 1 for unit_id in core.FREE_UNITS), seed
        assert all(
            tertiary_per_unit[unit_id] <= plan.controls.max_tertiary_per_unit == 2
            for unit_id in core.UNIT_ORDER
        ), seed

        for row in tertiary_rows:
            meta = metadata[row.curve_id]
            assert meta.level == 3
            assert meta.parent_id == row.parent_id
            assert meta.unit_id == _root_primary_id(plan, row.curve_id)


def test_fixed_seed_replay_is_stable(recursive_cases) -> None:
    p0, cases = recursive_cases
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


def test_samples_lie_in_their_recorded_legal_ranges(recursive_cases) -> None:
    _, cases = recursive_cases
    for seed, (plan, _) in cases.items():
        sample_by_key = {row.key: row for row in plan.samples}
        assert len(sample_by_key) == len(plan.samples), seed
        assert plan.samples, seed

        for row in plan.samples:
            assert all(math.isfinite(value) for value in (row.low, row.high, row.u, row.value))
            assert row.low < row.high, (seed, row.key)
            assert 0.0 <= row.u <= 1.0, (seed, row.key)
            assert row.low <= row.value <= row.high, (seed, row.key)
            assert row.value == pytest.approx(
                row.low + (row.high - row.low) * row.u,
                abs=1e-12,
            )

        for meta in plan.node_metadata:
            assert set(meta.sample_keys) <= set(sample_by_key), (seed, meta.curve_id)


def test_validator_is_read_only_without_claiming_geometry_passes(recursive_cases) -> None:
    p0, cases = recursive_cases
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


def test_generation_policy_declares_one_pass_without_retry(recursive_cases, monkeypatch) -> None:
    p0, cases = recursive_cases
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
