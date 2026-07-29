#!/usr/bin/env python3
"""Compile the frozen 5x3 stage-4 matrix into raw Bezier candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from dynamic_branch_curve import (
    CurveCompilationFailure,
    compile_dynamic_branch_curve,
    diagnose_curve_candidate,
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
DEFAULT_PREFLIGHT_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_preflight_v1"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_curves_v1"
)
CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_CURVE_CONTRACT.json"
STAGE2_MANIFEST_PATH = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage2_analysis_v1"
    / "manifest.json"
)
STAGE3_MANIFEST_PATH = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage3_plans_v3"
    / "manifest.json"
)
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
SEEDS = (4101, 4102, 4103)


class Stage4CompilationError(RuntimeError):
    """Raised for launch/package errors rather than preserved task failures."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage4CompilationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage4CompilationError(f"JSON root is not an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_file(relative: object, label: str) -> Path:
    path = (REPO_ROOT / Path(str(relative))).resolve()
    if REPO_ROOT.resolve() not in path.parents:
        raise Stage4CompilationError(f"{label} path escapes repository root")
    if not path.is_file():
        raise Stage4CompilationError(f"{label} is missing: {path}")
    return path


def _preflight_file(root: Path, relative: object, label: str) -> Path:
    path = (root / Path(str(relative))).resolve()
    if root.resolve() not in path.parents:
        raise Stage4CompilationError(f"{label} path escapes preflight root")
    if not path.is_file():
        raise Stage4CompilationError(f"{label} is missing: {path}")
    return path


def _verify_preflight(
    preflight_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_path = preflight_root / "manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != "dynamic_branch_stage4_preflight_manifest_v1":
        raise Stage4CompilationError("stage-4 preflight manifest schema mismatch")
    readiness_path = _preflight_file(
        preflight_root,
        manifest["stage4_readiness_path"],
        "stage-4 readiness",
    )
    matrix_path = _preflight_file(
        preflight_root,
        manifest["stage4_task_matrix_path"],
        "stage-4 task matrix",
    )
    if _sha256(readiness_path) != manifest["stage4_readiness_sha256"]:
        raise Stage4CompilationError("stage-4 readiness hash mismatch")
    if _sha256(matrix_path) != manifest["stage4_task_matrix_sha256"]:
        raise Stage4CompilationError("stage-4 task matrix hash mismatch")
    readiness = _read_json(readiness_path)
    matrix = _read_json(matrix_path)
    if readiness.get("schema") != "dynamic_branch_stage4_readiness_v1":
        raise Stage4CompilationError("stage-4 readiness schema mismatch")
    if matrix.get("schema") != "dynamic_branch_stage4_task_matrix_v1":
        raise Stage4CompilationError("stage-4 task matrix schema mismatch")
    if readiness.get("ready") is not True or readiness.get("blockers") != []:
        raise Stage4CompilationError("stage-4 readiness contains blockers")
    if matrix.get("task_matrix_digest") != manifest.get("task_matrix_digest"):
        raise Stage4CompilationError("stage-4 task matrix digest mismatch")
    expected_provenance = {
        "stage4_curve_contract_sha256": _sha256(CONTRACT_PATH),
        "stage2_manifest_sha256": _sha256(STAGE2_MANIFEST_PATH),
        "stage3_manifest_sha256": _sha256(STAGE3_MANIFEST_PATH),
    }
    if manifest.get("provenance") != expected_provenance:
        raise Stage4CompilationError("stage-4 preflight provenance has drifted")
    if readiness.get("provenance") != expected_provenance:
        raise Stage4CompilationError("stage-4 readiness provenance has drifted")
    contract = _read_json(CONTRACT_PATH)
    if contract.get("schema") != "dynamic_branch_stage4_curve_contract_v1":
        raise Stage4CompilationError("stage-4 curve contract schema mismatch")
    tasks = matrix.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 15:
        raise Stage4CompilationError("stage-4 matrix is not exactly fifteen tasks")
    expected_ids = [
        f"{prototype_id}__seed_{seed}__raw_1"
        for prototype_id in PROTOTYPE_IDS
        for seed in SEEDS
    ]
    if [task.get("task_id") for task in tasks] != expected_ids:
        raise Stage4CompilationError("stage-4 task order/id mismatch")
    return manifest, readiness, matrix, contract


def _load_task_inputs(task: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    plan_path = _repo_file(task["stage3_plan_path"], f'{task["task_id"]} plan')
    analysis_path = _repo_file(
        task["prototype_analysis_path"],
        f'{task["task_id"]} analysis',
    )
    if _sha256(plan_path) != task["stage3_plan_sha256"]:
        raise Stage4CompilationError(f'{task["task_id"]} plan hash mismatch')
    if _sha256(analysis_path) != task["prototype_analysis_sha256"]:
        raise Stage4CompilationError(f'{task["task_id"]} analysis hash mismatch')
    plan = _read_json(plan_path)
    analysis = _read_json(analysis_path)
    if plan.get("plan_digest") != task["stage3_plan_digest"]:
        raise Stage4CompilationError(f'{task["task_id"]} plan digest mismatch')
    if analysis.get("analysis_digest") != task["prototype_analysis_digest"]:
        raise Stage4CompilationError(f'{task["task_id"]} analysis digest mismatch')
    return analysis, plan


def _input_snapshot(
    task: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "dynamic_branch_stage4_input_snapshot_v1",
        "task_id": task["task_id"],
        "prototype_id": task["prototype_id"],
        "family_id": task["family_id"],
        "seed": task["seed"],
        "raw_curve_candidate_index": 1,
        "curve_contract_id": contract["contract_id"],
        "curve_contract_sha256": _sha256(CONTRACT_PATH),
        "inputs": {
            "stage3_plan_path": task["stage3_plan_path"],
            "stage3_plan_sha256": task["stage3_plan_sha256"],
            "stage3_plan_digest": task["stage3_plan_digest"],
            "prototype_analysis_path": task["prototype_analysis_path"],
            "prototype_analysis_sha256": task["prototype_analysis_sha256"],
            "prototype_analysis_digest": task["prototype_analysis_digest"],
        },
        "candidate_policy": dict(contract["candidate_policy"]),
        "scope": dict(contract["stage_boundary"]),
    }


def _pending_review(
    candidate: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "dynamic_branch_original_curve_review_v1",
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
        "schema": "dynamic_branch_original_curve_review_v1",
        "candidate_id": None,
        "candidate_digest": None,
        "task_id": task["task_id"],
        "prototype_id": task["prototype_id"],
        "seed": task["seed"],
        "status": "curve_compilation_failed",
        "failure_code": failure["code"],
        "numeric_checks_cannot_auto_approve": True,
        "reviewer": None,
        "reviewed_at": None,
        "notes": ["Fatal compilation failure preserved; no retry or repair was attempted."],
        "editor_unlocked": False,
    }


def run(
    preflight_root: Path = DEFAULT_PREFLIGHT_ROOT,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    if output.exists():
        raise Stage4CompilationError(
            f"stage-4 output already exists and will not be overwritten: {output}"
        )
    preflight_manifest, _, matrix, contract = _verify_preflight(preflight_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".dynamic_branch_stage4_curves_", dir=output.parent)
    )
    task_rows: list[dict[str, Any]] = []
    original_pngs: list[Path] = []
    triple_pngs: list[Path] = []
    prototype_originals: dict[str, list[Path]] = {
        prototype_id: [] for prototype_id in PROTOTYPE_IDS
    }
    prototype_triples: dict[str, list[Path]] = {
        prototype_id: [] for prototype_id in PROTOTYPE_IDS
    }
    try:
        for task in matrix["tasks"]:
            prototype_id = str(task["prototype_id"])
            case_dir = temporary / str(task["expected_output_directory"])
            case_dir.mkdir(parents=True, exist_ok=False)
            snapshot_path = case_dir / "stage4_input_snapshot.json"
            _write_json(snapshot_path, _input_snapshot(task, contract))
            analysis, plan = _load_task_inputs(task)
            try:
                candidate = compile_dynamic_branch_curve(
                    analysis,
                    plan,
                    contract,
                )
            except CurveCompilationFailure as exc:
                failure = exc.as_dict()
                failure.update(
                    {
                        "task_id": task["task_id"],
                        "prototype_id": prototype_id,
                        "family_id": task["family_id"],
                        "seed": task["seed"],
                        "raw_curve_candidate_index": 1,
                    }
                )
                failure_path = case_dir / "curve_compilation_failure.json"
                review_path = case_dir / "original_visual_review.json"
                _write_json(failure_path, failure)
                _write_json(review_path, _failure_review(task, failure))
                task_rows.append(
                    {
                        "task_id": task["task_id"],
                        "prototype_id": prototype_id,
                        "family_id": task["family_id"],
                        "seed": task["seed"],
                        "state": "curve_compilation_failed",
                        "output_directory": task["expected_output_directory"],
                        "stage4_input_snapshot_path": snapshot_path.relative_to(
                            temporary
                        ).as_posix(),
                        "curve_compilation_failure_path": failure_path.relative_to(
                            temporary
                        ).as_posix(),
                        "original_visual_review_path": review_path.relative_to(
                            temporary
                        ).as_posix(),
                        "retry_count": 0,
                    }
                )
                continue
            diagnostics = diagnose_curve_candidate(
                analysis,
                plan,
                candidate,
                contract,
            )
            candidate_path = case_dir / "dynamic_branch_curve.json"
            diagnostics_path = case_dir / "curve_compile_diagnostics.json"
            original_svg_path = case_dir / "original_curve.svg"
            original_png_path = case_dir / "original_curve.png"
            triple_svg_path = case_dir / "three_repeat_curve.svg"
            triple_png_path = case_dir / "three_repeat_curve.png"
            review_path = case_dir / "original_visual_review.json"
            _write_json(candidate_path, candidate)
            _write_json(diagnostics_path, diagnostics)
            render_original_svg(
                analysis,
                candidate,
                diagnostics,
                original_svg_path,
            )
            render_original_png(
                analysis,
                candidate,
                diagnostics,
                original_png_path,
            )
            render_three_repeat_svg(
                analysis,
                candidate,
                diagnostics,
                triple_svg_path,
            )
            render_three_repeat_png(
                analysis,
                candidate,
                diagnostics,
                triple_png_path,
            )
            _write_json(
                review_path,
                _pending_review(candidate, diagnostics, contract),
            )
            original_pngs.append(original_png_path)
            triple_pngs.append(triple_png_path)
            prototype_originals[prototype_id].append(original_png_path)
            prototype_triples[prototype_id].append(triple_png_path)
            artifact_paths = {
                "stage4_input_snapshot": snapshot_path,
                "dynamic_branch_curve": candidate_path,
                "curve_compile_diagnostics": diagnostics_path,
                "original_curve_svg": original_svg_path,
                "original_curve_png": original_png_path,
                "three_repeat_curve_svg": triple_svg_path,
                "three_repeat_curve_png": triple_png_path,
                "original_visual_review": review_path,
            }
            row: dict[str, Any] = {
                "task_id": task["task_id"],
                "prototype_id": prototype_id,
                "family_id": task["family_id"],
                "seed": task["seed"],
                "state": "original_pending_review",
                "output_directory": task["expected_output_directory"],
                "candidate_id": candidate["candidate_id"],
                "candidate_digest": candidate["candidate_digest"],
                "branch_curve_count": diagnostics["curve_count"],
                "cubic_segment_count": diagnostics["cubic_segment_count"],
                "diagnostic_issue_count": diagnostics["issue_count"],
                "curve_curve_crossing_count": diagnostics[
                    "curve_curve_crossing_count"
                ],
                "non_root_backbone_crossing_count": diagnostics[
                    "non_root_backbone_crossing_count"
                ],
                "retry_count": 0,
            }
            for label, path in artifact_paths.items():
                row[f"{label}_path"] = path.relative_to(temporary).as_posix()
                row[f"{label}_sha256"] = _sha256(path)
            task_rows.append(row)

        contact_sheets: list[dict[str, Any]] = []
        for prototype_id in PROTOTYPE_IDS:
            if prototype_originals[prototype_id]:
                original_sheet = (
                    temporary
                    / prototype_id
                    / "prototype_original_curve_contact_sheet.png"
                )
                triple_sheet = (
                    temporary
                    / prototype_id
                    / "prototype_three_repeat_contact_sheet.png"
                )
                render_contact_sheet(
                    prototype_originals[prototype_id],
                    original_sheet,
                )
                render_contact_sheet(
                    prototype_triples[prototype_id],
                    triple_sheet,
                    thumb_height=320,
                )
                for view, path in (
                    ("original_curve", original_sheet),
                    ("three_repeat", triple_sheet),
                ):
                    contact_sheets.append(
                        {
                            "scope": prototype_id,
                            "view": view,
                            "path": path.relative_to(temporary).as_posix(),
                            "sha256": _sha256(path),
                            "image_count": 3,
                        }
                    )
        if original_pngs:
            global_original = temporary / "stage4_original_curve_contact_sheet.png"
            global_triple = temporary / "stage4_three_repeat_contact_sheet.png"
            render_contact_sheet(original_pngs, global_original)
            render_contact_sheet(
                triple_pngs,
                global_triple,
                thumb_height=320,
            )
            for view, path in (
                ("original_curve", global_original),
                ("three_repeat", global_triple),
            ):
                contact_sheets.append(
                    {
                        "scope": "all_five_prototypes",
                        "view": view,
                        "path": path.relative_to(temporary).as_posix(),
                        "sha256": _sha256(path),
                        "image_count": 15,
                    }
                )

        success_count = sum(
            row["state"] == "original_pending_review" for row in task_rows
        )
        failure_count = sum(
            row["state"] == "curve_compilation_failed" for row in task_rows
        )
        issue_count = sum(
            int(row.get("diagnostic_issue_count", 0)) for row in task_rows
        )
        crossing_count = sum(
            int(row.get("curve_curve_crossing_count", 0))
            + int(row.get("non_root_backbone_crossing_count", 0))
            for row in task_rows
        )
        manifest = {
            "schema": contract["output"]["manifest_schema"],
            "candidate_schema": contract["output"]["schema"],
            "curve_contract_id": contract["contract_id"],
            "prototype_ids": list(PROTOTYPE_IDS),
            "seeds": list(SEEDS),
            "task_count": len(task_rows),
            "success_count": success_count,
            "failure_count": failure_count,
            "diagnostic_issue_count": issue_count,
            "crossing_count": crossing_count,
            "all_tasks_preserved": len(task_rows) == 15,
            "raw_curve_candidate_count_per_successful_task": 1,
            "tasks": task_rows,
            "contact_sheets": contact_sheets,
            "review_gate": {
                "status": "original_curve_review_pending",
                "pending_review_count": success_count,
                "compilation_failure_count": failure_count,
                "numeric_checks_cannot_auto_approve_visual_gate": True,
                "all_fifteen_candidates_require_terminal_review_state": True,
                "editor_unlocked": False,
            },
            "policy": {
                "single_forward_compilation": True,
                "validation_guided_retry_used": False,
                "validation_guided_resample_used": False,
                "automatic_repair_used": False,
                "automatic_deletion_used": False,
            },
            "project_scope": dict(contract["stage_boundary"]),
            "provenance": {
                "preflight_manifest_sha256": _sha256(
                    preflight_root / "manifest.json"
                ),
                "preflight_task_matrix_digest": matrix["task_matrix_digest"],
                "curve_contract_sha256": _sha256(CONTRACT_PATH),
                "compiler_source_sha256": _sha256(
                    DYNAMIC_DIR / "dynamic_branch_curve.py"
                ),
                "renderer_source_sha256": _sha256(
                    DYNAMIC_DIR / "render_dynamic_branch_curve.py"
                ),
                **preflight_manifest["provenance"],
            },
            "stage_scope": {
                "completed": [
                    "approved_stage3_plan_ingestion",
                    "single_forward_cubic_bezier_compilation",
                    "stage3_mount_direction_waypoint_and_tip_preservation",
                    "read_only_compile_diagnostics",
                    "single_and_three_repeat_rendering",
                ],
                "not_started": [
                    "human_original_curve_review",
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
    parser.add_argument(
        "--preflight-root",
        type=Path,
        default=DEFAULT_PREFLIGHT_ROOT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = run(args.preflight_root, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
