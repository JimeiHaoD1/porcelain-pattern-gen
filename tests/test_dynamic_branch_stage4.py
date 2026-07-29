from __future__ import annotations

import json
import shutil
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import dynamic_branch_curve as compiler  # noqa: E402
import record_stage3_approval as approval  # noqa: E402
import render_dynamic_branch_curve as render  # noqa: E402
import run_stage4_compilation as stage4  # noqa: E402


STAGE2_ROOT = ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE3_ROOT = ROOT / "artifacts" / "runs" / "dynamic_branch_stage3_plans_v3"
CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_CURVE_CONTRACT.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _contract() -> dict:
    return _read(CONTRACT_PATH)


@lru_cache(maxsize=None)
def _plan(prototype_id: str, seed: int) -> dict:
    return _read(
        STAGE3_ROOT
        / prototype_id
        / f"seed_{seed}"
        / "dynamic_branch_plan.json"
    )


@lru_cache(maxsize=None)
def _analysis(prototype_id: str) -> dict:
    return _read(STAGE2_ROOT / prototype_id / "prototype_analysis.json")


@lru_cache(maxsize=None)
def _candidate(prototype_id: str, seed: int) -> dict:
    return compiler.compile_dynamic_branch_curve(
        _analysis(prototype_id),
        _plan(prototype_id, seed),
        _contract(),
    )


def test_stage4_contract_freezes_bezier_only_branch_skeleton_scope() -> None:
    contract = _contract()
    assert contract["required_input"]["task_count"] == 15
    assert contract["curve_representation"]["type"] == "cubic_bezier"
    assert contract["curve_representation"]["maximum_cubic_segments_per_branch"] == 2
    assert (
        contract["curve_representation"][
            "parent_tangent_is_derivative_only_not_a_straight_preview_segment"
        ]
        is True
    )
    assert contract["candidate_policy"]["automatic_repair_allowed"] is False
    assert contract["candidate_policy"]["automatic_deletion_allowed"] is False
    assert contract["stage_boundary"]["leaves_present"] is False
    assert contract["stage_boundary"]["buds_present"] is False
    assert contract["stage_boundary"]["curl_heads_present"] is False


def test_all_fifteen_plans_compile_once_and_preserve_stage3_geometry() -> None:
    for prototype_id in stage4.PROTOTYPE_IDS:
        for seed in stage4.SEEDS:
            plan = _plan(prototype_id, seed)
            candidate = _candidate(prototype_id, seed)
            assert candidate["schema"] == compiler.SCHEMA
            assert len(candidate["branch_curves"]) == len(plan["branch_units"])
            assert candidate["compilation_policy"]["automatic_repair_used"] is False
            assert candidate["compilation_policy"]["stage3_unit_count_preserved"] is True
            units = {
                unit["branch_unit_id"]: unit for unit in plan["branch_units"]
            }
            for curve in candidate["branch_curves"]:
                unit = units[curve["branch_unit_id"]]
                path = unit["directional_layout_intent"]["path_points"]
                cubics = curve["cubic_segments"]
                assert cubics[0]["p0"] == path[0]
                assert cubics[-1]["p3"] == path[-1]
                assert len(cubics) == len(path) - 1
                assert len(cubics) <= 2
                assert (
                    _contract()["curve_representation"][
                        "minimum_root_handle_length"
                    ]
                    - 1e-9
                    <= curve["compiler_trace"]["root_handle_length"]
                    <= _contract()["curve_representation"][
                        "maximum_root_handle_length"
                    ]
                    + 1e-9
                )
                assert (
                    curve["compiler_trace"][
                        "straight_parent_tangent_prefix_present"
                    ]
                    is False
                )
                if len(path) == 3:
                    assert cubics[0]["p3"] == path[1]
                    assert cubics[1]["p0"] == path[1]
                    assert curve["compiler_trace"]["join_continuity"] == "G1"


def test_compile_diagnostics_report_no_crossing_without_modifying_candidates() -> None:
    for prototype_id in stage4.PROTOTYPE_IDS:
        for seed in stage4.SEEDS:
            plan = _plan(prototype_id, seed)
            candidate = _candidate(prototype_id, seed)
            diagnostics = compiler.diagnose_curve_candidate(
                _analysis(prototype_id),
                plan,
                candidate,
                _contract(),
            )
            assert diagnostics["candidate_modified"] is False
            assert diagnostics["retry_attempted"] is False
            assert diagnostics["automatic_repair_attempted"] is False
            assert diagnostics["curve_curve_crossing_count"] == 0
            assert diagnostics["non_root_backbone_crossing_count"] == 0
            assert diagnostics["issue_count"] == 0


def test_stage3_approval_recorder_promotes_all_fifteen_reviews(
    tmp_path: Path,
) -> None:
    source_manifest = _read(STAGE3_ROOT / "manifest.json")
    copied_root = tmp_path / "stage3"
    copied_root.mkdir()
    shutil.copy2(STAGE3_ROOT / "manifest.json", copied_root / "manifest.json")
    for row in source_manifest["tasks"]:
        for key in ("dynamic_branch_plan_path", "plan_review_path"):
            source = STAGE3_ROOT / row[key]
            target = copied_root / row[key]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        review_path = copied_root / row["plan_review_path"]
        review = _read(review_path)
        review["status"] = "plan_pending_review"
        review["reviewer"] = None
        review["reviewed_at"] = None
        review["stage_4_unlocked"] = False
        review["notes"] = []
        review_path.write_text(
            json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        row["state"] = "plan_pending_review"
        row["plan_review_sha256"] = approval._sha256(review_path)
    source_manifest["tasks"] = source_manifest["tasks"]
    source_manifest["review_gate"]["status"] = "plan_review_pending"
    source_manifest["review_gate"]["stage_4_unlocked"] = False
    (copied_root / "manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    result = approval.approve(
        copied_root,
        reviewer="test_user",
        note="Approved for test curve compilation.",
        approved_at="2026-07-28T20:00:00+08:00",
    )
    assert result["approved_plan_count"] == 15
    assert result["stage_4_unlocked"] is True
    manifest = _read(copied_root / "manifest.json")
    assert manifest["review_gate"]["stage_4_unlocked"] is True
    assert all(
        row["state"] == "plan_approved_for_curve_compilation"
        for row in manifest["tasks"]
    )


def test_renderer_emits_exact_bezier_and_review_images(tmp_path: Path) -> None:
    prototype_id = "proto_sw_3_1"
    seed = 4101
    candidate = _candidate(prototype_id, seed)
    diagnostics = compiler.diagnose_curve_candidate(
        _analysis(prototype_id),
        _plan(prototype_id, seed),
        candidate,
        _contract(),
    )
    original_svg = tmp_path / "original.svg"
    original_png = tmp_path / "original.png"
    triple_svg = tmp_path / "triple.svg"
    triple_png = tmp_path / "triple.png"
    render.render_original_svg(
        _analysis(prototype_id),
        candidate,
        diagnostics,
        original_svg,
    )
    render.render_original_png(
        _analysis(prototype_id),
        candidate,
        diagnostics,
        original_png,
    )
    render.render_three_repeat_svg(
        _analysis(prototype_id),
        candidate,
        diagnostics,
        triple_svg,
    )
    render.render_three_repeat_png(
        _analysis(prototype_id),
        candidate,
        diagnostics,
        triple_png,
    )
    ET.parse(original_svg)
    ET.parse(triple_svg)
    svg = original_svg.read_text(encoding="utf-8")
    assert 'data-layer="bezier-branch-curves"' in svg
    assert 'data-geometry="cubic_bezier_branch_skeleton"' in svg
    assert " C " in svg
    with Image.open(original_png) as image:
        assert image.size == (render.WIDTH, render.HEIGHT)
    with Image.open(triple_png) as image:
        assert image.size == (render.TRIPLE_WIDTH, render.TRIPLE_HEIGHT)


def test_stage4_runner_materializes_all_raw_candidates(tmp_path: Path) -> None:
    output = tmp_path / "stage4"
    manifest = stage4.run(output=output)
    assert manifest["schema"] == "dynamic_branch_stage4_curve_manifest_v1"
    assert manifest["task_count"] == 15
    assert manifest["success_count"] == 15
    assert manifest["failure_count"] == 0
    assert manifest["crossing_count"] == 0
    assert manifest["diagnostic_issue_count"] == 0
    assert manifest["review_gate"]["status"] == "original_curve_review_pending"
    assert manifest["review_gate"]["editor_unlocked"] is False
    required = set(_contract()["output"]["required_artifacts_per_task"])
    for row in manifest["tasks"]:
        case_dir = output / row["output_directory"]
        assert required == {path.name for path in case_dir.iterdir()}
        review = _read(case_dir / "original_visual_review.json")
        assert review["status"] == "original_pending_review"
        assert row["retry_count"] == 0
