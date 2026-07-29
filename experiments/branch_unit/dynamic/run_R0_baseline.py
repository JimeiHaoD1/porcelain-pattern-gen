#!/usr/bin/env python3
"""Freeze and automatically verify optimization-line-R stage R0."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw

from optimization_line_r_metrics import (
    angle_degrees,
    ellipse_wrap_stats,
    file_sha256,
    geometry_digest_from_stage3b,
    horizontal_progress_ratio,
    metric_row,
    nearest_backbone_sample,
    non_root_backbone_min_distance,
    out_of_bounds_stats,
    pairwise_curve_crossing_count,
    periodic_curve_crossing_count,
    polyline_length,
    read_json,
    root_local_density,
    root_tangent_error,
    sample_segments,
    scope,
    selection_digest_from_stage5,
    write_json,
)
from run_stage3b_l1_flow import run as run_stage3b
from run_stage5_global_selection import run as run_stage5


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
CONTRACT_PATH = DYNAMIC_DIR / "R0_BASELINE_CONTRACT_V1.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_R0_baseline_v1"
)


class R0Error(RuntimeError):
    """R0 cannot produce a complete, evidence-backed baseline."""


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _case_paths(
    roots: Mapping[str, Path],
    prototype_id: str,
    seed: int,
) -> dict[str, Path]:
    return {
        "strict": (
            REPO_ROOT
            / "artifacts"
            / "runs"
            / "dynamic_branch_stage1_inputs_v1"
            / prototype_id
            / "strict_p0_v2.json"
        ),
        "analysis": (
            roots["stage2"] / prototype_id / "prototype_analysis.json"
        ),
        "plan": (
            roots["stage3b"]
            / prototype_id
            / f"seed_{seed}"
            / "global_l1_flow_plan.json"
        ),
        "inventory": (
            roots["stage4"]
            / prototype_id
            / f"seed_{seed}"
            / "unit_candidate_inventory.json"
        ),
        "selection": (
            roots["stage5"]
            / prototype_id
            / f"seed_{seed}"
            / "global_unit_selection.json"
        ),
        "conflict_graph": (
            roots["stage5"]
            / prototype_id
            / f"seed_{seed}"
            / "candidate_conflict_graph.json"
        ),
    }


def _curve_points(curve: Mapping[str, object], samples: int) -> list[tuple[float, float]]:
    return sample_segments(curve["cubic_segments"], samples)  # type: ignore[arg-type]


def _flower_by_id(
    strict: Mapping[str, object],
    flower_id: object,
) -> Mapping[str, object] | None:
    for flower in strict["flowers"]:  # type: ignore[index]
        if flower["flower_id"] == flower_id:
            return flower
    return None


def _selected_curves(
    selection: Mapping[str, object],
) -> list[tuple[Mapping[str, object], Mapping[str, object]]]:
    result: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    for candidate in selection["selected_candidates"]:  # type: ignore[index]
        for curve in candidate["curves"]:
            result.append((candidate, curve))
    return result


def _collect_case_metrics(
    roots: Mapping[str, Path],
    prototype_id: str,
    seed: int,
    contract: Mapping[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    paths = _case_paths(roots, prototype_id, seed)
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise R0Error(f"missing baseline case inputs: {missing}")
    strict = read_json(paths["strict"])
    plan = read_json(paths["plan"])
    inventory = read_json(paths["inventory"])
    selection = read_json(paths["selection"])
    conflict_graph = read_json(paths["conflict_graph"])
    samples = int(contract["measurement"]["curve_samples_per_cubic"])  # type: ignore[index]
    root_exclusion = float(
        contract["measurement"]["backbone_root_exclusion_fraction"]  # type: ignore[index]
    )
    epsilon = float(contract["measurement"]["intersection_epsilon"])  # type: ignore[index]
    periodic_shifts = [
        float(value)
        for value in contract["measurement"]["periodic_shifts"]  # type: ignore[index]
    ]
    canvas = strict["frame"]["local"]["canvas_bounds"]
    y_min = float(canvas[1])
    y_max = float(canvas[3])
    rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    l1_points: list[list[tuple[float, float]]] = []
    root_s_values: list[float] = []
    support_contact_errors: list[float] = []
    core_counts: dict[str, dict[str, int]] = {
        str(flower["flower_id"]): {"support": 0, "wrap": 0, "balance": 0}
        for flower in strict["flowers"]
    }

    for lane in plan["lanes"]:
        lane_id = str(lane["slot_id"])
        curve_id = f'{plan["plan_id"]}__{lane_id}.L1'
        lane_scope = scope(
            prototype_id,
            seed,
            lane_id,
            f'{plan["plan_id"]}__{lane_id}',
            curve_id,
        )
        points = sample_segments(lane["segments"], samples)
        l1_points.append(points)
        root_s_values.append(float(lane["root_s"]))
        backbone = nearest_backbone_sample(strict, float(lane["root_s"]))
        tangent = tuple(float(value) for value in backbone["tangent"])
        root_error = root_tangent_error(lane["segments"], tangent)
        horizontal = horizontal_progress_ratio(points)
        outside_length, outside_ratio = out_of_bounds_stats(points, y_min, y_max)
        non_root_distance = non_root_backbone_min_distance(
            points,
            strict,
            root_exclusion,
        )
        rows.extend(
            [
                metric_row(
                    "root_tangent_error_deg",
                    root_error,
                    lane_scope,
                    source=str(paths["plan"].relative_to(REPO_ROOT)),
                ),
                metric_row(
                    "horizontal_progress_ratio",
                    horizontal,
                    lane_scope,
                    source=str(paths["plan"].relative_to(REPO_ROOT)),
                ),
                metric_row(
                    "out_of_bounds_length",
                    outside_length,
                    lane_scope,
                    source=str(paths["plan"].relative_to(REPO_ROOT)),
                ),
                metric_row(
                    "out_of_bounds_ratio",
                    outside_ratio,
                    lane_scope,
                    source=str(paths["plan"].relative_to(REPO_ROOT)),
                ),
                metric_row(
                    "non_root_backbone_min_distance",
                    non_root_distance,
                    lane_scope,
                    source=str(paths["plan"].relative_to(REPO_ROOT)),
                ),
            ]
        )
        role = str(lane["role"])
        flower_id = lane.get("flower_id")
        if flower_id is not None and flower_id in core_counts:
            if role in {"flower_support", "terminal_flower_support"}:
                core_counts[str(flower_id)]["support"] += 1
                flower = _flower_by_id(strict, flower_id)
                if flower is not None:
                    end = points[-1]
                    center = flower["center"]
                    underside = (
                        float(center[0]),
                        float(center[1]) + float(flower["ry"]),
                    )
                    support_contact_errors.append(
                        ((end[0] - underside[0]) ** 2 + (end[1] - underside[1]) ** 2)
                        ** 0.5
                    )
            elif role == "balance":
                core_counts[str(flower_id)]["balance"] += 1

    rows.append(
        metric_row(
            "root_local_density",
            root_local_density(
                root_s_values,
                float(contract["measurement"]["root_density_window"]),  # type: ignore[index]
            ),
            scope(prototype_id, seed),
            source=str(paths["plan"].relative_to(REPO_ROOT)),
        )
    )
    direct_crossings = pairwise_curve_crossing_count(l1_points, epsilon)
    periodic_crossings = periodic_curve_crossing_count(
        l1_points,
        periodic_shifts,
        epsilon,
    )
    rows.extend(
        [
            metric_row(
                "curve_crossing_count",
                direct_crossings,
                scope(prototype_id, seed),
                source=str(paths["plan"].relative_to(REPO_ROOT)),
            ),
            metric_row(
                "periodic_L1_crossing_count",
                periodic_crossings,
                scope(prototype_id, seed),
                source=str(paths["plan"].relative_to(REPO_ROOT)),
            ),
        ]
    )

    selected = _selected_curves(selection)
    selected_by_id = {
        str(curve["curve_id"]): (candidate, curve)
        for candidate, curve in selected
    }
    selected_l1_lengths = {
        str(curve["curve_id"]): float(curve["actual_length"])
        for _, curve in selected
        if curve["level"] == "L1"
    }
    selected_l2_lengths = {
        str(curve["curve_id"]): float(curve["actual_length"])
        for _, curve in selected
        if curve["level"] == "L2"
    }
    l2_ratios: list[float] = []
    l3_ratios: list[float] = []
    wrap_spans: list[float] = []
    total_selected_outside = 0.0
    for candidate, curve in selected:
        curve_id = str(curve["curve_id"])
        curve_scope = scope(
            prototype_id,
            seed,
            str(candidate["source_lane_id"]),
            str(candidate["branch_unit_id"]),
            curve_id,
        )
        points = _curve_points(curve, samples)
        outside_length, _ = out_of_bounds_stats(points, y_min, y_max)
        total_selected_outside += outside_length
        level = str(curve["level"])
        parent_id = curve.get("parent_curve_id")
        if level == "L2" and parent_id in selected_l1_lengths:
            ratio = float(curve["actual_length"]) / selected_l1_lengths[str(parent_id)]
            l2_ratios.append(ratio)
            rows.append(
                metric_row(
                    "L2_L1_length_ratio",
                    ratio,
                    curve_scope,
                    source=str(paths["selection"].relative_to(REPO_ROOT)),
                )
            )
        elif level == "L3" and parent_id in selected_l2_lengths:
            ratio = float(curve["actual_length"]) / selected_l2_lengths[str(parent_id)]
            l3_ratios.append(ratio)
            rows.append(
                metric_row(
                    "L3_L2_length_ratio",
                    ratio,
                    curve_scope,
                    source=str(paths["selection"].relative_to(REPO_ROOT)),
                )
            )
        if curve["semantic_role"] == "flower_wrap":
            flower_id = candidate["flower_relation"]["flower_id"]
            flower = _flower_by_id(strict, flower_id)
            if flower is not None:
                stats = ellipse_wrap_stats(points, flower)
                wrap_spans.append(stats["wrap_span_deg"])
                core_counts[str(flower_id)]["wrap"] += 1
                for name, value in stats.items():
                    rows.append(
                        metric_row(
                            name,
                            value,
                            curve_scope,
                            source=str(paths["selection"].relative_to(REPO_ROOT)),
                        )
                    )

    case_scope = scope(prototype_id, seed)
    rows.extend(
        [
            metric_row(
                "L2_L1_length_ratio",
                sum(l2_ratios) / len(l2_ratios) if l2_ratios else 0.0,
                case_scope,
                source=str(paths["selection"].relative_to(REPO_ROOT)),
                applicable=bool(l2_ratios),
            ),
            metric_row(
                "L3_L2_length_ratio",
                sum(l3_ratios) / len(l3_ratios) if l3_ratios else 0.0,
                case_scope,
                source=str(paths["selection"].relative_to(REPO_ROOT)),
                applicable=bool(l3_ratios),
            ),
            metric_row(
                "out_of_bounds_length",
                total_selected_outside,
                case_scope,
                source=str(paths["selection"].relative_to(REPO_ROOT)),
                applicable=bool(selected),
            ),
            metric_row(
                "support_contact_error",
                min(support_contact_errors) if support_contact_errors else 0.0,
                case_scope,
                source=str(paths["plan"].relative_to(REPO_ROOT)),
                applicable=bool(support_contact_errors),
            ),
            metric_row(
                "wrap_span_deg",
                max(wrap_spans) if wrap_spans else 0.0,
                case_scope,
                source=str(paths["selection"].relative_to(REPO_ROOT)),
                applicable=bool(wrap_spans),
            ),
            metric_row(
                "Y2C_usage_rate",
                (
                    sum(
                        1
                        for candidate in selection["selected_candidates"]
                        if candidate["grammar_id"] == "Y-2C"
                    )
                    / len(selection["selected_candidates"])
                    if selection["selected_candidates"]
                    else 0.0
                ),
                case_scope,
                source=str(paths["selection"].relative_to(REPO_ROOT)),
                applicable=bool(selection["selected_candidates"]),
            ),
            metric_row(
                "candidate_conflict_edge_count",
                int(conflict_graph["edge_count"]),
                case_scope,
                source=str(paths["conflict_graph"].relative_to(REPO_ROOT)),
            ),
        ]
    )
    for flower_id, counts in core_counts.items():
        rows.append(
            metric_row(
                "flower_core_branch_count",
                sum(counts.values()),
                scope(prototype_id, seed, branch_unit_id=flower_id),
                source=str(paths["selection"].relative_to(REPO_ROOT)),
            )
        )
        for role, count in counts.items():
            rows.append(
                metric_row(
                    f"flower_core_{role}_count",
                    count,
                    scope(prototype_id, seed, branch_unit_id=flower_id),
                    source=str(paths["selection"].relative_to(REPO_ROOT)),
                )
            )

    if not selection["feasible"]:
        for edge in conflict_graph["edges"]:
            first_crossing = edge["crossings"][0]
            first_curve_id = str(first_crossing["first_curve_id"])
            first_candidate_id = str(edge["first_candidate_id"])
            failures.append(
                {
                    "failure_code": "baseline_stage5_candidate_conflict",
                    "stage": "R0",
                    "scope": scope(
                        prototype_id,
                        seed,
                        str(edge["first_lane_id"]),
                        first_candidate_id.rsplit("__", 2)[0],
                        first_curve_id,
                    ),
                    "related_scope": scope(
                        prototype_id,
                        seed,
                        str(edge["second_lane_id"]),
                        str(edge["second_candidate_id"]).rsplit("__", 2)[0],
                        str(first_crossing["second_curve_id"]),
                    ),
                    "reason": edge["reason"],
                    "evidence_file": str(
                        paths["conflict_graph"].relative_to(REPO_ROOT)
                    ).replace("\\", "/"),
                }
            )
    return rows, failures


def _acceptance_metric(
    name: str,
    value: object,
    threshold: str,
    passed: bool,
    evidence: str,
) -> dict[str, object]:
    return {
        "metric_name": name,
        "scope": scope(),
        "measured_value": value,
        "threshold": threshold,
        "pass": passed,
        "evidence_file": evidence,
    }


def _make_before_after(
    before_path: Path,
    replay_path: Path,
    output_path: Path,
) -> None:
    before = Image.open(before_path).convert("RGB")
    replay = Image.open(replay_path).convert("RGB")
    height = max(before.height, replay.height)
    margin = 34
    canvas = Image.new(
        "RGB",
        (before.width + replay.width, height + margin),
        "white",
    )
    canvas.paste(before, (0, margin))
    canvas.paste(replay, (before.width, margin))
    draw = ImageDraw.Draw(canvas)
    draw.text((10, 10), "FROZEN BASELINE", fill=(20, 35, 70))
    draw.text((before.width + 10, 10), "DETERMINISTIC REPLAY", fill=(20, 35, 70))
    canvas.save(output_path)


def _directory_file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def run(output: Path) -> None:
    if output.exists():
        raise R0Error(f"R0 output already exists: {output}")
    contract = read_json(CONTRACT_PATH)
    prototypes = [str(value) for value in contract["prototype_ids"]]
    seeds = [int(value) for value in contract["seeds"]]
    cases = [(prototype_id, seed) for prototype_id in prototypes for seed in seeds]
    roots = {
        name: REPO_ROOT / relative
        for name, relative in contract["baseline_roots"].items()
    }
    missing_roots = [str(path) for path in roots.values() if not path.is_dir()]
    if missing_roots:
        raise R0Error(f"baseline roots are missing: {missing_roots}")
    output.parent.mkdir(parents=True, exist_ok=True)
    source_hashes_before = {
        name: _directory_file_hashes(path) for name, path in roots.items()
    }
    baseline_geometry_digest = geometry_digest_from_stage3b(
        roots["stage3b"],
        cases,
    )
    baseline_selection_digest = selection_digest_from_stage5(
        roots["stage5"],
        cases,
    )
    commit_before = _git_head()
    scratch_root = REPO_ROOT / ".codex_tmp"
    scratch_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="dynamic_branch_R0_",
        dir=scratch_root,
    ) as directory:
        temporary_root = Path(directory)
        replay1_stage3b = temporary_root / "replay1_stage3b"
        replay2_stage3b = temporary_root / "replay2_stage3b"
        replay1_stage5 = temporary_root / "replay1_stage5"
        replay2_stage5 = temporary_root / "replay2_stage5"
        run_stage3b(replay1_stage3b)
        run_stage3b(replay2_stage3b)
        run_stage5(replay1_stage5)
        run_stage5(replay2_stage5)

        replay1_geometry_digest = geometry_digest_from_stage3b(
            replay1_stage3b,
            cases,
        )
        replay2_geometry_digest = geometry_digest_from_stage3b(
            replay2_stage3b,
            cases,
        )
        replay1_selection_digest = selection_digest_from_stage5(
            replay1_stage5,
            cases,
        )
        replay2_selection_digest = selection_digest_from_stage5(
            replay2_stage5,
            cases,
        )
        geometry_reproducible = replay1_geometry_digest == replay2_geometry_digest
        selection_reproducible = (
            replay1_selection_digest == replay2_selection_digest
        )
        baseline_geometry_changed = (
            baseline_geometry_digest != replay1_geometry_digest
        )
        baseline_selection_changed = (
            baseline_selection_digest != replay1_selection_digest
        )

        metrics: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        missing_cases: list[dict[str, object]] = []
        for prototype_id, seed in cases:
            try:
                case_metrics, case_failures = _collect_case_metrics(
                    roots,
                    prototype_id,
                    seed,
                    contract,
                )
                metrics.extend(case_metrics)
                failures.extend(case_failures)
            except R0Error as exc:
                missing_cases.append(
                    {
                        "prototype_id": prototype_id,
                        "seed": seed,
                        "reason": str(exc),
                    }
                )

        present_metric_names = {str(row["metric_name"]) for row in metrics}
        missing_metric_names = sorted(
            set(str(value) for value in contract["required_metric_names"])
            - present_metric_names
        )
        unresolved_failure_references = [
            failure
            for failure in failures
            if any(
                failure["scope"].get(key) in ("", None)
                for key in (
                    "prototype_id",
                    "seed",
                    "lane_id",
                    "branch_unit_id",
                    "curve_id",
                )
            )
        ]
        reproducibility_pass = (
            geometry_reproducible
            and selection_reproducible
            and not baseline_geometry_changed
            and not baseline_selection_changed
        )

        with tempfile.TemporaryDirectory(
            prefix="dynamic_branch_R0_publish_",
            dir=output.parent,
        ) as publish_directory:
            publish = Path(publish_directory)
            write_json(
                publish / "metrics.json",
                {
                    "schema": "dynamic_branch_R_metrics_v1",
                    "stage": "R0",
                    "case_count": len(cases) - len(missing_cases),
                    "metric_count": len(metrics),
                    "required_metric_names": contract["required_metric_names"],
                    "missing_metric_names": missing_metric_names,
                    "metrics": metrics,
                    "digests": {
                        "baseline_geometry": baseline_geometry_digest,
                        "replay1_geometry": replay1_geometry_digest,
                        "replay2_geometry": replay2_geometry_digest,
                        "baseline_selection": baseline_selection_digest,
                        "replay1_selection": replay1_selection_digest,
                        "replay2_selection": replay2_selection_digest,
                    },
                },
            )
            write_json(
                publish / "failures.json",
                {
                    "schema": "dynamic_branch_R_failures_v1",
                    "stage": "R0",
                    "baseline_failures_are_preserved_not_repaired": True,
                    "failure_count": len(failures),
                    "unresolved_failure_reference_count": len(
                        unresolved_failure_references
                    ),
                    "missing_cases": missing_cases,
                    "failures": failures,
                },
            )
            _make_before_after(
                roots["stage5"] / "stage5_global_selection_contact_sheet.png",
                replay1_stage5 / "stage5_global_selection_contact_sheet.png",
                publish / "before_after_contact_sheet.png",
            )
            shutil.copyfile(
                roots["stage3b"]
                / "proto_sw_3_2"
                / "seed_4101"
                / "l1_flow.svg",
                publish / "debug_overlay.svg",
            )
            iteration = {
                "stage": "R0",
                "iteration": 1,
                "commit_before": commit_before,
                "files_changed": [
                    "experiments/branch_unit/dynamic/R0_BASELINE_CONTRACT_V1.json",
                    "experiments/branch_unit/dynamic/optimization_line_r_metrics.py",
                    "experiments/branch_unit/dynamic/run_R0_baseline.py",
                    "artifacts/runs/dynamic_branch_R0_baseline_v1",
                ],
                "failed_metrics": [],
                "root_causes": [],
                "changes_made": [
                    "Added read-only baseline measurement and deterministic replay.",
                    "Preserved all existing Stage 2, 3B, 4, and 5 geometry and selections.",
                    "Expanded the existing infeasible selection into curve-scoped evidence.",
                ],
                "result": "PASS",
            }
            write_json(publish / "iteration_history.json", [iteration])
            summary = f"""# R0 baseline freeze

- Status: `PASSED`
- Cases: {len(cases) - len(missing_cases)} / {len(cases)}
- Detailed metrics: {len(metrics)}
- Preserved Stage-5 infeasible conflict records: {len(failures)}
- Missing required metrics: {len(missing_metric_names)}
- Unresolved failure references: {len(unresolved_failure_references)}
- Geometry deterministic replay: {geometry_reproducible}
- Selection deterministic replay: {selection_reproducible}
- Baseline geometry changed: {baseline_geometry_changed}
- Baseline selection changed: {baseline_selection_changed}

R0 adds measurement and audit artifacts only. It does not modify Stage 2 analysis,
Stage 3B lanes, Stage 4 candidates, or Stage 5 selections.
"""
            (publish / "stage_summary.md").write_text(
                summary,
                encoding="utf-8",
                newline="\n",
            )
            required_artifacts = [str(value) for value in contract["required_artifacts"]]
            acceptance_metrics = [
                _acceptance_metric(
                    "case_count",
                    len(cases) - len(missing_cases),
                    f"== {contract['acceptance']['case_count']}",
                    len(cases) - len(missing_cases)
                    == int(contract["acceptance"]["case_count"]),
                    "metrics.json",
                ),
                _acceptance_metric(
                    "missing_case_count",
                    len(missing_cases),
                    "== 0",
                    not missing_cases,
                    "failures.json",
                ),
                _acceptance_metric(
                    "unresolved_failure_reference_count",
                    len(unresolved_failure_references),
                    "== 0",
                    not unresolved_failure_references,
                    "failures.json",
                ),
                _acceptance_metric(
                    "required_metric_missing_count",
                    len(missing_metric_names),
                    "== 0",
                    not missing_metric_names,
                    "metrics.json",
                ),
                _acceptance_metric(
                    "geometry_digest_run1_equals_run2",
                    geometry_reproducible,
                    "== true",
                    geometry_reproducible,
                    "metrics.json",
                ),
                _acceptance_metric(
                    "selection_digest_run1_equals_run2",
                    selection_reproducible,
                    "== true",
                    selection_reproducible,
                    "metrics.json",
                ),
                _acceptance_metric(
                    "baseline_geometry_changed",
                    baseline_geometry_changed,
                    "== false",
                    not baseline_geometry_changed,
                    "metrics.json",
                ),
                _acceptance_metric(
                    "baseline_selection_changed",
                    baseline_selection_changed,
                    "== false",
                    not baseline_selection_changed,
                    "metrics.json",
                ),
            ]
            hard_failure_count = sum(
                1 for metric in acceptance_metrics if not metric["pass"]
            )
            predicted_missing = [
                name
                for name in required_artifacts
                if name not in {"acceptance_report.json", "run_manifest.json"}
                and not (publish / name).is_file()
            ]
            acceptance_metrics.append(
                _acceptance_metric(
                    "required_artifact_missing_count",
                    len(predicted_missing),
                    "== 0",
                    not predicted_missing,
                    "run_manifest.json",
                )
            )
            hard_failure_count += len(predicted_missing)
            stage_pass = hard_failure_count == 0 and reproducibility_pass
            if not stage_pass:
                iteration["failed_metrics"] = [
                    metric["metric_name"]
                    for metric in acceptance_metrics
                    if not metric["pass"]
                ]
                iteration["result"] = "FAIL"
                write_json(publish / "iteration_history.json", [iteration])
            write_json(
                publish / "acceptance_report.json",
                {
                    "schema": "dynamic_branch_R_acceptance_report_v1",
                    "stage": "R0",
                    "stage_status": "PASSED" if stage_pass else "FAILED_RETRYING",
                    "hard_failure_count": hard_failure_count,
                    "reproducibility_pass": reproducibility_pass,
                    "required_artifact_missing_count": len(predicted_missing),
                    "metrics": acceptance_metrics,
                },
            )
            source_hashes_after = {
                name: _directory_file_hashes(path)
                for name, path in roots.items()
            }
            write_json(
                publish / "run_manifest.json",
                {
                    "schema": "dynamic_branch_R_run_manifest_v1",
                    "stage": "R0",
                    "contract": {
                        "path": str(CONTRACT_PATH.relative_to(REPO_ROOT)).replace(
                            "\\",
                            "/",
                        ),
                        "sha256": file_sha256(CONTRACT_PATH),
                    },
                    "commit_before": commit_before,
                    "prototype_ids": prototypes,
                    "seeds": seeds,
                    "case_count": len(cases),
                    "source_hashes_before": source_hashes_before,
                    "source_hashes_after": source_hashes_after,
                    "source_files_unchanged": (
                        source_hashes_before == source_hashes_after
                    ),
                    "artifacts": {
                        path.name: file_sha256(path)
                        for path in sorted(publish.iterdir())
                        if path.is_file()
                    },
                },
            )
            final_missing = [
                name for name in required_artifacts if not (publish / name).is_file()
            ]
            if final_missing:
                raise R0Error(f"R0 required artifacts are missing: {final_missing}")
            if not stage_pass:
                raise R0Error(
                    "R0 acceptance failed: "
                    + ", ".join(iteration["failed_metrics"])
                )
            publish.replace(output)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    run(args.output.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except R0Error as exc:
        raise SystemExit(f"R0 error: {exc}") from exc
