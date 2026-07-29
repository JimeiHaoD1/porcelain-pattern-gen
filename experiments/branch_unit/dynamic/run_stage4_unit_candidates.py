#!/usr/bin/env python3
"""Run the formal 15-task stage-4 complete Unit candidate generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from branch_unit_grammar_v1 import (
    UnitGrammarError,
    generate_unit_candidate_inventory,
    validate_unit_candidate_inventory,
)
from render_stage4_unit_atlas import (
    render_contact_sheet,
    render_fixed_baseline_pair,
    render_lane_context_atlas,
    render_role_grammar_atlas,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
STAGE2_ROOT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE3A_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3a_fixed_visual_prior_v1"
)
STAGE3B_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3b_global_l1_flow_v1"
)
FIXED_ROOT = (
    REPO_ROOT / "artifacts" / "frozen_baselines" / "fixed_depth_7_12_2_v23"
)
CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V1.json"
APPROVAL_PATH = STAGE3B_ROOT / "stage3b_approval.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_unit_candidates_v1"
)
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
SEEDS = (4101, 4102, 4103)


class Stage4RunError(RuntimeError):
    """The formal stage-4 launch matrix or output package is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage4RunError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified_file(
    root: Path,
    relative: object,
    expected_sha256: object,
    label: str,
) -> Path:
    path = (root / str(relative)).resolve()
    if root.resolve() not in path.parents:
        raise Stage4RunError(f"{label} path escapes its artifact root")
    if not path.is_file() or _sha256(path) != expected_sha256:
        raise Stage4RunError(f"{label} file/hash mismatch: {path}")
    return path


def _load_inputs() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[tuple[str, int], dict[str, Any]],
    dict[str, str],
]:
    required = (
        CONTRACT_PATH,
        APPROVAL_PATH,
        STAGE2_ROOT / "manifest.json",
        STAGE3A_ROOT / "manifest.json",
        STAGE3A_ROOT / "fixed_visual_prior.json",
        STAGE3B_ROOT / "manifest.json",
    )
    for path in required:
        if not path.is_file():
            raise Stage4RunError(f"required stage-4 input is missing: {path}")

    contract = _read_json(CONTRACT_PATH)
    approval = _read_json(APPROVAL_PATH)
    stage2_manifest = _read_json(STAGE2_ROOT / "manifest.json")
    stage3a_manifest = _read_json(STAGE3A_ROOT / "manifest.json")
    stage3b_manifest = _read_json(STAGE3B_ROOT / "manifest.json")
    prior = _read_json(STAGE3A_ROOT / "fixed_visual_prior.json")
    if contract.get("schema") != "dynamic_branch_stage4_unit_grammar_contract_v1":
        raise Stage4RunError("stage-4 contract schema mismatch")
    if approval.get("schema") != contract["required_inputs"]["stage3b_approval_schema"]:
        raise Stage4RunError("stage-3B approval schema mismatch")
    if approval.get("status") != contract["required_inputs"]["stage3b_approval_status"]:
        raise Stage4RunError("stage-3B visual gate is not approved")
    if approval.get("approved_task_count") != 15 or approval.get("stage4_unlocked") is not True:
        raise Stage4RunError("stage-3B approval does not unlock all fifteen tasks")
    if approval.get("stage3b_manifest_sha256") != _sha256(
        STAGE3B_ROOT / "manifest.json"
    ):
        raise Stage4RunError("stage-3B manifest changed after approval")
    if stage2_manifest.get("schema") != "dynamic_branch_stage2_analysis_manifest_v1":
        raise Stage4RunError("stage-2 manifest schema mismatch")
    if stage3a_manifest.get("schema") != "dynamic_branch_stage3a_manifest_v1":
        raise Stage4RunError("stage-3A manifest schema mismatch")
    if stage3b_manifest.get("schema") != contract["required_inputs"]["stage3b_schema"]:
        raise Stage4RunError("stage-3B manifest schema mismatch")
    if prior.get("schema") != contract["required_inputs"]["stage3a_prior_schema"]:
        raise Stage4RunError("stage-3A prior schema mismatch")
    if tuple(stage3b_manifest.get("prototype_ids", ())) != PROTOTYPE_IDS:
        raise Stage4RunError("stage-3B prototype matrix mismatch")
    if tuple(stage3b_manifest.get("seeds", ())) != SEEDS:
        raise Stage4RunError("stage-3B seed matrix mismatch")

    stage2_rows = {
        str(row["prototype_id"]): row
        for row in stage2_manifest.get("profiles", [])
    }
    if tuple(stage2_rows) != PROTOTYPE_IDS:
        raise Stage4RunError("stage-2 prototype matrix mismatch")
    analyses: dict[str, dict[str, Any]] = {}
    for prototype_id in PROTOTYPE_IDS:
        row = stage2_rows[prototype_id]
        path = _verified_file(
            STAGE2_ROOT,
            row["prototype_analysis_path"],
            row["prototype_analysis_sha256"],
            f"{prototype_id} analysis",
        )
        analysis = _read_json(path)
        if analysis.get("schema") != contract["required_inputs"]["stage2_analysis_schema"]:
            raise Stage4RunError(f"{prototype_id} analysis schema mismatch")
        if analysis.get("analysis_core_digest") != row.get(
            "analysis_core_digest"
        ):
            raise Stage4RunError(
                f"{prototype_id} analysis core digest mismatch"
            )
        analyses[prototype_id] = analysis

    approved_rows = {
        (str(row["prototype_id"]), int(row["seed"])): row
        for row in approval["approved_tasks"]
    }
    expected = [
        (prototype_id, seed)
        for prototype_id in PROTOTYPE_IDS
        for seed in SEEDS
    ]
    if list(approved_rows) != expected:
        raise Stage4RunError("stage-3B approval launch matrix mismatch")
    plans: dict[tuple[str, int], dict[str, Any]] = {}
    for key in expected:
        row = approved_rows[key]
        plan_path = _verified_file(
            STAGE3B_ROOT,
            row["plan_path"],
            row["plan_sha256"],
            f"{row['task_id']} approved plan",
        )
        plan = _read_json(plan_path)
        if plan.get("plan_digest") != row.get("plan_digest"):
            raise Stage4RunError(f"{row['task_id']} approved digest mismatch")
        if len(plan.get("lanes", ())) != row.get("lane_count"):
            raise Stage4RunError(f"{row['task_id']} approved lane count mismatch")
        plans[key] = plan

    provenance = {
        "stage2_manifest_sha256": _sha256(STAGE2_ROOT / "manifest.json"),
        "stage3a_manifest_sha256": _sha256(STAGE3A_ROOT / "manifest.json"),
        "fixed_visual_prior_sha256": _sha256(
            STAGE3A_ROOT / "fixed_visual_prior.json"
        ),
        "stage3b_manifest_sha256": _sha256(STAGE3B_ROOT / "manifest.json"),
        "stage3b_approval_sha256": _sha256(APPROVAL_PATH),
        "stage4_contract_sha256": _sha256(CONTRACT_PATH),
    }
    return contract, prior, analyses, plans, provenance


def _write_readme(output: Path) -> None:
    output.write_text(
        """# 阶段4完整Unit候选池

- 输入：阶段3B明确验收通过并冻结的15组L1规划。
- 内容：按角色语法生成L2/L3三次贝塞尔枝条候选，并保留全部合法与非法候选。
- 隔离：不读取被否决的旧阶段3布局或旧阶段4曲线。
- 生成：带种子的确定性Halton分位映射，每个声明的语法/角色/参数层只生成一次。
- 禁止：验证引导重试、重采样、自动修复、删枝、静默回退、best-of-N优选。
- 边界：本阶段不执行跨Unit全局组合；候选冲突图和全局选择属于阶段5。
- 范围：仅枝条骨架，不包含叶片、芽头或卷头。
- 状态：`unit_candidate_pool_pending_visual_review`。
""",
        encoding="utf-8",
        newline="\n",
    )


def run(output: Path) -> None:
    if output.exists():
        raise Stage4RunError(f"formal stage-4 output already exists: {output}")
    contract, prior, analyses, plans, provenance = _load_inputs()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="stage4_unit_candidates_",
        dir=str(output.parent),
    ) as directory:
        temporary = Path(directory)
        task_rows: list[dict[str, Any]] = []
        all_candidates: list[dict[str, Any]] = []
        all_atlases: list[Path] = []
        prototype_atlases: dict[str, list[Path]] = {
            prototype_id: [] for prototype_id in PROTOTYPE_IDS
        }
        invalid_reason_counts: Counter[str] = Counter()
        total_lane_count = 0
        total_candidate_count = 0
        total_feasible_count = 0
        total_level_counts: Counter[str] = Counter()

        for prototype_id in PROTOTYPE_IDS:
            for seed in SEEDS:
                plan = plans[(prototype_id, seed)]
                analysis = analyses[prototype_id]
                try:
                    inventory = generate_unit_candidate_inventory(
                        plan,
                        analysis,
                        prior,
                        contract,
                    )
                    validate_unit_candidate_inventory(inventory, contract)
                except UnitGrammarError as exc:
                    raise Stage4RunError(
                        f"{prototype_id} seed {seed} candidate generation failed: {exc}"
                    ) from exc
                if prototype_id == "proto_sw_1_3" and not any(
                    lane["source_channel"] == "fixed_warp_visual_prior"
                    for lane in plan["lanes"]
                ):
                    raise Stage4RunError(
                        f"proto_sw_1_3 seed {seed} lacks its required fixed-derived L1 channel"
                    )

                case = temporary / prototype_id / f"seed_{seed}"
                case.mkdir(parents=True)
                inventory_path = case / "unit_candidate_inventory.json"
                atlas_path = case / "unit_candidate_context_atlas.png"
                _write_json(inventory_path, inventory)
                render_lane_context_atlas(
                    analysis,
                    plan,
                    inventory,
                    atlas_path,
                )
                all_atlases.append(atlas_path)
                prototype_atlases[prototype_id].append(atlas_path)
                all_candidates.extend(inventory["candidates"])
                total_lane_count += inventory["lane_count"]
                total_candidate_count += inventory["candidate_count"]
                total_feasible_count += inventory["feasible_candidate_count"]
                for candidate in inventory["candidates"]:
                    for curve in candidate["curves"]:
                        total_level_counts[curve["level"]] += 1
                    for issue in candidate["intrinsic_diagnostics"]["issues"]:
                        invalid_reason_counts[str(issue["code"])] += 1

                pair_path: Path | None = None
                if prototype_id == "proto_sw_1_3":
                    fixed_image = (
                        FIXED_ROOT / "outputs" / f"seed_{seed}_units.png"
                    )
                    if not fixed_image.is_file():
                        raise Stage4RunError(
                            f"fixed paired baseline image is missing: {fixed_image}"
                        )
                    pair_path = case / "fixed_stage4_visual_pair.png"
                    render_fixed_baseline_pair(
                        fixed_image,
                        atlas_path,
                        pair_path,
                        seed=seed,
                    )

                files = [inventory_path, atlas_path]
                if pair_path is not None:
                    files.append(pair_path)
                task_rows.append(
                    {
                        "task_id": f"{prototype_id}__seed_{seed}__unit_candidates_v1",
                        "prototype_id": prototype_id,
                        "family_id": inventory["family_id"],
                        "seed": seed,
                        "state": inventory["review"]["status"],
                        "source_plan_digest": inventory["source_plan_digest"],
                        "lane_count": inventory["lane_count"],
                        "candidate_count": inventory["candidate_count"],
                        "feasible_candidate_count": inventory[
                            "feasible_candidate_count"
                        ],
                        "invalid_candidate_count": inventory[
                            "invalid_candidate_count"
                        ],
                        "lanes_without_feasible_candidate": inventory[
                            "coverage"
                        ]["lanes_without_feasible_candidate"],
                        "inventory_digest": inventory["inventory_digest"],
                        "files": {
                            path.name: {
                                "path": str(path.relative_to(temporary)).replace(
                                    "\\",
                                    "/",
                                ),
                                "sha256": _sha256(path),
                            }
                            for path in files
                        },
                    }
                )

            prototype_sheet = (
                temporary / prototype_id / "prototype_unit_candidate_atlas.png"
            )
            render_contact_sheet(
                prototype_atlases[prototype_id],
                prototype_sheet,
                columns=3,
            )

        role_atlas = temporary / "stage4_role_grammar_atlas.png"
        all_sheet = temporary / "stage4_unit_candidate_contact_sheet.png"
        render_role_grammar_atlas(all_candidates, role_atlas)
        render_contact_sheet(all_atlases, all_sheet, columns=3)
        _write_readme(temporary / "README.md")

        manifest = {
            "schema": "dynamic_branch_stage4_unit_candidate_manifest_v1",
            "stage": "4",
            "contract_id": contract["contract_id"],
            "prototype_ids": list(PROTOTYPE_IDS),
            "seeds": list(SEEDS),
            "task_count": len(task_rows),
            "success_count": len(task_rows),
            "failure_count": 0,
            "total_lane_count": total_lane_count,
            "total_candidate_count": total_candidate_count,
            "total_feasible_candidate_count": total_feasible_count,
            "total_invalid_candidate_count": (
                total_candidate_count - total_feasible_count
            ),
            "total_candidate_curve_level_counts": dict(
                sorted(total_level_counts.items())
            ),
            "invalid_reason_counts": dict(sorted(invalid_reason_counts.items())),
            "scope": {
                "complete_branch_unit_candidates_present": True,
                "global_unit_selection_present": False,
                "whole_composition_output_present": False,
                "leaves_present": False,
                "buds_present": False,
                "curl_heads_present": False,
            },
            "generation_policy": {
                "declared_grammar_role_strata_enumerated_once": True,
                "experimental_variants_created": False,
                "validation_guided_retry_used": False,
                "validation_guided_resample_used": False,
                "automatic_repair_used": False,
                "automatic_deletion_used": False,
                "silent_fallback_used": False,
                "best_of_n_selection_used": False,
            },
            "coverage": {
                "all_approved_l1_lanes_consumed": True,
                "every_lane_has_feasible_complete_unit_candidate": True,
                "lanes_without_feasible_candidate": [],
            },
            "review_gate": {
                "status": contract["output"]["review_state"],
                "numeric_checks_cannot_auto_approve_visual_gate": True,
                "stage5_unlocked": False,
            },
            "contact_sheets": {
                role_atlas.name: _sha256(role_atlas),
                all_sheet.name: _sha256(all_sheet),
            },
            "provenance": provenance,
            "tasks": task_rows,
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.replace(output)


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
    except Stage4RunError as exc:
        raise SystemExit(f"stage-4 run error: {exc}") from exc
