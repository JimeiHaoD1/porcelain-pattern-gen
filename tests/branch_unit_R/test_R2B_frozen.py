from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
sys.path.insert(0, str(DYNAMIC))

FROZEN_TOPOLOGY_DIGEST = (
    "195e214afd784983e4d4b236795b22b0058ca2c8fd16121c8c78effc89003a36"
)
ROLE_NAMES = {
    "flower_forbidden_region",
    "backbone_protection_region",
    "seam_guard_region",
    "existing_structure_protection_region",
    "support_region",
    "wrap_region",
    "remote_support_region",
    "balance_region",
    "settle_region",
    "ordinary_fill_region",
    "axis_flow_region",
}


def _inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    from run_stage3b_l1_flow import _load_inputs
    from topology_contract_loader import materialize_prototype_topology

    inputs, _, _, _ = _load_inputs(DYNAMIC / "R1_L1_MOTION_CONTRACT_V1.json")
    analysis = inputs["proto_sw_1_1"]["analysis"]
    topology = materialize_prototype_topology(
        "proto_sw_1_1",
        [row["flower_id"] for row in analysis["flowers"]],
    )
    return analysis, topology


def _orientation(
    a: Sequence[float],
    b: Sequence[float],
    c: Sequence[float],
) -> float:
    return (
        (float(b[0]) - float(a[0])) * (float(c[1]) - float(a[1]))
        - (float(b[1]) - float(a[1])) * (float(c[0]) - float(a[0]))
    )


def _proper_crossing(
    a: Sequence[float],
    b: Sequence[float],
    c: Sequence[float],
    d: Sequence[float],
) -> bool:
    return (
        _orientation(a, b, c) * _orientation(a, b, d) < 0.0
        and _orientation(c, d, a) * _orientation(c, d, b) < 0.0
    )


def _self_crossing_count(points: list[list[float]]) -> int:
    segment_count = len(points) - 1
    return sum(
        _proper_crossing(
            points[left],
            points[left + 1],
            points[right],
            points[right + 1],
        )
        for left in range(segment_count)
        for right in range(left + 1, segment_count)
        if abs(left - right) > 1
        and not (left == 0 and right == segment_count - 1)
    )


def _boundary_interlock_count(
    first: list[list[float]],
    second: list[list[float]],
) -> int:
    return sum(
        _proper_crossing(
            first[left - 1],
            first[left],
            second[right - 1],
            second[right],
        )
        for left in range(1, len(first))
        for right in range(1, len(second))
    )


def _guide_angle(points: list[list[float]]) -> float:
    return math.degrees(
        math.atan2(
            float(points[-1][1]) - float(points[0][1]),
            float(points[-1][0]) - float(points[0][0]),
        )
    )


def _angle_difference(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _horizontal_progress(points: list[list[float]]) -> float:
    length = sum(
        math.dist(points[index - 1], points[index])
        for index in range(1, len(points))
    )
    return abs(float(points[-1][0]) - float(points[0][0])) / length


def test_R2B_semantic_checkpoint_covers_every_frozen_region() -> None:
    root = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_R2B_v2"
    table = json.loads(
        (root / "resolved_region_role_table.json").read_text(encoding="utf-8")
    )
    review = (root / "region_semantics_review.md").read_text(encoding="utf-8")
    assert {row["role"] for row in table["regions"]} == ROLE_NAMES
    assert all(f"`{role}`" in review for role in ROLE_NAMES)
    assert table["R2B_fixed_instance"]["new_branch_curve_count"] == 0
    assert table["R2B_fixed_instance"]["seed_affects_geometry"] is False


def test_R2B_region_plan_independently_satisfies_frozen_geometry() -> None:
    from role_region_plan import build_sw1_role_region_plan

    analysis, topology = _inputs()
    plan = build_sw1_role_region_plan(analysis, topology, "flower_1")
    replay = build_sw1_role_region_plan(analysis, topology, "flower_1")
    assert plan["region_plan_digest"] == replay["region_plan_digest"]
    assert plan["topology_contract_digest"] == FROZEN_TOPOLOGY_DIGEST
    assert plan["stage_scope"]["new_branch_curve_count"] == 0
    assert plan["input_provenance"] == {
        "stage2_analysis_only": True,
        "R2A_topology_only": True,
        "branch_geometry_used_as_input": False,
        "selected_candidate_used_as_input": False,
        "stage5_selection_used_as_input": False,
        "seed_used_as_geometry_input": False,
    }

    roles = Counter(row["role"] for row in plan["regions"])
    assert roles["support_region"] == 1
    assert roles["wrap_region"] == 1
    assert roles["balance_region"] == 1
    assert roles["flower_forbidden_region"] == 1
    assert roles["backbone_protection_region"] >= 1
    by_role = {row["role"]: row for row in plan["regions"]}
    role_regions = [
        by_role["support_region"],
        by_role["wrap_region"],
        by_role["balance_region"],
    ]
    for region in role_regions:
        assert region["boundary"][0] == region["boundary"][-1]
        assert _self_crossing_count(region["boundary"]) == 0
        assert len(region["guide_centerline"]) >= 12
        assert len(region["guide_tangents"]) == len(region["guide_centerline"])
        assert len(region["width_profile"]) >= 5
        assert len(region["entry_s_range"]) == 2
        assert len(region["exit_direction"]) == 2
        assert region["capacity"]["maximum_l1_count"] == 1
        assert region["service_flower_id"] == "flower_1"
        assert region["region_plan_digest"] == plan["region_plan_digest"]
        assert (
            region["geometry_kind"]
            == "morphology_derived_variable_width_soft_channel"
        )

    support = by_role["support_region"]
    wrap = by_role["wrap_region"]
    assert support["region_id"] != wrap["region_id"]
    assert support["entry_s_range"] != wrap["entry_s_range"]
    assert (
        support["guide_centerline_digest"]
        != wrap["guide_centerline_digest"]
    )
    assert support["service_flower_id"] == wrap["service_flower_id"]
    assert _boundary_interlock_count(
        support["boundary"],
        wrap["boundary"],
    ) >= 1
    assert _angle_difference(
        _guide_angle(support["guide_centerline"]),
        _guide_angle(wrap["guide_centerline"]),
    ) >= 25.0
    assert _horizontal_progress(support["guide_centerline"]) >= 0.20
    assert _horizontal_progress(wrap["guide_centerline"]) >= 0.20

    flower = analysis["flowers"][0]
    cx, cy = [float(value) for value in flower["center"]]
    rx = float(flower["protection_rx"])
    ry = float(flower["protection_ry"])
    for region in role_regions:
        assert all(
            math.hypot(
                (float(point[0]) - cx) / rx,
                (float(point[1]) - cy) / ry,
            )
            >= 1.0
            for point in region["boundary"]
        )
        bounds = plan["unit_bounds"]
        assert all(
            float(bounds[0]) <= float(point[0]) <= float(bounds[2])
            and float(bounds[1]) <= float(point[1]) <= float(bounds[3])
            for field in ("guide_centerline", "boundary")
            for point in region[field]
        )

    digest_source = json.loads(json.dumps(plan))
    digest_source["region_plan_digest"] = None
    for region in digest_source["regions"]:
        region["region_plan_digest"] = None
    independent_digest = hashlib.sha256(
        json.dumps(
            digest_source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert independent_digest == plan["region_plan_digest"]


def test_R2B_region_plan_precedes_geometry_and_has_no_forbidden_inputs() -> None:
    import global_l1_flow
    import role_region_plan

    signature = inspect.signature(role_region_plan.build_sw1_role_region_plan)
    assert list(signature.parameters) == [
        "analysis",
        "topology",
        "service_flower_id",
    ]
    region_source = inspect.getsource(role_region_plan)
    identifiers = {
        node.id
        for node in ast.walk(ast.parse(region_source))
        if isinstance(node, ast.Name)
    }
    assert "selected_candidate" not in identifiers
    assert "stage5_selection" not in identifiers
    assert "seed" not in identifiers
    assert "if __name__" not in region_source
    soft_geometry_source = "\n".join(
        inspect.getsource(value)
        for value in (
            role_region_plan._sample_catmull_rom,
            role_region_plan._enforce_flower_clearance,
            role_region_plan._soft_channel_boundary,
            role_region_plan._role_region,
        )
    )
    assert "math.cos" not in soft_geometry_source
    assert "math.sin" not in soft_geometry_source
    soft_identifiers = {
        node.id
        for node in ast.walk(ast.parse(soft_geometry_source))
        if isinstance(node, ast.Name)
    }
    assert "rectangle" not in soft_identifiers
    assert "sector" not in soft_identifiers

    planner_source = inspect.getsource(
        global_l1_flow.generate_global_l1_flow_plan
    )
    region_index = planner_source.index("build_sw1_role_region_plan")
    slot_index = planner_source.index("slots = _make_slots")
    candidate_index = planner_source.index("for slot in slots")
    assert region_index < slot_index < candidate_index
