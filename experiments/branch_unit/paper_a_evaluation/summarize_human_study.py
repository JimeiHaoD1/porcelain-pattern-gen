#!/usr/bin/env python3
"""Summarize returned RQ4 ratings using the frozen participant-level tests."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
from scipy.stats import friedmanchisquare, rankdata, wilcoxon


REPO_ROOT = Path(__file__).resolve().parents[3]
METHODS = ("FixedSlot", "LocalGreedy", "Ours")
DIMENSIONS = (
    "structural_coherence_1_5",
    "visual_balance_1_5",
    "vine_scroll_structural_plausibility_1_5",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


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


def _score(raw: str) -> float | None:
    if not raw.strip():
        return None
    value = float(raw)
    if value < 1 or value > 5:
        raise ValueError(f"rating outside frozen 1-5 scale: {raw!r}")
    return value


def _describe(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(np.mean(array)),
        "std": float(np.std(array, ddof=1)) if len(array) > 1 else 0.0,
        "median": float(np.median(array)),
        "q25": float(np.quantile(array, 0.25)),
        "q75": float(np.quantile(array, 0.75)),
    }


def _matched_rank_biserial(first: np.ndarray, second: np.ndarray) -> float:
    differences = first - second
    differences = differences[np.abs(differences) > 1e-12]
    if not len(differences):
        return 0.0
    ranks = rankdata(np.abs(differences), method="average")
    positive = float(ranks[differences > 0].sum())
    negative = float(ranks[differences < 0].sum())
    return (positive - negative) / max(positive + negative, 1e-12)


def _holm_adjust(rows: list[dict[str, object]]) -> None:
    order = sorted(range(len(rows)), key=lambda index: float(rows[index]["p_raw"]))
    running = 0.0
    total = len(rows)
    for rank, index in enumerate(order):
        adjusted = min(1.0, (total - rank) * float(rows[index]["p_raw"]))
        running = max(running, adjusted)
        rows[index]["p_holm"] = running


def run(ratings_csv: Path, blind_key_csv: Path, output_dir: Path) -> bool:
    ratings = _read_csv(ratings_csv)
    key_rows = _read_csv(blind_key_csv)
    key = {
        (row["blind_stimulus_id"], row["order_form"], row["panel_label"]): row["method"]
        for row in key_rows
    }

    scored_rows: list[dict[str, object]] = []
    for row in ratings:
        scores = {dimension: _score(row.get(dimension, "")) for dimension in DIMENSIONS}
        if all(value is None for value in scores.values()):
            continue
        if any(value is None for value in scores.values()):
            raise ValueError(
                "partially filled panel rating: "
                f"{row['participant_id']} {row['blind_stimulus_id']} {row['panel_label']}"
            )
        key_tuple = (row["blind_stimulus_id"], row["order_form"], row["panel_label"])
        if key_tuple not in key:
            raise ValueError(f"blind key missing {key_tuple}")
        scored_rows.append({**row, "method": key[key_tuple], **scores})

    if not scored_rows:
        print("PENDING: ratings_raw.csv contains no participant scores")
        return False

    by_triplet: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in scored_rows:
        by_triplet[(str(row["participant_id"]), str(row["blind_stimulus_id"]))].append(row)
    complete_triplets = {
        key_tuple: rows
        for key_tuple, rows in by_triplet.items()
        if len(rows) == 3 and {str(row["method"]) for row in rows} == set(METHODS)
    }
    complete_count = CounterLike()
    for participant_id, _ in complete_triplets:
        complete_count[participant_id] += 1
    eligible_participants = {
        participant_id for participant_id, count in complete_count.items() if count >= 12
    }

    participant_values: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for (participant_id, _), triplet_rows in complete_triplets.items():
        if participant_id not in eligible_participants:
            continue
        for row in triplet_rows:
            for dimension in DIMENSIONS:
                participant_values[(participant_id, str(row["method"]), dimension)].append(
                    float(row[dimension])
                )

    participant_rows: list[dict[str, object]] = []
    for participant_id in sorted(eligible_participants):
        for method in METHODS:
            for dimension in DIMENSIONS:
                values = participant_values[(participant_id, method, dimension)]
                if values:
                    participant_rows.append(
                        {
                            "participant_id": participant_id,
                            "complete_triplet_count": complete_count[participant_id],
                            "method": method,
                            "dimension": dimension,
                            "participant_mean_score": float(np.mean(values)),
                        }
                    )
    _write_csv(output_dir / "participant_method_scores.csv", participant_rows)

    lookup = {
        (str(row["participant_id"]), str(row["method"]), str(row["dimension"])): float(
            row["participant_mean_score"]
        )
        for row in participant_rows
    }
    summary_rows: list[dict[str, object]] = []
    test_rows: list[dict[str, object]] = []
    for dimension in DIMENSIONS:
        paired_participants = [
            participant_id
            for participant_id in sorted(eligible_participants)
            if all((participant_id, method, dimension) in lookup for method in METHODS)
        ]
        arrays = {
            method: np.asarray(
                [lookup[(participant_id, method, dimension)] for participant_id in paired_participants],
                dtype=np.float64,
            )
            for method in METHODS
        }
        for method in METHODS:
            summary_rows.append(
                {
                    "dimension": dimension,
                    "method": method,
                    "participant_n": len(paired_participants),
                    **_describe(arrays[method]),
                }
            )
        if len(paired_participants) < 2:
            continue
        friedman = friedmanchisquare(*(arrays[method] for method in METHODS))
        kendall_w = float(friedman.statistic) / (len(paired_participants) * (len(METHODS) - 1))
        test_rows.append(
            {
                "dimension": dimension,
                "test": "Friedman",
                "comparison": "FixedSlot;LocalGreedy;Ours",
                "participant_n": len(paired_participants),
                "statistic": float(friedman.statistic),
                "p_raw": float(friedman.pvalue),
                "p_holm": "",
                "effect_name": "Kendall_W",
                "effect_value": kendall_w,
                "alpha": 0.05,
            }
        )
        pair_rows: list[dict[str, object]] = []
        for first, second in (("Ours", "FixedSlot"), ("Ours", "LocalGreedy"), ("LocalGreedy", "FixedSlot")):
            result = wilcoxon(arrays[first], arrays[second], alternative="two-sided", zero_method="wilcox")
            pair_rows.append(
                {
                    "dimension": dimension,
                    "test": "Wilcoxon_signed_rank",
                    "comparison": f"{first}-{second}",
                    "participant_n": len(paired_participants),
                    "statistic": float(result.statistic),
                    "p_raw": float(result.pvalue),
                    "effect_name": "matched_rank_biserial_first_minus_second",
                    "effect_value": _matched_rank_biserial(arrays[first], arrays[second]),
                    "alpha": 0.05,
                }
            )
        _holm_adjust(pair_rows)
        test_rows.extend(pair_rows)

    _write_csv(output_dir / "ratings_summary.csv", summary_rows)
    _write_csv(output_dir / "ratings_tests.csv", test_rows)
    _write_csv(
        output_dir / "rating_completion.csv",
        [
            {
                "participant_id": participant_id,
                "complete_triplet_count": complete_count[participant_id],
                "included_in_formal_statistics": int(participant_id in eligible_participants),
            }
            for participant_id in sorted(complete_count)
        ],
    )
    return True


class CounterLike(defaultdict[str, int]):
    def __init__(self) -> None:
        super().__init__(int)


def main() -> int:
    parser = argparse.ArgumentParser()
    default_dir = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq4" / "human_evaluation"
    parser.add_argument("--ratings-csv", type=Path, default=default_dir / "ratings_raw.csv")
    parser.add_argument("--blind-key-csv", type=Path, default=default_dir / "blind_key.csv")
    parser.add_argument("--output-dir", type=Path, default=default_dir)
    args = parser.parse_args()
    run(args.ratings_csv.resolve(), args.blind_key_csv.resolve(), args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
