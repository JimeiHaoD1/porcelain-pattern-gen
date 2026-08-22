#!/usr/bin/env python3
"""Audit the eight legacy real-structure SVGs for Paper A RQ4.

The source SVGs are never rewritten.  Legacy stroke colours are normalized in
this experiment adapter only.  Metrics that require explicit parent links are
reported as exploratory geometric inferences and are excluded from the formal
real/generated comparison.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import chanzhi_sw.chanzhi_svg_skeleton_io as skeleton_io  # noqa: E402

from experiments.branch_unit.paper_a_evaluation.evaluate_formal_cases import (  # noqa: E402
    _arc_length,
    _occupied_area_ratio,
    _point_segment_distances,
    _root_features,
)


LEGACY_ROLE_BY_STROKE = {
    "#ff8300": "primary_branch",
    "#ff7900": "primary_branch",
    "#ff7700": "primary_branch",
    "#008200": "structural_branch",
    "#007700": "structural_branch",
    "#007900": "structural_branch",
    "#ff7bff": "secondary_backbone",
    "#ff78ff": "secondary_backbone",
}

FORMAL_COMPARABLE_METRICS = (
    "l1_count",
    "l2_count",
    "l2_per_l1",
    "ordinary_total_length",
    "ordinary_mean_length",
    "vertical_span",
    "occupied_area_ratio",
)


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _normalized(points: Sequence[tuple[float, float]], left: float, period: float) -> np.ndarray:
    array = np.asarray(points, dtype=np.float64)
    return np.column_stack(((array[:, 0] - left) / period, array[:, 1] / period))


def _endpoint_projection(
    child: np.ndarray,
    parent: np.ndarray,
) -> tuple[float, float, int]:
    """Return distance, normalized parent arclength and child root endpoint."""

    segment_start = parent[:-1]
    segment_end = parent[1:]
    vectors = segment_end - segment_start
    squared = np.maximum(np.sum(vectors * vectors, axis=1), 1e-12)
    segment_lengths = np.linalg.norm(vectors, axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    total = max(float(cumulative[-1]), 1e-12)
    best = (float("inf"), 0.0, 0)
    for endpoint_index in (0, len(child) - 1):
        endpoint = child[endpoint_index]
        position = np.clip(
            np.sum((endpoint - segment_start) * vectors, axis=1) / squared,
            0.0,
            1.0,
        )
        projections = segment_start + position[:, None] * vectors
        distances = np.linalg.norm(projections - endpoint, axis=1)
        segment_index = int(np.argmin(distances))
        candidate = (
            float(distances[segment_index]),
            float(
                (cumulative[segment_index] + position[segment_index] * segment_lengths[segment_index])
                / total
            ),
            endpoint_index,
        )
        if candidate[0] < best[0]:
            best = candidate
    return best


def _describe(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(np.mean(array)),
        "std": float(np.std(array, ddof=1)) if len(array) > 1 else 0.0,
        "median": float(np.median(array)),
        "q25": float(np.quantile(array, 0.25)),
        "q75": float(np.quantile(array, 0.75)),
        "min": float(np.min(array)),
        "max": float(np.max(array)),
    }


def _numeric(rows: Iterable[Mapping[str, str]], metric: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        if metric == "l2_per_l1" and row.get(metric, "") in {"", None}:
            l1 = float(row.get("l1_count", "0") or 0)
            raw = float(row.get("l2_count", "0") or 0) / max(l1, 1.0)
        else:
            raw = row.get(metric, "")
        if raw not in {"", None}:
            values.append(float(raw))
    return values


def audit_reference(svg_path: Path, reference_id: str, occupancy_radius: float) -> dict[str, object]:
    width, height, paths, flowers = skeleton_io._load_skeleton(svg_path, tile_width=100000)
    boundaries = [path for path in paths if path.role == "unit_boundary"]
    if len(boundaries) != 2:
        raise ValueError(f"{svg_path.name}: expected two repeat boundaries, got {len(boundaries)}")
    boundary_x = sorted(float(np.mean(np.asarray(path.points)[:, 0])) for path in boundaries)
    left, right = boundary_x
    period = right - left
    if period <= 0:
        raise ValueError(f"{svg_path.name}: invalid repeat period {period}")

    backbones = [path for path in paths if path.role == "backbone"]
    if len(backbones) != 1:
        raise ValueError(f"{svg_path.name}: expected one primary backbone, got {len(backbones)}")
    backbone = _normalized(backbones[0].points, left, period)
    if backbone[0, 0] > backbone[-1, 0]:
        backbone = backbone[::-1].copy()

    l1_paths = [path for path in paths if path.role == "primary_branch"]
    l2_paths = [path for path in paths if path.role == "scroll_branch"]
    ordinary_paths = l1_paths + l2_paths
    ordinary = [_normalized(path.points, left, period) for path in ordinary_paths]
    l1 = [_normalized(path.points, left, period) for path in l1_paths]
    l2 = [_normalized(path.points, left, period) for path in l2_paths]

    lengths = [_arc_length(points) for points in ordinary]
    all_points = np.concatenate(ordinary, axis=0)
    normalized_height = height / period
    curve_mappings = [{"centerline": points.tolist()} for points in ordinary]

    # Exploratory only: infer a root on the primary backbone from the nearest
    # L1 endpoint.  These legacy files do not contain data-parent-id.
    root_inferences = [_endpoint_projection(points, backbone) for points in l1]
    median_stroke_width = float(
        np.median([path.stroke_width for path in l1_paths if path.stroke_width is not None])
    )
    attachment_tolerance = max(0.015, 1.5 * median_stroke_width / period)
    confident_roots = [
        {"root_s": root_s}
        for distance, root_s, _ in root_inferences
        if distance <= attachment_tolerance
    ]
    root_metrics = _root_features({"lanes": confident_roots})

    # Exploratory only: nearest L1 endpoint relation for each cyan L2 path.
    l2_parent_distances: list[float] = []
    l2_parent_indices: list[int] = []
    for child in l2:
        candidates = [_endpoint_projection(child, parent)[0] for parent in l1]
        if candidates:
            parent_index = int(np.argmin(candidates))
            l2_parent_distances.append(float(candidates[parent_index]))
            l2_parent_indices.append(parent_index)
    child_counts = [0] * len(l1)
    confident_l2 = 0
    for parent_index, distance in zip(l2_parent_indices, l2_parent_distances):
        if distance <= attachment_tolerance:
            child_counts[parent_index] += 1
            confident_l2 += 1

    mean_backbone_excursion = float(
        np.mean(
            [
                _point_segment_distances(points, backbone[:-1], backbone[1:]).min(axis=1).mean()
                for points in ordinary
            ]
        )
    )
    role_counts: dict[str, int] = {}
    for path in paths:
        role_counts[path.role] = role_counts.get(path.role, 0) + 1

    result: dict[str, object] = {
        "reference_id": reference_id,
        "source_file": str(svg_path.resolve()),
        "analysis_role": "DESCRIPTIVE_ONLY_CALIBRATION_INFORMED",
        "independent_evaluation_eligible": 0,
        "period_width_px": period,
        "normalized_canvas_height": normalized_height,
        "l1_count": len(l1),
        "l2_count": len(l2),
        "l2_per_l1": len(l2) / max(len(l1), 1),
        "branchunit_count_evaluated": len(l1),
        "ordinary_total_length": sum(lengths),
        "ordinary_mean_length": float(np.mean(lengths)),
        "mean_backbone_excursion": mean_backbone_excursion,
        "vertical_span": float(all_points[:, 1].max() - all_points[:, 1].min()),
        "occupied_area_ratio": _occupied_area_ratio(
            curve_mappings,
            [0.0, 0.0, 1.0, normalized_height],
            occupancy_radius,
        ),
        "flower_count": len(flowers),
        "secondary_backbone_count": role_counts.get("secondary_backbone", 0),
        "flower_support_count": role_counts.get("structural_branch", 0),
        "wrap_flower_count": role_counts.get("wrap_flower", 0),
        "legacy_color_normalization_applied": 1,
        "explicit_role_metadata_count": 0,
        "explicit_parent_metadata_count": 0,
        "inferred_attachment_tolerance": attachment_tolerance,
        "inferred_l1_root_count": len(confident_roots),
        "inferred_l1_root_ratio": len(confident_roots) / max(len(l1), 1),
        "inferred_l2_parent_count": confident_l2,
        "inferred_l2_parent_ratio": confident_l2 / max(len(l2), 1),
        "inferred_hierarchy_l1_only_ratio": sum(count == 0 for count in child_counts)
        / max(len(child_counts), 1),
        "inferred_hierarchy_single_l2_ratio": sum(count == 1 for count in child_counts)
        / max(len(child_counts), 1),
        "inferred_hierarchy_multi_l2_ratio": sum(count >= 2 for count in child_counts)
        / max(len(child_counts), 1),
    }
    result.update({f"inferred_{key}": value for key, value in root_metrics.items()})
    return result


def run(reference_dir: Path, generated_csv: Path, output_dir: Path, occupancy_radius: float) -> None:
    original_role_map = dict(skeleton_io.ROLE_BY_STROKE)
    skeleton_io.ROLE_BY_STROKE.update(LEGACY_ROLE_BY_STROKE)
    try:
        real_rows = [
            audit_reference(svg_path, f"REAL_{index:02d}", occupancy_radius)
            for index, svg_path in enumerate(sorted(reference_dir.glob("*.svg")), start=1)
        ]
    finally:
        skeleton_io.ROLE_BY_STROKE.clear()
        skeleton_io.ROLE_BY_STROKE.update(original_role_map)

    _write_csv(output_dir / "real_reference_raw.csv", real_rows)

    adjudicated = []
    for row in real_rows:
        adjudicated.append(
            {
                "reference_id": row["reference_id"],
                "source_file": row["source_file"],
                "used_for_rule_or_parameter_calibration": "YES",
                "calibration_evidence": (
                    "Project history: the user's observations from these real-structure annotations "
                    "directly motivated sparse L2 and L1-based complexity rules."
                ),
                "role_review_status": "COMPLETE_WITH_LEGACY_COLOR_NORMALIZATION",
                "parent_relation_status": "NO_EXPLICIT_PARENT_METADATA;EXPLORATORY_INFERENCE_ONLY",
                "independent_evaluation_eligible": 0,
                "analysis_role": "DESCRIPTIVE_ONLY_CALIBRATION_INFORMED",
                "exclusion_reason": (
                    "Calibration-informed set and no explicit data-parent-id; excluded from independent "
                    "hypothesis testing, retained for descriptive structural reference."
                ),
            }
        )
    _write_csv(output_dir / "reference_manifest_adjudicated.csv", adjudicated)

    comparability_rows = [
        {
            "metric": metric,
            "formal_comparison_eligible": 1,
            "basis": "direct role geometry after period normalization",
        }
        for metric in FORMAL_COMPARABLE_METRICS
    ]
    comparability_rows.extend(
        {
            "metric": metric,
            "formal_comparison_eligible": 0,
            "basis": "requires explicit parent topology; exploratory inference is reported separately",
        }
        for metric in (
            "root_position",
            "root_spacing",
            "hierarchy_state",
            "upper_lower_allocation",
        )
    )
    _write_csv(output_dir / "metric_comparability.csv", comparability_rows)

    generated_rows = [
        row
        for row in _read_csv(generated_csv)
        if row.get("generation_success") == "1"
        and row.get("matrix_id", "A") == "A"
        and row.get("backbone_variant") == "expanded"
        and row.get("density_level") == "medium"
    ]
    summary: list[dict[str, object]] = []
    for metric in FORMAL_COMPARABLE_METRICS:
        for group_name, rows in (("real_reference", real_rows), ("generated_ours", generated_rows)):
            values = _numeric(rows, metric)
            if not values:
                continue
            summary.append(
                {
                    "group": group_name,
                    "analysis_role": (
                        "DESCRIPTIVE_CALIBRATION_REFERENCE"
                        if group_name == "real_reference"
                        else "FORMAL_GENERATED_OUTPUT"
                    ),
                    "metric": metric,
                    "n": len(values),
                    **_describe(values),
                    "inferential_test_performed": 0,
                }
            )
    _write_csv(output_dir / "descriptive_comparison_summary.csv", summary)
    _write_csv(output_dir / "summary.csv", summary)
    combined_raw: list[dict[str, object]] = []
    for row in real_rows:
        combined_raw.append(
            {
                "group": "real_reference",
                "sample_id": row["reference_id"],
                "analysis_role": row["analysis_role"],
                **{metric: row[metric] for metric in FORMAL_COMPARABLE_METRICS},
            }
        )
    for row in generated_rows:
        combined_raw.append(
            {
                "group": "generated_ours",
                "sample_id": row["case_id"],
                "analysis_role": "FORMAL_GENERATED_OUTPUT_CANONICAL_CONDITION",
                **{
                    metric: (
                        float(row["l2_count"]) / max(float(row["l1_count"]), 1.0)
                        if metric == "l2_per_l1"
                        else row[metric]
                    )
                    for metric in FORMAL_COMPARABLE_METRICS
                },
            }
        )
    _write_csv(output_dir / "raw_results.csv", combined_raw)
    _write_csv(
        output_dir / "figure_data.csv",
        [
            {
                "figure_panel": "9",
                "status": "NOT_RUN_NO_INDEPENDENT_REFERENCE",
                "independent_reference_count": 0,
                "descriptive_reference_count": len(real_rows),
                "generated_canonical_count": len(generated_rows),
                "reason": (
                    "All eight available annotations informed method calibration and lack explicit "
                    "parent metadata; Figure 9 formal W1 distributions are withheld."
                ),
            }
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-dir", type=Path, default=REPO_ROOT / "data" / "annotation")
    parser.add_argument(
        "--generated-csv",
        type=Path,
        default=REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq3" / "raw_results.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq4",
    )
    parser.add_argument("--occupancy-radius", type=float, default=0.01)
    args = parser.parse_args()
    run(args.reference_dir.resolve(), args.generated_csv.resolve(), args.output_dir.resolve(), args.occupancy_radius)
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
