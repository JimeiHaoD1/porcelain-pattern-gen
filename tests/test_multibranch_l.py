from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = REPO_ROOT / "experiments" / "branch_unit"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

import multibranch_l as core  # noqa: E402
import run_multibranch_l_dev as runner  # noqa: E402


def _profile() -> dict[str, object]:
    return json.loads(runner.SOURCE_PROFILE.read_text(encoding="utf-8"))


def _p0() -> core.StrippedP0:
    return core.strip_profile(_profile())


def test_stripped_p0_is_exactly_backbone_flowers_and_bounds() -> None:
    p0 = _p0()
    payload = p0.as_dict()
    assert p0.policy_id == core.POLICY_ID
    assert payload["existing_guides"] == []
    assert payload["backbone"]["source_path_order"] == [0, 1, 2, 3, 4]
    assert len(payload["flowers"]) == 2
    assert payload["repeat_x_range"] == [0.0, 256.0]
    assert payload["canvas"] == {"width": 1024.0, "height": 304.0}
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in ("growth_regions", "space_samples", "region_graph", "guide_id"):
        assert forbidden not in serialized


def test_ignored_branch_fields_cannot_change_input() -> None:
    proof = core.profile_intervention_proof(_profile())
    assert proof["identical"] is True
    assert proof["original_digest"] == proof["poisoned_ignored_fields_digest"]


def test_l0_token_intervention_is_row_local() -> None:
    p0 = _p0()
    tokens = core.materialize_tokens(2505, 5)
    for changed_index in range(5):
        before, after = core.l0_token_intervention(p0, tokens, changed_index)
        changed_roles = {
            left.role.role_id
            for left, right in zip(before.intents, after.intents)
            if left.as_dict() != right.as_dict()
        }
        assert changed_roles <= {before.intents[changed_index].role.role_id}


def test_l1_free_mounts_are_one_center_gap_mapping() -> None:
    p0 = _p0()
    for count, seed in runner.DEV_CASES:
        plan = core.plan_l1_joint(p0, core.materialize_tokens(seed, count))
        free = sorted(intent.mount_s for intent in plan.intents if intent.role.kind == "free")
        gaps = [right - left for left, right in zip(free, free[1:])]
        if gaps:
            assert max(gaps) - min(gaps) <= 1e-12
            assert abs(gaps[0] - float(plan.trace["gap"])) <= 1e-10
        assert abs(sum(free) / len(free) - float(plan.trace["center"])) <= 1e-10
        assert plan.trace["generation_policy"]["candidate_count"] == 1
        assert plan.trace["generation_policy"]["repair_count"] == 0


def test_development_cases_have_four_or_five_generated_first_level_branches() -> None:
    p0 = _p0()
    for count, seed in runner.DEV_CASES:
        case = core.build_case(p0, count, seed)
        for variant in ("L0", "L1"):
            branch_set = case[variant]["branch_set"]
            assert len(branch_set.branches) == count
            assert sum(branch.role.kind == "flower" for branch in branch_set.branches) == 2
            assert sum(branch.role.kind == "free" for branch in branch_set.branches) == count - 2
            assert all(branch.curve.parent_id == "backbone" for branch in branch_set.branches)
            assert all(branch.compiler_trace["source"] == "program_generated" for branch in branch_set.branches)
            assert all(len(branch.curve.cubics) <= 2 for branch in branch_set.branches)


def test_every_development_branch_has_at_most_two_measured_bends() -> None:
    p0 = _p0()
    for count, seed in runner.DEV_CASES:
        case = core.build_case(p0, count, seed)
        for variant in ("L0", "L1"):
            diagnostics = case[variant]["validation"]["diagnostics"]["branches"]
            assert all(item["bend_audit"]["bend_count"] <= 2 for item in diagnostics)
            assert all(item["bend_audit"]["curvature_sign_reversal_count"] <= 1 for item in diagnostics)


def test_joint_development_outputs_are_structurally_valid_and_fair() -> None:
    p0 = _p0()
    for count, seed in runner.DEV_CASES:
        case = core.build_case(p0, count, seed)
        assert case["L1"]["validation"]["valid"] is True
        assert case["fairness"]["budget_match"] is True
        assert case["fairness"]["total_length_symmetric_delta"] <= 0.002
        assert case["fairness"]["vector_ink_symmetric_delta"] <= 0.002


def test_rendered_svg_contains_only_program_branches(tmp_path: Path) -> None:
    p0 = _p0()
    case = core.build_case(p0, 5, 2505)
    output = tmp_path / "joint.svg"
    runner.render_svg(p0, case["L1"]["branch_set"], output)
    svg = output.read_text(encoding="utf-8")
    assert svg.count('data-source="program_generated"') == 5
    for forbidden in ("guide_", "#d5d9dd", "#ff7800", "#00ff00", "#007800"):
        assert forbidden not in svg

