from __future__ import annotations

import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import dynamic_branch_unit_curve_v2 as compiler  # noqa: E402
import render_dynamic_branch_curve as render  # noqa: E402
import run_stage4_unit_compilation_v2 as stage4_v2  # noqa: E402


STAGE2_ROOT = ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE3_ROOT = ROOT / "artifacts" / "runs" / "dynamic_branch_stage3_plans_v3"
STAGE4_V2_ROOT = (
    ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_unit_curves_v2"
)
CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_CURVE_CONTRACT_V2.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    return compiler.compile_dynamic_branch_units(
        _analysis(prototype_id),
        _plan(prototype_id, seed),
        _contract(),
    )


@lru_cache(maxsize=None)
def _diagnostics(prototype_id: str, seed: int) -> dict:
    return compiler.diagnose_dynamic_branch_units(
        _analysis(prototype_id),
        _plan(prototype_id, seed),
        _candidate(prototype_id, seed),
        _contract(),
    )


def test_stage4_v2_contract_requires_complete_branch_units() -> None:
    contract = _contract()
    assert contract["required_input"]["task_count"] == 15
    assert contract["unit_topology_materialization"]["maximum_hierarchy_level"] == 3
    assert (
        contract["unit_topology_materialization"][
            "actual_l2_count_is_selected_once_from_each_stage3_child_rhythm_envelope"
        ]
        is True
    )
    assert contract["unit_topology_materialization"][
        "l3_parent_local_turn_sign_candidates"
    ] == [-1, 1]
    assert contract["primary_curve_compilation"]["ordinary_primary_cubic_count"] == 2
    assert (
        contract["dependent_curve_compilation"][
            "child_entry_derivative_uses_actual_parent_local_tangent"
        ]
        is True
    )
    assert contract["candidate_policy"]["validation_guided_retry_allowed"] is False
    assert contract["candidate_policy"]["automatic_repair_allowed"] is False
    assert contract["candidate_policy"]["automatic_deletion_allowed"] is False
    assert contract["stage_boundary"]["complete_branch_units_present"] is True
    assert contract["stage_boundary"]["leaves_present"] is False
    assert contract["stage_boundary"]["buds_present"] is False
    assert contract["stage_boundary"]["curl_heads_present"] is False


def test_dense_case_compiles_hierarchically_and_deterministically() -> None:
    prototype_id = "proto_sw_1_1"
    seed = 4102
    plan = _plan(prototype_id, seed)
    candidate = _candidate(prototype_id, seed)
    diagnostics = _diagnostics(prototype_id, seed)
    assert candidate["schema"] == compiler.SCHEMA
    assert len(candidate["branch_units"]) == len(plan["branch_units"]) == 6
    assert diagnostics["level_counts"] == {"L1": 6, "L2": 11, "L3": 3}
    assert diagnostics["issue_count"] == 0
    assert diagnostics["near_straight_curve_count"] == 0
    assert diagnostics["curve_curve_crossing_count"] == 0
    assert diagnostics["wrong_flower_entry_count"] == 0
    assert any(unit["actual_l3_count"] for unit in candidate["branch_units"])
    assert all(
        spec["orientation_candidate_count"] == 2
        for unit in candidate["branch_units"]
        for spec in unit["l3_specs"]
    )

    curve_by_id = {
        curve["curve_id"]: curve for curve in candidate["branch_curves"]
    }
    for curve in candidate["branch_curves"]:
        if curve["level"] == "L1":
            assert len(curve["cubic_segments"]) == 2
            bad, _ = compiler._shape_issue(curve, _contract())
            assert bad is False
            continue
        parent = curve_by_id[curve["parent_curve_id"]]
        assert curve["hierarchy_level"] == parent["hierarchy_level"] + 1
        parent_points = compiler._curve_points(parent, 96)
        expected_root, expected_tangent = compiler._sample_polyline(
            parent_points,
            curve["mount_fraction"],
        )
        actual_root = compiler._point(curve["cubic_segments"][0]["p0"])
        assert compiler._distance(actual_root, expected_root) < 2e-5
        actual_entry = compiler._unit(
            compiler._sub(
                compiler._point(curve["cubic_segments"][0]["p1"]),
                actual_root,
            )
        )
        cosine = max(-1.0, min(1.0, compiler._dot(actual_entry, expected_tangent)))
        assert math.degrees(math.acos(cosine)) < 2.0

    repeated = compiler.compile_dynamic_branch_units(
        _analysis(prototype_id),
        plan,
        _contract(),
    )
    assert repeated["candidate_digest"] == candidate["candidate_digest"]
    assert repeated["unit_topology_digest"] == candidate["unit_topology_digest"]


def test_sw3_support_preserves_remote_below_flower_route() -> None:
    prototype_id = "proto_sw_3_1"
    seed = 4101
    plan = _plan(prototype_id, seed)
    candidate = _candidate(prototype_id, seed)
    support_unit = next(
        unit
        for unit in plan["branch_units"]
        if unit["structural_role"] == "terminal_flower_support"
    )
    support_curve = next(
        curve
        for curve in candidate["branch_curves"]
        if curve["branch_unit_id"] == support_unit["branch_unit_id"]
        and curve["level"] == "L1"
    )
    path = support_unit["directional_layout_intent"]["path_points"]
    cubics = support_curve["cubic_segments"]
    assert len(cubics) == 2
    assert cubics[0]["p0"] == path[0]
    assert cubics[0]["p3"] == path[1]
    assert cubics[1]["p0"] == path[1]
    assert cubics[1]["p3"] == path[2]
    relation = support_unit["flower_relation_intents"][0]
    assert relation["origin_policy"] == "remote_parent_mount_long_terminal_reach"
    assert relation["route_policy"] == "below_flower_corridor"
    assert relation["contact_policy"] == "underside_flower_boundary"
    assert relation["under_approach_waypoint"] == path[1]
    assert relation["contact_point"] == path[2]
    assert _diagnostics(prototype_id, seed)["issue_count"] == 0


def test_stage4_v2_formal_package_preserves_all_pending_candidates() -> None:
    manifest = _read(STAGE4_V2_ROOT / "manifest.json")
    assert manifest["schema"] == "dynamic_branch_stage4_unit_curve_manifest_v2"
    assert manifest["task_count"] == 15
    assert manifest["success_count"] == 15
    assert manifest["failure_count"] == 0
    assert manifest["total_branch_unit_count"] == 66
    assert manifest["total_level_counts"] == {"L1": 66, "L2": 94, "L3": 12}
    assert manifest["near_straight_curve_count"] == 0
    assert manifest["crossing_count"] == 0
    assert manifest["wrong_flower_entry_count"] == 0
    assert manifest["diagnostic_issue_count"] == 0
    assert manifest["review_gate"]["status"] == "original_unit_curve_review_pending"
    assert manifest["review_gate"]["pending_review_count"] == 15
    assert manifest["review_gate"]["editor_unlocked"] is False
    required = set(_contract()["output"]["required_artifacts_per_task"])
    for row in manifest["tasks"]:
        case_dir = STAGE4_V2_ROOT / row["output_directory"]
        assert required == {path.name for path in case_dir.iterdir()}
        review = _read(case_dir / "original_visual_review.json")
        assert review["status"] == "original_pending_review"
        assert review["numeric_checks_cannot_auto_approve"] is True
        assert row["retry_count"] == 0
        for key, value in row.items():
            if not key.endswith("_path"):
                continue
            artifact = STAGE4_V2_ROOT / value
            assert artifact.is_file()
            assert _sha256(artifact) == row[f"{key[:-5]}_sha256"]


def test_stage4_v2_renderer_emits_hierarchy_and_beziers(
    tmp_path: Path,
) -> None:
    prototype_id = "proto_sw_3_1"
    seed = 4101
    original_svg = tmp_path / "original.svg"
    original_png = tmp_path / "original.png"
    render.render_original_svg(
        _analysis(prototype_id),
        _candidate(prototype_id, seed),
        _diagnostics(prototype_id, seed),
        original_svg,
    )
    render.render_original_png(
        _analysis(prototype_id),
        _candidate(prototype_id, seed),
        _diagnostics(prototype_id, seed),
        original_png,
    )
    ET.parse(original_svg)
    svg = original_svg.read_text(encoding="utf-8")
    assert 'data-layer="bezier-branch-curves"' in svg
    assert 'data-geometry="cubic_bezier_branch_skeleton"' in svg
    assert svg.count(" C ") >= len(_candidate(prototype_id, seed)["branch_curves"])
    with Image.open(original_png) as image:
        assert image.size == (render.WIDTH, render.HEIGHT)
    contract, manifest, stage2_manifest, analysis_rows = (
        stage4_v2._load_launch_inputs()
    )
    assert contract["schema"] == _contract()["schema"]
    assert manifest["review_gate"]["stage_4_unlocked"] is True
    assert stage2_manifest["review_gate"]["stage_3_unlocked"] is True
    assert tuple(analysis_rows) == stage4_v2.PROTOTYPE_IDS
