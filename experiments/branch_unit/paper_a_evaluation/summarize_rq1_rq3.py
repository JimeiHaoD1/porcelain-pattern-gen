#!/usr/bin/env python3
"""Create the frozen descriptive RQ1/RQ3 tables from evaluated formal cases."""

from __future__ import annotations

import argparse
import csv
import itertools
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN_DIR = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq1_rq3" / "formal_ours"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1"

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
STRUCTURAL_FEATURES = (
    "l1_count",
    "l2_count",
    "branchunit_count_evaluated",
    "ordinary_total_length",
    "ordinary_mean_length",
    "root_hist_0",
    "root_hist_1",
    "root_hist_2",
    "root_hist_3",
    "root_hist_4",
    "root_hist_5",
    "root_hist_6",
    "root_hist_7",
    "root_gap_q25",
    "root_gap_q50",
    "root_gap_q75",
    "root_gap_max",
    "vertical_span",
    "occupied_area_ratio",
    "upper_allocation_ratio",
    "hierarchy_l1_only_ratio",
    "hierarchy_single_l2_ratio",
    "hierarchy_opposed_l2_ratio",
)
CONTROL_METRICS = (
    "density_resource_D",
    "l1_count",
    "l2_count",
    "branchunit_count_evaluated",
    "ordinary_total_length",
    "ordinary_mean_length",
    "mean_backbone_excursion",
    "vertical_span",
    "occupied_area_ratio",
    "root_coverage_qcov",
    "root_gap_max",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _value(row: Mapping[str, str], name: str) -> float:
    return float(row[name])


def _describe(values: Sequence[float]) -> dict[str, object]:
    if not values:
        return {"n": 0, "mean": "", "median": "", "minimum": "", "maximum": ""}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def _mechanically_legal(row: Mapping[str, str]) -> bool:
    return (
        row["generation_success"] == "1"
        and row.get("mechanical_evaluation_success") == "1"
        and all(int(float(row[name])) == 0 for name in HARD_METRICS)
    )


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    half_width = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return max(0.0, center - half_width), min(1.0, center + half_width)


def _rq1_summary(rows: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    scopes: list[tuple[str, str, Sequence[Mapping[str, str]]]] = [("overall", "all", rows)]
    for field in ("prototype_id", "backbone_variant", "density_level"):
        for value in sorted({row[field] for row in rows}):
            scopes.append((field, value, [row for row in rows if row[field] == value]))
    output: list[dict[str, object]] = []
    for scope_type, scope_value, selected in scopes:
        planned = len(selected)
        success = sum(row["generation_success"] == "1" for row in selected)
        evaluated = sum(row.get("mechanical_evaluation_success") == "1" for row in selected)
        legal = sum(_mechanically_legal(row) for row in selected)
        success_wilson = _wilson_interval(success, planned)
        legal_wilson = _wilson_interval(legal, planned)
        result: dict[str, object] = {
            "scope_type": scope_type,
            "scope_value": scope_value,
            "planned_count": planned,
            "generation_success_count": success,
            "generation_success_rate": success / planned,
            "generation_success_wilson95_low": success_wilson[0],
            "generation_success_wilson95_high": success_wilson[1],
            "mechanically_evaluated_count": evaluated,
            "mechanically_legal_case_count": legal,
            "mechanically_legal_case_rate": legal / planned,
            "mechanically_legal_wilson95_low": legal_wilson[0],
            "mechanically_legal_wilson95_high": legal_wilson[1],
        }
        for metric in HARD_METRICS:
            values = [int(float(row[metric])) for row in selected if row.get(metric, "") != ""]
            result[f"{metric}.event_count"] = sum(values)
            result[f"{metric}.case_count"] = sum(value > 0 for value in values)
            result[f"{metric}.case_rate"] = sum(value > 0 for value in values) / planned
        for metric in (
            "l1_count",
            "l2_count",
            "branchunit_count_evaluated",
            "ordinary_total_length",
            "vertical_span",
            "occupied_area_ratio",
            "total_runtime_seconds",
            "l1_candidate_count",
            "branchunit_candidate_count",
            "search_node_count",
        ):
            values = [_value(row, metric) for row in selected if row.get(metric, "") != ""]
            described = _describe(values)
            result[f"{metric}.mean"] = described["mean"]
            result[f"{metric}.median"] = described["median"]
            result[f"{metric}.minimum"] = described["minimum"]
            result[f"{metric}.maximum"] = described["maximum"]
        output.append(result)
    return output


def _minmax(rows: Sequence[Mapping[str, str]]) -> dict[str, tuple[float, float]]:
    bounds: dict[str, tuple[float, float]] = {}
    for feature in STRUCTURAL_FEATURES:
        values = [_value(row, feature) for row in rows]
        bounds[feature] = (min(values), max(values))
    return bounds


def _vector(row: Mapping[str, str], bounds: Mapping[str, tuple[float, float]]) -> tuple[float, ...]:
    values: list[float] = []
    for feature in STRUCTURAL_FEATURES:
        value = _value(row, feature)
        low, high = bounds[feature]
        values.append(0.0 if high <= low else (value - low) / (high - low))
    return tuple(values)


def _distance(
    first: Mapping[str, str],
    second: Mapping[str, str],
    bounds: Mapping[str, tuple[float, float]],
) -> float:
    first_vector = _vector(first, bounds)
    second_vector = _vector(second, bounds)
    return statistics.fmean(abs(a - b) for a, b in zip(first_vector, second_vector))


def _rq3_level_summaries(rows_a: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for control, field in (("backbone", "backbone_variant"), ("density", "density_level")):
        for prototype in ("all", *sorted({row["prototype_id"] for row in rows_a})):
            prototype_rows = rows_a if prototype == "all" else [row for row in rows_a if row["prototype_id"] == prototype]
            for level in sorted({row[field] for row in prototype_rows}):
                selected = [row for row in prototype_rows if row[field] == level]
                for metric in CONTROL_METRICS:
                    described = _describe([_value(row, metric) for row in selected])
                    output.append(
                        {
                            "analysis": "level_distribution",
                            "control": control,
                            "prototype_id": prototype,
                            "level": level,
                            "metric": metric,
                            **described,
                        }
                    )
    return output


def _monotonic_density(rows_a: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], dict[str, Mapping[str, str]]] = defaultdict(dict)
    for row in rows_a:
        key = (row["prototype_id"], row["backbone_variant"], row["replicate"])
        groups[key][row["density_level"]] = row
    output: list[dict[str, object]] = []
    for prototype in ("all", *sorted({row["prototype_id"] for row in rows_a})):
        selected_groups = [
            values for key, values in groups.items() if prototype == "all" or key[0] == prototype
        ]
        for metric in CONTROL_METRICS:
            complete = [values for values in selected_groups if all(level in values for level in ("simple", "medium", "rich"))]
            monotonic = sum(
                _value(values["simple"], metric)
                <= _value(values["medium"], metric) + 1e-12
                <= _value(values["rich"], metric) + 1e-12
                for values in complete
            )
            output.append(
                {
                    "analysis": "density_monotonicity",
                    "control": "density",
                    "prototype_id": prototype,
                    "level": "simple<=medium<=rich",
                    "metric": metric,
                    "n": len(complete),
                    "monotonic_triplet_count": monotonic,
                    "monotonic_triplet_fraction": monotonic / max(len(complete), 1),
                }
            )
    return output


def _paired_control_distances(
    rows_a: Sequence[Mapping[str, str]],
    bounds: Mapping[str, tuple[float, float]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    specifications = (
        ("backbone", "backbone_variant", ("expanded", "compact", "swept"), ("prototype_id", "density_level", "replicate")),
        ("density", "density_level", ("simple", "medium", "rich"), ("prototype_id", "backbone_variant", "replicate")),
    )
    for control, field, levels, keys in specifications:
        grouped: dict[tuple[str, ...], dict[str, Mapping[str, str]]] = defaultdict(dict)
        for row in rows_a:
            grouped[tuple(row[key] for key in keys)][row[field]] = row
        for first_level, second_level in itertools.combinations(levels, 2):
            distances = [
                _distance(values[first_level], values[second_level], bounds)
                for values in grouped.values()
                if first_level in values and second_level in values
            ]
            output.append(
                {
                    "analysis": "paired_structural_distance",
                    "control": control,
                    "prototype_id": "all",
                    "level": f"{first_level}|{second_level}",
                    "metric": "numeric_gower_structural_distance",
                    **_describe(distances),
                }
            )
    return output


def _seed_diversity(
    rows_b: Sequence[Mapping[str, str]],
    bounds: Mapping[str, tuple[float, float]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for prototype in sorted({row["prototype_id"] for row in rows_b}):
        selected = [row for row in rows_b if row["prototype_id"] == prototype]
        distances = [
            _distance(first, second, bounds)
            for first, second in itertools.combinations(selected, 2)
        ]
        signatures = {
            tuple(round(_value(row, feature), 6) for feature in STRUCTURAL_FEATURES)
            for row in selected
        }
        output.append(
            {
                "analysis": "seed_diversity",
                "control": "seed",
                "prototype_id": prototype,
                "level": "expanded+medium",
                "metric": "numeric_gower_structural_distance",
                **_describe(distances),
                "specimen_count": len(selected),
                "unique_signature_count": len(signatures),
                "unique_signature_ratio": len(signatures) / max(len(selected), 1),
                "signature_round_decimals": 6,
            }
        )
    return output


def _failure_rows(rows: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in rows:
        codes = [metric for metric in HARD_METRICS if row.get(metric, "") and int(float(row[metric])) > 0]
        if row["generation_success"] != "1" or codes:
            output.append(
                {
                    "case_id": row["case_id"],
                    "prototype_id": row["prototype_id"],
                    "backbone_variant": row["backbone_variant"],
                    "density_level": row["density_level"],
                    "production_seed": row["production_seed"],
                    "generation_success": row["generation_success"],
                    "violation_codes": ";".join(codes),
                    "case_dir": row["case_dir"],
                }
            )
    return output


def run(run_dir: Path, output_root: Path) -> None:
    rows = _read_csv(run_dir / "evaluated_results.csv")
    rows_a = [row for row in rows if row["matrix_id"] == "A"]
    rows_b = [row for row in rows if row["matrix_id"] == "B"]
    if len(rows_a) != 450 or len(rows_b) != 50:
        raise ValueError(f"expected Matrix-A/B = 450/50, got {len(rows_a)}/{len(rows_b)}")
    complete = [row for row in rows if row.get("mechanical_evaluation_success") == "1"]
    bounds = _minmax(complete)

    rq1_dir = output_root / "rq1"
    rq3_dir = output_root / "rq3"
    _write_csv(rq1_dir / "raw_results.csv", rows_a)
    _write_csv(rq1_dir / "summary.csv", _rq1_summary(rows_a))
    _write_csv(rq1_dir / "figure_data.csv", rows_a)
    _write_csv(rq1_dir / "failure_cases.csv", _failure_rows(rows_a))

    rq3_summary = (
        _rq3_level_summaries(rows_a)
        + _monotonic_density(rows_a)
        + _paired_control_distances(rows_a, bounds)
        + _seed_diversity(rows_b, bounds)
    )
    _write_csv(rq3_dir / "raw_results.csv", rows)
    _write_csv(rq3_dir / "summary.csv", rq3_summary)
    _write_csv(rq3_dir / "figure_data.csv", rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    run(args.run_dir.resolve(), args.output_root.resolve())
    print(args.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
