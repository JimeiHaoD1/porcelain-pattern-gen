#!/usr/bin/env python3
"""Summarize the frozen Matrix-C L1 and BranchUnit ablations."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN_DIR = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq2" / "matrix_c_four_methods"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq2"
DEFAULT_FORMAL_OURS_CSV = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq3" / "raw_results.csv"
BOOTSTRAP_SEED = 20260821
BOOTSTRAP_REPLICATES = 2000

RQ2A_METRICS = {
    "root_coverage_qcov": "higher",
    "root_gap_max": "lower",
    "root_concentration": "lower",
    "l1_layout_minimum_clearance": "higher",
    "l1_layout_parallel_cotravel_total": "lower",
    "l1_layout_parallel_cotravel_peak": "lower",
    "l1_layout_crossing_count": "lower",
    "l1_layout_periodic_crossing_count": "lower",
}
RQ2B_METRICS = {
    "cross_unit_crossing_count": "lower",
    "minimum_cross_unit_clearance": "higher",
    "clearance_violation_count": "lower",
    "parallel_cotravel_total": "lower",
    "parallel_cotravel_peak": "lower",
    "l2_unit_ratio": "descriptive",
    "l2_count": "descriptive",
    "mechanically_legal": "higher",
}
HARD_METRICS = (
    "internal_unit_crossing_count",
    "cross_unit_crossing_count",
    "ordinary_backbone_nonroot_crossing_count",
    "ordinary_support_crossing_count",
    "periodic_crossing_count",
    "clearance_violation_count",
    "flower_region_intrusion_curve_count",
    "periodic_seam_violation_count",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _float(row: Mapping[str, str], metric: str) -> float:
    return float(row[metric])


def _mechanically_legal(row: Mapping[str, str]) -> float:
    return float(
        row.get("mechanical_evaluation_success") == "1"
        and all(int(float(row[metric])) == 0 for metric in HARD_METRICS)
    )


def _enrich(rows: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for source in rows:
        row = dict(source)
        if row.get("mechanical_evaluation_success") == "1":
            row["l2_unit_ratio"] = str(1.0 - float(row["hierarchy_l1_only_ratio"]))
            row["mechanically_legal"] = str(_mechanically_legal(row))
        else:
            row["l2_unit_ratio"] = ""
            row["mechanically_legal"] = ""
        output.append(row)
    return output


def _bootstrap_median_difference(differences: Sequence[float]) -> tuple[float, float]:
    values = np.asarray(differences, dtype=np.float64)
    generator = np.random.default_rng(BOOTSTRAP_SEED)
    indices = generator.integers(0, len(values), size=(BOOTSTRAP_REPLICATES, len(values)))
    medians = np.median(values[indices], axis=1)
    low, high = np.quantile(medians, (0.025, 0.975))
    return float(low), float(high)


def _comparison_rows(
    rows: Sequence[Mapping[str, str]],
    *,
    experiment: str,
    baseline: str,
    ours: str,
    success_field: str,
    metrics: Mapping[str, str],
) -> list[dict[str, object]]:
    by_method = {
        method: {row["case_id"]: row for row in rows if row["method"] == method}
        for method in (baseline, ours)
    }
    planned = sorted(set(by_method[baseline]) & set(by_method[ours]))
    baseline_success = sum(by_method[baseline][case][success_field] == "1" for case in planned)
    ours_success = sum(by_method[ours][case][success_field] == "1" for case in planned)
    paired = [
        case
        for case in planned
        if by_method[baseline][case][success_field] == "1"
        and by_method[ours][case][success_field] == "1"
        and by_method[baseline][case].get("mechanical_evaluation_success") == "1"
        and by_method[ours][case].get("mechanical_evaluation_success") == "1"
    ]
    output: list[dict[str, object]] = [
        {
            "experiment": experiment,
            "comparison": f"{ours}-{baseline}",
            "metric": success_field,
            "desired_direction": "higher",
            "planned_context_count": len(planned),
            "baseline_success_count": baseline_success,
            "baseline_success_rate": baseline_success / len(planned),
            "ours_success_count": ours_success,
            "ours_success_rate": ours_success / len(planned),
            "paired_case_count": len(paired),
        }
    ]
    for metric, direction in metrics.items():
        valid = [
            case
            for case in paired
            if by_method[baseline][case].get(metric, "") != ""
            and by_method[ours][case].get(metric, "") != ""
        ]
        baseline_values = [_float(by_method[baseline][case], metric) for case in valid]
        ours_values = [_float(by_method[ours][case], metric) for case in valid]
        differences = [ours_value - baseline_value for baseline_value, ours_value in zip(baseline_values, ours_values)]
        low, high = _bootstrap_median_difference(differences)
        output.append(
            {
                "experiment": experiment,
                "comparison": f"{ours}-{baseline}",
                "metric": metric,
                "desired_direction": direction,
                "planned_context_count": len(planned),
                "baseline_success_count": baseline_success,
                "ours_success_count": ours_success,
                "paired_case_count": len(valid),
                "baseline_mean": statistics.fmean(baseline_values),
                "baseline_median": statistics.median(baseline_values),
                "ours_mean": statistics.fmean(ours_values),
                "ours_median": statistics.median(ours_values),
                "paired_median_difference": statistics.median(differences),
                "bootstrap_95ci_low": low,
                "bootstrap_95ci_high": high,
                "bootstrap_replicates": BOOTSTRAP_REPLICATES,
                "bootstrap_seed": BOOTSTRAP_SEED,
            }
        )
    return output


def _state(candidate: Mapping[str, object]) -> tuple[int, tuple[int, ...]]:
    turns = tuple(
        sorted(
            int(curve.get("turn_sign", 0))
            for curve in candidate["curves"]  # type: ignore[index]
            if str(curve.get("level")) == "L2"
        )
    )
    hierarchy = candidate["hierarchy"]  # type: ignore[index]
    return int(hierarchy["l2_count"]), turns  # type: ignore[index]


def _paired_state_rows(run_dir: Path, rows: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    by_method = {
        method: {row["case_id"]: row for row in rows if row["method"] == method}
        for method in ("LocalGreedy", "Ours")
    }
    output: list[dict[str, object]] = []
    for case_id in sorted(by_method["Ours"]):
        local_row = by_method["LocalGreedy"][case_id]
        ours_row = by_method["Ours"][case_id]
        if local_row["unit_generation_success"] != "1" or ours_row["unit_generation_success"] != "1":
            continue
        local = json.loads((run_dir / local_row["method_dir"] / "global_unit_selection.json").read_text(encoding="utf-8"))
        ours = json.loads((run_dir / ours_row["method_dir"] / "global_unit_selection.json").read_text(encoding="utf-8"))
        local_states = {str(candidate["source_lane_id"]): _state(candidate) for candidate in local["selected_candidates"]}
        ours_states = {str(candidate["source_lane_id"]): _state(candidate) for candidate in ours["selected_candidates"]}
        lane_ids = sorted(set(local_states) | set(ours_states))
        differing = sum(local_states.get(lane) != ours_states.get(lane) for lane in lane_ids)
        output.append(
            {
                "case_id": case_id,
                "prototype_id": ours_row["prototype_id"],
                "backbone_variant": ours_row["backbone_variant"],
                "density_level": ours_row["density_level"],
                "lane_count": len(lane_ids),
                "different_parent_lane_state_count": differing,
                "different_parent_lane_state_ratio": differing / max(len(lane_ids), 1),
                "local_selection_id": local["selection_id"],
                "ours_selection_id": ours["selection_id"],
            }
        )
    return output


def _figure_cases(rows: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    by_method = {
        method: {row["case_id"]: row for row in rows if row["method"] == method}
        for method in ("IndependentCurve", "FixedSlot", "LocalGreedy", "Ours")
    }
    all_l1_success = [
        case
        for case in sorted(by_method["Ours"])
        if all(by_method[method][case]["l1_generation_success"] == "1" for method in ("IndependentCurve", "FixedSlot", "Ours"))
        and all(by_method[method][case].get("root_coverage_qcov", "") != "" for method in ("IndependentCurve", "FixedSlot", "Ours"))
    ]
    qcov_differences = {
        case: _float(by_method["Ours"][case], "root_coverage_qcov")
        - _float(by_method["FixedSlot"][case], "root_coverage_qcov")
        for case in all_l1_success
    }
    qcov_median = statistics.median(qcov_differences.values())
    figure_a = min(all_l1_success, key=lambda case: (abs(qcov_differences[case] - qcov_median), case))

    all_unit_success = [
        case
        for case in sorted(by_method["Ours"])
        if by_method["LocalGreedy"][case]["unit_generation_success"] == "1"
        and by_method["Ours"][case]["unit_generation_success"] == "1"
        and by_method["LocalGreedy"][case].get("parallel_cotravel_peak", "") != ""
        and by_method["Ours"][case].get("parallel_cotravel_peak", "") != ""
    ]
    peak_differences = {
        case: _float(by_method["LocalGreedy"][case], "parallel_cotravel_peak")
        - _float(by_method["Ours"][case], "parallel_cotravel_peak")
        for case in all_unit_success
    }
    peak_median = statistics.median(peak_differences.values())
    figure_b = min(all_unit_success, key=lambda case: (abs(peak_differences[case] - peak_median), case))
    return [
        {
            "figure_panel": "7a",
            "case_id": figure_a,
            "selection_metric": "Ours-FixedSlot root_coverage_qcov",
            "case_difference": qcov_differences[figure_a],
            "paired_median_difference": qcov_median,
            "IndependentCurve_png": by_method["IndependentCurve"][figure_a]["method_dir"] + "/formal_triple.png",
            "FixedSlot_png": by_method["FixedSlot"][figure_a]["method_dir"] + "/formal_triple.png",
            "Ours_png": by_method["Ours"][figure_a]["method_dir"] + "/formal_triple.png",
        },
        {
            "figure_panel": "7b",
            "case_id": figure_b,
            "selection_metric": "LocalGreedy-Ours parallel_cotravel_peak",
            "case_difference": peak_differences[figure_b],
            "paired_median_difference": peak_median,
            "LocalGreedy_png": by_method["LocalGreedy"][figure_b]["method_dir"] + "/formal_triple.png",
            "Ours_png": by_method["Ours"][figure_b]["method_dir"] + "/formal_triple.png",
        },
    ]


def _failure_rows(rows: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "case_id": row["case_id"],
            "method": row["method"],
            "prototype_id": row["prototype_id"],
            "backbone_variant": row["backbone_variant"],
            "density_level": row["density_level"],
            "l1_generation_success": row["l1_generation_success"],
            "unit_generation_success": row["unit_generation_success"],
            "error_type": row["error_type"],
            "error_message": row["error_message"],
        }
        for row in rows
        if row["generation_success"] != "1"
    ]


def _runtime_summary(rows: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    matrix_a = [row for row in rows if row.get("matrix_id") == "A"]
    scopes: list[tuple[str, str, list[Mapping[str, str]]]] = [("overall", "all", matrix_a)]
    for field in ("prototype_id", "density_level"):
        for value in sorted({row[field] for row in matrix_a}):
            scopes.append((field, value, [row for row in matrix_a if row[field] == value]))
    metrics = (
        "total_runtime_seconds",
        "l1_candidate_count",
        "branchunit_candidate_count",
        "search_node_count",
    )
    output: list[dict[str, object]] = []
    for scope_type, scope_value, selected in scopes:
        result: dict[str, object] = {
            "source_matrix": "Matrix-A",
            "runtime_scope": "full single-repeat production chain",
            "scope_type": scope_type,
            "scope_value": scope_value,
            "case_count": len(selected),
            "search_node_limit_reached_rate": statistics.fmean(
                float(row["search_node_limit_reached"]) for row in selected
            ),
        }
        for metric in metrics:
            values = np.asarray([float(row[metric]) for row in selected], dtype=np.float64)
            result[f"{metric}.mean"] = float(np.mean(values))
            result[f"{metric}.median"] = float(np.median(values))
            result[f"{metric}.q25"] = float(np.quantile(values, 0.25))
            result[f"{metric}.q75"] = float(np.quantile(values, 0.75))
        output.append(result)
    return output


def run(run_dir: Path, output_dir: Path, formal_ours_csv: Path = DEFAULT_FORMAL_OURS_CSV) -> None:
    rows = _enrich(_read_csv(run_dir / "evaluated_results.csv"))
    summary = []
    summary += _comparison_rows(
        rows,
        experiment="RQ2-A",
        baseline="IndependentCurve",
        ours="Ours",
        success_field="l1_generation_success",
        metrics=RQ2A_METRICS,
    )
    summary += _comparison_rows(
        rows,
        experiment="RQ2-A",
        baseline="FixedSlot",
        ours="Ours",
        success_field="l1_generation_success",
        metrics=RQ2A_METRICS,
    )
    summary += _comparison_rows(
        rows,
        experiment="RQ2-B",
        baseline="LocalGreedy",
        ours="Ours",
        success_field="unit_generation_success",
        metrics=RQ2B_METRICS,
    )
    state_rows = _paired_state_rows(run_dir, rows)
    summary.append(
        {
            "experiment": "RQ2-B",
            "comparison": "Ours-LocalGreedy",
            "metric": "different_parent_lane_state_count",
            "desired_direction": "descriptive",
            "paired_case_count": len(state_rows),
            "baseline_mean": "",
            "ours_mean": "",
            "paired_median_difference": statistics.median(
                float(row["different_parent_lane_state_count"]) for row in state_rows
            ),
        }
    )
    _write_csv(output_dir / "raw_results.csv", rows)
    _write_csv(output_dir / "summary.csv", summary)
    _write_csv(output_dir / "paired_case_metrics.csv", state_rows)
    _write_csv(output_dir / "figure_data.csv", _figure_cases(rows))
    _write_csv(output_dir / "failure_cases.csv", _failure_rows(rows))
    _write_csv(output_dir / "computational_overhead.csv", _runtime_summary(_read_csv(formal_ours_csv)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--formal-ours-csv", type=Path, default=DEFAULT_FORMAL_OURS_CSV)
    args = parser.parse_args()
    run(args.run_dir.resolve(), args.output_dir.resolve(), args.formal_ours_csv.resolve())
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
