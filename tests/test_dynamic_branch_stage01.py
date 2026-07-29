from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import freeze_fixed_baseline as freeze  # noqa: E402
import run_stage1_inputs as stage1  # noqa: E402
import strict_p0_v2 as p0  # noqa: E402


PROFILE_ROOT = (
    ROOT
    / "artifacts"
    / "runs"
    / "run57_reproduction"
    / "01_skeleton_analysis"
)


def _profile(prototype_id: str) -> dict:
    return json.loads(
        (PROFILE_ROOT / prototype_id / "skeleton_profile.json").read_text(encoding="utf-8")
    )


def _scaled_and_shifted(profile: dict, *, scale: float, offset_x: float) -> dict:
    transformed = copy.deepcopy(profile)
    source_width = float(profile["canvas"]["width"])
    source_height = float(profile["canvas"]["height"])
    x0, x1 = (float(value) for value in profile["repeat_x_range"])
    transformed["canvas"] = {
        "width": source_width * scale + offset_x,
        "height": source_height * scale,
    }
    transformed["repeat_x_range"] = [
        offset_x + x0 * scale,
        offset_x + x1 * scale,
    ]
    for sample in transformed["backbone"]["arc_samples"]:
        sample["point"] = [
            offset_x + float(sample["point"][0]) * scale,
            float(sample["point"][1]) * scale,
        ]
    for flower in transformed["flowers"]:
        flower["center"] = [
            offset_x + float(flower["center"][0]) * scale,
            float(flower["center"][1]) * scale,
        ]
        flower["rx"] = float(flower["rx"]) * scale
        flower["ry"] = float(flower["ry"]) * scale
    return transformed


def test_implementation_contract_locks_the_four_decisions() -> None:
    contract = json.loads(
        (DYNAMIC_DIR / "IMPLEMENTATION_CONTRACT.json").read_text(encoding="utf-8")
    )
    assert contract["fixed_baseline"]["strict_paired_comparison_prototypes"] == [
        "proto_sw_1_3"
    ]
    assert contract["fixed_baseline"]["cross_prototype_fixed_baseline_claimed"] is False
    assert contract["candidate_policy"]["raw_candidate_count_per_prototype_seed"] == 1
    assert contract["candidate_policy"]["validation_guided_retry_allowed"] is False
    assert contract["failure_policy"]["fatal_errors_are_diagnostic_labels"] is False
    assert contract["visual_acceptance"]["all_fifteen_candidates_preserved"] is True
    assert (
        contract["visual_acceptance"]["minimum_edited_visually_approved_per_prototype"]
        == 1
    )


def test_fixed_snapshot_hashes_sources_and_replay_are_stable() -> None:
    verified = freeze.verify_snapshot(check_sources=True)
    assert verified["snapshot_verified"] is True
    assert verified["files_checked"] >= 20
    assert verified["files_checked"] == verified["current_sources_checked"]
    replay = freeze.replay_snapshot()
    assert replay["replay_verified"] is True
    assert replay["seeds"] == [4101, 4102, 4103]


@pytest.mark.parametrize(
    ("prototype_id", "flower_count"),
    (
        ("proto_sw_1_1", 2),
        ("proto_sw_1_3", 2),
        ("proto_sw_2_3", 1),
        ("proto_sw_3_1", 1),
        ("proto_sw_3_2", 2),
    ),
)
def test_all_five_profiles_load_through_one_strict_contract(
    prototype_id: str,
    flower_count: int,
) -> None:
    strict = p0.load_strict_p0_v2(_profile(prototype_id))
    assert strict.prototype_id == prototype_id
    assert len(strict.flowers) == flower_count
    assert len(strict.backbone_samples) == 81
    assert strict.frame.local_repeat_x_range == (0.0, 1.0)
    assert strict.frame.local_canvas_bounds == (0.0, 0.0, 4.0, 1.1875)
    assert strict.as_dict()["input_contract"]["prototype_specific_topology_consumed"] is False


@pytest.mark.parametrize("prototype_id", stage1.PROTOTYPE_IDS)
def test_legacy_branch_fields_cannot_change_strict_p0(prototype_id: str) -> None:
    profile = _profile(prototype_id)
    clean = p0.load_strict_p0_v2(profile)
    poisoned = p0.load_strict_p0_v2(p0.poison_ignored_fields(profile))
    assert poisoned.digest == clean.digest
    assert poisoned.as_dict() == clean.as_dict()


def test_repeat_local_coordinates_are_scale_and_translation_invariant() -> None:
    profile = _profile("proto_sw_1_3")
    original = p0.load_strict_p0_v2(profile)
    transformed = p0.load_strict_p0_v2(
        _scaled_and_shifted(profile, scale=1.5, offset_x=123.0)
    )
    assert transformed.backbone_samples == original.backbone_samples
    assert transformed.flowers == original.flowers
    assert transformed.frame.local_repeat_x_range == (0.0, 1.0)
    assert transformed.frame.local_canvas_bounds[1:] == pytest.approx(
        original.frame.local_canvas_bounds[1:]
    )


def test_coordinate_mapping_round_trips_source_points() -> None:
    strict = p0.load_strict_p0_v2(_profile("proto_sw_3_2"))
    source_point = (203.25, 117.75)
    local = strict.frame.to_local_point(source_point)
    assert strict.frame.to_source_point(local) == pytest.approx(source_point)
    assert strict.frame.to_source_length(strict.frame.to_local_length(37.5)) == pytest.approx(
        37.5
    )


def test_optional_structure_protection_zones_use_the_same_local_frame() -> None:
    profile = _profile("proto_sw_2_3")
    profile["structure_protection_zones"] = [
        {
            "zone_id": "guard_ellipse",
            "role": "manual_structure_guard",
            "required": True,
            "geometry": {
                "type": "ellipse",
                "center": [128.0, 152.0],
                "rx": 16.0,
                "ry": 32.0,
            },
        },
        {
            "zone_id": "guard_polygon",
            "role": "seam_guard",
            "required": False,
            "geometry": {
                "type": "polygon",
                "points": [[0.0, 0.0], [8.0, 0.0], [8.0, 40.0], [0.0, 40.0]],
            },
        },
    ]
    strict = p0.load_strict_p0_v2(profile)
    ellipse, polygon = strict.structure_protection_zones
    assert ellipse.center == pytest.approx((0.5, 0.59375))
    assert ellipse.rx == pytest.approx(0.0625)
    assert ellipse.ry == pytest.approx(0.125)
    assert polygon.points[2] == pytest.approx((0.03125, 0.15625))


@pytest.mark.parametrize(
    ("mutator", "code"),
    (
        (lambda profile: profile.pop("flowers"), "missing_required_field"),
        (lambda profile: profile.update(flowers=[]), "missing_required_field"),
        (
            lambda profile: profile["backbone"]["arc_samples"][4].update(point=[math.nan, 1.0]),
            "non_finite_geometry",
        ),
        (
            lambda profile: profile.update(repeat_x_range=[10.0, 10.0]),
            "invalid_coordinate",
        ),
    ),
)
def test_fatal_input_contract_errors_are_not_diagnostic_labels(mutator, code: str) -> None:
    profile = _profile("proto_sw_1_1")
    mutator(profile)
    with pytest.raises(p0.InputContractError) as captured:
        p0.load_strict_p0_v2(profile)
    assert captured.value.code == code
    payload = captured.value.as_dict()
    assert payload["classification"] == "fatal_contract_error"
    assert not payload["code"].endswith("_issue")


def test_stage1_runner_materializes_only_input_contract_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage1"
    manifest = stage1.run(PROFILE_ROOT, output)
    assert manifest["prototype_ids"] == list(stage1.PROTOTYPE_IDS)
    assert manifest["prototype_count"] == 5
    assert manifest["stage_scope"]["not_started"] == [
        "prototype_analysis",
        "candidate_slots",
        "dynamic_branch_plan",
        "curve_compilation",
        "candidate_validation",
        "editor_v2",
    ]
    assert (output / "manifest.json").is_file()
    for prototype_id in stage1.PROTOTYPE_IDS:
        payload = json.loads(
            (output / prototype_id / "strict_p0_v2.json").read_text(encoding="utf-8")
        )
        assert payload["schema"] == p0.SCHEMA
        assert "growth_regions" not in payload
        assert "existing_guides" not in payload
        assert "dynamic_branch_plan" not in payload
