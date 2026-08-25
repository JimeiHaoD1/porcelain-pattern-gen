#!/usr/bin/env python3
"""Summarize the frozen RQ2-B exact-L2 matched-budget results."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_DIR = (
    REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq2_matched_budget"
)
DEFAULT_SOURCE_RUN = (
    REPO_ROOT
    / "artifacts"
    / "paper_a_chapter4_v1"
    / "rq2"
    / "matrix_c_four_methods"
)
BOOTSTRAP_SEED = 20260825
BOOTSTRAP_REPLICATES = 2000
PRIMARY_METRICS = ("parallel_cotravel_total", "parallel_cotravel_peak")


class MatchedBudgetSummaryError(RuntimeError):
    """The matched-budget output is incomplete or internally inconsistent."""


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


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _bootstrap_context_median(values: Sequence[float]) -> tuple[float, float]:
    array = np.asarray(values, dtype=np.float64)
    generator = np.random.default_rng(BOOTSTRAP_SEED)
    indices = generator.integers(
        0, len(array), size=(BOOTSTRAP_REPLICATES, len(array))
    )
    medians = np.median(array[indices], axis=1)
    low, high = np.quantile(medians, (0.025, 0.975))
    return float(low), float(high)


def _natural_reference(source_run: Path) -> list[dict[str, object]]:
    rows = _read_csv(source_run / "evaluated_results.csv")
    by_method = {
        method: {
            row["case_id"]: row
            for row in rows
            if row["method"] == method
            and row["generation_success"] == "1"
            and row.get("mechanical_evaluation_success") == "1"
        }
        for method in ("LocalGreedy", "Ours")
    }
    cases = sorted(set(by_method["LocalGreedy"]) & set(by_method["Ours"]))
    output: list[dict[str, object]] = []
    for metric in PRIMARY_METRICS:
        differences = [
            float(by_method["Ours"][case][metric])
            - float(by_method["LocalGreedy"][case][metric])
            for case in cases
        ]
        low, high = _bootstrap_context_median(differences)
        output.append(
            {
                "diagnostic_id": "natural-budget-reference",
                "comparison": "Ours - LocalGreedy",
                "metric": metric,
                "desired_direction": "lower",
                "planned_context_count": 90,
                "shared_success_count": len(cases),
                "baseline_median": statistics.median(
                    float(by_method["LocalGreedy"][case][metric]) for case in cases
                ),
                "ours_median": statistics.median(
                    float(by_method["Ours"][case][metric]) for case in cases
                ),
                "paired_context_median_difference": statistics.median(differences),
                "bootstrap_95ci_low": low,
                "bootstrap_95ci_high": high,
                "bootstrap_replicates": BOOTSTRAP_REPLICATES,
                "bootstrap_seed": BOOTSTRAP_SEED,
            }
        )
    return output


def run(input_dir: Path, source_run: Path) -> None:
    raw = _read_csv(input_dir / "raw_results.csv")
    metrics = _read_csv(input_dir / "independent_metrics.csv")
    contexts = sorted({row["case_id"] for row in raw})
    if len(contexts) != 90:
        raise MatchedBudgetSummaryError(f"expected 90 contexts, got {len(contexts)}")

    raw_by_key = {
        (row["case_id"], row["method"], int(row["target_l2_count"])): row
        for row in raw
    }
    metric_by_key = {
        (row["case_id"], row["method"], int(row["target_l2_count"])): row
        for row in metrics
    }
    planned_pairs = sorted(
        {
            (row["case_id"], int(row["target_l2_count"]))
            for row in raw
        }
    )

    status_rows: list[dict[str, object]] = []
    for method in ("LocalGreedy@B", "Ours@B"):
        counts = Counter(
            row["selection_status"] for row in raw if row["method"] == method
        )
        for status, count in sorted(counts.items()):
            status_rows.append(
                {
                    "method": method,
                    "selection_status": status,
                    "count": count,
                }
            )

    shared_pairs: list[tuple[str, int]] = []
    for case_id, target in planned_pairs:
        local_key = (case_id, "LocalGreedy@B", target)
        ours_key = (case_id, "Ours@B", target)
        if (
            raw_by_key[local_key]["selection_status"] == "success"
            and raw_by_key[ours_key]["selection_status"] == "success"
            and local_key in metric_by_key
            and ours_key in metric_by_key
        ):
            shared_pairs.append((case_id, target))

    by_context: dict[str, list[tuple[int, dict[str, str], dict[str, str]]]] = defaultdict(list)
    for case_id, target in shared_pairs:
        by_context[case_id].append(
            (
                target,
                metric_by_key[(case_id, "LocalGreedy@B", target)],
                metric_by_key[(case_id, "Ours@B", target)],
            )
        )

    context_rows: list[dict[str, object]] = []
    for case_id in contexts:
        pairs = by_context.get(case_id, [])
        source = next(row for row in raw if row["case_id"] == case_id)
        row: dict[str, object] = {
            "case_id": case_id,
            "prototype_id": source["prototype_id"],
            "backbone_variant": source["backbone_variant"],
            "density_level": source["density_level"],
            "replicate": source["replicate"],
            "shared_success_budget_count": len(pairs),
            "shared_success_budgets": ";".join(str(pair[0]) for pair in pairs),
        }
        for metric in PRIMARY_METRICS:
            differences = [float(ours[metric]) - float(local[metric]) for _, local, ours in pairs]
            row[f"median_difference_{metric}"] = (
                statistics.median(differences) if differences else ""
            )
            row[f"local_median_{metric}"] = (
                statistics.median(float(local[metric]) for _, local, _ in pairs)
                if pairs
                else ""
            )
            row[f"ours_median_{metric}"] = (
                statistics.median(float(ours[metric]) for _, _, ours in pairs)
                if pairs
                else ""
            )
        context_rows.append(row)

    coverage_rows: list[dict[str, object]] = []
    cell_groups: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in context_rows:
        cell_groups[
            (
                str(row["prototype_id"]),
                str(row["backbone_variant"]),
                str(row["density_level"]),
            )
        ].append(row)
    for key, rows in sorted(cell_groups.items()):
        coverage_rows.append(
            {
                "prototype_id": key[0],
                "backbone_variant": key[1],
                "density_level": key[2],
                "planned_replicate_count": len(rows),
                "covered_context_count": sum(
                    int(row["shared_success_budget_count"]) > 0 for row in rows
                ),
                "shared_success_budget_count": sum(
                    int(row["shared_success_budget_count"]) for row in rows
                ),
                "covered": int(
                    any(int(row["shared_success_budget_count"]) > 0 for row in rows)
                ),
            }
        )

    covered_context_rows = [
        row for row in context_rows if int(row["shared_success_budget_count"]) > 0
    ]
    covered_cell_count = sum(int(row["covered"]) for row in coverage_rows)
    summary_rows = _natural_reference(source_run)
    for metric in PRIMARY_METRICS:
        differences = [
            float(row[f"median_difference_{metric}"]) for row in covered_context_rows
        ]
        low, high = _bootstrap_context_median(differences)
        summary_rows.append(
            {
                "diagnostic_id": "MB-L2",
                "comparison": "Ours@B - LocalGreedy@B",
                "metric": metric,
                "desired_direction": "lower",
                "planned_context_count": 90,
                "planned_budget_attempt_count": len(planned_pairs),
                "baseline_success_count": sum(
                    row["method"] == "LocalGreedy@B"
                    and row["selection_status"] == "success"
                    for row in raw
                ),
                "ours_success_count": sum(
                    row["method"] == "Ours@B"
                    and row["selection_status"] == "success"
                    for row in raw
                ),
                "shared_success_count": len(shared_pairs),
                "covered_context_count": len(covered_context_rows),
                "covered_stratum_count": covered_cell_count,
                "baseline_median": statistics.median(
                    float(row[f"local_median_{metric}"]) for row in covered_context_rows
                ),
                "ours_median": statistics.median(
                    float(row[f"ours_median_{metric}"]) for row in covered_context_rows
                ),
                "paired_context_median_difference": statistics.median(differences),
                "bootstrap_95ci_low": low,
                "bootstrap_95ci_high": high,
                "bootstrap_replicates": BOOTSTRAP_REPLICATES,
                "bootstrap_seed": BOOTSTRAP_SEED,
            }
        )

    mechanical_pair_counts: Counter[tuple[int, int]] = Counter()
    for case_id, target in shared_pairs:
        local = metric_by_key[(case_id, "LocalGreedy@B", target)]
        ours = metric_by_key[(case_id, "Ours@B", target)]
        mechanical_pair_counts[
            (
                int(float(local["mechanically_legal"])),
                int(float(ours["mechanically_legal"])),
            )
        ] += 1
    additional_illegal_pairs = mechanical_pair_counts[(1, 0)]

    mb_summary = {row["metric"]: row for row in summary_rows if row["diagnostic_id"] == "MB-L2"}
    numerical_coordination_gate = all(
        float(mb_summary[metric]["bootstrap_95ci_high"]) < 0
        for metric in PRIMARY_METRICS
    )
    coverage_gate = covered_cell_count == 45
    mechanical_gate = additional_illegal_pairs == 0
    natural_summary = {
        row["metric"]: row
        for row in summary_rows
        if row["diagnostic_id"] == "natural-budget-reference"
    }
    natural_improvement_gate = all(
        float(natural_summary[metric]["bootstrap_95ci_high"]) < 0
        for metric in PRIMARY_METRICS
    )
    if not coverage_gate or not mechanical_gate:
        protocol_decision_candidate = "MIXED_EVIDENCE"
    elif numerical_coordination_gate:
        protocol_decision_candidate = "COORDINATION_SUPPORTED"
    elif natural_improvement_gate:
        protocol_decision_candidate = "SELECTIVE_SPARSIFICATION_ONLY"
    else:
        protocol_decision_candidate = "MIXED_EVIDENCE"

    if not coverage_gate:
        diagnostic_status = "PARTIAL_COVERAGE"
    elif not mechanical_gate:
        diagnostic_status = "MECHANICAL_GATE_FAILED"
    else:
        diagnostic_status = "PRIMARY_DIAGNOSTIC_INTERPRETABLE"

    _write_csv(input_dir / "summary.csv", summary_rows)
    _write_csv(input_dir / "context_effects.csv", context_rows)
    _write_csv(input_dir / "coverage.csv", coverage_rows)
    _write_csv(input_dir / "status_counts.csv", status_rows)
    _write_json(
        input_dir / "result_gate.json",
        {
            "schema": "paper_a_rq2_mb_l2_result_gate_v1",
            "run_complete": len(contexts) == 90,
            "planned_context_count": 90,
            "planned_budget_pair_count": len(planned_pairs),
            "shared_success_pair_count": len(shared_pairs),
            "covered_context_count": len(covered_context_rows),
            "covered_cell_count": covered_cell_count,
            "coverage_gate": coverage_gate,
            "additional_mechanical_illegal_pair_count": additional_illegal_pairs,
            "mechanical_pair_contingency": {
                "both_legal": mechanical_pair_counts[(1, 1)],
                "local_illegal_ours_legal": mechanical_pair_counts[(0, 1)],
                "local_legal_ours_illegal": mechanical_pair_counts[(1, 0)],
                "both_illegal": mechanical_pair_counts[(0, 0)],
            },
            "mechanical_gate": mechanical_gate,
            "numerical_coordination_gate": numerical_coordination_gate,
            "natural_improvement_gate": natural_improvement_gate,
            "primary_diagnostic_status": diagnostic_status,
            "protocol_decision_candidate": protocol_decision_candidate,
            "scientific_interpretation": "RESULT_REVIEW_PENDING",
            "visual_status": "VISUAL_REVIEW_PENDING",
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE_RUN)
    args = parser.parse_args()
    run(args.input_dir.resolve(), args.source_run.resolve())
    print(args.input_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
