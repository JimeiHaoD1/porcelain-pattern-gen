#!/usr/bin/env python3
"""Generate the formal 5x3 complete dynamic BranchUnit stage-4 v2 package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from dynamic_branch_unit_curve_v2 import (
    UnitCurveCompilationFailure,
    compile_dynamic_branch_units,
    diagnose_dynamic_branch_units,
)
from render_dynamic_branch_curve import (
    render_contact_sheet,
    render_original_png,
    render_original_svg,
    render_three_repeat_png,
    render_three_repeat_svg,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_CURVE_CONTRACT_V2.json"
STAGE2_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
)
STAGE3_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3_plans_v3"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_unit_curves_v2"
)
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
SEEDS = (4101, 4102, 4103)


class Stage4V2RunError(RuntimeError):
    """Launch/package error rather than a preserved candidate issue."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage4V2RunError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage4V2RunError(f"JSON root is not an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_file(root: Path, relative: object, label: str) -> Path:
    path = (root / Path(str(relative))).resolve()
    if root.resolve() not in path.parents:
        raise Stage4V2RunError(f"{label} path escapes {root}")
    if not path.is_file():
        raise Stage4V2RunError(f"{label} is missing: {path}")
    return path


def _load_launch_inputs() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    contract = _read_json(CONTRACT_PATH)
    if contract.get("schema") != "dynamic_branch_stage4_unit_curve_contract_v2":
        raise Stage4V2RunError("stage-4 v2 contract schema mismatch")
    stage3_manifest = _read_json(STAGE3_ROOT / "manifest.json")
    if stage3_manifest.get("schema") != "dynamic_branch_stage3_plan_manifest_v3":
        raise Stage4V2RunError("stage-3 manifest schema mismatch")
    gate = stage3_manifest.get("review_gate", {})
    if (
        gate.get("status") != "plan_approved_for_curve_compilation"
        or gate.get("stage_4_unlocked") is not True
        or gate.get("approved_plan_count") != 15
    ):
        raise Stage4V2RunError("stage-3 review gate is not approved for stage 4")
    tasks = stage3_manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 15:
        raise Stage4V2RunError("stage-3 manifest does not contain fifteen tasks")
    expected_ids = [
        f"{prototype_id}__seed_{seed}__raw_1"
        for prototype_id in PROTOTYPE_IDS
        for seed in SEEDS
    ]
    if [task.get("task_id") for task in tasks] != expected_ids:
        raise Stage4V2RunError("stage-3 task order/id mismatch")
    if any(task.get("state") != "plan_approved_for_curve_compilation" for task in tasks):
        raise Stage4V2RunError("one or more stage-3 plans are not approved")
    stage2_manifest = _read_json(STAGE2_ROOT / "manifest.json")
    if (
        stage2_manifest.get("schema")
        != "dynamic_branch_stage2_analysis_manifest_v1"
    ):
        raise Stage4V2RunError("stage-2 manifest schema mismatch")
    analysis_rows = {
        str(row["prototype_id"]): row for row in stage2_manifest["profiles"]
    }
    if tuple(analysis_rows) != PROTOTYPE_IDS:
        raise Stage4V2RunError("stage-2 prototype order mismatch")
    return contract, stage3_manifest, stage2_manifest, analysis_rows


def _load_case(
    task: Mapping[str, Any],
    analysis_row: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    plan_path = _safe_file(
        STAGE3_ROOT,
        task["dynamic_branch_plan_path"],
        f'{task["task_id"]} plan',
    )
    analysis_path = _safe_file(
        STAGE2_ROOT,
        analysis_row["prototype_analysis_path"],
        f'{task["prototype_id"]} analysis',
    )
    if _sha256(plan_path) != task["dynamic_branch_plan_sha256"]:
        raise Stage4V2RunError(f'{task["task_id"]} plan hash mismatch')
    if _sha256(analysis_path) != analysis_row["prototype_analysis_sha256"]:
        raise Stage4V2RunError(f'{task["prototype_id"]} analysis hash mismatch')
    plan = _read_json(plan_path)
    analysis = _read_json(analysis_path)
    if plan.get("plan_digest") != task["plan_digest"]:
        raise Stage4V2RunError(f'{task["task_id"]} plan digest mismatch')
    if (
        analysis.get("analysis_core_digest")
        != analysis_row["analysis_core_digest"]
    ):
        raise Stage4V2RunError(f'{task["prototype_id"]} analysis digest mismatch')
    return analysis, plan, analysis_path, plan_path


def _snapshot(
    *,
    task: Mapping[str, Any],
    analysis_path: Path,
    plan_path: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "dynamic_branch_stage4_v2_input_snapshot_v1",
        "task_id": task["task_id"],
        "prototype_id": task["prototype_id"],
        "family_id": task["family_id"],
        "seed": task["seed"],
        "raw_candidate_index": 1,
        "contract_id": contract["contract_id"],
        "contract_sha256": _sha256(CONTRACT_PATH),
        "inputs": {
            "stage3_plan_path": plan_path.relative_to(REPO_ROOT).as_posix(),
            "stage3_plan_sha256": _sha256(plan_path),
            "stage3_plan_digest": task["plan_digest"],
            "prototype_analysis_path": analysis_path.relative_to(REPO_ROOT).as_posix(),
            "prototype_analysis_sha256": _sha256(analysis_path),
        },
        "stage_scope": dict(contract["stage_boundary"]),
        "candidate_policy": dict(contract["candidate_policy"]),
    }


def _review(
    candidate: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "dynamic_branch_original_unit_curve_review_v2",
        "candidate_id": candidate["candidate_id"],
        "candidate_digest": candidate["candidate_digest"],
        "task_id": candidate["task_id"],
        "prototype_id": candidate["prototype_id"],
        "seed": candidate["seed"],
        "status": contract["review"]["initial_state"],
        "allowed_states": list(contract["review"]["allowed_states"]),
        "criteria": list(contract["review"]["criteria"]),
        "diagnostic_issue_count": diagnostics["issue_count"],
        "diagnostic_issue_labels": diagnostics["issue_labels"],
        "numeric_checks_cannot_auto_approve": True,
        "reviewer": None,
        "reviewed_at": None,
        "notes": [],
        "editor_unlocked": False,
    }


def _failure_review(
    task: Mapping[str, Any],
    failure: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "dynamic_branch_original_unit_curve_review_v2",
        "candidate_id": None,
        "candidate_digest": None,
        "task_id": task["task_id"],
        "prototype_id": task["prototype_id"],
        "seed": task["seed"],
        "status": "unit_curve_compilation_failed",
        "failure_code": failure["code"],
        "numeric_checks_cannot_auto_approve": True,
        "reviewer": None,
        "reviewed_at": None,
        "notes": ["Fatal v2 compilation failure preserved; no retry or repair was used."],
        "editor_unlocked": False,
    }


def run(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    if output.exists():
        raise Stage4V2RunError(
            f"stage-4 v2 output already exists and will not be overwritten: {output}"
        )
    contract, stage3_manifest, stage2_manifest, analysis_rows = _load_launch_inputs()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".dynamic_branch_stage4_v2_", dir=output.parent)
    )
    task_rows: list[dict[str, Any]] = []
    originals: list[Path] = []
    triples: list[Path] = []
    prototype_originals = {prototype_id: [] for prototype_id in PROTOTYPE_IDS}
    prototype_triples = {prototype_id: [] for prototype_id in PROTOTYPE_IDS}
    try:
        for task in stage3_manifest["tasks"]:
            prototype_id = str(task["prototype_id"])
            case_dir = temporary / prototype_id / f'seed_{task["seed"]}'
            case_dir.mkdir(parents=True, exist_ok=False)
            analysis, plan, analysis_path, plan_path = _load_case(
                task,
                analysis_rows[prototype_id],
            )
            snapshot_path = case_dir / "stage4_v2_input_snapshot.json"
            _write_json(
                snapshot_path,
                _snapshot(
                    task=task,
                    analysis_path=analysis_path,
                    plan_path=plan_path,
                    contract=contract,
                ),
            )
            try:
                candidate = compile_dynamic_branch_units(analysis, plan, contract)
            except UnitCurveCompilationFailure as exc:
                failure = exc.as_dict()
                failure.update(
                    {
                        "task_id": task["task_id"],
                        "prototype_id": prototype_id,
                        "family_id": task["family_id"],
                        "seed": task["seed"],
                    }
                )
                failure_path = case_dir / "unit_curve_compilation_failure.json"
                review_path = case_dir / "original_visual_review.json"
                _write_json(failure_path, failure)
                _write_json(review_path, _failure_review(task, failure))
                task_rows.append(
                    {
                        "task_id": task["task_id"],
                        "prototype_id": prototype_id,
                        "family_id": task["family_id"],
                        "seed": task["seed"],
                        "state": "unit_curve_compilation_failed",
                        "output_directory": case_dir.relative_to(temporary).as_posix(),
                        "failure_path": failure_path.relative_to(temporary).as_posix(),
                        "review_path": review_path.relative_to(temporary).as_posix(),
                        "retry_count": 0,
                    }
                )
                print(f"{task['task_id']}: compilation failed ({exc.code})", flush=True)
                continue
            diagnostics = diagnose_dynamic_branch_units(
                analysis,
                plan,
                candidate,
                contract,
            )
            candidate_path = case_dir / "dynamic_branch_unit_curve.json"
            diagnostics_path = case_dir / "unit_curve_diagnostics.json"
            original_svg = case_dir / "original_unit_curve.svg"
            original_png = case_dir / "original_unit_curve.png"
            triple_svg = case_dir / "three_repeat_unit_curve.svg"
            triple_png = case_dir / "three_repeat_unit_curve.png"
            review_path = case_dir / "original_visual_review.json"
            _write_json(candidate_path, candidate)
            _write_json(diagnostics_path, diagnostics)
            render_original_svg(analysis, candidate, diagnostics, original_svg)
            render_original_png(analysis, candidate, diagnostics, original_png)
            render_three_repeat_svg(analysis, candidate, diagnostics, triple_svg)
            render_three_repeat_png(analysis, candidate, diagnostics, triple_png)
            _write_json(review_path, _review(candidate, diagnostics, contract))
            originals.append(original_png)
            triples.append(triple_png)
            prototype_originals[prototype_id].append(original_png)
            prototype_triples[prototype_id].append(triple_png)
            artifacts = {
                "stage4_v2_input_snapshot": snapshot_path,
                "dynamic_branch_unit_curve": candidate_path,
                "unit_curve_diagnostics": diagnostics_path,
                "original_unit_curve_svg": original_svg,
                "original_unit_curve_png": original_png,
                "three_repeat_unit_curve_svg": triple_svg,
                "three_repeat_unit_curve_png": triple_png,
                "original_visual_review": review_path,
            }
            row: dict[str, Any] = {
                "task_id": task["task_id"],
                "prototype_id": prototype_id,
                "family_id": task["family_id"],
                "seed": task["seed"],
                "state": "original_pending_review",
                "output_directory": case_dir.relative_to(temporary).as_posix(),
                "candidate_id": candidate["candidate_id"],
                "candidate_digest": candidate["candidate_digest"],
                "unit_topology_digest": candidate["unit_topology_digest"],
                "branch_unit_count": diagnostics["branch_unit_count"],
                "curve_count": diagnostics["curve_count"],
                "level_counts": diagnostics["level_counts"],
                "cubic_segment_count": diagnostics["cubic_segment_count"],
                "near_straight_curve_count": diagnostics[
                    "near_straight_curve_count"
                ],
                "curve_curve_crossing_count": diagnostics[
                    "curve_curve_crossing_count"
                ],
                "non_root_backbone_crossing_count": diagnostics[
                    "non_root_backbone_crossing_count"
                ],
                "wrong_flower_entry_count": diagnostics[
                    "wrong_flower_entry_count"
                ],
                "diagnostic_issue_count": diagnostics["issue_count"],
                "retry_count": 0,
            }
            for label, path in artifacts.items():
                row[f"{label}_path"] = path.relative_to(temporary).as_posix()
                row[f"{label}_sha256"] = _sha256(path)
            task_rows.append(row)
            print(
                f"{task['task_id']}: "
                f"units={diagnostics['branch_unit_count']} "
                f"L1/L2/L3={diagnostics['level_counts']['L1']}/"
                f"{diagnostics['level_counts']['L2']}/"
                f"{diagnostics['level_counts']['L3']} "
                f"issues={diagnostics['issue_count']}",
                flush=True,
            )

        contact_sheets: list[dict[str, Any]] = []
        for prototype_id in PROTOTYPE_IDS:
            if not prototype_originals[prototype_id]:
                continue
            original_sheet = (
                temporary / prototype_id / "prototype_original_unit_contact_sheet.png"
            )
            triple_sheet = (
                temporary / prototype_id / "prototype_three_repeat_unit_contact_sheet.png"
            )
            render_contact_sheet(prototype_originals[prototype_id], original_sheet)
            render_contact_sheet(
                prototype_triples[prototype_id],
                triple_sheet,
                thumb_height=320,
            )
            for view, path in (
                ("original_unit_curve", original_sheet),
                ("three_repeat_unit_curve", triple_sheet),
            ):
                contact_sheets.append(
                    {
                        "scope": prototype_id,
                        "view": view,
                        "path": path.relative_to(temporary).as_posix(),
                        "sha256": _sha256(path),
                        "image_count": len(prototype_originals[prototype_id]),
                    }
                )
        if originals:
            global_original = temporary / "stage4_v2_original_unit_contact_sheet.png"
            global_triple = temporary / "stage4_v2_three_repeat_contact_sheet.png"
            render_contact_sheet(originals, global_original)
            render_contact_sheet(triples, global_triple, thumb_height=320)
            for view, path in (
                ("original_unit_curve", global_original),
                ("three_repeat_unit_curve", global_triple),
            ):
                contact_sheets.append(
                    {
                        "scope": "all_five_prototypes",
                        "view": view,
                        "path": path.relative_to(temporary).as_posix(),
                        "sha256": _sha256(path),
                        "image_count": len(originals),
                    }
                )

        success_count = sum(row["state"] == "original_pending_review" for row in task_rows)
        failure_count = len(task_rows) - success_count
        manifest = {
            "schema": contract["output"]["manifest_schema"],
            "candidate_schema": contract["output"]["schema"],
            "contract_id": contract["contract_id"],
            "revision": "v2_complete_dynamic_branch_units",
            "prototype_ids": list(PROTOTYPE_IDS),
            "seeds": list(SEEDS),
            "task_count": len(task_rows),
            "success_count": success_count,
            "failure_count": failure_count,
            "all_tasks_preserved": len(task_rows) == 15,
            "total_branch_unit_count": sum(
                int(row.get("branch_unit_count", 0)) for row in task_rows
            ),
            "total_curve_count": sum(int(row.get("curve_count", 0)) for row in task_rows),
            "total_level_counts": {
                level: sum(
                    int(row.get("level_counts", {}).get(level, 0))
                    for row in task_rows
                )
                for level in ("L1", "L2", "L3")
            },
            "near_straight_curve_count": sum(
                int(row.get("near_straight_curve_count", 0)) for row in task_rows
            ),
            "crossing_count": sum(
                int(row.get("curve_curve_crossing_count", 0))
                + int(row.get("non_root_backbone_crossing_count", 0))
                for row in task_rows
            ),
            "wrong_flower_entry_count": sum(
                int(row.get("wrong_flower_entry_count", 0)) for row in task_rows
            ),
            "diagnostic_issue_count": sum(
                int(row.get("diagnostic_issue_count", 0)) for row in task_rows
            ),
            "tasks": task_rows,
            "contact_sheets": contact_sheets,
            "review_gate": {
                "status": "original_unit_curve_review_pending",
                "pending_review_count": success_count,
                "compilation_failure_count": failure_count,
                "numeric_checks_cannot_auto_approve_visual_gate": True,
                "editor_unlocked": False,
            },
            "policy": {
                "single_forward_generation": True,
                "global_primary_set_selection": True,
                "global_complete_unit_set_selection": True,
                "validation_guided_retry_used": False,
                "validation_guided_resample_used": False,
                "automatic_repair_used": False,
                "automatic_deletion_used": False,
            },
            "project_scope": dict(contract["stage_boundary"]),
            "provenance": {
                "contract_sha256": _sha256(CONTRACT_PATH),
                "compiler_source_sha256": _sha256(
                    DYNAMIC_DIR / "dynamic_branch_unit_curve_v2.py"
                ),
                "renderer_source_sha256": _sha256(
                    DYNAMIC_DIR / "render_dynamic_branch_curve.py"
                ),
                "stage2_manifest_sha256": _sha256(STAGE2_ROOT / "manifest.json"),
                "stage3_manifest_sha256": _sha256(STAGE3_ROOT / "manifest.json"),
                "stage3_approval": dict(stage3_manifest["approval"]),
                "stage2_review_gate": dict(stage2_manifest["review_gate"]),
            },
            "stage_scope": {
                "completed": [
                    "dynamic_l2_l3_topology_materialization",
                    "global_primary_curve_set_selection",
                    "parent_local_l1_l2_l3_curve_compilation",
                    "global_complete_branchunit_set_selection",
                    "read_only_structure_and_shape_diagnostics",
                    "single_and_three_repeat_rendering",
                ],
                "not_started": [
                    "human_original_unit_curve_review",
                    "editor_integration",
                    "manual_curve_editing",
                ],
            },
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = run(args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
