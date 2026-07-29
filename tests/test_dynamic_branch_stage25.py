from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import branch_morphology_spec as morphology  # noqa: E402
import record_stage25_approval as approval  # noqa: E402
import render_branch_morphology as render  # noqa: E402
import run_stage25_morphology as stage25  # noqa: E402
import strict_p0_v2 as p0  # noqa: E402


STAGE2_ROOT = ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
SOURCE_IMAGE_ROOT = ROOT / "artifacts" / "analysis" / "prototype_source_images"
CONTRACT_PATH = DYNAMIC_DIR / "MORPHOLOGY_CONTRACT.json"

EXPECTED_FAMILIES = {
    "proto_sw_1_1": "SW-1_valley_filling",
    "proto_sw_1_3": "SW-1_valley_filling",
    "proto_sw_2_3": "SW-2_axis_penetrating",
    "proto_sw_3_1": "SW-3_tangent_terminal",
    "proto_sw_3_2": "SW-3_tangent_terminal",
}


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _analysis(prototype_id: str) -> dict:
    return json.loads(
        (
            STAGE2_ROOT
            / prototype_id
            / "prototype_analysis.json"
        ).read_text(encoding="utf-8")
    )


def _profile(prototype_id: str) -> dict:
    contract = morphology.load_morphology_contract(
        _contract(),
        expected_prototype_ids=stage25.PROTOTYPE_IDS,
    )
    return morphology.materialize_branch_morphology_spec(
        _analysis(prototype_id),
        contract,
    ).as_dict()


def test_contract_has_two_separate_classification_axes() -> None:
    contract = morphology.load_morphology_contract(
        CONTRACT_PATH,
        expected_prototype_ids=stage25.PROTOTYPE_IDS,
    )
    axes = contract["classification_axes"]
    assert axes["pattern_skeleton_class"]["consumed_by_stage_3_v1"] is False
    assert axes["flower_branch_relation"]["consumed_by_stage_3_v1"] is True
    assert set(contract["families"]) == {
        "SW-1_valley_filling",
        "SW-2_axis_penetrating",
        "SW-3_tangent_terminal",
    }
    assert contract["policies"]["legacy_unit_type_consumed"] is False
    assert contract["policies"]["source_branch_geometry_consumed"] is False


@pytest.mark.parametrize(
    ("prototype_id", "family_id"),
    EXPECTED_FAMILIES.items(),
)
def test_all_five_profiles_bind_family_and_keep_stage3_locked(
    prototype_id: str,
    family_id: str,
) -> None:
    analysis = _analysis(prototype_id)
    profile = _profile(prototype_id)
    assert profile["schema"] == morphology.PROFILE_SCHEMA
    assert profile["source_stage2_analysis_digest"] == analysis["analysis_digest"]
    assert (
        profile["classification"]["flower_branch_relation"]["family_id"]
        == family_id
    )
    assert profile["review"]["status"] == "morphology_pending_review"
    assert profile["generation_boundary"] == {
        "strict_p0_modified": False,
        "source_branch_geometry_copied": False,
        "evidence_counts_are_generation_targets": False,
        "candidate_slots_present": False,
        "dynamic_branch_plan_present": False,
        "curve_geometry_present": False,
        "visual_guides_are_non_selecting_semantic_annotations": True,
    }
    assert (
        profile["instance_priors"]["source_observation_counts"][
            "flower_anchor_count"
        ]
        == len(analysis["flowers"])
    )


def test_same_family_instances_retain_distinct_density_and_rhythm_priors() -> None:
    dense = _profile("proto_sw_1_1")["instance_priors"]
    sparse = _profile("proto_sw_1_3")["instance_priors"]
    assert dense["density_class"] == "dense"
    assert sparse["density_class"] == "sparse"
    assert dense["side_rhythm"] != sparse["side_rhythm"]
    assert (
        dense["source_observation_counts"]["branch_guide_count"],
        sparse["source_observation_counts"]["branch_guide_count"],
    ) == (27, 3)
    assert dense["count_usage"] == "evidence_prior_not_fixed_generation_target"


def test_strict_p0_contract_remains_geometry_only() -> None:
    fields = set(p0.StrictP0V2.__dataclass_fields__)
    assert "morphology_family" not in fields
    assert "node_rule" not in fields
    assert "unit_type" not in fields
    assert not any("morphology" in path for path in p0.CONSUMED_PROFILE_PATHS)
    assert not any("node_rule" in path for path in p0.CONSUMED_PROFILE_PATHS)


def test_contract_rejects_legacy_unit_type_as_control_input() -> None:
    poisoned = copy.deepcopy(_contract())
    poisoned["instances"]["proto_sw_2_3"]["unit_type"] = "two_flower_unit"
    with pytest.raises(
        morphology.MorphologyContractError,
        match="legacy unit_type is not a morphology input",
    ):
        morphology.load_morphology_contract(poisoned)


def test_profile_rejects_flower_evidence_that_disagrees_with_strict_p0() -> None:
    poisoned = copy.deepcopy(_contract())
    poisoned["instances"]["proto_sw_3_1"]["evidence_priors"][
        "flower_anchor_count"
    ] = 2
    contract = morphology.load_morphology_contract(poisoned)
    with pytest.raises(
        morphology.MorphologyContractError,
        match="does not match StrictP0-derived stage-2 flower count",
    ):
        morphology.materialize_branch_morphology_spec(
            _analysis("proto_sw_3_1"),
            contract,
        )


def test_renderer_emits_morphology_layers_and_source_comparison(
    tmp_path: Path,
) -> None:
    prototype_id = "proto_sw_2_3"
    analysis = _analysis(prototype_id)
    profile = _profile(prototype_id)
    source = SOURCE_IMAGE_ROOT / f"{prototype_id}.source.png"
    svg = tmp_path / "morphology.svg"
    png = tmp_path / "morphology.png"
    render.render_svg(analysis, profile, svg)
    render.render_png(analysis, profile, source, png)
    svg_text = svg.read_text(encoding="utf-8")
    for layer in (
        "source-reference",
        "allowed-attachment-regions",
        "flower-reserve-and-prohibited-relations",
        "backbone",
        "morphology-family",
        "flower-binding-intent",
        "flowers",
        "instance-priors",
    ):
        assert f'data-layer="{layer}"' in svg_text
    assert 'data-family="SW-2_axis_penetrating"' in svg_text
    assert "无槽位 · 无计划 · 无曲线" in svg_text
    assert png.stat().st_size > 100_000


def test_stage25_runner_materializes_review_only_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage25"
    manifest = stage25.run(
        STAGE2_ROOT,
        output,
        SOURCE_IMAGE_ROOT,
        CONTRACT_PATH,
    )
    assert manifest["prototype_ids"] == list(stage25.PROTOTYPE_IDS)
    assert manifest["review_gate"] == {
        "status": "morphology_pending_review",
        "all_five_visual_reviews_required": True,
        "stage_3_unlocked": False,
    }
    assert manifest["input_isolation"]["strict_p0_modified"] is False
    assert manifest["input_isolation"]["old_branch_geometry_consumed"] is False
    assert manifest["input_isolation"]["legacy_unit_type_consumed"] is False
    assert manifest["stage_scope"]["not_started"] == [
        "candidate_slots",
        "dynamic_branch_plan",
        "curve_compilation",
        "candidate_validation",
        "editor_v2",
    ]
    assert (output / "morphology_contact_sheet.png").is_file()
    for prototype_id, family_id in EXPECTED_FAMILIES.items():
        case_dir = output / prototype_id
        assert {path.name for path in case_dir.iterdir()} == {
            "morphology_profile.json",
            "morphology_overlay.svg",
            "morphology_overlay.png",
            "morphology_review.json",
            "source_reference.png",
        }
        profile = json.loads(
            (case_dir / "morphology_profile.json").read_text(encoding="utf-8")
        )
        review = json.loads(
            (case_dir / "morphology_review.json").read_text(encoding="utf-8")
        )
        assert (
            profile["classification"]["flower_branch_relation"]["family_id"]
            == family_id
        )
        assert review["status"] == "morphology_pending_review"
        assert review["stage_3_unlocked"] is False


def test_explicit_approval_promotes_both_review_gates_atomically(
    tmp_path: Path,
) -> None:
    stage2_copy = tmp_path / "stage2"
    stage25_copy = tmp_path / "stage25"
    stage2_copy.mkdir()
    stage25_copy.mkdir()
    shutil.copy2(STAGE2_ROOT / "manifest.json", stage2_copy / "manifest.json")
    source_stage25 = ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
    shutil.copy2(source_stage25 / "manifest.json", stage25_copy / "manifest.json")
    for prototype_id in stage25.PROTOTYPE_IDS:
        stage2_case = stage2_copy / prototype_id
        stage25_case = stage25_copy / prototype_id
        stage2_case.mkdir()
        stage25_case.mkdir()
        for name in ("prototype_analysis.json", "analysis_review.json"):
            shutil.copy2(STAGE2_ROOT / prototype_id / name, stage2_case / name)
        for name in ("morphology_profile.json", "morphology_review.json"):
            shutil.copy2(source_stage25 / prototype_id / name, stage25_case / name)

    stage2_manifest = json.loads(
        (stage2_copy / "manifest.json").read_text(encoding="utf-8")
    )
    stage25_manifest = json.loads(
        (stage25_copy / "manifest.json").read_text(encoding="utf-8")
    )
    stage2_rows = {row["prototype_id"]: row for row in stage2_manifest["profiles"]}
    stage25_rows = {row["prototype_id"]: row for row in stage25_manifest["profiles"]}
    for prototype_id in stage25.PROTOTYPE_IDS:
        analysis_review_path = stage2_copy / prototype_id / "analysis_review.json"
        analysis_review = json.loads(analysis_review_path.read_text(encoding="utf-8"))
        analysis_review.update(
            {
                "status": "analysis_pending_review",
                "reviewer": None,
                "reviewed_at": None,
                "notes": [],
                "stage_3_unlocked": False,
            }
        )
        analysis_review_path.write_text(
            json.dumps(
                analysis_review,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        stage2_rows[prototype_id]["analysis_review_sha256"] = hashlib.sha256(
            analysis_review_path.read_bytes()
        ).hexdigest()
        stage2_rows[prototype_id]["review_status"] = "analysis_pending_review"

        morphology_review_path = (
            stage25_copy / prototype_id / "morphology_review.json"
        )
        morphology_review = json.loads(
            morphology_review_path.read_text(encoding="utf-8")
        )
        morphology_review.update(
            {
                "status": "morphology_pending_review",
                "reviewer": None,
                "reviewed_at": None,
                "notes": [],
                "stage_3_unlocked": False,
            }
        )
        morphology_review_path.write_text(
            json.dumps(
                morphology_review,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        stage25_rows[prototype_id]["morphology_review_sha256"] = hashlib.sha256(
            morphology_review_path.read_bytes()
        ).hexdigest()
        stage25_rows[prototype_id]["review_status"] = "morphology_pending_review"

    stage2_manifest.pop("approval", None)
    stage2_manifest["review_gate"] = {
        "status": "analysis_pending_review",
        "all_five_visual_reviews_required": True,
        "stage_3_unlocked": False,
    }
    (stage2_copy / "manifest.json").write_text(
        json.dumps(stage2_manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    stage25_manifest.pop("approval", None)
    stage25_manifest["review_gate"] = {
        "status": "morphology_pending_review",
        "all_five_visual_reviews_required": True,
        "stage_3_unlocked": False,
    }
    stage25_manifest["stage2_manifest_sha256"] = hashlib.sha256(
        (stage2_copy / "manifest.json").read_bytes()
    ).hexdigest()
    (stage25_copy / "manifest.json").write_text(
        json.dumps(stage25_manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    result = approval.approve(
        stage2_copy,
        stage25_copy,
        reviewer="user",
        note="Stage 2.5 visual acceptance passed.",
        approved_at="2026-07-28T12:00:00+08:00",
    )
    assert result["stage_3_unlocked"] is True
    stage2_manifest = json.loads(
        (stage2_copy / "manifest.json").read_text(encoding="utf-8")
    )
    stage25_manifest = json.loads(
        (stage25_copy / "manifest.json").read_text(encoding="utf-8")
    )
    assert stage2_manifest["review_gate"]["status"] == "analysis_approved"
    assert stage25_manifest["review_gate"]["status"] == "morphology_approved"
    assert stage25_manifest["stage2_manifest_sha256"] == hashlib.sha256(
        (stage2_copy / "manifest.json").read_bytes()
    ).hexdigest()
    for prototype_id in stage25.PROTOTYPE_IDS:
        analysis_review = json.loads(
            (stage2_copy / prototype_id / "analysis_review.json").read_text(
                encoding="utf-8"
            )
        )
        morphology_review = json.loads(
            (stage25_copy / prototype_id / "morphology_review.json").read_text(
                encoding="utf-8"
            )
        )
        assert analysis_review["status"] == "analysis_approved"
        assert morphology_review["status"] == "morphology_approved"
        assert analysis_review["stage_3_unlocked"] is True
        assert morphology_review["stage_3_unlocked"] is True
