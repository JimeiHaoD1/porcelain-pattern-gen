from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "branch_unit"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

import run_l  # noqa: E402


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
    return run_l.scene_from_profile(json.loads(PROFILE_PATH.read_text(encoding="utf-8")))


def test_preregistered_matrix_is_exactly_twelve_with_eight_child_positive() -> None:
    assert [trial.trial_id for trial in run_l.TRIALS] == [f"L{index:02d}" for index in range(1, 13)]
    assert len(run_l.TRIALS) == 12
    assert sum(trial.child_count == 0 for trial in run_l.TRIALS) == 4
    assert sum(trial.child_count >= 1 for trial in run_l.TRIALS) == 8
    assert {(trial.length_ratio, trial.sweep_depth) for trial in run_l.TRIALS} == {
        (0.65, 0.22),
        (0.65, 0.32),
        (0.80, 0.22),
        (0.80, 0.32),
    }


def test_named_random_stream_is_token_stable_and_mapper_boundary_is_structural() -> None:
    trial = run_l.TRIALS[2]
    first = run_l.materialize_raw_trial(trial)
    second = run_l.materialize_raw_trial(trial)
    assert first == second
    assert tuple(first) == run_l.RAW_TOKENS
    assert len(set(first.values())) == len(first)
    assert "summary" not in inspect.signature(run_l.map_l0).parameters
    assert "summary" in inspect.signature(run_l.map_l1).parameters


def test_l0_child_lengths_are_independent_before_shared_budget_freeze() -> None:
    scene = _scene()
    trial = run_l.TRIALS[2]
    raw = run_l.materialize_raw_trial(trial)
    first = run_l.build_budget(trial, raw, scene.max_clearance)
    changed = dict(raw)
    changed["child.2.length"] = 1.0 - changed["child.2.length"]
    second = run_l.build_budget(trial, changed, scene.max_clearance)
    assert first.child_lengths[0] == second.child_lengths[0]
    assert first.child_lengths[1] != second.child_lengths[1]


def test_all_pairs_share_primary_topology_widths_and_budget() -> None:
    scene = _scene()
    for trial in run_l.TRIALS:
        case = run_l.build_trial(scene, trial)
        l0 = case["L0"]["unit"]
        l1 = case["L1"]["unit"]
        fairness = case["fairness"]
        assert l0.primary.as_dict() == l1.primary.as_dict()
        assert len(l0.primary.cubics) == len(l1.primary.cubics) == 2
        assert l0.semantic_curve_count == l1.semantic_curve_count == 2 + trial.child_count
        assert l0.cubic_segment_count == l1.cubic_segment_count == 3 + trial.child_count
        assert fairness["primary_control_points_equal"] is True
        assert fairness["semantic_curve_count_equal"] is True
        assert fairness["cubic_segment_count_equal"] is True
        assert fairness["role_widths_equal"] is True
        assert fairness["total_length_symmetric_delta"] <= 0.03
        assert fairness["vector_ink_symmetric_delta"] <= 0.03
        assert fairness["raster_ink_symmetric_delta"] <= 0.05
        assert fairness["budget_match"] is True
        assert case["L0"]["validation"]["diagnostics"]["check_only"] is True
        assert case["L1"]["validation"]["diagnostics"]["check_only"] is True
        assert case["L0"]["validation"]["diagnostics"]["geometry_hash_after_check"] == l0.geometry_hash
        assert case["L1"]["validation"]["diagnostics"]["geometry_hash_after_check"] == l1.geometry_hash

        l0_children = case["L0"]["mapping"]["children"]
        l1_children = case["L1"]["mapping"]["children"]
        for field in ("mount_fraction", "target_length", "angle_degrees", "bow"):
            assert sorted(child[field] for child in l0_children) == sorted(child[field] for child in l1_children)
        assert len(case["primary_summary"]["turn_samples"]) > 100
        assert len(case["L1"]["mapping"]["primary_local_turns_at_mounts"]) == trial.child_count


def test_primary_svg_serialization_keeps_both_cubics(tmp_path: Path) -> None:
    scene = _scene()
    case = run_l.build_trial(scene, run_l.TRIALS[0])
    output = tmp_path / "unit.svg"
    run_l.render_unit_svg(scene, case["L0"]["unit"], output)
    text = output.read_text(encoding="utf-8")
    primary_line = next(
        line
        for line in text.splitlines()
        if 'stroke="#111820"' in line and 'stroke-width="3.000"' in line
    )
    assert primary_line.count("C ") == 2
