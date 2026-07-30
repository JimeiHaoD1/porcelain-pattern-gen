from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
sys.path.insert(0, str(DYNAMIC))

FROZEN_R2B_DIGEST = (
    "880a0a03c3cf4321ed750eadb15d02d07e50f98442f55b61ed24ca7e71541688"
)


def _inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from run_stage3b_l1_flow import _load_inputs
    from topology_contract_loader import materialize_prototype_topology

    inputs, _, _, _ = _load_inputs(DYNAMIC / "R1_L1_MOTION_CONTRACT_V1.json")
    analysis = inputs["proto_sw_1_1"]["analysis"]
    topology = materialize_prototype_topology(
        "proto_sw_1_1",
        [row["flower_id"] for row in analysis["flowers"]],
    )
    frozen_plan = json.loads(
        (
            REPO_ROOT
            / "artifacts"
            / "runs"
            / "dynamic_branch_R2B_v2"
            / "role_region_plan.json"
        ).read_text(encoding="utf-8")
    )
    return analysis, topology, frozen_plan


def _profile_width(region: Mapping[str, Any], fraction: float) -> float:
    profile = [
        (float(row["u"]), float(row["half_width"]))
        for row in region["width_profile"]
    ]
    u = max(0.0, min(1.0, fraction))
    for (left_u, left_width), (right_u, right_width) in zip(
        profile,
        profile[1:],
    ):
        if u <= right_u:
            local = (u - left_u) / (right_u - left_u)
            return left_width + (right_width - left_width) * local
    return profile[-1][1]


def _projection(
    point: Sequence[float],
    start: Sequence[float],
    end: Sequence[float],
) -> tuple[float, float]:
    vector = (
        float(end[0]) - float(start[0]),
        float(end[1]) - float(start[1]),
    )
    denominator = vector[0] ** 2 + vector[1] ** 2
    local = max(
        0.0,
        min(
            1.0,
            (
                (float(point[0]) - float(start[0])) * vector[0]
                + (float(point[1]) - float(start[1])) * vector[1]
            )
            / denominator,
        ),
    )
    projected = (
        float(start[0]) + local * vector[0],
        float(start[1]) + local * vector[1],
    )
    return math.dist(point, projected), local


def _channel_metrics(
    points: Sequence[Sequence[float]],
    region: Mapping[str, Any],
) -> dict[str, float]:
    guide = region["guide_centerline"]
    guide_lengths = [0.0]
    for start, end in zip(guide, guide[1:]):
        guide_lengths.append(guide_lengths[-1] + math.dist(start, end))
    total = 0.0
    covered = 0.0
    weighted_alignment = 0.0
    alignments: list[tuple[float, float]] = []
    for start, end in zip(points, points[1:]):
        length = math.dist(start, end)
        if length <= 1e-12:
            continue
        midpoint = (
            (float(start[0]) + float(end[0])) * 0.5,
            (float(start[1]) + float(end[1])) * 0.5,
        )
        distance, local, index = min(
            (
                *_projection(midpoint, guide[index], guide[index + 1]),
                index,
            )
            for index in range(len(guide) - 1)
        )
        curve_tangent = (
            float(end[0]) - float(start[0]),
            float(end[1]) - float(start[1]),
        )
        guide_tangent = (
            float(guide[index + 1][0]) - float(guide[index][0]),
            float(guide[index + 1][1]) - float(guide[index][1]),
        )
        alignment = (
            curve_tangent[0] * guide_tangent[0]
            + curve_tangent[1] * guide_tangent[1]
        ) / (
            math.hypot(*curve_tangent) * math.hypot(*guide_tangent)
        )
        guide_fraction = (
            guide_lengths[index]
            + local * math.dist(guide[index], guide[index + 1])
        ) / guide_lengths[-1]
        width = _profile_width(region, guide_fraction)
        total += length
        weighted_alignment += alignment * length
        alignments.append((alignment, length))
        if distance <= width + 1e-12:
            covered += length
    alignments.sort(key=lambda row: row[0])
    p10_target = total * 0.10
    accumulated = 0.0
    p10 = alignments[0][0]
    for alignment, length in alignments:
        accumulated += length
        p10 = alignment
        if accumulated >= p10_target:
            break
    return {
        "coverage": covered / total,
        "mean_alignment": weighted_alignment / total,
        "p10_alignment": p10,
    }


def _proper_intersection(
    first_start: Sequence[float],
    first_end: Sequence[float],
    second_start: Sequence[float],
    second_end: Sequence[float],
) -> bool:
    epsilon = 1e-9
    first_delta = (
        float(first_end[0]) - float(first_start[0]),
        float(first_end[1]) - float(first_start[1]),
    )
    second_delta = (
        float(second_end[0]) - float(second_start[0]),
        float(second_end[1]) - float(second_start[1]),
    )
    denominator = (
        first_delta[0] * second_delta[1]
        - first_delta[1] * second_delta[0]
    )
    if abs(denominator) <= epsilon:
        return False
    offset = (
        float(second_start[0]) - float(first_start[0]),
        float(second_start[1]) - float(first_start[1]),
    )
    first_t = (
        offset[0] * second_delta[1] - offset[1] * second_delta[0]
    ) / denominator
    second_t = (
        offset[0] * first_delta[1] - offset[1] * first_delta[0]
    ) / denominator
    return (
        epsilon < first_t < 1.0 - epsilon
        and epsilon < second_t < 1.0 - epsilon
    )


def _crossing_count(
    first: Sequence[Sequence[float]],
    second: Sequence[Sequence[float]],
) -> int:
    return sum(
        _proper_intersection(
            first[left - 1],
            first[left],
            second[right - 1],
            second[right],
        )
        for left in range(1, len(first))
        for right in range(1, len(second))
    )


def _self_crossing_count(points: Sequence[Sequence[float]]) -> int:
    return sum(
        _proper_intersection(
            points[left],
            points[left + 1],
            points[right],
            points[right + 1],
        )
        for left in range(len(points) - 1)
        for right in range(left + 2, len(points) - 1)
        if not (left == 0 and right == len(points) - 2)
    )


def test_R2C_consumes_exact_frozen_R2B_plan_and_is_reproducible() -> None:
    from global_l1_flow import generate_sw1_region_l1_pair
    from role_region_plan import (
        build_sw1_role_region_plan,
        validate_role_region_plan,
    )

    analysis, topology, frozen = _inputs()
    validate_role_region_plan(frozen)
    rebuilt = build_sw1_role_region_plan(analysis, topology, "flower_1")
    assert frozen["region_plan_digest"] == FROZEN_R2B_DIGEST
    assert rebuilt["region_plan_digest"] == FROZEN_R2B_DIGEST
    first = generate_sw1_region_l1_pair(analysis, frozen)
    second = generate_sw1_region_l1_pair(analysis, frozen)
    assert first["pair_digest"] == second["pair_digest"]
    assert first["source_region_plan_digest"] == FROZEN_R2B_DIGEST
    assert first["region_plan_regenerated_after_curve_generation"] is False


def test_R2C_selected_pair_satisfies_frozen_topology_and_geometry() -> None:
    from global_l1_flow import generate_sw1_region_l1_pair
    from optimization_line_r_metrics import ellipse_wrap_stats

    analysis, _, frozen = _inputs()
    pair = generate_sw1_region_l1_pair(analysis, frozen)
    selected = {row["role"]: row for row in pair["selected_curves"]}
    support = selected["flower_support"]
    wrap = selected["flower_wrap"]
    regions = {row["role"]: row for row in frozen["regions"]}
    assert pair["stage_scope"] == {
        "selected_L1_count": 2,
        "support_L1_count": 1,
        "wrap_L1_count": 1,
        "L2_count": 0,
        "L3_count": 0,
    }
    assert support["level"] == "L1" and wrap["level"] == "L1"
    assert support["parent_curve_id"] is None
    assert wrap["parent_curve_id"] is None
    assert support["root_s"] != wrap["root_s"]
    assert support["service_flower_id"] == wrap["service_flower_id"]
    assert support["region_id"] != wrap["region_id"]
    assert support["source_region_plan_digest"] == FROZEN_R2B_DIGEST
    assert wrap["source_region_plan_digest"] == FROZEN_R2B_DIGEST
    assert wrap["level"] != "L2"
    assert wrap["parent_curve_id"] != support["curve_id"]
    trough = next(
        row
        for row in analysis["backbone"]["extrema"]
        if row["feature_id"] == wrap["root_feature_id"]
    )
    assert wrap["root_feature_kind"] == "trough"
    assert math.dist(wrap["centerline"][0], trough["point"]) <= 1e-9
    root_delta = abs(float(wrap["root_s"]) - float(trough["s"]))
    assert min(root_delta, 1.0 - root_delta) <= 0.05
    assert wrap["flower_service_start_index"] > 0
    assert wrap["flower_service_centerline"] == wrap["centerline"][
        wrap["flower_service_start_index"]:
    ]
    assert (
        wrap["flower_service_phase_policy"]
        == "first_preselection_centerline_sample_with_normalized_rho_lte_1_80"
    )

    support_metrics = _channel_metrics(
        support["centerline"],
        regions["support_region"],
    )
    wrap_metrics = _channel_metrics(
        wrap["centerline"],
        regions["wrap_region"],
    )
    assert support_metrics["coverage"] >= 0.85
    assert support_metrics["mean_alignment"] >= 0.70
    assert support_metrics["p10_alignment"] >= 0.35
    assert wrap_metrics["coverage"] >= 0.85
    assert wrap_metrics["mean_alignment"] >= 0.70
    assert wrap_metrics["p10_alignment"] >= 0.35

    flower = analysis["flowers"][0]
    contact = support["centerline"][-1]
    expected_contact = [
        float(flower["center"][0]),
        float(flower["center"][1]) + float(flower["ry"]),
    ]
    assert math.dist(contact, expected_contact) <= 0.01
    assert (
        abs(float(contact[0]) - float(flower["center"][0]))
        / float(flower["rx"])
        <= 0.15
    )
    assert (
        abs(float(contact[1]) - expected_contact[1]) / float(flower["ry"])
        <= 0.10
    )
    wrap_stats = ellipse_wrap_stats(
        [tuple(point) for point in wrap["flower_service_centerline"]],
        flower,
    )
    assert 90.0 <= wrap_stats["wrap_span_deg"] <= 180.0
    assert wrap_stats["minimum_rho"] >= 1.00
    assert 1.05 <= wrap_stats["mean_rho"] <= 1.45
    assert wrap_stats["rho_cv"] <= 0.20

    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    assert _self_crossing_count(support["centerline"]) == 0
    assert _self_crossing_count(wrap["centerline"]) == 0
    assert _crossing_count(
        support["centerline"],
        wrap["centerline"],
    ) == 0
    assert _crossing_count(support["centerline"][1:], backbone) == 0
    assert _crossing_count(wrap["centerline"][1:], backbone) == 0
    center = [float(value) for value in flower["center"]]
    rx = float(flower["rx"])
    ry = float(flower["ry"])
    intrusion_count = sum(
        math.hypot(
            (float(point[0]) - center[0]) / rx,
            (float(point[1]) - center[1]) / ry,
        )
        < 1.0 - 1e-9
        for curve in (support, wrap)
        for point in curve["centerline"]
    )
    assert intrusion_count == 0
    x_min, y_min, x_max, y_max = [
        float(value)
        for value in frozen["unit_bounds"]
    ]
    assert all(
        x_min <= float(point[0]) <= x_max
        and y_min <= float(point[1]) <= y_max
        for curve in (support, wrap)
        for point in curve["centerline"]
    )


def test_R2C_candidate_diversity_and_no_posthoc_region_fit() -> None:
    from global_l1_flow import generate_sw1_region_l1_pair

    analysis, _, frozen = _inputs()
    pair = generate_sw1_region_l1_pair(analysis, frozen)
    inventory = pair["candidate_inventory"]
    by_region: dict[str, list[dict[str, Any]]] = {}
    for candidate in inventory:
        by_region.setdefault(candidate["region_id"], []).append(candidate)
        assert candidate["source_region_plan_digest"] == FROZEN_R2B_DIGEST
        assert (
            candidate["generation_policy"]["posthoc_region_fit_used"]
            is False
        )
        assert (
            candidate["generation_policy"][
                "validation_guided_retry_used"
            ]
            is False
        )
    assert all(len(rows) >= 3 for rows in by_region.values())
    assert all(
        len({row["geometry_digest"] for row in rows}) >= 2
        for rows in by_region.values()
    )
    assert (
        len(
            {
                row["source_region_plan_digest"]
                for row in inventory
            }
        )
        == 1
    )
    digest_source = {
        row["candidate_id"]: hashlib.sha256(
            json.dumps(
                row["segments"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        for row in inventory
    }
    assert len(set(digest_source.values())) == len(inventory)
