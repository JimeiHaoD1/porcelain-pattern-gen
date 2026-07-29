#!/usr/bin/env python3
"""Run the formal five-prototype by three-seed stage-3B L1 global solve."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from fixed_visual_prior import file_sha256, validate_fixed_visual_prior
from global_l1_flow import (
    GlobalL1FlowError,
    PROTOTYPE_IDS,
    SEEDS,
    generate_global_l1_flow_plan,
    validate_global_l1_flow_plan,
)
from render_global_l1_flow import render_contact_sheet, render_png, render_svg


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
STAGE1_ROOT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
STAGE2_ROOT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE25_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
)
STAGE3A_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3a_fixed_visual_prior_v1"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3b_global_l1_flow_v1"
)
CONTRACT_PATH = DYNAMIC_DIR / "STAGE3B_L1_FLOW_CONTRACT_V1.json"


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


def _verified_file(root: Path, relative: object, sha256: object, label: str) -> Path:
    path = root / str(relative)
    if not path.is_file():
        raise Stage3BRunError(f"{label} is missing: {path}")
    if file_sha256(path) != sha256:
        raise Stage3BRunError(f"{label} hash mismatch: {path}")
    return path


def _load_inputs(contract_path: Path = CONTRACT_PATH) -> tuple[
    dict[str, dict[str, Any]],
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
        contract_path,
    ):
        if not path.is_file():
            raise Stage3BRunError(f"required stage-3B input is missing: {path}")

    stage1 = _read_json(stage1_manifest_path)
    stage2 = _read_json(stage2_manifest_path)
    stage25 = _read_json(stage25_manifest_path)
    stage3a = _read_json(stage3a_manifest_path)
    contract = _read_json(contract_path)
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

    stage1_rows = _profile_rows(stage1, "stage-1")
    stage2_rows = _profile_rows(stage2, "stage-2")
    stage25_rows = _profile_rows(stage25, "stage-2.5")
    prior_path = _verified_file(
        STAGE3A_ROOT,
        "fixed_visual_prior.json",
        stage3a["files"]["fixed_visual_prior.json"]["sha256"],
        "stage-3A fixed visual prior",
    )
    prior = _read_json(prior_path)
    validate_fixed_visual_prior(prior)

    inputs: dict[str, dict[str, Any]] = {}
    for prototype_id in PROTOTYPE_IDS:
        strict_row = stage1_rows[prototype_id]
        analysis_row = stage2_rows[prototype_id]
        morphology_row = stage25_rows[prototype_id]
        strict_path = _verified_file(
            STAGE1_ROOT,
            strict_row["strict_p0_path"],
            strict_row["strict_p0_sha256"],
            f"{prototype_id} StrictP0",
        )
        analysis_path = _verified_file(
            STAGE2_ROOT,
            analysis_row["prototype_analysis_path"],
            analysis_row["prototype_analysis_sha256"],
            f"{prototype_id} analysis",
        )
        morphology_path = _verified_file(
            STAGE25_ROOT,
            morphology_row["morphology_profile_path"],
            morphology_row["morphology_profile_sha256"],
            f"{prototype_id} morphology",
        )
        strict = _read_json(strict_path)
        analysis = _read_json(analysis_path)
        morphology = _read_json(morphology_path)
        if analysis["strict_p0_digest"] != strict_row["strict_p0_digest"]:
            raise Stage3BRunError(f"{prototype_id} StrictP0/analysis digest mismatch")
        if analysis["analysis_digest"] != morphology["source_stage2_analysis_digest"]:
            raise Stage3BRunError(f"{prototype_id} analysis/morphology digest mismatch")
        if morphology["morphology_digest"] != morphology_row["morphology_digest"]:
            raise Stage3BRunError(f"{prototype_id} morphology digest mismatch")
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
        "stage1_manifest_sha256": file_sha256(stage1_manifest_path),
        "stage2_manifest_sha256": file_sha256(stage2_manifest_path),
        "stage25_manifest_sha256": file_sha256(stage25_manifest_path),
        "stage3a_manifest_sha256": file_sha256(stage3a_manifest_path),
        "stage3b_contract_sha256": file_sha256(contract_path),
        "fixed_visual_prior_sha256": file_sha256(prior_path),
    }
    return inputs, prior, contract, provenance


def _write_readme(output: Path) -> None:
    text = """# 阶段3B全局L1流线

- 范围：五个SW原型 × seeds 4101/4102/4103。
- 内容：只规划L1的根位、方向、距离、目标区和花位关系。
- 不包含：L2、L3、叶片、芽头、卷头和最终枝条曲线编译。
- 求解：每个任务执行一次前向全局集合求解；候选枚举属于求解过程。
- 禁止：自动修复、自动删枝、验证引导重试、验证引导重采样和静默回退。
- 状态：全部结果均为 `l1_flow_pending_visual_review`，数值诊断不能替代人工验收。
"""
    output.write_text(text, encoding="utf-8", newline="\n")


def run(output: Path, contract_path: Path = CONTRACT_PATH) -> None:
    if output.exists():
        raise Stage3BRunError(f"formal stage-3B output already exists: {output}")
    inputs, prior, contract, provenance = _load_inputs(contract_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="stage3b_", dir=str(output.parent)) as directory:
        temporary = Path(directory)
        task_rows: list[dict[str, Any]] = []
        clean_paths: list[Path] = []
        debug_paths: list[Path] = []
        triple_paths: list[Path] = []
        for prototype_id in PROTOTYPE_IDS:
            prototype_clean: list[Path] = []
            prototype_triple: list[Path] = []
            payload = inputs[prototype_id]
            for seed in SEEDS:
                case = temporary / prototype_id / f"seed_{seed}"
                case.mkdir(parents=True)
                try:
                    plan, inventory = generate_global_l1_flow_plan(
                        payload["strict"],
                        payload["analysis"],
                        payload["morphology"],
                        prior,
                        contract,
                        seed,
                    )
                except GlobalL1FlowError as exc:
                    raise Stage3BRunError(
                        f"{prototype_id} seed {seed} L1 solve failed: {exc}"
                    ) from exc
                validate_global_l1_flow_plan(plan)
                plan_path = case / "global_l1_flow_plan.json"
                inventory_path = case / "global_l1_candidate_inventory.json"
                clean_path = case / "l1_flow.png"
                debug_path = case / "l1_flow_debug.png"
                triple_path = case / "three_repeat_l1_flow.png"
                svg_path = case / "l1_flow.svg"
                triple_svg_path = case / "three_repeat_l1_flow.svg"
                _write_json(plan_path, plan)
                _write_json(inventory_path, inventory)
                render_png(payload["analysis"], plan, clean_path)
                render_png(payload["analysis"], plan, debug_path, debug=True)
                render_png(
                    payload["analysis"],
                    plan,
                    triple_path,
                    repeat_count=3,
                )
                render_svg(payload["analysis"], plan, svg_path)
                render_svg(
                    payload["analysis"],
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
                        "task_id": f"{prototype_id}__seed_{seed}__global_l1_flow_v1",
                        "prototype_id": prototype_id,
                        "family_id": plan["family_id"],
                        "seed": seed,
                        "state": plan["review"]["status"],
                        "l1_count": len(plan["lanes"]),
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
                                "sha256": file_sha256(path),
                            }
                            for path in (
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
            "schema": "dynamic_branch_stage3b_l1_flow_manifest_v1",
            "stage": "3B",
            "contract_id": contract["contract_id"],
            "prototype_ids": list(PROTOTYPE_IDS),
            "seeds": list(SEEDS),
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
            },
            "review_gate": {
                "status": "l1_flow_pending_visual_review",
                "numeric_checks_cannot_auto_approve_visual_gate": True,
                "all_fifteen_tasks_require_terminal_review_state": True,
            },
            "contact_sheets": {
                clean_sheet.name: file_sha256(clean_sheet),
                debug_sheet.name: file_sha256(debug_sheet),
                triple_sheet.name: file_sha256(triple_sheet),
            },
            "provenance": provenance,
            "tasks": task_rows,
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args()
    run(args.output.resolve(), args.contract.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
