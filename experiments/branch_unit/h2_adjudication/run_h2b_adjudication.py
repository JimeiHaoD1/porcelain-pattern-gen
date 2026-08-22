#!/usr/bin/env python3
"""Run the frozen H2-B paired selection experiment on shared Stage4 inputs."""

from __future__ import annotations

import argparse
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont

from common import (
    ADJUDICATION_DIR,
    EDITOR_L2_PRIOR_PATH,
    H2B_CONTRACT_PATH,
    H2B_OLD_CONTRACT_PATH,
    STAGE4_CONTRACT_PATH,
    AdjudicationError,
    allocate_h2b_seeds,
    assert_frozen_contracts,
    ensure_empty_output,
    read_json,
    write_csv,
    write_json,
)


_WORKER: dict[str, Any] = {}


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    path = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size) if path.is_file() else ImageFont.load_default()


def _comparison_sheet(old_path: Path, new_path: Path, output: Path, title: str) -> None:
    width, height = 1800, 610
    header, half = 72, width // 2
    canvas = Image.new("RGB", (width, height), "#f3f1ec")
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 16), title, fill="#1c2a32", font=_font(23, bold=True))
    draw.text((half // 2 - 28, 20), "OLD", fill="#354750", font=_font(17, bold=True))
    draw.text((half + half // 2 - 28, 20), "NEW", fill="#354750", font=_font(17, bold=True))
    draw.line((half, header, half, height - 8), fill="#c3cbd0", width=2)
    for panel, path in enumerate((old_path, new_path)):
        with Image.open(path) as source:
            image = source.convert("RGB")
        image = image.crop((8, 80, image.width - 8, image.height - 40))
        image.thumbnail((half - 20, height - header - 16), Image.Resampling.LANCZOS)
        canvas.paste(image, (panel * half + (half - image.width) // 2, header + (height - header - image.height) // 2))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


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
        h2a_contract=contract,
        stage3_plan_contract=stage3_plan_contract,
        provenance=provenance,
        strategies=strategies,
        stage4_contract=read_json(STAGE4_CONTRACT_PATH),
        old_contract=read_json(H2B_OLD_CONTRACT_PATH),
        h2_contract=read_json(H2B_CONTRACT_PATH),
        editor_l2_prior=read_json(EDITOR_L2_PRIOR_PATH),
    )


def _run_case(task: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    from backbone_variation_v1 import split_generation_seeds
    from branch_unit_grammar_v1 import generate_unit_candidate_inventory
    from render_stage5_global_selection import render_global_selection
    from run_batch_generation import _downstream_unit_clearance
    from run_stage3b_l1_flow import generate_prototype_case
    from stage5_global_unit_selection import build_conflict_graph, select_global_units

    if not _WORKER:
        _init_worker()
    pair_id = str(task["pair_id"])
    prototype_id = str(task["prototype_id"])
    production_seed = int(task["production_seed"])
    expected_variant = str(task["backbone_variant"])
    expected_density = str(task["density_level"])
    strategy = _WORKER["strategies"][prototype_id]
    downstream_clearance = _downstream_unit_clearance(
        strategy,
        _WORKER["editor_l2_prior"],
        _WORKER["stage4_contract"],
    )
    generated = generate_prototype_case(
        payload=_WORKER["inputs"][prototype_id],
        prototype_strategy=strategy,
        production_seed=production_seed,
        prior=_WORKER["prior"],
        feedback_prior=_WORKER["feedback_prior"],
        curve_geometry_prior=_WORKER["curve_geometry_prior"],
        contract=_WORKER["h2a_contract"],
        stage3_plan_contract=_WORKER["stage3_plan_contract"],
        backbone_seed_override=None,
        flower_seed_override=None,
        branch_seed_override=None,
        unit_seed_override=None,
        backbone_rho=None,
        prototype_variant_id=None,
        flower_rho=None,
        ordinary_density_level_override=None,
        downstream_unit_clearance=downstream_clearance,
    )
    plan = generated["plan"]
    actual_variant = str(generated["variation"].get("prototype_variant_id"))
    actual_density = str(plan["count_derivation"]["ordinary_density_level"])
    if (actual_variant, actual_density) != (expected_variant, expected_density):
        raise AdjudicationError(
            f"stratified seed mismatch for {pair_id}: expected "
            f"{expected_variant}/{expected_density}, got {actual_variant}/{actual_density}"
        )

    analysis = generated["variant_analysis"]
    flower_mount_plan = generated["flower_mount_plan"]
    unit_inventory = generate_unit_candidate_inventory(
        plan,
        analysis,
        _WORKER["prior"],
        _WORKER["stage4_contract"],
        _WORKER["editor_l2_prior"],
    )
    conflict_graph = build_conflict_graph(
        unit_inventory,
        _WORKER["h2_contract"],
        _WORKER["editor_l2_prior"],
    )

    old_selection: dict[str, Any] | None = None
    h2_selection: dict[str, Any] | None = None
    old_error = ""
    h2_error = ""
    old_runtime = None
    h2_runtime = None
    try:
        started = time.perf_counter()
        old_selection = select_global_units(
            unit_inventory, conflict_graph, _WORKER["old_contract"]
        )
        old_runtime = time.perf_counter() - started
    except Exception as exc:  # record the allocated failure, never replace seed
        old_error = f"{type(exc).__name__}: {exc}"
    try:
        started = time.perf_counter()
        h2_selection = select_global_units(
            unit_inventory, conflict_graph, _WORKER["h2_contract"]
        )
        h2_runtime = time.perf_counter() - started
    except Exception as exc:  # record the allocated failure, never replace seed
        h2_error = f"{type(exc).__name__}: {exc}"

    case_dir = output_dir / "raw_cases" / pair_id
    case_dir.mkdir(parents=True, exist_ok=True)
    old_png = case_dir / "method_old_triple.png"
    h2_png = case_dir / "method_h2_triple.png"
    if old_selection is not None:
        render_global_selection(
            analysis,
            unit_inventory,
            conflict_graph,
            old_selection,
            old_png,
            triple_repeat=True,
            flower_mount_plan=flower_mount_plan,
        )
    if h2_selection is not None:
        render_global_selection(
            analysis,
            unit_inventory,
            conflict_graph,
            h2_selection,
            h2_png,
            triple_repeat=True,
            flower_mount_plan=flower_mount_plan,
        )
    comparison_path = output_dir / "comparison_sheets" / f"{pair_id}.png"
    if old_png.is_file() and h2_png.is_file():
        _comparison_sheet(
            old_png,
            h2_png,
            comparison_path,
            f"{pair_id}   {prototype_id}   {expected_variant}   {expected_density}   seed {production_seed}",
        )

    domains = split_generation_seeds(production_seed)
    evaluation_input = {
        "pair_id": pair_id,
        "prototype_id": prototype_id,
        "backbone_variant": expected_variant,
        "density_level": expected_density,
        "replicate": int(task["replicate"]),
        "production_seed": production_seed,
        "derived_seeds": domains,
        "same_stage4_inventory_object": True,
        "same_conflict_graph_object": True,
        "stage4_inventory_id": str(unit_inventory["inventory_id"]),
        "repeat_shifts": [float(value) for value in conflict_graph["repeat_shifts_checked"]],
        "minimum_clearance_required": float(conflict_graph["minimum_descendant_clearance"]),
        "parallel_soft_limit": float(conflict_graph["parallel_co_travel_soft_limit"]),
        "parallel_maximum": float(conflict_graph["maximum_parallel_co_travel_score"]),
        "old": {
            "selection_success": old_selection is not None,
            "selection_error": old_error,
            "selected_candidates": (
                old_selection["selected_candidates"] if old_selection is not None else []
            ),
            "solver_trace": old_selection.get("solver_trace", {}) if old_selection else {},
            "runtime_seconds": old_runtime,
        },
        "h2": {
            "selection_success": h2_selection is not None,
            "selection_error": h2_error,
            "selected_candidates": (
                h2_selection["selected_candidates"] if h2_selection is not None else []
            ),
            "solver_trace": h2_selection.get("solver_trace", {}) if h2_selection else {},
            "runtime_seconds": h2_runtime,
        },
    }
    evaluation_path = case_dir / "evaluation_input.json"
    write_json(evaluation_path, evaluation_input)
    return {
        "ok": True,
        "case": {
            "pair_id": pair_id,
            "prototype_id": prototype_id,
            "backbone_variant": expected_variant,
            "density_level": expected_density,
            "replicate": int(task["replicate"]),
            "production_seed": production_seed,
            **domains,
            "ordinary_l1_count": len(plan["lanes"]),
            "stage4_candidate_count": len(unit_inventory["candidates"]),
            "stage4_eligible_candidate_count": int(unit_inventory["feasible_candidate_count"]),
            "conflict_graph_node_count": int(conflict_graph["node_count"]),
            "conflict_graph_edge_count": int(conflict_graph["edge_count"]),
            "conflict_graph_pair_penalty_count": int(conflict_graph["pair_penalty_count"]),
            "old_selection_success": old_selection is not None,
            "h2_selection_success": h2_selection is not None,
            "old_selection_error": old_error,
            "h2_selection_error": h2_error,
            "old_runtime_seconds": old_runtime,
            "h2_runtime_seconds": h2_runtime,
            "evaluation_input_file": str(evaluation_path.relative_to(output_dir)).replace("\\", "/"),
            "old_render_file": (
                str(old_png.relative_to(output_dir)).replace("\\", "/")
                if old_png.is_file() else ""
            ),
            "h2_render_file": (
                str(h2_png.relative_to(output_dir)).replace("\\", "/")
                if h2_png.is_file() else ""
            ),
            "comparison_sheet": (
                str(comparison_path.relative_to(output_dir)).replace("\\", "/")
                if comparison_path.is_file() else ""
            ),
        },
    }


def _safe_run(task: Mapping[str, Any], output_dir_str: str) -> dict[str, Any]:
    try:
        return _run_case(task, Path(output_dir_str))
    except Exception as exc:
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
    allocation = allocate_h2b_seeds()
    allocation = [dict(row, pair_id=f"B{index:03d}") for index, row in enumerate(allocation, 1)]
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

    successes = {result["case"]["pair_id"]: result["case"] for result in results if result["ok"]}
    failures = [result for result in results if not result["ok"]]
    case_rows: list[dict[str, Any]] = []
    for task in tasks:
        pair_id = str(task["pair_id"])
        if pair_id in successes:
            case_rows.append(successes[pair_id])
        else:
            failure = next(result for result in failures if result["task"]["pair_id"] == pair_id)
            case_rows.append(
                {
                    **task,
                    "old_selection_success": False,
                    "h2_selection_success": False,
                    "upstream_failure": True,
                    "upstream_error": f"{failure['error_type']}: {failure['error_message']}",
                }
            )
    fields = (
        "pair_id", "prototype_id", "backbone_variant", "density_level", "replicate",
        "production_seed", "backbone_seed", "flower_seed", "branch_seed", "unit_seed",
        "ordinary_l1_count", "stage4_candidate_count", "stage4_eligible_candidate_count",
        "conflict_graph_node_count", "conflict_graph_edge_count",
        "conflict_graph_pair_penalty_count", "old_selection_success", "h2_selection_success",
        "old_selection_error", "h2_selection_error", "upstream_failure", "upstream_error",
        "old_runtime_seconds", "h2_runtime_seconds",
        "evaluation_input_file", "old_render_file", "h2_render_file", "comparison_sheet",
    )
    write_csv(output_dir / "cases.csv", case_rows, fields)
    write_json(output_dir / "failures.json", failures)
    write_json(
        output_dir / "run_manifest.json",
        {
            "mode": "smoke" if smoke else "full",
            "allocated_case_count": len(tasks),
            "upstream_success_count": len(successes),
            "upstream_failure_count": len(failures),
            "seed_allocation": tasks,
            "stage4_inventory_generated_once_per_case": True,
            "conflict_graph_built_once_per_case": True,
            "same_inventory_and_graph_passed_to_both_selectors": True,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ADJUDICATION_DIR / "h2b",
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
