#!/usr/bin/env python3
"""Run the formal five-prototype by three-seed stage-3B L1 global solve."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backbone_variation_v1 import (
    generate_backbone_variant,
    split_generation_seeds,
    validate_seed,
)
from fixed_visual_prior import validate_fixed_visual_prior
from flower_placement_v1 import generate_flower_layout_and_mount
from global_l1_flow import (
    SEEDS,
    generate_global_l1_flow_plan,
    validate_global_l1_flow_plan,
)
from prototype_strategy_v1 import (
    DEFAULT_REGISTRY_PATH,
    PROTOTYPE_IDS,
    PrototypeStrategyError,
    load_prototype_strategy_registry,
    parse_route_request,
    resolve_prototype_strategy,
    validate_route_request_against_strategy,
    validate_strategy_against_inputs,
)
from render_global_l1_flow import render_contact_sheet, render_png, render_svg
from strict_p0_v2 import load_materialized_strict_p0_v2


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
INPUT_REPO_ROOT = Path(
    os.environ.get("CHANZHI_FROZEN_INPUT_ROOT", str(REPO_ROOT))
).resolve()
STAGE1_ROOT = (
    INPUT_REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
)
STAGE2_ROOT = (
    INPUT_REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
)
STAGE25_ROOT = (
    INPUT_REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage25_morphology_v1"
)
STAGE3A_ROOT = (
    INPUT_REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage3a_fixed_visual_prior_v1"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage3b_edit_feedback_l1_flow_v2"
)
CONTRACT_PATH = DYNAMIC_DIR / "STAGE3B_L1_FLOW_CONTRACT_V2.json"
FEEDBACK_PRIOR_PATH = DYNAMIC_DIR / "EDIT_FEEDBACK_PRIOR_V1.json"
CURVE_GEOMETRY_PRIOR_PATH = (
    DYNAMIC_DIR / "EDITOR_CURVE_GEOMETRY_PRIOR_V4.json"
)
STAGE3_PLAN_CONTRACT_PATH = DYNAMIC_DIR / "STAGE3_PLAN_CONTRACT.json"


class Stage3BRunError(RuntimeError):
    """Formal stage-3B execution cannot proceed."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage3BRunError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _profile_rows(manifest: Mapping[str, Any], label: str) -> dict[str, Mapping[str, Any]]:
    rows = manifest.get("profiles")
    if not isinstance(rows, list) or [row.get("prototype_id") for row in rows] != list(
        PROTOTYPE_IDS
    ):
        raise Stage3BRunError(f"{label} prototype inventory/order mismatch")
    return {str(row["prototype_id"]): row for row in rows}


def _required_file(root: Path, relative: object, label: str) -> Path:
    path = root / str(relative)
    if not path.is_file():
        raise Stage3BRunError(f"{label} is missing: {path}")
    return path


def _load_inputs() -> tuple[
    dict[str, dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, str],
]:
    stage1_manifest_path = STAGE1_ROOT / "manifest.json"
    stage2_manifest_path = STAGE2_ROOT / "manifest.json"
    stage25_manifest_path = STAGE25_ROOT / "manifest.json"
    stage3a_manifest_path = STAGE3A_ROOT / "manifest.json"
    for path in (
        stage1_manifest_path,
        stage2_manifest_path,
        stage25_manifest_path,
        stage3a_manifest_path,
        CONTRACT_PATH,
        FEEDBACK_PRIOR_PATH,
        CURVE_GEOMETRY_PRIOR_PATH,
        STAGE3_PLAN_CONTRACT_PATH,
        DEFAULT_REGISTRY_PATH,
    ):
        if not path.is_file():
            raise Stage3BRunError(f"required stage-3B input is missing: {path}")

    stage1 = _read_json(stage1_manifest_path)
    stage2 = _read_json(stage2_manifest_path)
    stage25 = _read_json(stage25_manifest_path)
    stage3a = _read_json(stage3a_manifest_path)
    contract = _read_json(CONTRACT_PATH)
    feedback_prior = _read_json(FEEDBACK_PRIOR_PATH)
    curve_geometry_prior = _read_json(CURVE_GEOMETRY_PRIOR_PATH)
    stage3_plan_contract = _read_json(STAGE3_PLAN_CONTRACT_PATH)
    if stage1.get("schema") != "dynamic_branch_stage1_input_manifest_v1":
        raise Stage3BRunError("stage-1 manifest schema mismatch")
    if stage2.get("schema") != "dynamic_branch_stage2_analysis_manifest_v1":
        raise Stage3BRunError("stage-2 manifest schema mismatch")
    if stage25.get("schema") != "dynamic_branch_stage25_morphology_manifest_v1":
        raise Stage3BRunError("stage-2.5 manifest schema mismatch")
    if stage3a.get("schema") != "dynamic_branch_stage3a_manifest_v1":
        raise Stage3BRunError("stage-3A manifest schema mismatch")
    if stage2.get("review_gate", {}).get("status") != "analysis_approved":
        raise Stage3BRunError("stage-2 analysis gate is not approved")
    if stage25.get("review_gate", {}).get("status") != "morphology_approved":
        raise Stage3BRunError("stage-2.5 morphology gate is not approved")
    if stage3a.get("status") != "fixed_visual_prior_complete":
        raise Stage3BRunError("stage-3A visual prior is incomplete")
    if feedback_prior.get("schema") != "dynamic_branch_edit_feedback_prior_v1":
        raise Stage3BRunError("edit feedback prior schema mismatch")
    if curve_geometry_prior.get("schema") != (
        "dynamic_branch_editor_curve_geometry_prior_v4"
    ):
        raise Stage3BRunError("editor curve geometry prior schema mismatch")

    stage1_rows = _profile_rows(stage1, "stage-1")
    stage2_rows = _profile_rows(stage2, "stage-2")
    stage25_rows = _profile_rows(stage25, "stage-2.5")
    prior_path = _required_file(
        STAGE3A_ROOT,
        "fixed_visual_prior.json",
        "stage-3A fixed visual prior",
    )
    prior = _read_json(prior_path)
    validate_fixed_visual_prior(prior)

    inputs: dict[str, dict[str, Any]] = {}
    for prototype_id in PROTOTYPE_IDS:
        strict_row = stage1_rows[prototype_id]
        analysis_row = stage2_rows[prototype_id]
        morphology_row = stage25_rows[prototype_id]
        strict_path = _required_file(
            STAGE1_ROOT,
            strict_row["strict_p0_path"],
            f"{prototype_id} StrictP0",
        )
        analysis_path = _required_file(
            STAGE2_ROOT,
            analysis_row["prototype_analysis_path"],
            f"{prototype_id} analysis",
        )
        morphology_path = _required_file(
            STAGE25_ROOT,
            morphology_row["morphology_profile_path"],
            f"{prototype_id} morphology",
        )
        strict = _read_json(strict_path)
        analysis = _read_json(analysis_path)
        morphology = _read_json(morphology_path)
        if analysis_row["review_status"] != "analysis_approved":
            raise Stage3BRunError(f"{prototype_id} analysis is not approved")
        if morphology_row["review_status"] != "morphology_approved":
            raise Stage3BRunError(f"{prototype_id} morphology is not approved")
        inputs[prototype_id] = {
            "strict": strict,
            "analysis": analysis,
            "morphology": morphology,
        }

    provenance = {
        "frozen_input_root": str(INPUT_REPO_ROOT),
        "stage1_manifest": str(stage1_manifest_path),
        "stage2_manifest": str(stage2_manifest_path),
        "stage25_manifest": str(stage25_manifest_path),
        "stage3a_manifest": str(stage3a_manifest_path),
        "stage3b_contract": str(CONTRACT_PATH),
        "edit_feedback_prior": str(FEEDBACK_PRIOR_PATH),
        "editor_curve_geometry_prior": str(CURVE_GEOMETRY_PRIOR_PATH),
        "fixed_visual_prior": str(prior_path),
        "stage3_plan_contract": str(STAGE3_PLAN_CONTRACT_PATH),
        "prototype_strategy_registry": str(DEFAULT_REGISTRY_PATH),
    }
    return (
        inputs,
        prior,
        feedback_prior,
        curve_geometry_prior,
        contract,
        stage3_plan_contract,
        provenance,
    )


def generate_prototype_case(
    *,
    payload: Mapping[str, Any],
    prototype_strategy: Mapping[str, Any],
    production_seed: int,
    prior: Mapping[str, Any],
    feedback_prior: Mapping[str, Any],
    curve_geometry_prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    stage3_plan_contract: Mapping[str, Any],
    backbone_seed_override: int | None,
    branch_seed_override: int | None,
    backbone_rho: float | None,
    prototype_variant_id: str | None = None,
    flower_seed_override: int | None = None,
    unit_seed_override: int | None = None,
    flower_rho: float | None = None,
    ordinary_density_level_override: str | None = None,
) -> dict[str, Any]:
    """Run the one active per-case production chain under one frozen strategy."""

    baseline_strict = load_materialized_strict_p0_v2(payload["strict"])
    validate_strategy_against_inputs(
        prototype_strategy,
        baseline_strict,
        payload["analysis"],
        payload["morphology"],
    )
    derived_seeds = split_generation_seeds(production_seed)
    backbone_seed = (
        derived_seeds["backbone_seed"]
        if backbone_seed_override is None
        else validate_seed(backbone_seed_override, "backbone_seed")
    )
    flower_seed = (
        derived_seeds["flower_seed"]
        if flower_seed_override is None
        else validate_seed(flower_seed_override, "flower_seed")
    )
    branch_seed = (
        derived_seeds["branch_seed"]
        if branch_seed_override is None
        else validate_seed(branch_seed_override, "branch_seed")
    )
    unit_seed = (
        derived_seeds["unit_seed"]
        if unit_seed_override is None
        else validate_seed(unit_seed_override, "unit_seed")
    )
    backbone_strict, variation = generate_backbone_variant(
        baseline_strict,
        backbone_seed,
        backbone_rho,
        prototype_strategy=prototype_strategy,
        prototype_variant_id=prototype_variant_id,
    )
    (
        variant_strict,
        variant_analysis,
        flower_layout_plan,
        flower_mount_plan,
    ) = generate_flower_layout_and_mount(
        backbone_strict,
        payload["morphology"],
        stage3_plan_contract,
        flower_seed=flower_seed,
        prototype_strategy=prototype_strategy,
        rho=flower_rho,
    )
    validate_strategy_against_inputs(
        prototype_strategy,
        variant_strict,
        variant_analysis,
        payload["morphology"],
    )
    plan, inventory = generate_global_l1_flow_plan(
        variant_strict.as_dict(),
        variant_analysis,
        payload["morphology"],
        prior,
        contract,
        branch_seed,
        feedback_prior,
        curve_geometry_prior,
        flower_mount_plan,
        backbone_seed=backbone_seed,
        flower_seed=flower_seed,
        unit_seed=unit_seed,
        prototype_strategy=prototype_strategy,
        backbone_variation=variation,
        flower_layout_plan=flower_layout_plan,
        ordinary_density_level_override=ordinary_density_level_override,
    )
    validate_global_l1_flow_plan(plan)
    return {
        "backbone_seed": backbone_seed,
        "flower_seed": flower_seed,
        "branch_seed": branch_seed,
        "unit_seed": unit_seed,
        "variant_strict": variant_strict,
        "variant_analysis": variant_analysis,
        "variation": variation,
        "flower_layout_plan": flower_layout_plan,
        "flower_mount_plan": flower_mount_plan,
        "plan": plan,
        "inventory": inventory,
    }


def _write_readme(output: Path) -> None:
    text = """# 阶段3B全局L1流线

- 范围：五个SW原型 × seeds 4101/4102/4103。
- 内容：先按形态家族生成并冻结花朵挂接L1，再规划剩余普通L1的根位、方向、距离和目标区。
- 不包含：L2、L3、叶片、芽头、卷头和最终枝条曲线编译。
- 求解：花朵挂接枝不等待普通枝；普通枝在剩余容量中执行一次前向全局集合求解。
- 禁止：自动修复、自动删枝、验证引导重试、验证引导重采样和静默回退。
- 状态：全部结果均为 `l1_flow_pending_visual_review`，数值诊断不能替代人工验收。
"""
    output.write_text(text, encoding="utf-8", newline="\n")


def run(
    output: Path,
    prototype_ids: tuple[str, ...] = PROTOTYPE_IDS,
    seeds: tuple[int, ...] = SEEDS,
    *,
    route_request: Mapping[str, Any] | None = None,
    backbone_seed_override: int | None = None,
    flower_seed_override: int | None = None,
    branch_seed_override: int | None = None,
    unit_seed_override: int | None = None,
    backbone_rho: float | None = None,
    flower_rho: float | None = None,
    prototype_variant_id: str | None = None,
    ordinary_density_level_override: str | None = None,
) -> None:
    if output.exists():
        raise Stage3BRunError(f"formal stage-3B output already exists: {output}")
    registry = load_prototype_strategy_registry()
    if route_request is not None:
        if prototype_ids != PROTOTYPE_IDS:
            raise Stage3BRunError(
                "explicit prototype selection and semantic route request are mutually exclusive"
            )
        try:
            routed_strategy = resolve_prototype_strategy(route_request, registry)
        except PrototypeStrategyError as exc:
            raise Stage3BRunError(str(exc)) from exc
        prototype_ids = (str(routed_strategy["prototype_id"]),)
    strategies = {
        prototype_id: resolve_prototype_strategy(
            {"prototype_id": prototype_id},
            registry,
        )
        for prototype_id in prototype_ids
    }
    if route_request is not None:
        validate_route_request_against_strategy(
            route_request,
            strategies[prototype_ids[0]],
        )
    (
        inputs,
        prior,
        feedback_prior,
        curve_geometry_prior,
        contract,
        stage3_plan_contract,
        provenance,
    ) = _load_inputs()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="stage3b_", dir=str(output.parent)) as directory:
        temporary = Path(directory)
        task_rows: list[dict[str, Any]] = []
        clean_paths: list[Path] = []
        debug_paths: list[Path] = []
        triple_paths: list[Path] = []
        for prototype_id in prototype_ids:
            prototype_clean: list[Path] = []
            prototype_triple: list[Path] = []
            payload = inputs[prototype_id]
            prototype_strategy = strategies[prototype_id]
            for production_seed in seeds:
                case_result = generate_prototype_case(
                    payload=payload,
                    prototype_strategy=prototype_strategy,
                    production_seed=production_seed,
                    prior=prior,
                    feedback_prior=feedback_prior,
                    curve_geometry_prior=curve_geometry_prior,
                    contract=contract,
                    stage3_plan_contract=stage3_plan_contract,
                    backbone_seed_override=backbone_seed_override,
                    flower_seed_override=flower_seed_override,
                    branch_seed_override=branch_seed_override,
                    unit_seed_override=unit_seed_override,
                    backbone_rho=backbone_rho,
                    flower_rho=flower_rho,
                    prototype_variant_id=prototype_variant_id,
                    ordinary_density_level_override=(
                        ordinary_density_level_override
                    ),
                )
                backbone_seed = int(case_result["backbone_seed"])
                flower_seed = int(case_result["flower_seed"])
                branch_seed = int(case_result["branch_seed"])
                unit_seed = int(case_result["unit_seed"])
                variant_strict = case_result["variant_strict"]
                variant_analysis = case_result["variant_analysis"]
                variation = case_result["variation"]
                flower_layout_plan = case_result["flower_layout_plan"]
                flower_mount_plan = case_result["flower_mount_plan"]
                plan = case_result["plan"]
                inventory = case_result["inventory"]
                case = temporary / prototype_id / f"seed_{production_seed}"
                case.mkdir(parents=True)
                strict_variant_path = case / "strict_p0_variant.json"
                analysis_variant_path = case / "prototype_analysis_variant.json"
                flower_layout_path = case / "flower_layout_plan.json"
                flower_mount_path = case / "flower_mount_plan.json"
                plan_path = case / "global_l1_flow_plan.json"
                inventory_path = case / "global_l1_candidate_inventory.json"
                clean_path = case / "l1_flow.png"
                debug_path = case / "l1_flow_debug.png"
                triple_path = case / "three_repeat_l1_flow.png"
                svg_path = case / "l1_flow.svg"
                triple_svg_path = case / "three_repeat_l1_flow.svg"
                _write_json(strict_variant_path, variant_strict.as_dict())
                _write_json(analysis_variant_path, variant_analysis)
                _write_json(flower_layout_path, flower_layout_plan)
                _write_json(flower_mount_path, flower_mount_plan)
                _write_json(plan_path, plan)
                _write_json(inventory_path, inventory)
                render_png(variant_analysis, plan, clean_path)
                render_png(variant_analysis, plan, debug_path, debug=True)
                render_png(
                    variant_analysis,
                    plan,
                    triple_path,
                    repeat_count=3,
                )
                render_svg(variant_analysis, plan, svg_path)
                render_svg(
                    variant_analysis,
                    plan,
                    triple_svg_path,
                    repeat_count=3,
                )
                clean_paths.append(clean_path)
                debug_paths.append(debug_path)
                triple_paths.append(triple_path)
                prototype_clean.append(clean_path)
                prototype_triple.append(triple_path)
                task_rows.append(
                    {
                        "task_id": (
                            f"{prototype_id}__seed_{production_seed}__"
                            "dynamic_global_l1_flow_v2"
                        ),
                        "prototype_id": prototype_id,
                        "family_id": plan["family_id"],
                        "prototype_strategy": prototype_strategy,
                        "production_seed": production_seed,
                        "seed": branch_seed,
                        "backbone_seed": backbone_seed,
                        "flower_seed": flower_seed,
                        "branch_seed": branch_seed,
                        "unit_seed": unit_seed,
                        "ordinary_density_level": plan["count_derivation"][
                            "ordinary_density_level"
                        ],
                        "ordinary_density_source": plan["count_derivation"][
                            "ordinary_density_source"
                        ],
                        "backbone_variation": variation,
                        "flower_layout": flower_layout_plan,
                        "state": plan["review"]["status"],
                        "l1_count": len(plan["lanes"]),
                        "flower_mount_count": len(
                            flower_mount_plan["mounts"]
                        ),
                        "total_l1_with_flower_support_count": (
                            len(plan["lanes"])
                            + len(flower_mount_plan["mounts"])
                        ),
                        "role_counts": plan["role_counts"],
                        "candidate_count": plan["diagnostics"]["candidate_count"],
                        "feasible_candidate_count": plan["diagnostics"][
                            "feasible_candidate_count"
                        ],
                        "hard_issue_count": plan["diagnostics"]["hard_issue_count"],
                        "plan_digest": plan["plan_digest"],
                        "files": {
                            path.name: {
                                "path": str(path.relative_to(temporary)).replace("\\", "/"),
                            }
                            for path in (
                                strict_variant_path,
                                analysis_variant_path,
                                flower_layout_path,
                                flower_mount_path,
                                plan_path,
                                inventory_path,
                                clean_path,
                                debug_path,
                                triple_path,
                                svg_path,
                                triple_svg_path,
                            )
                        },
                    }
                )
            render_contact_sheet(
                prototype_clean,
                temporary / prototype_id / "prototype_l1_flow_contact_sheet.png",
                columns=3,
            )
            render_contact_sheet(
                prototype_triple,
                temporary / prototype_id / "prototype_three_repeat_l1_flow_contact_sheet.png",
                columns=3,
            )

        clean_sheet = temporary / "stage3b_l1_flow_contact_sheet.png"
        debug_sheet = temporary / "stage3b_l1_flow_debug_contact_sheet.png"
        triple_sheet = temporary / "stage3b_three_repeat_l1_flow_contact_sheet.png"
        render_contact_sheet(clean_paths, clean_sheet, columns=3)
        render_contact_sheet(debug_paths, debug_sheet, columns=3)
        render_contact_sheet(triple_paths, triple_sheet, columns=3)
        _write_readme(temporary / "README.md")

        manifest = {
            "schema": "dynamic_branch_stage3b_l1_flow_manifest_v2",
            "stage": "3B",
            "contract_id": contract["contract_id"],
            "prototype_ids": list(prototype_ids),
            "prototype_strategies": [strategies[value] for value in prototype_ids],
            "seeds": list(seeds),
            "task_count": len(task_rows),
            "success_count": len(task_rows),
            "failure_count": 0,
            "scope": {
                "l1_only": True,
                "l2_present": False,
                "l3_present": False,
                "terminal_content_present": False,
            },
            "generation_policy": {
                "one_forward_global_solve_per_task": True,
                "experimental_variants_created": False,
                "automatic_repair_used": False,
                "automatic_deletion_used": False,
                "validation_guided_retry_used": False,
                "validation_guided_resample_used": False,
                "silent_fallback_used": False,
                "edit_feedback_prior_consumed": True,
                "edited_svg_templates_consumed": False,
                "strict_p0_variant_generated_per_task": True,
                "prototype_analysis_variant_generated_per_task": True,
                "flower_layout_generated_between_backbone_and_mount": True,
                "sw3_joint_flower_mount_feasibility_consumed": True,
                "flower_seed_independent_from_other_seed_domains": True,
                "dynamic_l1_count_enabled": True,
                "ordinary_l1_density_level_enabled": True,
                "ordinary_l1_density_level_uses_branch_seed_by_default": True,
                "flower_support_excluded_from_ordinary_density_count": True,
                "dynamic_non_equidistant_root_rhythm_enabled": True,
                "flower_mounting_generated_before_ordinary_l1": True,
                "ordinary_l1_candidates_constrained_by_flower_mounting": True,
                "prototype_strategy_resolved_once_before_seed_split": True,
                "prototype_strategy_frozen_through_stage3b": True,
            },
            "review_gate": {
                "status": "l1_flow_pending_visual_review",
                "numeric_checks_cannot_auto_approve_visual_gate": True,
                "all_fifteen_tasks_require_terminal_review_state": True,
            },
            "contact_sheets": {
                "clean": clean_sheet.name,
                "debug": debug_sheet.name,
                "triple_repeat": triple_sheet.name,
            },
            "provenance": provenance,
            "tasks": task_rows,
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--prototype",
        choices=PROTOTYPE_IDS,
        action="append",
        dest="prototypes",
        help="Run only the selected prototype; may be repeated.",
    )
    parser.add_argument(
        "--route-request",
        help="Semantic route as a JSON object or path to a JSON object.",
    )
    parser.add_argument(
        "--seed",
        action="append",
        type=int,
        dest="seeds",
        help="Run only the selected seed; may be repeated.",
    )
    parser.add_argument("--backbone-seed", type=int)
    parser.add_argument("--flower-seed", type=int)
    parser.add_argument("--branch-seed", type=int)
    parser.add_argument("--unit-seed", type=int)
    parser.add_argument("--backbone-rho", type=float)
    parser.add_argument("--flower-rho", type=float)
    parser.add_argument(
        "--ordinary-density-level",
        choices=("simple", "medium", "rich"),
        help=(
            "Controlled 5D review override; production defaults to the "
            "branch-seed density level."
        ),
    )
    parser.add_argument(
        "--prototype-variant",
        choices=("expanded", "compact", "swept"),
        help="Explicit combined prototype variant; default selection is deterministic from the backbone seed.",
    )
    args = parser.parse_args()
    if args.route_request is not None and args.prototypes:
        parser.error("--route-request cannot be combined with --prototype")
    try:
        route_request = (
            parse_route_request(args.route_request)
            if args.route_request is not None
            else None
        )
    except PrototypeStrategyError as exc:
        parser.error(str(exc))
    run(
        args.output.resolve(),
        tuple(args.prototypes or PROTOTYPE_IDS),
        tuple(args.seeds or SEEDS),
        route_request=route_request,
        backbone_seed_override=args.backbone_seed,
        flower_seed_override=args.flower_seed,
        branch_seed_override=args.branch_seed,
        unit_seed_override=args.unit_seed,
        backbone_rho=args.backbone_rho,
        flower_rho=args.flower_rho,
        prototype_variant_id=args.prototype_variant,
        ordinary_density_level_override=args.ordinary_density_level,
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
