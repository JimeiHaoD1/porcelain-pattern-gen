from __future__ import annotations

import inspect
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "branch_unit"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

import l_v3_planner as planner  # noqa: E402
import run_l as harness  # noqa: E402
from l_core import Cubic, Curve, compile_primary, compile_unit, cross, dot, primary_summary, sub  # noqa: E402


PROFILE_PATH = (
    ROOT
    / "artifacts"
    / "runs"
    / "run57_reproduction"
    / "01_skeleton_analysis"
    / "proto_sw_1_3"
    / "skeleton_profile.json"
)


def _scene():
    return harness.scene_from_profile(json.loads(PROFILE_PATH.read_text(encoding="utf-8")))


def _fixture(child_count: int = 2, *, sweep_depth: float = 0.27):
    scene = _scene()
    spec = harness.TrialSpec("D", 0.725, sweep_depth, child_count, 700 + child_count)
    raw = {token: 0.5 for token in harness.RAW_TOKENS}
    budget = harness.build_budget(spec, raw, scene.max_clearance)
    primary = compile_primary(
        root=scene.anchor_point,
        parent_tangent=scene.anchor_tangent,
        outward=scene.growth_direction,
        target_length=budget.primary_length,
        sweep_depth=spec.sweep_depth,
        handle_u=raw["main.handle"],
        tip_u=raw["main.tip"],
        width=budget.primary_width,
    )
    return scene, raw, budget, primary


def _replace(raw: dict[str, float], key: str, value: float) -> dict[str, float]:
    changed = dict(raw)
    changed[key] = value
    return changed


def _signed_turn(curve: Curve) -> float:
    points = curve.points(96)
    previous = _unit(sub(points[1], points[0]))
    total = 0.0
    for start, end in zip(points[1:], points[2:]):
        current = _unit(sub(end, start))
        total += math.atan2(cross(previous, current), dot(previous, current))
        previous = current
    return total


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(*vector)
    return vector[0] / length, vector[1] / length


def _mirror_x(curve: Curve) -> Curve:
    axis = curve.root[0]

    def point(value: tuple[float, float]) -> tuple[float, float]:
        return 2.0 * axis - value[0], value[1]

    return Curve(
        curve_id=curve.curve_id,
        role=curve.role,
        parent_id=curve.parent_id,
        width=curve.width,
        target_length=curve.target_length,
        cubics=tuple(
            Cubic(p0=point(cubic.p0), p1=point(cubic.p1), p2=point(cubic.p2), p3=point(cubic.p3))
            for cubic in curve.cubics
        ),
        mount_fraction=curve.mount_fraction,
    )


def test_contract_interfaces_exclude_l0_scene_validation_and_trial_identity() -> None:
    assert tuple(inspect.signature(planner.plan_l1_joint).parameters) == ("primary", "raw", "budget")
    assert tuple(inspect.signature(planner.map_l0_independent).parameters) == ("raw", "budget")
    source = inspect.getsource(planner.plan_l1_joint)
    assert "trial_id" not in source
    assert "validate_unit" not in source
    assert "Scene" not in source


def test_joint_planner_is_deterministic_and_all_formal_trials_stay_in_shared_domains() -> None:
    scene = _scene()
    for spec in harness.TRIALS:
        raw = harness.materialize_raw_trial(spec)
        budget = harness.build_budget(spec, raw, scene.max_clearance)
        primary = compile_primary(
            root=scene.anchor_point,
            parent_tangent=scene.anchor_tangent,
            outward=scene.growth_direction,
            target_length=budget.primary_length,
            sweep_depth=spec.sweep_depth,
            handle_u=raw["main.handle"],
            tip_u=raw["main.tip"],
            width=budget.primary_width,
        )
        first = planner.plan_l1_joint(primary, raw, budget)
        second = planner.plan_l1_joint(primary, raw, budget)
        l0_children, l0_terminal, _ = planner.map_l0_independent(raw, budget)
        assert first.as_dict() == second.as_dict()
        assert abs(sum(child.target_length for child in first.children) - sum(budget.child_lengths)) < 1e-8
        for child in (*l0_children, *first.children):
            assert planner.MOUNT_MIN <= child.mount_fraction <= planner.MOUNT_MAX
            assert 0.20 * budget.primary_length <= child.target_length <= 0.33 * budget.primary_length
            assert planner.CHILD_ANGLE_MIN <= child.angle_degrees <= planner.CHILD_ANGLE_MAX
            assert planner.CHILD_BOW_MIN <= child.bow <= planner.CHILD_BOW_MAX
        assert planner.TERMINAL_ANGLE_MIN <= l0_terminal.angle_degrees <= planner.TERMINAL_ANGLE_MAX
        assert planner.TERMINAL_BOW_MIN <= l0_terminal.bow <= planner.TERMINAL_BOW_MAX
        assert planner.TERMINAL_ANGLE_MIN <= first.terminal.angle_degrees <= planner.TERMINAL_ANGLE_MAX
        assert planner.TERMINAL_BOW_MIN <= first.terminal.bow <= planner.TERMINAL_BOW_MAX


def test_center_and_gap_tokens_are_true_joint_mount_interventions() -> None:
    _, raw, budget, primary = _fixture(2)
    center_low = planner.plan_l1_joint(primary, _replace(raw, "child.1.mount", 0.25), budget)
    center_high = planner.plan_l1_joint(primary, _replace(raw, "child.1.mount", 0.75), budget)
    center_deltas = [
        center_high.children[index].mount_fraction - center_low.children[index].mount_fraction
        for index in range(2)
    ]
    assert center_deltas[0] > 0.0
    assert abs(center_deltas[0] - center_deltas[1]) < 1e-12

    gap_low = planner.plan_l1_joint(primary, _replace(raw, "child.2.mount", 0.25), budget)
    gap_high = planner.plan_l1_joint(primary, _replace(raw, "child.2.mount", 0.75), budget)
    low_mounts = [child.mount_fraction for child in gap_low.children]
    high_mounts = [child.mount_fraction for child in gap_high.children]
    assert high_mounts[0] < low_mounts[0]
    assert high_mounts[1] > low_mounts[1]
    assert abs(sum(low_mounts) - sum(high_mounts)) < 1e-12
    assert 10.0 <= (high_mounts[1] - high_mounts[0]) * budget.primary_length <= 18.0


def test_dominance_and_fan_tokens_couple_both_children_without_pool_sorting() -> None:
    _, raw, budget, primary = _fixture(2)
    dominance_low = planner.plan_l1_joint(primary, _replace(raw, "child.1.side", 0.25), budget)
    dominance_high = planner.plan_l1_joint(primary, _replace(raw, "child.1.side", 0.75), budget)
    low_lengths = [child.target_length for child in dominance_low.children]
    high_lengths = [child.target_length for child in dominance_high.children]
    assert high_lengths[0] > low_lengths[0]
    assert high_lengths[1] < low_lengths[1]
    assert abs(sum(high_lengths) - sum(low_lengths)) < 1e-12

    center_low = planner.plan_l1_joint(primary, _replace(raw, "child.1.angle", 0.25), budget)
    center_high = planner.plan_l1_joint(primary, _replace(raw, "child.1.angle", 0.75), budget)
    center_delta = [
        center_high.children[index].angle_degrees - center_low.children[index].angle_degrees
        for index in range(2)
    ]
    assert center_delta[0] > 0.0
    assert abs(center_delta[0] - center_delta[1]) < 1e-12

    spread_low = planner.plan_l1_joint(primary, _replace(raw, "child.2.angle", 0.25), budget)
    spread_high = planner.plan_l1_joint(primary, _replace(raw, "child.2.angle", 0.75), budget)
    low_angles = [child.angle_degrees for child in spread_low.children]
    high_angles = [child.angle_degrees for child in spread_high.children]
    assert high_angles[0] > low_angles[0]
    assert high_angles[1] < low_angles[1]
    assert abs(sum(high_angles) - sum(low_angles)) < 1e-12


def test_mirrored_primary_flips_children_and_terminal_together() -> None:
    _, raw, budget, primary = _fixture(2)
    original = planner.plan_l1_joint(primary, raw, budget)
    mirrored = planner.plan_l1_joint(_mirror_x(primary), raw, budget)
    assert mirrored.release_side == -original.release_side
    assert [child.turn_sign for child in mirrored.children] == [
        -child.turn_sign for child in original.children
    ]
    assert mirrored.terminal.turn_sign == -original.terminal.turn_sign
    for first, second in zip(original.children, mirrored.children):
        assert second.mount_fraction == first.mount_fraction
        assert second.target_length == first.target_length
        assert second.angle_degrees == first.angle_degrees
        assert second.bow == first.bow
        assert second.width == first.width
    assert mirrored.terminal.target_length == original.terminal.target_length
    assert mirrored.terminal.angle_degrees == original.terminal.angle_degrees
    assert mirrored.terminal.bow == original.terminal.bow
    assert mirrored.terminal.width == original.terminal.width

    original_unit = compile_unit(
        unit_id="mirror_original",
        primary=primary,
        child_specs=original.children,
        terminal_spec=original.terminal,
    )
    mirrored_primary = _mirror_x(primary)
    mirrored_unit = compile_unit(
        unit_id="mirror_reflected",
        primary=mirrored_primary,
        child_specs=mirrored.children,
        terminal_spec=mirrored.terminal,
    )
    axis = primary.root[0]
    for original_curve, mirrored_curve in zip(original_unit.curves, mirrored_unit.curves):
        for original_point, mirrored_point in zip(original_curve.points(96), mirrored_curve.points(96)):
            assert abs(mirrored_point[0] - (2.0 * axis - original_point[0])) < 1e-8
            assert abs(mirrored_point[1] - original_point[1]) < 1e-8


def test_l1_realized_sets_are_not_l0_value_pool_permutations() -> None:
    _, raw, budget, primary = _fixture(2)
    l0_children, _, _ = planner.map_l0_independent(raw, budget)
    l1 = planner.plan_l1_joint(primary, raw, budget)
    assert sorted(child.mount_fraction for child in l1.children) != sorted(
        child.mount_fraction for child in l0_children
    )
    assert sorted(child.target_length for child in l1.children) != sorted(
        child.target_length for child in l0_children
    )
    assert sorted(child.angle_degrees for child in l1.children) != sorted(
        child.angle_degrees for child in l0_children
    )


def test_every_l0_child2_token_cannot_change_child1_or_terminal() -> None:
    scene, raw, budget, _ = _fixture(2)
    spec = harness.TrialSpec("D", 0.725, 0.27, 2, 703)
    first_children, first_terminal, _ = planner.map_l0_independent(raw, budget)
    interventions = {
        "child.2.mount": 0.9,
        "child.2.length": 0.9,
        "child.2.angle": 0.9,
        "child.2.side": 0.1,
        "child.2.bow": 0.9,
    }
    for token, value in interventions.items():
        changed_raw = _replace(raw, token, value)
        changed_budget = harness.build_budget(spec, changed_raw, scene.max_clearance)
        second_children, second_terminal, _ = planner.map_l0_independent(changed_raw, changed_budget)
        assert first_children[0].as_dict() == second_children[0].as_dict(), token
        assert first_children[1].as_dict() != second_children[1].as_dict(), token
        assert first_terminal.as_dict() == second_terminal.as_dict(), token


def test_terminal_consumes_exit_fan_and_token_and_releases_actual_curve() -> None:
    scene, raw, budget, primary = _fixture(2)
    plan = planner.plan_l1_joint(primary, raw, budget)
    unit = compile_unit(
        unit_id="terminal_contract",
        primary=primary,
        child_specs=plan.children,
        terminal_spec=plan.terminal,
    )
    primary_turn = _signed_turn(primary)
    terminal_turn = _signed_turn(unit.terminal)
    assert (1 if terminal_turn > 0.0 else -1) == plan.release_side
    assert abs(primary_turn + terminal_turn) < abs(primary_turn)
    exit_tangent = primary.exit_tangent
    terminal_points = unit.terminal.points(96)
    assert all(
        dot(_unit(sub(end, start)), exit_tangent) > 0.0
        for start, end in zip(terminal_points, terminal_points[1:])
    )

    token_low = planner.plan_l1_joint(primary, _replace(raw, "terminal.turn", 0.1), budget)
    token_high = planner.plan_l1_joint(primary, _replace(raw, "terminal.turn", 0.9), budget)
    assert token_high.terminal.angle_degrees > token_low.terminal.angle_degrees

    fan_low = planner.plan_l1_joint(primary, _replace(raw, "child.1.angle", 0.1), budget)
    fan_high = planner.plan_l1_joint(primary, _replace(raw, "child.1.angle", 0.9), budget)
    assert fan_high.terminal.angle_degrees > fan_low.terminal.angle_degrees

    _, _, _, shallow_exit_primary = _fixture(2, sweep_depth=0.22)
    _, _, _, deep_exit_primary = _fixture(2, sweep_depth=0.32)
    shallow = planner.plan_l1_joint(shallow_exit_primary, raw, budget)
    deep = planner.plan_l1_joint(deep_exit_primary, raw, budget)
    assert shallow.trace["terminal_closure"]["q_exit"] != deep.trace["terminal_closure"]["q_exit"]
    assert shallow.terminal.angle_degrees != deep.terminal.angle_degrees


def test_compiled_terminal_invariants_cover_dev_and_all_twelve_formal_inputs() -> None:
    scene = _scene()
    inputs = []
    for child_count in (0, 1, 2):
        _, raw, budget, primary = _fixture(child_count)
        inputs.append((raw, budget, primary))
    for spec in harness.TRIALS:
        raw = harness.materialize_raw_trial(spec)
        budget = harness.build_budget(spec, raw, scene.max_clearance)
        primary = compile_primary(
            root=scene.anchor_point,
            parent_tangent=scene.anchor_tangent,
            outward=scene.growth_direction,
            target_length=budget.primary_length,
            sweep_depth=spec.sweep_depth,
            handle_u=raw["main.handle"],
            tip_u=raw["main.tip"],
            width=budget.primary_width,
        )
        inputs.append((raw, budget, primary))

    for index, (raw, budget, primary) in enumerate(inputs):
        plan = planner.plan_l1_joint(primary, raw, budget)
        unit = compile_unit(
            unit_id=f"terminal_matrix_{index}",
            primary=primary,
            child_specs=plan.children,
            terminal_spec=plan.terminal,
        )
        primary_turn = _signed_turn(primary)
        terminal_turn = _signed_turn(unit.terminal)
        assert (1 if terminal_turn > 0.0 else -1) == plan.release_side
        assert abs(primary_turn + terminal_turn) < abs(primary_turn)
        exit_tangent = primary.exit_tangent
        terminal_points = unit.terminal.points(96)
        assert all(
            dot(_unit(sub(end, start)), exit_tangent) > 0.0
            for start, end in zip(terminal_points, terminal_points[1:])
        )


def test_existing_compiler_validator_is_shared_and_check_only() -> None:
    scene, raw, budget, primary = _fixture(2)
    l0_children, l0_terminal, _ = planner.map_l0_independent(raw, budget)
    l1_plan = planner.plan_l1_joint(primary, raw, budget)
    l0 = compile_unit(unit_id="D2_L0", primary=primary, child_specs=l0_children, terminal_spec=l0_terminal)
    l1 = compile_unit(unit_id="D2_L1", primary=primary, child_specs=l1_plan.children, terminal_spec=l1_plan.terminal)
    l0_validation = harness.validate_unit(scene, l0, 2)
    l1_validation = harness.validate_unit(scene, l1, 2)
    assert l0.primary.as_dict() == l1.primary.as_dict()
    assert l0.semantic_curve_count == l1.semantic_curve_count
    assert l0.cubic_segment_count == l1.cubic_segment_count
    assert l0_validation.diagnostics["check_only"] is True
    assert l1_validation.diagnostics["check_only"] is True
