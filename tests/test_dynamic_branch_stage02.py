from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import prototype_analysis as pa  # noqa: E402
import render_prototype_analysis as render  # noqa: E402
import run_stage1_inputs as stage1  # noqa: E402
import run_stage2_analysis as stage2  # noqa: E402
import strict_p0_v2 as p0  # noqa: E402


PROFILE_ROOT = (
    ROOT
    / "artifacts"
    / "runs"
    / "run57_reproduction"
    / "01_skeleton_analysis"
)
STAGE1_ROOT = ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"


def _profile(prototype_id: str) -> dict:
    return json.loads(
        (PROFILE_ROOT / prototype_id / "skeleton_profile.json").read_text(
            encoding="utf-8"
        )
    )


def _strict(prototype_id: str) -> p0.StrictP0V2:
    return p0.load_strict_p0_v2(_profile(prototype_id))


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


@pytest.mark.parametrize("prototype_id", stage2.PROTOTYPE_IDS)
def test_materialized_stage1_artifacts_round_trip(prototype_id: str) -> None:
    payload = json.loads(
        (STAGE1_ROOT / prototype_id / "strict_p0_v2.json").read_text(
            encoding="utf-8"
        )
    )
    strict = p0.load_materialized_strict_p0_v2(payload)
    assert strict.as_dict() == payload
    assert strict.digest == next(
        row["strict_p0_digest"]
        for row in json.loads(
            (STAGE1_ROOT / "manifest.json").read_text(encoding="utf-8")
        )["profiles"]
        if row["prototype_id"] == prototype_id
    )


@pytest.mark.parametrize("prototype_id", stage2.PROTOTYPE_IDS)
def test_all_five_prototypes_have_complete_planner_free_analysis(
    prototype_id: str,
) -> None:
    strict = _strict(prototype_id)
    analysis = pa.analyze_prototype(strict)
    assert analysis["schema"] == pa.SCHEMA
    assert analysis["strict_p0_digest"] == strict.digest
    assert analysis["review"]["status"] == "analysis_pending_review"
    assert analysis["stage_boundary"] == {
        "stage_2_prototype_analysis_complete": True,
        "stage_3_candidate_slots_started": False,
        "dynamic_branch_plan_present": False,
        "curve_compilation_present": False,
    }
    assert len(analysis["flowers"]) == len(strict.flowers)
    assert analysis["backbone"]["extrema"]
    assert analysis["backbone"]["long_slopes"]
    assert analysis["space_analysis"]["continuous_blank_regions"]
    assert analysis["candidate_l1_attachment_regions"]
    assert {
        row["side_id"] for row in analysis["space_analysis"]["probes"]
    } == {"left_normal", "right_normal"}
    assert all(
        row["planner_selected"] is False
        for row in analysis["candidate_l1_attachment_regions"]
    )


@pytest.mark.parametrize("prototype_id", stage2.PROTOTYPE_IDS)
def test_legacy_fields_cannot_change_stage2_analysis(prototype_id: str) -> None:
    profile = _profile(prototype_id)
    clean = pa.analyze_prototype(p0.load_strict_p0_v2(profile))
    poisoned = pa.analyze_prototype(
        p0.load_strict_p0_v2(p0.poison_ignored_fields(profile))
    )
    assert poisoned["analysis_core_digest"] == clean["analysis_core_digest"]
    assert poisoned["analysis_digest"] == clean["analysis_digest"]
    assert poisoned == clean


def test_analysis_is_repeat_local_scale_and_translation_invariant() -> None:
    profile = _profile("proto_sw_1_3")
    transformed = _scaled_and_shifted(profile, scale=1.5, offset_x=123.0)
    original_analysis = pa.analyze_prototype(p0.load_strict_p0_v2(profile))
    transformed_analysis = pa.analyze_prototype(
        p0.load_strict_p0_v2(transformed)
    )
    assert (
        transformed_analysis["analysis_core_digest"]
        == original_analysis["analysis_core_digest"]
    )
    # The complete artifact remains traceable to its specific StrictP0 source
    # frame, while the geometry-only analysis is frame invariant.
    assert transformed_analysis["strict_p0_digest"] != original_analysis["strict_p0_digest"]


@pytest.mark.parametrize("prototype_id", stage2.PROTOTYPE_IDS)
def test_repeat_seam_is_periodic_and_not_a_horizontal_wall(
    prototype_id: str,
) -> None:
    analysis = pa.analyze_prototype(_strict(prototype_id))
    seam = analysis["repeat_seam"]
    assert seam["ghost_offsets"] == [-1, 1]
    assert seam["horizontal_repeat_is_not_a_wall"] is True
    assert seam["space_probes_use_periodic_backbone_copies"] is True
    assert seam["position_gap"] == pytest.approx(0.0)
    assert all(
        row["blocked_by"] != "canvas_horizontal_boundary"
        for row in analysis["space_analysis"]["probes"]
    )


def test_explicit_protection_zone_becomes_a_prohibited_region() -> None:
    profile = _profile("proto_sw_2_3")
    profile["structure_protection_zones"] = [
        {
            "zone_id": "manual_guard",
            "role": "manual_structure_guard",
            "required": True,
            "geometry": {
                "type": "ellipse",
                "center": [128.0, 152.0],
                "rx": 200.0,
                "ry": 140.0,
            },
        }
    ]
    analysis = pa.analyze_prototype(p0.load_strict_p0_v2(profile))
    prohibited = analysis["space_analysis"]["prohibited_regions"]
    assert any(
        row["region_id"] == "manual_guard"
        and row["source"] == "strict_p0_explicit_zone"
        for row in prohibited
    )
    assert any(
        row["blocked_by"] == "structure_protection_zone"
        for row in analysis["space_analysis"]["probes"]
    )


def test_renderer_emits_all_review_layers(tmp_path: Path) -> None:
    analysis = pa.analyze_prototype(_strict("proto_sw_3_1"))
    svg = tmp_path / "analysis.svg"
    png = tmp_path / "analysis.png"
    render.render_svg(analysis, svg)
    render.render_png(analysis, png)
    svg_text = svg.read_text(encoding="utf-8")
    for layer in (
        "ghost-repeats",
        "continuous-blank-regions",
        "prohibited-regions",
        "space-probes",
        "flower-relations",
        "backbone",
        "long-slopes",
        "crowded-regions",
        "candidate-l1-regions",
        "child-continuation-space",
        "backbone-landmarks",
    ):
        assert f'data-layer="{layer}"' in svg_text
    assert "No slots. No plan. No curves." in svg_text
    assert png.stat().st_size > 25_000


def test_stage2_runner_materializes_only_analysis_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage2"
    manifest = stage2.run(STAGE1_ROOT, output)
    assert manifest["prototype_ids"] == list(stage2.PROTOTYPE_IDS)
    assert manifest["review_gate"]["status"] == "analysis_pending_review"
    assert manifest["review_gate"]["stage_3_unlocked"] is False
    assert manifest["input_isolation"]["source_profiles_opened_by_stage2"] is False
    assert manifest["stage_scope"]["not_started"] == [
        "candidate_slots",
        "dynamic_branch_plan",
        "curve_compilation",
        "candidate_validation",
        "editor_v2",
    ]
    assert (output / "prototype_analysis_contact_sheet.png").is_file()
    for prototype_id in stage2.PROTOTYPE_IDS:
        case_dir = output / prototype_id
        assert {path.name for path in case_dir.iterdir()} == {
            "prototype_analysis.json",
            "prototype_analysis.svg",
            "prototype_analysis.png",
            "analysis_review.json",
        }
        review = json.loads(
            (case_dir / "analysis_review.json").read_text(encoding="utf-8")
        )
        assert review["status"] == "analysis_pending_review"
        assert review["stage_3_unlocked"] is False
