#!/usr/bin/env python3
"""Independent geometry evaluator for frozen H2-B selected compositions.

This file intentionally does not import selector geometry helpers or trust
selection validity/status fields.  It recomputes the adjudication metrics from
the selected curve coordinates.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from common import ADJUDICATION_DIR, EVALUATOR_VERSION, read_csv, read_json, write_csv, write_json


EPS = 1e-10


def _points(values: Sequence[Sequence[float]], shift_x: float = 0.0) -> np.ndarray:
    points = np.asarray([[float(v[0]) + shift_x, float(v[1])] for v in values], dtype=float)
    if points.ndim != 2 or points.shape[0] < 2 or points.shape[1] != 2:
        raise ValueError("curve centerline must contain at least two 2D points")
    return points


def _cross(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    return first[..., 0] * second[..., 1] - first[..., 1] * second[..., 0]


def _polyline_intersects(first: np.ndarray, second: np.ndarray) -> bool:
    a0, a1 = first[:-1], first[1:]
    b0, b1 = second[:-1], second[1:]
    if (
        float(first[:, 0].max()) < float(second[:, 0].min())
        or float(first[:, 0].min()) > float(second[:, 0].max())
        or float(first[:, 1].max()) < float(second[:, 1].min())
        or float(first[:, 1].min()) > float(second[:, 1].max())
    ):
        return False
    av = a1 - a0
    bv = b1 - b0
    o1 = _cross(av[:, None, :], b0[None, :, :] - a0[:, None, :])
    o2 = _cross(av[:, None, :], b1[None, :, :] - a0[:, None, :])
    o3 = _cross(bv[None, :, :], a0[:, None, :] - b0[None, :, :])
    o4 = _cross(bv[None, :, :], a1[:, None, :] - b0[None, :, :])
    proper = ((o1 > EPS) & (o2 < -EPS) | (o1 < -EPS) & (o2 > EPS)) & (
        (o3 > EPS) & (o4 < -EPS) | (o3 < -EPS) & (o4 > EPS)
    )
    if np.any(proper):
        return True
    # Endpoint/collinear contact is also a crossing for the hard evaluator.
    def on_segment(p: np.ndarray, q: np.ndarray, r: np.ndarray) -> np.ndarray:
        return (
            (q[..., 0] >= np.minimum(p[..., 0], r[..., 0]) - EPS)
            & (q[..., 0] <= np.maximum(p[..., 0], r[..., 0]) + EPS)
            & (q[..., 1] >= np.minimum(p[..., 1], r[..., 1]) - EPS)
            & (q[..., 1] <= np.maximum(p[..., 1], r[..., 1]) + EPS)
        )
    return bool(
        np.any((np.abs(o1) <= EPS) & on_segment(a0[:, None, :], b0[None, :, :], a1[:, None, :]))
        or np.any((np.abs(o2) <= EPS) & on_segment(a0[:, None, :], b1[None, :, :], a1[:, None, :]))
        or np.any((np.abs(o3) <= EPS) & on_segment(b0[None, :, :], a0[:, None, :], b1[None, :, :]))
        or np.any((np.abs(o4) <= EPS) & on_segment(b0[None, :, :], a1[:, None, :], b1[None, :, :]))
    )


def _point_segment_distances(points: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    vectors = end - start
    denominator = np.sum(vectors * vectors, axis=1)
    delta = points[:, None, :] - start[None, :, :]
    projection = np.sum(delta * vectors[None, :, :], axis=2) / np.maximum(denominator[None, :], EPS)
    projection = np.clip(projection, 0.0, 1.0)
    nearest = start[None, :, :] + projection[..., None] * vectors[None, :, :]
    return np.linalg.norm(points[:, None, :] - nearest, axis=2)


def _polyline_distance(first: np.ndarray, second: np.ndarray) -> float:
    if _polyline_intersects(first, second):
        return 0.0
    first_to_second = _point_segment_distances(first, second[:-1], second[1:]).min()
    second_to_first = _point_segment_distances(second, first[:-1], first[1:]).min()
    return float(min(first_to_second, second_to_first))


def _arc_length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _resample_polyline(points: np.ndarray, count: int = 48) -> tuple[np.ndarray, np.ndarray, float]:
    segment_lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    total = float(segment_lengths.sum())
    if total <= EPS:
        raise ValueError("zero-length curve")
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    targets = np.linspace(0.0, total, count)
    output = np.empty((count, 2), dtype=float)
    for index, target in enumerate(targets):
        segment = min(int(np.searchsorted(cumulative, target, side="right") - 1), len(segment_lengths) - 1)
        local = (target - cumulative[segment]) / max(segment_lengths[segment], EPS)
        output[index] = points[segment] * (1.0 - local) + points[segment + 1] * local
    tangents = np.gradient(output, axis=0)
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1, keepdims=True), EPS)
    return output, tangents, total


def _parallel_score(
    first: np.ndarray,
    second: np.ndarray,
    repeat_shifts: Sequence[float],
) -> float:
    points_a, tangents_a, length_a = _resample_polyline(first)
    points_b, tangents_b, length_b = _resample_polyline(second)
    if length_a > length_b:
        points_a, points_b = points_b, points_a
        tangents_a, tangents_b = tangents_b, tangents_a
        length_a = length_b
    nearest_distance = np.full(len(points_a), np.inf)
    nearest_alignment = np.zeros(len(points_a))
    for shift_x in repeat_shifts:
        shifted = points_b + np.asarray((float(shift_x), 0.0))
        distances = np.linalg.norm(points_a[:, None, :] - shifted[None, :, :], axis=2)
        indices = np.argmin(distances, axis=1)
        selected_distances = distances[np.arange(len(points_a)), indices]
        alignments = np.abs(np.sum(tangents_a * tangents_b[indices], axis=1))
        closer = selected_distances < nearest_distance
        nearest_distance[closer] = selected_distances[closer]
        nearest_alignment[closer] = alignments[closer]
    normalized_distance = nearest_distance / max(length_a, EPS)
    return float(np.mean(nearest_alignment**8 / (1.0 + normalized_distance**4)))


def _candidate_pair_metrics(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    repeat_shifts: Sequence[float],
    required_clearance: float,
    parallel_soft_limit: float,
    parallel_maximum: float,
) -> dict[str, Any]:
    base_crossings = 0
    periodic_crossings = 0
    minimum_base = float("inf")
    minimum_periodic = float("inf")
    maximum_parallel = 0.0
    for first_curve in first["curves"]:
        first_points = _points(first_curve["centerline"])
        for second_curve in second["curves"]:
            second_base = _points(second_curve["centerline"])
            for shift_x in repeat_shifts:
                shifted = second_base + np.asarray((float(shift_x), 0.0))
                intersects = _polyline_intersects(first_points, shifted)
                clearance = 0.0 if intersects else _polyline_distance(first_points, shifted)
                if abs(float(shift_x)) <= EPS:
                    base_crossings += int(intersects)
                    minimum_base = min(minimum_base, clearance)
                else:
                    periodic_crossings += int(intersects)
                    minimum_periodic = min(minimum_periodic, clearance)
            if not (first_curve.get("level") == "L1" and second_curve.get("level") == "L1"):
                maximum_parallel = max(
                    maximum_parallel,
                    _parallel_score(first_points, second_base, repeat_shifts),
                )
    minimum_clearance = min(minimum_base, minimum_periodic)
    normalized_penalty = max(0.0, maximum_parallel - parallel_soft_limit) / max(
        parallel_maximum - parallel_soft_limit, 0.01
    )
    return {
        "base_crossing_count": base_crossings,
        "periodic_crossing_count": periodic_crossings,
        "minimum_base_clearance": minimum_base,
        "minimum_periodic_clearance": minimum_periodic,
        "minimum_clearance": minimum_clearance,
        "clearance_violation": minimum_clearance < required_clearance - 1e-9,
        "parallel_score": maximum_parallel,
        "parallel_hard_violation": maximum_parallel > parallel_maximum + 1e-9,
        "normalized_parallel_penalty": normalized_penalty,
    }


def _tangent_at_fraction(points: np.ndarray, fraction: float) -> np.ndarray:
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    target = min(1.0, max(0.0, fraction)) * cumulative[-1]
    index = min(int(np.searchsorted(cumulative, target, side="right") - 1), len(lengths) - 1)
    tangent = points[index + 1] - points[index]
    return tangent / max(float(np.linalg.norm(tangent)), EPS)


def _point_at_fraction(points: np.ndarray, fraction: float) -> np.ndarray:
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    target = min(1.0, max(0.0, fraction)) * cumulative[-1]
    index = min(int(np.searchsorted(cumulative, target, side="right") - 1), len(lengths) - 1)
    local = (target - cumulative[index]) / max(lengths[index], EPS)
    return points[index] * (1.0 - local) + points[index + 1] * local


def _bbox(candidate: Mapping[str, Any]) -> tuple[float, float, float, float]:
    points = np.concatenate([_points(curve["centerline"]) for curve in candidate["curves"]], axis=0)
    return float(points[:, 0].min()), float(points[:, 0].max()), float(points[:, 1].min()), float(points[:, 1].max())


def _bbox_overlap_ratio(first: tuple[float, float, float, float], second: tuple[float, float, float, float], shift: float) -> float:
    ax0, ax1, ay0, ay1 = first
    bx0, bx1, by0, by1 = second
    bx0 += shift; bx1 += shift
    overlap_x = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    overlap_y = max(0.0, min(ay1, by1) - max(ay0, by0))
    overlap = overlap_x * overlap_y
    area_a = max((ax1 - ax0) * (ay1 - ay0), EPS)
    area_b = max((bx1 - bx0) * (by1 - by0), EPS)
    return overlap / min(area_a, area_b)


def _occupied_space_balance(candidates: Sequence[Mapping[str, Any]]) -> float:
    points = np.concatenate(
        [_points(curve["centerline"]) for candidate in candidates for curve in candidate["curves"]],
        axis=0,
    )
    center = np.median(points, axis=0)
    bins = np.zeros(4, dtype=float)
    for point in points:
        index = int(point[0] >= center[0]) + 2 * int(point[1] >= center[1])
        bins[index] += 1.0
    probabilities = bins[bins > 0] / bins.sum()
    return float(-np.sum(probabilities * np.log(probabilities)) / math.log(4.0))


def _local_l2_rows(candidate: Mapping[str, Any], method: str, pair_id: str) -> list[dict[str, Any]]:
    curves = {str(curve["curve_id"]): curve for curve in candidate["curves"]}
    radii = {
        str(tube["curve_id"]): float(tube["radius"])
        for tube in candidate.get("occupancy_tubes", [])
    }
    rows: list[dict[str, Any]] = []
    l2_curves = [curve for curve in candidate["curves"] if curve.get("level") == "L2"]
    sibling_clearance = None
    if len(l2_curves) >= 2:
        sibling_clearance = min(
            _polyline_distance(_points(first["centerline"]), _points(second["centerline"]))
            for index, first in enumerate(l2_curves)
            for second in l2_curves[index + 1 :]
        )
    for child in candidate["curves"]:
        if child.get("level") != "L2":
            continue
        parent = curves[str(child["parent_curve_id"])]
        child_points = _points(child["centerline"])
        parent_points = _points(parent["centerline"])
        child_length = _arc_length(child_points)
        parent_length = _arc_length(parent_points)
        p0 = np.asarray(child["cubic_segments"][0]["p0"], dtype=float)
        p1 = np.asarray(child["cubic_segments"][0]["p1"], dtype=float)
        child_tangent = p1 - p0
        child_tangent /= max(float(np.linalg.norm(child_tangent)), EPS)
        parent_tangent = _tangent_at_fraction(parent_points, float(child["mount_fraction"]))
        expected_root = _point_at_fraction(parent_points, float(child["mount_fraction"]))
        attachment_error = float(np.linalg.norm(p0 - expected_root))
        opening = math.degrees(
            math.acos(float(np.clip(np.dot(parent_tangent, child_tangent), -1.0, 1.0)))
        )
        parent_distances = _point_segment_distances(
            child_points, parent_points[:-1], parent_points[1:]
        ).min(axis=1)
        required = 2.0 * max(
            radii.get(str(child["curve_id"]), 0.0),
            radii.get(str(parent["curve_id"]), 0.0),
        )
        first_clear = next(
            (index for index, value in enumerate(parent_distances[1:], 1) if value >= required),
            None,
        )
        if first_clear is None:
            clearance_margin = float(np.max(parent_distances) - required)
        else:
            clearance_margin = float(np.min(parent_distances[first_clear:]) - required)
        rows.append(
            {
                "pair_id": pair_id,
                "method": method,
                "source_lane_id": str(candidate["source_lane_id"]),
                "candidate_id": str(candidate["candidate_id"]),
                "child_curve_id": str(child["curve_id"]),
                "child_parent_length_ratio": child_length / max(parent_length, EPS),
                "entry_opening_degrees": opening,
                "clearance_margin": clearance_margin,
                "child_parent_clearance": clearance_margin + required,
                "parent_child_attachment_error": attachment_error,
                "sibling_clearance": sibling_clearance,
            }
        )
    return rows


def _evaluate_selection(
    candidates: Sequence[Mapping[str, Any]],
    *,
    method: str,
    pair_id: str,
    repeat_shifts: Sequence[float],
    required_clearance: float,
    parallel_soft_limit: float,
    parallel_maximum: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lane_ids = [str(candidate["source_lane_id"]) for candidate in candidates]
    geometry_evaluable = bool(candidates) and len(lane_ids) == len(set(lane_ids))
    if not geometry_evaluable:
        return {
            "geometry_evaluable": False,
            "selected_unit_count": len(candidates),
        }, []
    pair_rows = [
        _candidate_pair_metrics(
            first,
            second,
            repeat_shifts=repeat_shifts,
            required_clearance=required_clearance,
            parallel_soft_limit=parallel_soft_limit,
            parallel_maximum=parallel_maximum,
        )
        for index, first in enumerate(candidates)
        for second in candidates[index + 1 :]
    ]
    base_crossings = sum(int(row["base_crossing_count"]) for row in pair_rows)
    periodic_crossings = sum(int(row["periodic_crossing_count"]) for row in pair_rows)
    clearance_violations = sum(bool(row["clearance_violation"]) for row in pair_rows)
    parallel_hard = sum(bool(row["parallel_hard_violation"]) for row in pair_rows)
    total_penalty = sum(float(row["normalized_parallel_penalty"]) for row in pair_rows)
    peak_penalty = max((float(row["normalized_parallel_penalty"]) for row in pair_rows), default=0.0)
    minimum_clearance = min((float(row["minimum_clearance"]) for row in pair_rows), default=float("inf"))
    local_crowding_pair_count = sum(
        float(row["minimum_clearance"]) < 1.5 * required_clearance
        for row in pair_rows
    )
    boxes = [_bbox(candidate) for candidate in candidates]
    bbox_overlap_total = sum(
        max(_bbox_overlap_ratio(first, second, float(shift)) for shift in repeat_shifts)
        for index, first in enumerate(boxes)
        for second in boxes[index + 1 :]
    )
    l2_counts = [
        sum(curve.get("level") == "L2" for curve in candidate["curves"])
        for candidate in candidates
    ]
    turn_signs = [
        [int(curve["turn_sign"]) for curve in candidate["curves"] if curve.get("level") == "L2"]
        for candidate in candidates
    ]
    local_rows = [
        row
        for candidate in candidates
        for row in _local_l2_rows(candidate, method, pair_id)
    ]
    attachment_invalid_count = sum(
        float(row["parent_child_attachment_error"]) > 2e-6 for row in local_rows
    )
    return {
        "geometry_evaluable": True,
        "selected_unit_count": len(candidates),
        "cross_unit_curve_crossing_count": base_crossings,
        "periodic_repeat_crossing_count": periodic_crossings,
        "minimum_cross_unit_clearance": minimum_clearance,
        "clearance_violation_count": clearance_violations,
        "parallel_hard_violation_count": parallel_hard,
        "parent_child_attachment_invalid_count": attachment_invalid_count,
        "hard_violation": bool(base_crossings or periodic_crossings or clearance_violations or parallel_hard or attachment_invalid_count),
        "total_parallel_penalty": total_penalty,
        "peak_parallel_penalty": peak_penalty,
        "local_crowding_pair_count": local_crowding_pair_count,
        "spatial_bbox_overlap_tendency": bbox_overlap_total,
        "occupied_space_balance": _occupied_space_balance(candidates),
        "upgraded_lane_count": sum(count > 0 for count in l2_counts),
        "selected_L2_count": sum(l2_counts),
        "L1_only_count": sum(count == 0 for count in l2_counts),
        "single_L2_unit_count": sum(count == 1 for count in l2_counts),
        "opposed_pair_unit_count": sum(
            count == 2 and len(signs) == 2 and signs[0] != signs[1]
            for count, signs in zip(l2_counts, turn_signs)
        ),
    }, local_rows


def run(h2b_dir: Path) -> None:
    case_rows = read_csv(h2b_dir / "cases.csv")
    paired_rows: list[dict[str, Any]] = []
    local_rows: list[dict[str, Any]] = []
    for case in case_rows:
        pair_id = case["pair_id"]
        input_name = case.get("evaluation_input_file", "")
        if not input_name:
            paired_rows.append(
                {
                    "pair_id": pair_id,
                    "prototype_id": case["prototype_id"],
                    "backbone_variant": case["backbone_variant"],
                    "density_level": case["density_level"],
                    "production_seed": case["production_seed"],
                    "old_geometry_evaluable": False,
                    "h2_geometry_evaluable": False,
                    "evaluation_error": case.get("upstream_error", "missing evaluation input"),
                }
            )
            continue
        data = read_json(h2b_dir / input_name)
        common_args = {
            "pair_id": pair_id,
            "repeat_shifts": [float(value) for value in data["repeat_shifts"]],
            "required_clearance": float(data["minimum_clearance_required"]),
            "parallel_soft_limit": float(data["parallel_soft_limit"]),
            "parallel_maximum": float(data["parallel_maximum"]),
        }
        old, old_local = _evaluate_selection(
            data["old"]["selected_candidates"], method="old", **common_args
        )
        h2, h2_local = _evaluate_selection(
            data["h2"]["selected_candidates"], method="h2", **common_args
        )
        local_rows.extend(old_local)
        local_rows.extend(h2_local)
        row: dict[str, Any] = {
            "pair_id": pair_id,
            "prototype_id": case["prototype_id"],
            "backbone_variant": case["backbone_variant"],
            "density_level": case["density_level"],
            "replicate": case["replicate"],
            "production_seed": case["production_seed"],
            "minimum_clearance_required": common_args["required_clearance"],
            "parallel_soft_limit": common_args["parallel_soft_limit"],
            "parallel_maximum": common_args["parallel_maximum"],
        }
        for prefix, metrics in (("old", old), ("h2", h2)):
            for name, value in metrics.items():
                row[f"{prefix}_{name}"] = value
        if old.get("geometry_evaluable") and h2.get("geometry_evaluable"):
            row["delta_total"] = h2["total_parallel_penalty"] - old["total_parallel_penalty"]
            row["delta_peak"] = h2["peak_parallel_penalty"] - old["peak_parallel_penalty"]
            row["relative_total_penalty_reduction"] = (
                (old["total_parallel_penalty"] - h2["total_parallel_penalty"])
                / old["total_parallel_penalty"]
                if old["total_parallel_penalty"] > EPS
                else ""
            )
            row["relative_peak_penalty_reduction"] = (
                (old["peak_parallel_penalty"] - h2["peak_parallel_penalty"])
                / old["peak_parallel_penalty"]
                if old["peak_parallel_penalty"] > EPS
                else ""
            )
        old_trace = data["old"].get("solver_trace", {})
        h2_trace = data["h2"].get("solver_trace", {})
        row["old_search_node_count"] = old_trace.get("search_node_count", "")
        row["h2_search_node_count"] = h2_trace.get("search_node_count", "")
        row["old_backtrack_count"] = old_trace.get("backtrack_count", "")
        row["h2_backtrack_count"] = h2_trace.get("backtrack_count", "")
        row["h2_node_limit_reached"] = h2_trace.get("node_limit_reached", "")
        row["old_runtime_seconds"] = data["old"].get("runtime_seconds", "")
        row["h2_runtime_seconds"] = data["h2"].get("runtime_seconds", "")
        paired_rows.append(row)

    fields = (
        "pair_id", "prototype_id", "backbone_variant", "density_level", "replicate",
        "production_seed", "minimum_clearance_required", "parallel_soft_limit", "parallel_maximum",
        "old_geometry_evaluable", "h2_geometry_evaluable", "evaluation_error",
        "old_cross_unit_curve_crossing_count", "h2_cross_unit_curve_crossing_count",
        "old_periodic_repeat_crossing_count", "h2_periodic_repeat_crossing_count",
        "old_minimum_cross_unit_clearance", "h2_minimum_cross_unit_clearance",
        "old_clearance_violation_count", "h2_clearance_violation_count",
        "old_parallel_hard_violation_count", "h2_parallel_hard_violation_count",
        "old_parent_child_attachment_invalid_count", "h2_parent_child_attachment_invalid_count",
        "old_hard_violation", "h2_hard_violation",
        "old_total_parallel_penalty", "h2_total_parallel_penalty", "delta_total",
        "relative_total_penalty_reduction",
        "old_peak_parallel_penalty", "h2_peak_parallel_penalty", "delta_peak",
        "relative_peak_penalty_reduction",
        "old_local_crowding_pair_count", "h2_local_crowding_pair_count",
        "old_spatial_bbox_overlap_tendency", "h2_spatial_bbox_overlap_tendency",
        "old_occupied_space_balance", "h2_occupied_space_balance",
        "old_upgraded_lane_count", "h2_upgraded_lane_count",
        "old_selected_L2_count", "h2_selected_L2_count",
        "old_L1_only_count", "h2_L1_only_count",
        "old_single_L2_unit_count", "h2_single_L2_unit_count",
        "old_opposed_pair_unit_count", "h2_opposed_pair_unit_count",
        "old_search_node_count", "h2_search_node_count", "old_backtrack_count", "h2_backtrack_count",
        "h2_node_limit_reached", "old_runtime_seconds", "h2_runtime_seconds",
    )
    write_csv(h2b_dir / "paired_metrics.csv", paired_rows, fields)
    write_csv(
        h2b_dir / "local_l2_metrics.csv",
        local_rows,
        (
            "pair_id", "method", "source_lane_id", "candidate_id", "child_curve_id",
            "child_parent_length_ratio", "entry_opening_degrees", "clearance_margin",
            "child_parent_clearance", "parent_child_attachment_error", "sibling_clearance",
        ),
    )
    write_json(
        h2b_dir / "evaluation_manifest.json",
        {
            "evaluator_version": EVALUATOR_VERSION,
            "case_count": len(case_rows),
            "paired_metric_row_count": len(paired_rows),
            "local_l2_metric_row_count": len(local_rows),
            "selector_geometry_helpers_imported": False,
            "repeat_shifts_required": [-1.0, 0.0, 1.0],
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--h2b-dir", type=Path, default=ADJUDICATION_DIR / "h2b")
    args = parser.parse_args()
    run(args.h2b_dir.resolve())
    print(args.h2b_dir.resolve() / "paired_metrics.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
