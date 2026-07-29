from __future__ import annotations

import json
import math
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = REPO_ROOT / "experiments" / "branch_unit"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

import multibranch_l as legacy  # noqa: E402
import recursive_branch_unit_v3 as core  # noqa: E402
import whole_local_branch as baseline  # noqa: E402
from l_core import angle_degrees, dist, sample_polyline, sub  # noqa: E402


PROFILE_PATH = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "run57_reproduction"
    / "01_skeleton_analysis"
    / "proto_sw_1_3"
    / "skeleton_profile.json"
)

EXPECTED_POLICY = {
    "candidate_count": 1,
    "retry_count": 0,
    "resample_count": 0,
    "repair_count": 0,
    "validation_feedback_consumed": False,
}


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _level_rows(plan, level: int):
    return tuple(row for row in plan.descendants if row.level == level)


def _level_nodes(result, level: int):
    return {
        node.curve.curve_id: node
        for node in result.curves
        if node.level == level
    }


def _root_unit_id(plan, curve_id: str) -> str:
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


def _sample_by_suffix(plan, meta, *suffixes: str):
    sample_by_key = {row.key: row for row in plan.samples}
    matches = [
        sample_by_key[key]
        for key in meta.sample_keys
        if key in sample_by_key and any(key.endswith(suffix) for suffix in suffixes)
    ]
    assert len(matches) == 1, (
        meta.curve_id,
        suffixes,
        meta.sample_keys,
    )
    return matches[0]


def _signed_parent_relative_chord_angle(result, row) -> float:
    parent = result.by_id[row.parent_id].curve
    child = result.by_id[row.curve_id].curve
    _, tangent = sample_polyline(parent.points(192), row.mount_fraction)
    chord = sub(child.tip, child.root)
    opening = angle_degrees(tangent, chord)
    cross = tangent[0] * chord[1] - tangent[1] * chord[0]
    return math.copysign(opening, cross if abs(cross) > 1e-12 else row.turn_sign)


def _circular_delta(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _symmetric_relative_difference(first: float, second: float) -> float:
    return abs(first - second) / max(0.5 * (first + second), 1e-12)


@pytest.fixture(scope="module")
def recursive_v3_cases():
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    p0 = core.strip_profile(profile)
    cases = {}
    failures = {}
    for seed in core.DEV_SEEDS:
        baseline_plan = baseline.plan_j0a(p0, seed)
        baseline_result = baseline.compile_plan(baseline_plan, p0)
        try:
            plan = core.plan_recursive(p0, seed)
        except core.PlanningFailure as error:
            failures[seed] = error
            continue
        result = core.compile_plan(plan, p0)
        cases[seed] = (baseline_plan, baseline_result, plan, result)
    return p0, cases, failures


def test_fixed_seed_attempts_retain_empty_domain_failures(recursive_v3_cases) -> None:
    _, cases, failures = recursive_v3_cases
    assert set(cases) | set(failures) == set(core.DEV_SEEDS)
    assert not (set(cases) & set(failures))
    assert set(failures) == {4101, 4103}
    assert set(cases) == {4102}
    assert all("empty joint parent/side domain" in str(error) for error in failures.values())


def test_contract_identifies_the_frozen_baseline_and_rule() -> None:
    assert core.BASELINE_PLAN_ID == baseline.PLAN_ID
    assert isinstance(core.RULE_ID, str) and core.RULE_ID
    assert tuple(core.DEV_SEEDS) == (4101, 4102, 4103)


def test_v23_level_1_and_level_2_plan_rows_are_byte_identical(
    recursive_v3_cases,
) -> None:
    _, cases, _ = recursive_v3_cases
    for seed, (baseline_plan, _, plan, _) in cases.items():
        assert _canonical_bytes([row.as_dict() for row in plan.primaries]) == (
            _canonical_bytes([row.as_dict() for row in baseline_plan.primaries])
        ), seed
        assert _canonical_bytes([row.as_dict() for row in _level_rows(plan, 2)]) == (
            _canonical_bytes([row.as_dict() for row in _level_rows(baseline_plan, 2)])
        ), seed


def test_v23_level_1_and_level_2_compiled_geometry_are_byte_identical(
    recursive_v3_cases,
) -> None:
    _, cases, _ = recursive_v3_cases
    for seed, (_, baseline_result, _, result) in cases.items():
        for level in (1, 2):
            expected = _level_nodes(baseline_result, level)
            observed = _level_nodes(result, level)
            assert set(observed) == set(expected), (seed, level)
            for curve_id in sorted(expected):
                assert _canonical_bytes(observed[curve_id].as_dict()) == (
                    _canonical_bytes(expected[curve_id].as_dict())
                ), (seed, level, curve_id)


def test_topology_is_exactly_7_12_and_6_to_9(recursive_v3_cases) -> None:
    _, cases, _ = recursive_v3_cases
    for seed, (_, _, plan, result) in cases.items():
        nodes = result.by_id
        level_counts = Counter(node.level for node in result.curves)
        assert level_counts[1] == 7, seed
        assert level_counts[2] == 12, seed
        assert 6 <= level_counts[3] <= 9, seed
        assert set(level_counts) == {1, 2, 3}, seed
        assert max(level_counts) == plan.controls.max_depth == 3, seed

        assert len(_level_rows(plan, 2)) == 12, seed
        assert 6 <= len(_level_rows(plan, 3)) <= 9, seed
        for row in plan.descendants:
            assert row.curve_id in nodes, (seed, row.curve_id)
            assert row.parent_id in nodes, (seed, row.curve_id, row.parent_id)
            assert nodes[row.curve_id].level == row.level
            assert row.level == nodes[row.parent_id].level + 1


def test_tertiaries_only_use_free_units_with_bounded_recursive_fanout(
    recursive_v3_cases,
) -> None:
    _, cases, _ = recursive_v3_cases
    flower_units = set(core.UNIT_ORDER) - set(core.FREE_UNITS)
    assert flower_units == {"primary_4_flower_1", "primary_5_flower_2"}

    for seed, (_, _, plan, result) in cases.items():
        tertiary_rows = _level_rows(plan, 3)
        per_parent = Counter(row.parent_id for row in tertiary_rows)
        per_unit = Counter(_root_unit_id(plan, row.curve_id) for row in tertiary_rows)

        assert set(per_unit) == set(core.FREE_UNITS), seed
        assert not (set(per_unit) & flower_units), seed
        assert all(1 <= per_unit[unit_id] <= 2 for unit_id in core.FREE_UNITS), seed
        assert all(count == 1 for count in per_parent.values()), seed

        for row in tertiary_rows:
            assert result.by_id[row.parent_id].level == 2, (seed, row.curve_id)
            assert row.level == 3
            meta = plan.metadata_by_id[row.curve_id]
            assert meta.level == 3
            assert meta.parent_id == row.parent_id
            assert meta.unit_id == _root_unit_id(plan, row.curve_id)


def test_every_tertiary_parameter_is_sampled_once_inside_the_final_legal_domain(
    recursive_v3_cases,
) -> None:
    _, cases, _ = recursive_v3_cases
    for seed, (_, _, plan, result) in cases.items():
        sample_by_key = {row.key: row for row in plan.samples}
        assert len(sample_by_key) == len(plan.samples), seed

        for sample in plan.samples:
            assert all(
                math.isfinite(value)
                for value in (sample.low, sample.high, sample.u, sample.value)
            ), (seed, sample.key)
            assert sample.low < sample.high, (seed, sample.key)
            assert 0.0 <= sample.u <= 1.0, (seed, sample.key)
            assert sample.low <= sample.value <= sample.high, (seed, sample.key)
            assert sample.value == pytest.approx(
                sample.low + (sample.high - sample.low) * sample.u,
                abs=1e-12,
            ), (seed, sample.key)

        for row in _level_rows(plan, 3):
            meta = plan.metadata_by_id[row.curve_id]
            assert meta.sample_keys
            assert len(meta.sample_keys) == len(set(meta.sample_keys))
            assert set(meta.sample_keys) <= set(sample_by_key), (seed, row.curve_id)

            parent_length = result.by_id[row.parent_id].curve.length
            maximum_mount = min(0.72, 1.0 - max(8.0, 0.20 * parent_length) / parent_length)
            chord_low = max(12.0, 0.48 * parent_length)
            chord_high = min(34.0, 0.72 * parent_length)

            mount_sample = _sample_by_suffix(plan, meta, ".mount_fraction")
            entry_sample = _sample_by_suffix(plan, meta, ".entry_opening_degrees")
            opening_sample = _sample_by_suffix(
                plan,
                meta,
                ".opening_angle_degrees",
                ".chord_opening_degrees",
            )
            chord_sample = _sample_by_suffix(plan, meta, ".chord_length")
            handle_sample = _sample_by_suffix(plan, meta, ".handle_ratio")
            release_sample = _sample_by_suffix(plan, meta, ".exit_release_degrees")

            assert 0.28 - 1e-12 <= mount_sample.low
            assert mount_sample.high <= maximum_mount + 1e-12
            assert 34.0 - 1e-12 <= entry_sample.low
            assert entry_sample.high <= 60.0 + 1e-12
            assert 42.0 - 1e-12 <= opening_sample.low
            assert opening_sample.high <= 78.0 + 1e-12
            assert chord_low - 1e-12 <= chord_sample.low
            assert chord_sample.high <= chord_high + 1e-12

            assert mount_sample.value == pytest.approx(row.mount_fraction)
            assert entry_sample.value == pytest.approx(row.entry_opening_degrees)
            assert opening_sample.value == pytest.approx(row.opening_angle_degrees)
            assert chord_sample.value == pytest.approx(row.chord_length)
            assert handle_sample.value == pytest.approx(row.handle_ratio)
            assert release_sample.value == pytest.approx(row.exit_release_degrees)


def test_tertiary_compiled_geometry_obeys_attachment_direction_length_and_bends(
    recursive_v3_cases,
) -> None:
    _, cases, _ = recursive_v3_cases
    for seed, (_, _, plan, result) in cases.items():
        for row in _level_rows(plan, 3):
            parent = result.by_id[row.parent_id].curve
            child = result.by_id[row.curve_id].curve
            expected_root, parent_tangent = sample_polyline(
                parent.points(192),
                row.mount_fraction,
            )
            chord = dist(child.root, child.tip)
            entry_opening = angle_degrees(parent_tangent, child.entry_tangent)
            chord_opening = angle_degrees(parent_tangent, sub(child.tip, child.root))
            sagitta = baseline._normalized_sagitta(child)  # noqa: SLF001
            bend_audit = legacy.bend_audit(child)

            assert row.target_boundary is None, (seed, row.curve_id)
            assert row.target_point is None, (seed, row.curve_id)
            assert row.terminal_tangent is None, (seed, row.curve_id)
            assert dist(child.root, expected_root) <= 1e-6, (seed, row.curve_id)
            assert 0.28 - 1e-9 <= row.mount_fraction <= 0.72 + 1e-9
            assert (1.0 - row.mount_fraction) * parent.length + 1e-6 >= max(
                8.0,
                0.20 * parent.length,
            ), (seed, row.curve_id)

            assert 34.0 - 0.5 <= row.entry_opening_degrees <= 60.0 + 0.5
            assert entry_opening == pytest.approx(row.entry_opening_degrees, abs=0.5)
            assert 34.0 - 0.5 <= entry_opening <= 60.0 + 0.5
            assert 42.0 - 0.5 <= row.opening_angle_degrees <= 78.0 + 0.5
            assert chord_opening == pytest.approx(row.opening_angle_degrees, abs=0.5)
            assert 42.0 - 0.5 <= chord_opening <= 78.0 + 0.5

            assert chord == pytest.approx(row.chord_length, abs=1e-6)
            assert 12.0 - 1e-6 <= chord <= 34.0 + 1e-6
            assert 0.48 * parent.length - 1e-6 <= chord
            assert chord <= 0.72 * parent.length + 1e-6
            assert child.length < 0.82 * parent.length + 1e-6

            assert len(child.cubics) <= 2
            assert int(bend_audit["bend_count"]) <= 2
            assert int(bend_audit["curvature_sign_reversal_count"]) <= 1
            assert 0.055 - 1e-6 <= sagitta <= 0.20 + 1e-6
            assert not baseline._self_intersects(child.points(192))  # noqa: SLF001
            assert all(
                dist(cubic.p0, cubic.p1) > 1e-8
                and dist(cubic.p2, cubic.p3) > 1e-8
                for cubic in child.cubics
            )


def test_fixed_seed_replay_is_byte_and_geometry_stable(recursive_v3_cases) -> None:
    p0, cases, failures = recursive_v3_cases
    for seed, (_, _, first_plan, first_result) in cases.items():
        second_plan = core.plan_recursive(p0, seed)
        second_result = core.compile_plan(second_plan, p0)

        assert second_plan == first_plan
        assert second_plan.digest == first_plan.digest
        assert second_result == first_result
        assert second_result.geometry_hash == first_result.geometry_hash
        assert _canonical_bytes(second_plan.as_dict()) == _canonical_bytes(
            first_plan.as_dict()
        )
        assert _canonical_bytes(second_result.as_dict()) == _canonical_bytes(
            first_result.as_dict()
        )
    for seed, first_error in failures.items():
        with pytest.raises(core.PlanningFailure) as replay_error:
            core.plan_recursive(p0, seed)
        assert str(replay_error.value) == str(first_error)


def test_generation_policy_is_one_pass_and_does_not_consume_validation(
    recursive_v3_cases,
    monkeypatch,
) -> None:
    p0, cases, _ = recursive_v3_cases
    for seed, (_, _, plan, _) in cases.items():
        assert plan.as_dict()["generation_policy"] == EXPECTED_POLICY, seed

    def forbidden_validation(*_args, **_kwargs):
        raise AssertionError("planning consumed validation feedback")

    monkeypatch.setattr(core, "validate_result", forbidden_validation)
    successful_seed = next(iter(cases))
    probe = core.plan_recursive(p0, successful_seed)
    assert probe.as_dict()["generation_policy"] == EXPECTED_POLICY


def test_validator_is_strictly_read_only(recursive_v3_cases) -> None:
    p0, cases, _ = recursive_v3_cases
    for seed, (_, _, _, result) in cases.items():
        before_hash = result.geometry_hash
        before_bytes = _canonical_bytes(result.as_dict())

        validation = core.validate_result(p0, result)

        assert validation["diagnostics"]["check_only"] is True, seed
        assert validation["diagnostics"]["geometry_unchanged"] is True, seed
        assert validation["diagnostics"]["geometry_hash_before_check"] == before_hash
        assert validation["diagnostics"]["geometry_hash_after_check"] == before_hash
        assert validation["valid"] is (not validation["issues"])
        assert result.geometry_hash == before_hash
        assert _canonical_bytes(result.as_dict()) == before_bytes


def test_three_seed_variation_gate_is_blocked_by_retained_planning_failures(
    recursive_v3_cases,
) -> None:
    _, cases, failures = recursive_v3_cases
    assert len(cases) < len(core.DEV_SEEDS)
    assert failures
    assert set(cases) == {4102}
    assert set(failures) == {4101, 4103}
