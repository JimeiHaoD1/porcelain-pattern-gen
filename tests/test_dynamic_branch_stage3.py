from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import dynamic_branch_plan as planner  # noqa: E402
import render_dynamic_branch_plan as render  # noqa: E402
import run_stage3_planning as stage3  # noqa: E402


STAGE2_ROOT = ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE25_ROOT = (
    ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
)
CONTRACT_PATH = DYNAMIC_DIR / "STAGE3_PLAN_CONTRACT.json"
EXPECTED_UNIT_COUNTS = {
    "proto_sw_1_1": 6,
    "proto_sw_1_3": 4,
    "proto_sw_2_3": 4,
    "proto_sw_3_1": 3,
    "proto_sw_3_2": 5,
}
REQUIRED_UNIT_FIELDS = {
    "branch_unit_id",
    "parent_ref",
    "family_id",
    "structural_role",
    "root_interval_ref",
    "root_tangent_intent",
    "primary_sweep_intent",
    "directional_layout_intent",
    "flower_relation_intents",
    "child_rhythm_envelope",
    "occupancy_envelope",
    "reserve_zone_refs",
    "terminal_intent",
    "provenance",
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _inputs(prototype_id: str) -> tuple[dict, dict, dict]:
    analysis = _read(STAGE2_ROOT / prototype_id / "prototype_analysis.json")
    morphology = _read(STAGE25_ROOT / prototype_id / "morphology_profile.json")
    return analysis, morphology, _read(CONTRACT_PATH)


@lru_cache(maxsize=None)
def _plan(prototype_id: str, seed: int) -> dict:
    analysis, morphology, contract = _inputs(prototype_id)
    return planner.generate_dynamic_branch_plan(
        analysis,
        morphology,
        contract,
        seed=seed,
    )


def _walk_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


@pytest.mark.parametrize("prototype_id", stage3.PROTOTYPE_IDS)
def test_all_five_prototypes_emit_complete_branchunit_plans(
    prototype_id: str,
) -> None:
    plan = _plan(prototype_id, 4101)
    assert plan["schema"] == planner.SCHEMA
    assert len(plan["branch_units"]) == EXPECTED_UNIT_COUNTS[prototype_id]
    assert plan["review"]["status"] == "plan_pending_review"
    assert plan["review"]["stage_4_unlocked"] is False
    assert plan["stage_boundary"] == {
        "candidate_slots_are_symbolic": True,
        "dynamic_branch_plan_present": True,
        "directional_layout_only": True,
        "branch_shape_simulation_present": False,
        "curve_geometry_present": False,
        "leaves_present": False,
        "buds_present": False,
        "curl_heads_present": False,
        "editor_integration_present": False,
    }
    for unit in plan["branch_units"]:
        assert REQUIRED_UNIT_FIELDS <= set(unit)
        assert unit["parent_ref"]["kind"] == "backbone"
        assert unit["terminal_intent"]["leaves_present"] is False
        assert unit["terminal_intent"]["buds_present"] is False
        assert unit["terminal_intent"]["curl_head_present"] is False
        assert unit["provenance"]["legacy_branch_geometry_used"] is False
        assert unit["root_tangent_intent"]["parent_tangent_is_reference_only"] is True
        assert unit["root_tangent_intent"]["must_start_along_parent_tangent"] is False
        directional = unit["directional_layout_intent"]
        assert directional["position_distance_direction_only"] is True
        assert directional["branch_shape_simulation"] is False
        assert directional["path_points"][0] == unit["parent_ref"]["mount_point"]
    assert not (
        {"control_points", "bezier_segments", "spline_segments", "curve_path"}
        & _walk_keys(plan)
    )


def test_family_specific_flower_branch_relations_are_structural() -> None:
    valley = _plan("proto_sw_1_1", 4101)
    axis = _plan("proto_sw_2_3", 4101)
    terminal = _plan("proto_sw_3_2", 4101)

    valley_supports = [
        unit
        for unit in valley["branch_units"]
        if unit["structural_role"] == "flower_support"
    ]
    assert len(valley_supports) == len(
        _inputs("proto_sw_1_1")[0]["flowers"]
    )
    assert {
        relation["flower_id"]
        for unit in valley_supports
        for relation in unit["flower_relation_intents"]
    } == {flower["flower_id"] for flower in _inputs("proto_sw_1_1")[0]["flowers"]}

    assert all(unit["structural_role"] == "primary_sweep" for unit in axis["branch_units"])
    assert all(not unit["flower_relation_intents"] for unit in axis["branch_units"])

    terminal_supports = [
        unit
        for unit in terminal["branch_units"]
        if unit["structural_role"] == "terminal_flower_support"
    ]
    assert len(terminal_supports) == len(
        _inputs("proto_sw_3_2")[0]["flowers"]
    )
    remote_policy = _inputs("proto_sw_3_2")[2]["initial_layout_constraints"][
        "sw3_remote_terminal_support"
    ]
    for unit in terminal_supports:
        interval = unit["root_interval_ref"]
        relation = unit["flower_relation_intents"][0]
        flower = next(
            row
            for row in _inputs("proto_sw_3_2")[0]["flowers"]
            if row["flower_id"] == relation["flower_id"]
        )
        root, under_approach, contact = unit["directional_layout_intent"][
            "path_points"
        ]
        assert interval["kind"] == "remote_terminal_support_corridor"
        assert interval["near_flower_stub_allowed"] is False
        assert interval["route_below_flower"] is True
        assert interval["contact_side"] == "underside"
        assert (
            interval["arc_distance_from_nearest_flower_mount"]
            >= remote_policy["minimum_arc_distance_from_nearest_flower_mount"]
        )
        assert (
            relation["root_to_flower_boundary_reach"]
            >= remote_policy["minimum_root_to_flower_boundary_reach"]
        )
        assert relation["origin_policy"] == "remote_parent_mount_long_terminal_reach"
        assert relation["route_policy"] == "below_flower_corridor"
        assert relation["contact_policy"] == "underside_flower_boundary"
        assert root[1] > flower["center"][1]
        assert under_approach[1] > (
            flower["center"][1] + flower["protection_ry"]
        )
        assert contact[0] == pytest.approx(flower["center"][0])
        assert contact[1] == pytest.approx(
            flower["center"][1] + flower["ry"] * 1.03
        )


@pytest.mark.parametrize("prototype_id", stage3.PROTOTYPE_IDS)
def test_global_layout_enforces_spacing_direction_and_density_bins(
    prototype_id: str,
) -> None:
    plan = _plan(prototype_id, 4101)
    policy = plan["initial_layout_policy"]
    units = plan["branch_units"]
    assert plan["global_selection"]["role_density_field_consumed"] is True
    assert policy["constraints_applied_before_curve_compilation"] is True
    assert policy["root_spacing_is_hard_constraint"] is True
    assert policy["local_direction_difference_is_hard_constraint"] is True
    assert policy["density_bin_capacity_is_hard_constraint"] is True
    assert policy["symbolic_intent_crossing_is_hard_failure"] is True
    assert policy["parent_backbone_hugging_is_hard_failure"] is True
    assert policy["symbolic_intent_polyline_crossing_allowed"] is False
    assert (
        policy["symbolic_intent_polyline_clearance_is_hard_constraint"]
        is True
    )
    assert (
        plan["global_selection"]["objective"]["symbolic_intent_crossing_count"]
        == 0
    )
    assert (
        plan["global_selection"]["objective"][
            "minimum_symbolic_intent_clearance"
        ]
        + 1e-9
        >= policy["minimum_symbolic_intent_clearance"]
    )
    bins: set[int] = set()
    for index, first in enumerate(units):
        first_directional = first["directional_layout_intent"]
        first_s = float(first["parent_ref"]["mount_s"])
        first_bin = planner._density_bin_index(first_s)
        assert first_bin not in bins
        bins.add(first_bin)
        for second in units[index + 1 :]:
            second_s = float(second["parent_ref"]["mount_s"])
            separation = planner._circular_s_distance(first_s, second_s)
            assert separation + 1e-9 >= policy["minimum_periodic_root_spacing"]
            if separation < policy["direction_neighborhood_s"]:
                difference = planner._angle_degrees(
                    tuple(first["primary_sweep_intent"]["eventual_direction"]),
                    tuple(second["primary_sweep_intent"]["eventual_direction"]),
                )
                assert (
                    difference
                    <= policy["maximum_local_direction_difference_degrees"] + 1e-9
                )
            first_candidate = {
                "root": first["occupancy_envelope"]["start"],
                "end_hint": first["occupancy_envelope"]["end_hint"],
                "direction_path_points": first_directional["path_points"],
            }
            second_candidate = {
                "root": second["occupancy_envelope"]["start"],
                "end_hint": second["occupancy_envelope"]["end_hint"],
                "direction_path_points": second["directional_layout_intent"][
                    "path_points"
                ],
            }
            clearance = planner._symbolic_intent_clearance(
                first_candidate,
                second_candidate,
            )
            required = max(
                policy["minimum_symbolic_intent_clearance"],
                policy["occupancy_radius_clearance_factor"]
                * (
                    first["occupancy_envelope"]["radius"]
                    + second["occupancy_envelope"]["radius"]
                ),
            )
            assert clearance + 1e-9 >= required
        if first["structural_role"] == "primary_sweep":
            assert first_directional["segment_count"] == 1
            assert (
                first_directional["outward_normal_alignment"] + 1e-9
                >= policy["minimum_outward_normal_alignment"]
            )
            assert (
                first_directional["parent_clearance_after_initial_departure"]
                + 1e-9
                >= policy["minimum_parent_clearance_after_initial_departure"]
            )


def test_crossing_segments_are_detected_as_zero_clearance() -> None:
    assert planner._segment_distance(
        (0.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
        (1.0, 0.0),
    ) == 0.0


def test_all_fifteen_tasks_are_deterministic_but_seed_variant() -> None:
    for prototype_id in stage3.PROTOTYPE_IDS:
        plans = [_plan(prototype_id, seed) for seed in stage3.SEEDS]
        assert len({plan["task_id"] for plan in plans}) == 3
        assert len({plan["plan_digest"] for plan in plans}) == 3
        assert all(plan["prototype_id"] == prototype_id for plan in plans)
        assert all(plan["raw_candidate_index"] == 1 for plan in plans)

    analysis, morphology, contract = _inputs("proto_sw_1_3")
    repeated = planner.generate_dynamic_branch_plan(
        analysis,
        morphology,
        contract,
        seed=4102,
    )
    assert repeated == _plan("proto_sw_1_3", 4102)


def test_second_raw_candidate_is_preserved_as_policy_failure() -> None:
    analysis, morphology, contract = _inputs("proto_sw_1_3")
    with pytest.raises(planner.PlanningFailure) as captured:
        planner.generate_dynamic_branch_plan(
            analysis,
            morphology,
            contract,
            seed=4101,
            raw_candidate_index=2,
        )
    failure = captured.value.as_dict()
    assert failure["code"] == "raw_candidate_index_violation"
    assert failure["retry_attempted"] is False
    assert failure["resample_attempted"] is False
    assert failure["automatic_repair_attempted"] is False
    assert failure["automatic_deletion_attempted"] is False


def test_renderer_exposes_symbolic_review_layers(tmp_path: Path) -> None:
    analysis = _inputs("proto_sw_3_1")[0]
    plan = _plan("proto_sw_3_1", 4101)
    svg_path = tmp_path / "plan.svg"
    png_path = tmp_path / "plan.png"
    render.render_svg(analysis, plan, svg_path)
    render.render_png(analysis, plan, png_path)

    ET.parse(svg_path)
    svg = svg_path.read_text(encoding="utf-8")
    for layer in (
        "role-density-field",
        "flower-reserves",
        "backbone",
        "occupancy-envelopes",
        "branchunit-intents",
        "flower-relation-intents",
        "unit-labels",
        "flowers",
        "plan-summary",
    ):
        assert f'data-layer="{layer}"' in svg
    assert 'data-geometry="directional_layout_not_branch_shape"' in svg
    assert "不模拟枝形 · 不允许交叉 · 无末端内容" in svg
    with Image.open(png_path) as image:
        assert image.size == (render.WIDTH, render.HEIGHT)


def test_runner_materializes_all_fifteen_review_tasks(tmp_path: Path) -> None:
    output = tmp_path / "stage3"
    manifest = stage3.run(output=output)
    assert manifest["schema"] == "dynamic_branch_stage3_plan_manifest_v3"
    assert manifest["task_count"] == 15
    assert manifest["success_count"] == 15
    assert manifest["failure_count"] == 0
    assert manifest["all_tasks_preserved"] is True
    assert manifest["review_gate"]["status"] == "plan_review_pending"
    assert manifest["review_gate"]["stage_4_unlocked"] is False
    assert manifest["project_scope"]["branch_skeleton_only"] is True
    assert manifest["project_scope"]["leaves_in_current_or_later_scope"] is False
    assert len(manifest["contact_sheets"]) == 6

    required = set(_read(CONTRACT_PATH)["output"]["required_artifacts_per_task"])
    for row in manifest["tasks"]:
        case_dir = output / row["output_directory"]
        assert required == {path.name for path in case_dir.iterdir()}
        review = _read(case_dir / "plan_review.json")
        assert review["status"] == "plan_pending_review"
        assert review["stage_4_scope_if_approved"] == "branch_curve_compilation_only"
        assert review["leaves_buds_or_curl_heads_in_project_scope"] is False
        assert row["retry_count"] == 0

    with pytest.raises(stage3.Stage3PlanningError, match="will not be overwritten"):
        stage3.run(output=output)
