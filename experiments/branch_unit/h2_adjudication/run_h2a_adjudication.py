#!/usr/bin/env python3
"""Run the frozen H2-A paired necessity adjudication."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from common import (
    ADJUDICATION_DIR,
    DENSITY_LEVELS,
    H2A_CONTRACT_PATH,
    RESOURCE_WEIGHTS,
    AdjudicationError,
    allocate_h2a_seeds,
    assert_frozen_contracts,
    ensure_empty_output,
    minmax,
    read_json,
    write_csv,
    write_json,
)


_WORKER: dict[str, Any] = {}


def _init_worker() -> None:
    from prototype_strategy_v1 import (
        load_prototype_strategy_registry,
        resolve_prototype_strategy,
    )
    from run_stage3b_l1_flow import _load_inputs

    (
        inputs,
        prior,
        feedback_prior,
        curve_geometry_prior,
        contract,
        stage3_plan_contract,
        provenance,
    ) = _load_inputs()
    registry = load_prototype_strategy_registry()
    strategies = {
        prototype_id: resolve_prototype_strategy({"prototype_id": prototype_id}, registry)
        for prototype_id in inputs
    }
    _WORKER.update(
        inputs=inputs,
        prior=prior,
        feedback_prior=feedback_prior,
        curve_geometry_prior=curve_geometry_prior,
        h2_contract=contract,
        stage3_plan_contract=stage3_plan_contract,
        provenance=provenance,
        strategies=strategies,
    )


def _clean_feasible_pool(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    ignored = {
        "hard_rejections",
        "selected",
        "selected_l1_id",
        "slot_id",
        "legacy_identity_alias",
    }
    return [
        {key: value for key, value in candidate.items() if key not in ignored}
        for candidate in inventory["candidates"]
        if not candidate.get("hard_rejections")
    ]


def _resource_metrics(
    selected: Sequence[Mapping[str, Any]],
    *,
    analysis: Mapping[str, Any],
    count_derivation: Mapping[str, Any],
    prototype_strategy: Mapping[str, Any],
    normalization_bounds: Mapping[str, Mapping[str, float]],
) -> dict[str, float]:
    import global_l1_flow as glf

    structural_score, features = glf._common_set_score(
        selected,
        analysis=analysis,
        preferred_total_count=None,
        support_count=None,
        support_roots=[float(value) for value in count_derivation["flower_support_reserved_root_s"]],
        root_spacing=float(count_derivation["minimum_root_spacing"]),
        prototype_strategy=prototype_strategy,
    )
    resource_names = tuple(RESOURCE_WEIGHTS)
    normalized = {
        name: minmax(
            float(features[name]),
            float(normalization_bounds[name]["minimum"]),
            float(normalization_bounds[name]["maximum"]),
        )
        for name in resource_names
    }
    resource_score = sum(RESOURCE_WEIGHTS[name] * normalized[name] for name in resource_names)
    return {
        "ordinary_l1_count": float(features["ordinary_l1_count"]),
        "total_planning_length": float(features["total_planning_length"]),
        "mean_backbone_excursion": float(features["mean_backbone_excursion"]),
        "mean_vertical_span": float(features["mean_vertical_span"]),
        "composite_resource_score": float(resource_score),
        "structural_score": float(structural_score),
        "root_coverage": float(features["root_arc_coverage"]),
        "minimum_root_spacing_actual": float(features["minimum_selected_root_gap"]),
    }


def _mechanical_metrics(
    selected: Sequence[Mapping[str, Any]],
    *,
    analysis: Mapping[str, Any],
    family_id: str,
    prior: Mapping[str, Any],
    feedback_profile: Mapping[str, Any],
    flower_mount_plan: Mapping[str, Any],
    curve_profile: Mapping[str, Any],
    mount_mechanism: str,
) -> dict[str, Any]:
    from geometry_batch import global_l1_polyline_distance_batch, polyline_pair_intersects
    import global_l1_flow as glf

    centerlines = [
        np.asarray([[float(p[0]), float(p[1])] for p in lane["centerline"]], dtype=float)
        for lane in selected
    ]
    base_crossings = 0
    periodic_crossings = 0
    minimum_clearance = float("inf")
    for index, first in enumerate(centerlines):
        for second in centerlines[index + 1 :]:
            for shift in (-1.0, 0.0, 1.0):
                shifted = second + np.asarray((shift, 0.0))
                crossed = bool(polyline_pair_intersects(first, shifted))
                if abs(shift) <= 1e-12:
                    base_crossings += int(crossed)
                else:
                    periodic_crossings += int(crossed)
                minimum_clearance = min(
                    minimum_clearance,
                    float(global_l1_polyline_distance_batch(first, second, shift)),
                )
        for shift in (-1.0, 1.0):
            shifted = first + np.asarray((shift, 0.0))
            periodic_crossings += int(bool(polyline_pair_intersects(first, shifted)))
            minimum_clearance = min(
                minimum_clearance,
                float(global_l1_polyline_distance_batch(first, first, shift)),
            )
    flower_intrusions = 0
    for candidate in selected:
        reasons = glf._candidate_rejections(
            candidate,
            analysis,
            family_id,
            prior,
            feedback_profile,
            flower_mount_plan,
            curve_profile,
            mount_mechanism,
        )
        flower_intrusions += sum(reason == "ordinary_lane_enters_flower_reserve" for reason in reasons)
    return {
        "root_distribution": [round(float(row["root_s"]), 9) for row in selected],
        "minimum_lane_clearance": (
            float(minimum_clearance) if math.isfinite(minimum_clearance) else None
        ),
        "curve_crossing_count": base_crossings,
        "periodic_crossing_count": periodic_crossings,
        "flower_reserve_intrusion_count": flower_intrusions,
    }


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    path = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size) if path.is_file() else ImageFont.load_default()


def _crop_structure(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGB")
    return image.crop((8, 74, image.width - 8, image.height - 34))


def _render_comparison_sheet(
    render_paths: Mapping[tuple[str, str], Path],
    output: Path,
    *,
    prototype_id: str,
    variant: str,
    production_seed: int,
) -> None:
    cell_width, cell_height = 610, 350
    left, top = 92, 82
    canvas = Image.new("RGB", (left + 3 * cell_width, top + 2 * cell_height), "#f3f1ec")
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (18, 12),
        f"{prototype_id}   {variant}   seed {production_seed}",
        fill="#1c2a32",
        font=_font(23, bold=True),
    )
    for column, density in enumerate(DENSITY_LEVELS):
        draw.text((left + column * cell_width + 16, 50), density, fill="#34464f", font=_font(16, bold=True))
    for row_index, (label, method_key) in enumerate((("OLD", "old"), ("NEW", "h2"))):
        draw.text((18, top + row_index * cell_height + 18), label, fill="#1c2a32", font=_font(17, bold=True))
        for column, density in enumerate(DENSITY_LEVELS):
            x0, y0 = left + column * cell_width, top + row_index * cell_height
            draw.rectangle((x0 + 3, y0 + 3, x0 + cell_width - 4, y0 + cell_height - 4), outline="#c3cbd0", width=2)
            image = _crop_structure(render_paths[(method_key, density)])
            image.thumbnail((cell_width - 18, cell_height - 16), Image.Resampling.LANCZOS)
            canvas.paste(image, (x0 + (cell_width - image.width) // 2, y0 + (cell_height - image.height) // 2))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def _solve_one(
    *,
    feasible_pool: Sequence[Mapping[str, Any]],
    count_derivation: Mapping[str, Any],
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    curve_profile: Mapping[str, Any],
    prototype_strategy: Mapping[str, Any],
    branch_seed: int,
    soft_density_policy: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import global_l1_flow as glf

    return glf._solve_common_set(
        feasible_pool,
        count_derivation,
        analysis,
        prior,
        curve_profile,
        prototype_strategy,
        rescue_seed=branch_seed,
        soft_density_policy=soft_density_policy,
    )


def _run_context(task: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    import global_l1_flow as glf
    from backbone_variation_v1 import split_generation_seeds
    from run_stage3b_l1_flow import generate_prototype_case
    from render_global_l1_flow import render_png as render_l1_png

    if not _WORKER:
        _init_worker()
    prototype_id = str(task["prototype_id"])
    production_seed = int(task["production_seed"])
    expected_variant = str(task["backbone_variant"])
    payload = _WORKER["inputs"][prototype_id]
    strategy = _WORKER["strategies"][prototype_id]
    domains = split_generation_seeds(production_seed)

    captured_graphs: list[tuple[Any, Any, float, float]] = []
    original_builder = glf._build_common_conflict_graph

    def capture_builder(*args: Any, **kwargs: Any) -> tuple[Any, Any, float, float]:
        result = original_builder(*args, **kwargs)
        captured_graphs.append(copy.deepcopy(result))
        return result

    glf._build_common_conflict_graph = capture_builder
    try:
        generated = generate_prototype_case(
            payload=payload,
            prototype_strategy=strategy,
            production_seed=production_seed,
            prior=_WORKER["prior"],
            feedback_prior=_WORKER["feedback_prior"],
            curve_geometry_prior=_WORKER["curve_geometry_prior"],
            contract=_WORKER["h2_contract"],
            stage3_plan_contract=_WORKER["stage3_plan_contract"],
            backbone_seed_override=None,
            flower_seed_override=None,
            branch_seed_override=None,
            unit_seed_override=None,
            backbone_rho=None,
            prototype_variant_id=None,
            flower_rho=None,
            ordinary_density_level_override="simple",
            downstream_unit_clearance=None,
        )
    finally:
        glf._build_common_conflict_graph = original_builder

    actual_variant = str(generated["variation"].get("prototype_variant_id"))
    if actual_variant != expected_variant:
        raise AdjudicationError(
            f"seed allocation variant mismatch: {prototype_id} {production_seed} "
            f"expected {expected_variant}, got {actual_variant}"
        )
    if len(captured_graphs) != 1:
        raise AdjudicationError(
            f"H2-A upstream built {len(captured_graphs)} L1 conflict graphs; expected one"
        )

    analysis = generated["variant_analysis"]
    flower_mount_plan = generated["flower_mount_plan"]
    feasible_pool = _clean_feasible_pool(generated["inventory"])
    captured_adjacency, captured_pair_cache, root_spacing, lane_clearance = captured_graphs[0]
    captured_ids = set(captured_adjacency)
    feasible_ids = {str(candidate["candidate_id"]) for candidate in feasible_pool}
    if captured_ids != feasible_ids:
        raise AdjudicationError("captured L1 graph does not cover the one generated pool")

    feedback_key = str(strategy["l1_profile"].get("feedback_profile_key", prototype_id))
    curve_key = str(strategy["l1_profile"].get("curve_geometry_profile_key", prototype_id))
    feedback_profile = glf._feedback_profile(
        _WORKER["feedback_prior"], prototype_id, feedback_key
    )
    curve_profile = glf._curve_geometry_profile(
        _WORKER["curve_geometry_prior"], prototype_id, curve_key
    )
    soft_policy = read_json(H2A_CONTRACT_PATH)["planning_policy"]["soft_density_objective"]

    graph_call_count = 0

    def cached_builder(
        candidates: Sequence[Mapping[str, Any]],
        prior: Mapping[str, Any],
        curve_geometry_profile: Mapping[str, Any],
        lane_clearance_override: float | None = None,
    ) -> tuple[Any, Any, float, float]:
        nonlocal graph_call_count
        graph_call_count += 1
        if lane_clearance_override is not None:
            raise AdjudicationError("H2-A comparison unexpectedly changed the hard graph")
        candidate_ids = {str(candidate["candidate_id"]) for candidate in candidates}
        if candidate_ids != captured_ids:
            raise AdjudicationError("H2-A selector did not consume the one frozen pool")
        return (
            copy.deepcopy(captured_adjacency),
            copy.deepcopy(captured_pair_cache),
            float(root_spacing),
            float(lane_clearance),
        )

    condition_rows: list[dict[str, Any]] = []
    raw_conditions: list[dict[str, Any]] = []
    render_paths: dict[tuple[str, str], Path] = {}
    context_id = f"{prototype_id}__{expected_variant}__r{int(task['replicate'])}"
    context_dir = output_dir / "raw_contexts" / context_id
    context_dir.mkdir(parents=True, exist_ok=True)
    glf._build_common_conflict_graph = cached_builder
    try:
        for density_level in DENSITY_LEVELS:
            old_count = glf._derive_common_count_domain(
                analysis,
                payload["morphology"],
                _WORKER["prior"],
                feedback_profile,
                flower_mount_plan,
                domains["branch_seed"],
                strategy,
                density_level,
                soft_density_mode=False,
            )
            h2_count = glf._derive_common_count_domain(
                analysis,
                payload["morphology"],
                _WORKER["prior"],
                feedback_profile,
                flower_mount_plan,
                domains["branch_seed"],
                strategy,
                density_level,
                soft_density_mode=True,
            )
            old_selected: list[dict[str, Any]] | None = None
            old_solver: dict[str, Any] | None = None
            h2_selected: list[dict[str, Any]] | None = None
            h2_solver: dict[str, Any] | None = None
            old_error = ""
            h2_error = ""
            old_runtime = None
            h2_runtime = None
            try:
                started = time.perf_counter()
                old_selected, old_solver = _solve_one(
                    feasible_pool=feasible_pool,
                    count_derivation=old_count,
                    analysis=analysis,
                    prior=_WORKER["prior"],
                    curve_profile=curve_profile,
                    prototype_strategy=strategy,
                    branch_seed=domains["branch_seed"],
                    soft_density_policy=None,
                )
                old_runtime = time.perf_counter() - started
            except Exception as exc:  # method failure is recorded, not resampled
                old_error = f"{type(exc).__name__}: {exc}"
            try:
                started = time.perf_counter()
                h2_selected, h2_solver = _solve_one(
                    feasible_pool=feasible_pool,
                    count_derivation=h2_count,
                    analysis=analysis,
                    prior=_WORKER["prior"],
                    curve_profile=curve_profile,
                    prototype_strategy=strategy,
                    branch_seed=domains["branch_seed"],
                    soft_density_policy=soft_policy,
                )
                h2_runtime = time.perf_counter() - started
            except Exception as exc:  # method failure is recorded, not resampled
                h2_error = f"{type(exc).__name__}: {exc}"

            row: dict[str, Any] = {
                "context_id": context_id,
                "prototype_id": prototype_id,
                "backbone_variant": expected_variant,
                "replicate": int(task["replicate"]),
                "production_seed": production_seed,
                **domains,
                "density_level": density_level,
                "candidate_pool_count": len(feasible_pool),
                "l1_conflict_edge_count": sum(len(v) for v in captured_adjacency.values()) // 2,
                "old_selection_success": old_selected is not None,
                "h2_selection_success": h2_selected is not None,
                "old_error": old_error,
                "h2_error": h2_error,
                "old_runtime_seconds": old_runtime,
                "h2_runtime_seconds": h2_runtime,
            }
            density_objective = (
                h2_solver.get("density_objective") if h2_solver is not None else None
            )
            if isinstance(density_objective, Mapping):
                target = float(density_objective["target_resource_score"])
                bounds = density_objective["normalization_bounds"]
                row["target_resource_score"] = target
                row["target_quantile"] = float(density_objective["target_quantile"])
                for prefix, selected, count in (
                    ("old", old_selected, old_count),
                    ("h2", h2_selected, h2_count),
                ):
                    if selected is None:
                        continue
                    metrics = _resource_metrics(
                        selected,
                        analysis=analysis,
                        count_derivation=count,
                        prototype_strategy=strategy,
                        normalization_bounds=bounds,
                    )
                    for name, value in metrics.items():
                        row[f"{prefix}_{name}"] = value
                    mechanics = _mechanical_metrics(
                        selected,
                        analysis=analysis,
                        family_id=str(strategy["family_id"]),
                        prior=_WORKER["prior"],
                        feedback_profile=feedback_profile,
                        flower_mount_plan=flower_mount_plan,
                        curve_profile=curve_profile,
                        mount_mechanism=str(strategy["flower_mount"]["mechanism"]),
                    )
                    for name, value in mechanics.items():
                        row[f"{prefix}_{name}"] = (
                            json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                        )
                    row[f"{prefix}_selected_L1_count"] = len(selected)
                    row[f"{prefix}_absolute_density_target_error"] = abs(
                        metrics["composite_resource_score"] - target
                    )
                    rendered_plan = copy.deepcopy(generated["plan"])
                    rendered_plan["lanes"] = selected
                    rendered_plan["solver"] = old_solver if prefix == "old" else h2_solver
                    rendered_plan["role_counts"] = {"primary_sweep": len(selected)}
                    rendered_plan["count_derivation"] = {
                        **count,
                        "ordinary_lane_count": len(selected),
                        "selected_ordinary_l1_count": len(selected),
                        "selected_l1_count": len(selected) + int(count["required_support_count"]),
                    }
                    render_path = context_dir / f"{prefix}_{density_level}.png"
                    render_l1_png(analysis, rendered_plan, render_path, debug=False)
                    render_paths[(prefix, density_level)] = render_path
                    row[f"{prefix}_render_file"] = str(render_path.relative_to(output_dir)).replace("\\", "/")
            raw_conditions.append(
                {
                    "density_level": density_level,
                    "old": {
                        "selection_success": old_selected is not None,
                        "selected_candidate_ids": (
                            [str(value["candidate_id"]) for value in old_selected]
                            if old_selected is not None
                            else []
                        ),
                        "solver": old_solver,
                        "error": old_error,
                    },
                    "h2": {
                        "selection_success": h2_selected is not None,
                        "selected_candidate_ids": (
                            [str(value["candidate_id"]) for value in h2_selected]
                            if h2_selected is not None
                            else []
                        ),
                        "solver": h2_solver,
                        "error": h2_error,
                    },
                }
            )
            condition_rows.append(row)
    finally:
        glf._build_common_conflict_graph = original_builder

    if graph_call_count != 2 * len(DENSITY_LEVELS):
        raise AdjudicationError(
            f"expected six selector reads of one cached graph, got {graph_call_count}"
        )
    comparison_path = output_dir / "comparison_sheets" / f"{context_id}.png"
    if len(render_paths) == 2 * len(DENSITY_LEVELS):
        _render_comparison_sheet(
            render_paths,
            comparison_path,
            prototype_id=prototype_id,
            variant=expected_variant,
            production_seed=production_seed,
        )
    context_path = context_dir / "context.json"
    write_json(
        context_path,
        {
            "context_id": context_id,
            "prototype_id": prototype_id,
            "backbone_variant": expected_variant,
            "replicate": int(task["replicate"]),
            "production_seed": production_seed,
            "derived_seeds": domains,
            "candidate_pool_generated_once": True,
            "candidate_pool_count": len(feasible_pool),
            "candidate_ids": sorted(feasible_ids),
            "l1_conflict_graph_built_once": True,
            "l1_conflict_node_count": len(captured_adjacency),
            "l1_conflict_edge_count": sum(len(v) for v in captured_adjacency.values()) // 2,
            "selector_graph_reads": graph_call_count,
            "conditions": raw_conditions,
            "comparison_sheet": str(comparison_path.relative_to(output_dir)).replace("\\", "/") if comparison_path.is_file() else "",
        },
    )
    return {
        "ok": True,
        "case": {
            "context_id": context_id,
            "prototype_id": prototype_id,
            "backbone_variant": expected_variant,
            "replicate": int(task["replicate"]),
            "production_seed": production_seed,
            **domains,
            "candidate_pool_count": len(feasible_pool),
            "l1_conflict_node_count": len(captured_adjacency),
            "l1_conflict_edge_count": sum(len(v) for v in captured_adjacency.values()) // 2,
            "raw_context_file": str(context_path.relative_to(output_dir)).replace("\\", "/"),
            "comparison_sheet": str(comparison_path.relative_to(output_dir)).replace("\\", "/") if comparison_path.is_file() else "",
        },
        "conditions": condition_rows,
    }


def _safe_run(task: Mapping[str, Any], output_dir_str: str) -> dict[str, Any]:
    try:
        return _run_context(task, Path(output_dir_str))
    except Exception as exc:  # no seed replacement; preserve the allocated failure
        return {
            "ok": False,
            "task": dict(task),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
        }


def run(output_dir: Path, *, smoke: bool, workers: int) -> None:
    assert_frozen_contracts()
    ensure_empty_output(output_dir)
    allocation = allocate_h2a_seeds()
    tasks = allocation[:2] if smoke else allocation
    results: list[dict[str, Any]] = []
    if workers == 1:
        _init_worker()
        results = [_safe_run(task, str(output_dir)) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as executor:
            futures = {
                executor.submit(_safe_run, task, str(output_dir)): task for task in tasks
            }
            for future in as_completed(futures):
                results.append(future.result())

    successful = [result for result in results if result["ok"]]
    failures = [result for result in results if not result["ok"]]
    successful_by_id = {result["case"]["context_id"]: result for result in successful}
    case_rows: list[dict[str, Any]] = []
    paired_rows: list[dict[str, Any]] = []
    for task in tasks:
        context_id = (
            f"{task['prototype_id']}__{task['backbone_variant']}__r{int(task['replicate'])}"
        )
        if context_id in successful_by_id:
            result = successful_by_id[context_id]
            case_rows.append({**result["case"], "status": "upstream_success"})
            paired_rows.extend(result["conditions"])
            continue
        failure = next(
            result
            for result in failures
            if result["task"]["prototype_id"] == task["prototype_id"]
            and int(result["task"]["production_seed"]) == int(task["production_seed"])
        )
        error = f"{failure['error_type']}: {failure['error_message']}"
        case_rows.append(
            {
                "context_id": context_id,
                **task,
                "status": "upstream_failed",
                "upstream_error": error,
            }
        )
        paired_rows.extend(
            {
                "context_id": context_id,
                **task,
                "density_level": density,
                "old_selection_success": False,
                "h2_selection_success": False,
                "old_error": error,
                "h2_error": error,
            }
            for density in DENSITY_LEVELS
        )
    case_fields = (
        "context_id", "prototype_id", "backbone_variant", "replicate",
        "production_seed", "backbone_seed", "flower_seed", "branch_seed", "unit_seed",
        "candidate_pool_count", "l1_conflict_node_count", "l1_conflict_edge_count",
        "raw_context_file", "comparison_sheet", "status", "upstream_error",
    )
    paired_fields = (
        "context_id", "prototype_id", "backbone_variant", "replicate",
        "production_seed", "backbone_seed", "flower_seed", "branch_seed", "unit_seed",
        "density_level", "candidate_pool_count", "l1_conflict_edge_count",
        "old_selection_success", "h2_selection_success", "old_error", "h2_error",
        "old_runtime_seconds", "h2_runtime_seconds",
        "target_quantile", "target_resource_score",
        "old_selected_L1_count", "h2_selected_L1_count",
        "old_ordinary_l1_count", "h2_ordinary_l1_count",
        "old_total_planning_length", "h2_total_planning_length",
        "old_mean_backbone_excursion", "h2_mean_backbone_excursion",
        "old_mean_vertical_span", "h2_mean_vertical_span",
        "old_composite_resource_score", "h2_composite_resource_score",
        "old_structural_score", "h2_structural_score",
        "old_root_distribution", "h2_root_distribution",
        "old_root_coverage", "h2_root_coverage",
        "old_minimum_root_spacing_actual", "h2_minimum_root_spacing_actual",
        "old_minimum_lane_clearance", "h2_minimum_lane_clearance",
        "old_curve_crossing_count", "h2_curve_crossing_count",
        "old_periodic_crossing_count", "h2_periodic_crossing_count",
        "old_flower_reserve_intrusion_count", "h2_flower_reserve_intrusion_count",
        "old_absolute_density_target_error", "h2_absolute_density_target_error",
        "old_render_file", "h2_render_file",
    )
    write_csv(output_dir / "cases.csv", case_rows, case_fields)
    write_csv(output_dir / "paired_metrics.csv", paired_rows, paired_fields)
    write_json(output_dir / "failures.json", failures)
    write_json(
        output_dir / "run_manifest.json",
        {
            "mode": "smoke" if smoke else "full",
            "allocated_base_context_count": len(tasks),
            "successful_base_context_count": len(successful),
            "failed_base_context_count": len(failures),
            "paired_condition_count": len(paired_rows),
            "seed_allocation": tasks,
            "candidate_pool_generated_once_per_context": True,
            "one_l1_conflict_graph_reused_by_both_selectors": True,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ADJUDICATION_DIR / "h2a",
    )
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    args = parser.parse_args()
    if args.workers <= 0:
        raise SystemExit("workers must be positive")
    run(args.output_dir.resolve(), smoke=args.smoke, workers=args.workers)
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
