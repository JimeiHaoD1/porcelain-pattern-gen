#!/usr/bin/env python3
"""Descriptive summaries and figures for the revised H2 adjudication."""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

from common import ADJUDICATION_DIR, DENSITY_LEVELS, PROTOTYPE_IDS, mean, median, read_csv, write_json


OLD_COLOR = "#7b8790"
NEW_COLOR = "#d28a58"
ACCENT = "#4f7f8f"
mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Microsoft YaHei", "DejaVu Sans"],
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "font.size": 8,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "axes.linewidth": 0.8,
        "legend.frameon": False,
    }
)


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _values(rows: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    return [value for row in rows if (value := _float(row.get(field))) is not None]


def _diffs(rows: Sequence[Mapping[str, Any]], old: str, new: str) -> list[float]:
    result = []
    for row in rows:
        old_value, new_value = _float(row.get(old)), _float(row.get(new))
        if old_value is not None and new_value is not None:
            result.append(new_value - old_value)
    return result


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "minimum": None, "maximum": None}
    return {
        "n": len(values),
        "mean": mean(values),
        "median": median(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".tiff"), dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _paired_outcome(
    rows: Sequence[Mapping[str, Any]],
    old_field: str,
    new_field: str,
    *,
    lower_is_better: bool,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    new_better = tie = old_better = 0
    differences: list[float] = []
    for row in rows:
        old, new = _float(row.get(old_field)), _float(row.get(new_field))
        if old is None or new is None:
            continue
        delta = new - old
        differences.append(delta)
        if abs(delta) <= tolerance:
            tie += 1
        elif (delta < 0) == lower_is_better:
            new_better += 1
        else:
            old_better += 1
    return {
        "n": len(differences),
        "NEW_better": new_better,
        "tie": tie,
        "OLD_better": old_better,
        "median_NEW_minus_OLD": median(differences),
        "mean_NEW_minus_OLD": mean(differences),
    }


def _grouped_outcomes(
    rows: Sequence[Mapping[str, Any]],
    old_field: str,
    new_field: str,
    *,
    lower_is_better: bool,
) -> dict[str, Any]:
    group_fields = {
        "prototype": "prototype_id",
        "density": "density_level",
        "backbone_variant": "backbone_variant",
    }
    result = {
        "overall": _paired_outcome(rows, old_field, new_field, lower_is_better=lower_is_better)
    }
    for label, field in group_fields.items():
        groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[str(row[field])].append(row)
        result[label] = {
            key: _paired_outcome(group, old_field, new_field, lower_is_better=lower_is_better)
            for key, group in sorted(groups.items())
        }
    return result


def _monotonic_summary(rows: Sequence[Mapping[str, Any]], method: str) -> dict[str, Any]:
    by_context: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_context[row["context_id"]][row["density_level"]] = row
    evaluable = monotonic = 0
    for levels in by_context.values():
        values = [_float(levels.get(level, {}).get(f"{method}_composite_resource_score")) for level in DENSITY_LEVELS]
        if all(value is not None for value in values):
            evaluable += 1
            monotonic += int(values[0] <= values[1] + 1e-9 <= values[2] + 2e-9)
    return {
        "context_count": len(by_context),
        "evaluable_triplet_count": evaluable,
        "monotonic_triplet_count": monotonic,
        "monotonic_rate": monotonic / evaluable if evaluable else 0.0,
    }


def _h2a_summary(h2a_dir: Path) -> dict[str, Any]:
    rows = read_csv(h2a_dir / "paired_metrics.csv")
    paired = [row for row in rows if _bool(row.get("old_selection_success")) and _bool(row.get("h2_selection_success"))]
    by_context: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in paired:
        by_context[row["context_id"]][row["density_level"]] = row
    same_count_rows = []
    for context_id, levels in by_context.items():
        for first, second in (("simple", "medium"), ("medium", "rich")):
            a, b = levels.get(first), levels.get(second)
            if not a or not b:
                continue
            count_a, count_b = _float(a.get("h2_selected_L1_count")), _float(b.get("h2_selected_L1_count"))
            resource_a, resource_b = _float(a.get("h2_composite_resource_score")), _float(b.get("h2_composite_resource_score"))
            if None not in (count_a, count_b, resource_a, resource_b) and int(count_a) == int(count_b):
                delta = float(resource_b) - float(resource_a)
                same_count_rows.append(
                    {
                        "context_id": context_id,
                        "density_pair": f"{first}->{second}",
                        "L1_count": int(count_a),
                        "resource_change": delta,
                        "positive_change": delta > 1e-9,
                    }
                )
    per_prototype = {}
    for prototype_id in PROTOTYPE_IDS:
        subset = [row for row in paired if row["prototype_id"] == prototype_id]
        per_prototype[prototype_id] = {
            "paired_conditions": len(subset),
            "old_monotonic": _monotonic_summary(subset, "old"),
            "new_monotonic": _monotonic_summary(subset, "h2"),
            "structural_score_difference": _distribution(_diffs(subset, "old_structural_score", "h2_structural_score")),
            "minimum_lane_clearance_difference": _distribution(_diffs(subset, "old_minimum_lane_clearance", "h2_minimum_lane_clearance")),
        }
    summary = {
        "intended_condition_count": len(rows),
        "paired_evaluable_count": len(paired),
        "success_rate": {
            "OLD": sum(_bool(row.get("old_selection_success")) for row in rows) / len(rows) if rows else 0.0,
            "NEW": sum(_bool(row.get("h2_selection_success")) for row in rows) / len(rows) if rows else 0.0,
        },
        "selected_L1_count_distribution": {
            "OLD": _distribution(_values(paired, "old_selected_L1_count")),
            "NEW": _distribution(_values(paired, "h2_selected_L1_count")),
        },
        "density_resource_distribution": {
            "OLD": _distribution(_values(paired, "old_composite_resource_score")),
            "NEW": _distribution(_values(paired, "h2_composite_resource_score")),
        },
        "monotonic_response": {
            "OLD": _monotonic_summary(paired, "old"),
            "NEW": _monotonic_summary(paired, "h2"),
        },
        "same_count_control": {
            "pair_count": len(same_count_rows),
            "positive_resource_change_count": sum(row["positive_change"] for row in same_count_rows),
            "positive_resource_change_rate": (
                sum(row["positive_change"] for row in same_count_rows) / len(same_count_rows)
                if same_count_rows else 0.0
            ),
            "pairs": same_count_rows,
        },
        "structural_quality": {
            "structural_score_NEW_minus_OLD": _distribution(_diffs(paired, "old_structural_score", "h2_structural_score")),
            "minimum_lane_clearance_NEW_minus_OLD": _distribution(_diffs(paired, "old_minimum_lane_clearance", "h2_minimum_lane_clearance")),
            "OLD_crossings": sum(int(float(row.get("old_curve_crossing_count") or 0)) for row in paired),
            "NEW_crossings": sum(int(float(row.get("h2_curve_crossing_count") or 0)) for row in paired),
            "OLD_periodic_crossings": sum(int(float(row.get("old_periodic_crossing_count") or 0)) for row in paired),
            "NEW_periodic_crossings": sum(int(float(row.get("h2_periodic_crossing_count") or 0)) for row in paired),
            "OLD_flower_intrusions": sum(int(float(row.get("old_flower_reserve_intrusion_count") or 0)) for row in paired),
            "NEW_flower_intrusions": sum(int(float(row.get("h2_flower_reserve_intrusion_count") or 0)) for row in paired),
        },
        "per_prototype": per_prototype,
        "visual_review_status": "PENDING_USER_BLIND_REVIEW",
        "recommendation": "PENDING_USER_BLIND_REVIEW",
    }
    write_json(h2a_dir / "summary.json", summary)
    return summary


def _h2b_summary(h2b_dir: Path) -> dict[str, Any]:
    rows = read_csv(h2b_dir / "paired_metrics.csv")
    paired = [row for row in rows if _bool(row.get("old_geometry_evaluable")) and _bool(row.get("h2_geometry_evaluable"))]
    local_rows = read_csv(h2b_dir / "local_l2_metrics.csv")
    local = {}
    for metric in (
        "child_parent_length_ratio", "entry_opening_degrees", "child_parent_clearance",
        "sibling_clearance", "parent_child_attachment_error",
    ):
        old = _values([row for row in local_rows if row["method"] == "old"], metric)
        new = _values([row for row in local_rows if row["method"] == "h2"], metric)
        local[metric] = {"OLD": _distribution(old), "NEW": _distribution(new)}
    metrics = {
        "total_parallel_co_travel": ("old_total_parallel_penalty", "h2_total_parallel_penalty", True),
        "peak_parallel_co_travel": ("old_peak_parallel_penalty", "h2_peak_parallel_penalty", True),
        "minimum_clearance": ("old_minimum_cross_unit_clearance", "h2_minimum_cross_unit_clearance", False),
        "local_crowding": ("old_local_crowding_pair_count", "h2_local_crowding_pair_count", True),
        "spatial_overlap_tendency": ("old_spatial_bbox_overlap_tendency", "h2_spatial_bbox_overlap_tendency", True),
        "occupied_space_balance": ("old_occupied_space_balance", "h2_occupied_space_balance", False),
        "selected_L2_count": ("old_selected_L2_count", "h2_selected_L2_count", False),
        "upgraded_lane_count": ("old_upgraded_lane_count", "h2_upgraded_lane_count", False),
    }
    outcome = {
        name: _grouped_outcomes(paired, old, new, lower_is_better=lower)
        for name, (old, new, lower) in metrics.items()
    }
    summary = {
        "intended_case_count": len(rows),
        "paired_evaluable_count": len(paired),
        "structural_validity": {
            "OLD_hard_violation_cases": sum(_bool(row.get("old_hard_violation")) for row in paired),
            "NEW_hard_violation_cases": sum(_bool(row.get("h2_hard_violation")) for row in paired),
            "OLD_crossings": sum(int(float(row.get("old_cross_unit_curve_crossing_count") or 0)) for row in paired),
            "NEW_crossings": sum(int(float(row.get("h2_cross_unit_curve_crossing_count") or 0)) for row in paired),
            "OLD_periodic_crossings": sum(int(float(row.get("old_periodic_repeat_crossing_count") or 0)) for row in paired),
            "NEW_periodic_crossings": sum(int(float(row.get("h2_periodic_repeat_crossing_count") or 0)) for row in paired),
            "OLD_attachment_invalid": sum(int(float(row.get("old_parent_child_attachment_invalid_count") or 0)) for row in paired),
            "NEW_attachment_invalid": sum(int(float(row.get("h2_parent_child_attachment_invalid_count") or 0)) for row in paired),
        },
        "paired_outcomes": outcome,
        "hierarchical_complexity": {
            "OLD_selected_L2": _distribution(_values(paired, "old_selected_L2_count")),
            "NEW_selected_L2": _distribution(_values(paired, "h2_selected_L2_count")),
            "OLD_upgraded_lanes": _distribution(_values(paired, "old_upgraded_lane_count")),
            "NEW_upgraded_lanes": _distribution(_values(paired, "h2_upgraded_lane_count")),
            "OLD_single_L2_units": _distribution(_values(paired, "old_single_L2_unit_count")),
            "NEW_single_L2_units": _distribution(_values(paired, "h2_single_L2_unit_count")),
            "OLD_opposed_pair_units": _distribution(_values(paired, "old_opposed_pair_unit_count")),
            "NEW_opposed_pair_units": _distribution(_values(paired, "h2_opposed_pair_unit_count")),
        },
        "local_geometry": local,
        "runtime": {
            "OLD_seconds": _distribution(_values(paired, "old_runtime_seconds")),
            "NEW_seconds": _distribution(_values(paired, "h2_runtime_seconds")),
            "NEW_search_nodes": _distribution(_values(paired, "h2_search_node_count")),
            "NEW_node_limit_reached_count": sum(_bool(row.get("h2_node_limit_reached")) for row in paired),
        },
        "visual_review_status": "PENDING_USER_BLIND_REVIEW",
        "recommendation": "PENDING_USER_BLIND_REVIEW",
    }
    write_json(h2b_dir / "summary.json", summary)
    return summary


def _figures(root: Path) -> None:
    h2a = read_csv(root / "h2a" / "paired_metrics.csv")
    h2b = read_csv(root / "h2b" / "paired_metrics.csv")
    figures = root / "figures"

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), sharey=True)
    for ax, method, color, title in zip(axes, ("old", "h2"), (OLD_COLOR, NEW_COLOR), ("OLD: cardinality", "NEW: soft density")):
        by_context: dict[str, dict[str, float]] = defaultdict(dict)
        for row in h2a:
            value = _float(row.get(f"{method}_composite_resource_score"))
            if value is not None:
                by_context[row["context_id"]][row["density_level"]] = value
        for levels in by_context.values():
            if all(level in levels for level in DENSITY_LEVELS):
                ax.plot(range(3), [levels[level] for level in DENSITY_LEVELS], color=color, alpha=0.28, linewidth=0.7)
        medians = [median([levels[level] for levels in by_context.values() if level in levels]) for level in DENSITY_LEVELS]
        ax.plot(range(3), medians, color=color, linewidth=2.2, marker="o")
        ax.set_xticks(range(3), DENSITY_LEVELS); ax.set_title(title); ax.grid(axis="y", color="#e7eaec", linewidth=0.6)
    axes[0].set_ylabel("Composite density resource")
    fig.suptitle("H2-A density response across all 30 contexts", x=0.08, ha="left", fontweight="bold")
    _save(fig, figures / "h2a_density_response")

    fig, ax = plt.subplots(figsize=(3.8, 3.0))
    for row in h2a:
        old, new = _float(row.get("old_structural_score")), _float(row.get("h2_structural_score"))
        if old is not None and new is not None:
            ax.plot([0, 1], [old, new], color="#c7cdd1", linewidth=0.55, alpha=0.65)
            ax.scatter([0, 1], [old, new], color=[OLD_COLOR, NEW_COLOR], s=10)
    ax.set_xticks([0, 1], ["OLD", "NEW"]); ax.set_ylabel("Common structural score")
    ax.set_title("H2-A structural quality", loc="left", fontweight="bold"); ax.grid(axis="y", color="#e7eaec", linewidth=0.6)
    _save(fig, figures / "h2a_structural_quality")

    fig, axes = plt.subplots(1, 3, figsize=(9.0, 3.0))
    for ax, old_field, new_field, ylabel, title in (
        (axes[0], "old_total_parallel_penalty", "h2_total_parallel_penalty", "Total penalty", "Parallel co-travel"),
        (axes[1], "old_minimum_cross_unit_clearance", "h2_minimum_cross_unit_clearance", "Minimum clearance", "Cross-Unit clearance"),
        (axes[2], "old_selected_L2_count", "h2_selected_L2_count", "Selected L2", "Hierarchy richness"),
    ):
        for row in h2b:
            old, new = _float(row.get(old_field)), _float(row.get(new_field))
            if old is not None and new is not None:
                ax.plot([0, 1], [old, new], color="#c7cdd1", linewidth=0.5, alpha=0.55)
                ax.scatter([0, 1], [old, new], color=[OLD_COLOR, NEW_COLOR], s=9)
        ax.set_xticks([0, 1], ["OLD", "NEW"]); ax.set_ylabel(ylabel); ax.set_title(title); ax.grid(axis="y", color="#e7eaec", linewidth=0.6)
    fig.suptitle("H2-B paired structural coordination", x=0.06, ha="left", fontweight="bold")
    _save(fig, figures / "h2b_coordination_and_complexity")

    fig, ax = plt.subplots(figsize=(3.8, 3.0))
    old = _values(h2b, "old_runtime_seconds"); new = _values(h2b, "h2_runtime_seconds")
    if old and new:
        parts = ax.violinplot([old, new], positions=[0, 1], showmedians=True, widths=0.72)
        for body, color in zip(parts["bodies"], (OLD_COLOR, NEW_COLOR)):
            body.set_facecolor(color); body.set_edgecolor("none"); body.set_alpha(0.6)
    ax.set_xticks([0, 1], ["OLD", "NEW"]); ax.set_ylabel("Selection runtime (s)")
    ax.set_title("H2-B search cost", loc="left", fontweight="bold"); ax.grid(axis="y", color="#e7eaec", linewidth=0.6)
    _save(fig, figures / "h2b_runtime")


def _report(h2a: Mapping[str, Any], h2b: Mapping[str, Any]) -> str:
    a = h2a["monotonic_response"]
    b_total = h2b["paired_outcomes"]["total_parallel_co_travel"]["overall"]
    b_clearance = h2b["paired_outcomes"]["minimum_clearance"]["overall"]
    return f"""# H2 Adjudication Experiment

## 1 Experimental Design

The experiment uses paired comparisons at the fixed production commit. H2-A shares backbone, flower structure, ordinary-L1 candidate pool, conflict relations, and seeds within each OLD/NEW pair. H2-B shares the H2-A L1 plan, complete Stage4 BranchUnit inventory, conflict graph, and unit seed. Production code, contracts, and priors were not changed.

## 2 H2-A

### 2.1 Density response

OLD monotonic simple-to-medium-to-rich response: {a['OLD']['monotonic_triplet_count']}/{a['OLD']['evaluable_triplet_count']} ({a['OLD']['monotonic_rate']:.1%}). NEW: {a['NEW']['monotonic_triplet_count']}/{a['NEW']['evaluable_triplet_count']} ({a['NEW']['monotonic_rate']:.1%}).

### 2.2 Same-count structural control

NEW produced {h2a['same_count_control']['pair_count']} adjacent same-count density pairs; {h2a['same_count_control']['positive_resource_change_count']} changed composite resource in the positive density direction ({h2a['same_count_control']['positive_resource_change_rate']:.1%}).

### 2.3 Structural quality

The median NEW-minus-OLD structural-score difference was {h2a['structural_quality']['structural_score_NEW_minus_OLD']['median']}. Crossing totals were OLD={h2a['structural_quality']['OLD_crossings']} and NEW={h2a['structural_quality']['NEW_crossings']}; periodic crossings were OLD={h2a['structural_quality']['OLD_periodic_crossings']} and NEW={h2a['structural_quality']['NEW_periodic_crossings']}; flower-reserve intrusions were OLD={h2a['structural_quality']['OLD_flower_intrusions']} and NEW={h2a['structural_quality']['NEW_flower_intrusions']}.

### 2.4 Visual comparison materials

Thirty labeled 2×3 context sheets and ninety randomized OLD/NEW blind pairs are provided. Codex did not assign visual preferences.

### 2.5 Summary

**PENDING USER BLIND REVIEW** — final choice must be one of RETAIN, SIMPLIFY, or REVERT after the visual evidence is reviewed.

## 3 H2-B

### 3.1 Structural validity

Hard-violation cases were OLD={h2b['structural_validity']['OLD_hard_violation_cases']} and NEW={h2b['structural_validity']['NEW_hard_violation_cases']}. These legality checks are treated as prerequisites rather than the main benefit when both methods are already near zero.

### 3.2 Cross-unit coordination

For total parallel co-travel, NEW/ tie / OLD outcomes were {b_total['NEW_better']}/{b_total['tie']}/{b_total['OLD_better']}; the median NEW-minus-OLD difference was {b_total['median_NEW_minus_OLD']}. For minimum clearance, outcomes were {b_clearance['NEW_better']}/{b_clearance['tie']}/{b_clearance['OLD_better']}.

### 3.3 Hierarchical complexity

Median selected L2 count was OLD={h2b['hierarchical_complexity']['OLD_selected_L2']['median']} and NEW={h2b['hierarchical_complexity']['NEW_selected_L2']['median']}; median upgraded lanes were OLD={h2b['hierarchical_complexity']['OLD_upgraded_lanes']['median']} and NEW={h2b['hierarchical_complexity']['NEW_upgraded_lanes']['median']}.

### 3.4 Runtime

Median selection runtime was OLD={h2b['runtime']['OLD_seconds']['median']} s and NEW={h2b['runtime']['NEW_seconds']['median']} s. NEW median search-node count was {h2b['runtime']['NEW_search_nodes']['median']}; node limit was reached in {h2b['runtime']['NEW_node_limit_reached_count']} cases.

### 3.5 Visual comparison materials

Ninety randomized A/B sheets and a blank scoring template are provided. Codex did not fill visual scores.

### 3.6 Summary

**PENDING USER BLIND REVIEW** — final choice must be one of RETAIN, SIMPLIFY, or REVERT after the visual evidence is reviewed.

## 4 Final Comparison Table

| Mechanism | Main benefit | Measured gain | Visual gain | Added complexity | Recommendation |
|---|---|---|---|---|---|
| H2-A soft density | Continuous density control beyond L1 count | See paired resource, same-count, and structural summaries | Pending blind review | Cross-cardinality resource objective | Pending |
| H2-B joint composition | Cross-Unit coordination | See co-travel, clearance, overlap, hierarchy, and runtime summaries | Pending blind review | Bounded joint search | Pending |
"""


def run(root: Path) -> None:
    h2a = _h2a_summary(root / "h2a")
    h2b = _h2b_summary(root / "h2b")
    _figures(root)
    (root / "ADJUDICATION_REPORT.md").write_text(_report(h2a, h2b), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ADJUDICATION_DIR)
    args = parser.parse_args()
    run(args.root.resolve())
    print(args.root.resolve() / "ADJUDICATION_REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
