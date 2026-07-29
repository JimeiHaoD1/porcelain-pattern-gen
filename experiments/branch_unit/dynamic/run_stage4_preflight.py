#!/usr/bin/env python3
"""Verify approved stage-3 plans and freeze the stage-4 compilation matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
DEFAULT_STAGE2_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
)
DEFAULT_STAGE3_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3_plans_v3"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_preflight_v1"
)
CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_CURVE_CONTRACT.json"
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
SEEDS = (4101, 4102, 4103)


class Stage4PreflightError(RuntimeError):
    """Raised when approved stage-3 artifacts are unsafe to compile."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage4PreflightError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage4PreflightError(f"JSON root is not an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _child_file(root: Path, relative: object, label: str) -> Path:
    path = (root / Path(str(relative))).resolve()
    resolved_root = root.resolve()
    if resolved_root not in path.parents:
        raise Stage4PreflightError(f"{label} path escapes artifact root")
    if not path.is_file():
        raise Stage4PreflightError(f"{label} is missing: {path}")
    return path


def build_readiness(
    stage2_root: Path = DEFAULT_STAGE2_ROOT,
    stage3_root: Path = DEFAULT_STAGE3_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = _read_json(CONTRACT_PATH)
    if contract.get("schema") != "dynamic_branch_stage4_curve_contract_v1":
        raise Stage4PreflightError("stage-4 curve contract schema mismatch")
    stage2_manifest_path = stage2_root / "manifest.json"
    stage3_manifest_path = stage3_root / "manifest.json"
    stage2_manifest = _read_json(stage2_manifest_path)
    stage3_manifest = _read_json(stage3_manifest_path)
    if stage2_manifest.get("schema") != "dynamic_branch_stage2_analysis_manifest_v1":
        raise Stage4PreflightError("stage-2 manifest schema mismatch")
    if stage3_manifest.get("schema") != "dynamic_branch_stage3_plan_manifest_v3":
        raise Stage4PreflightError("stage-3 manifest schema mismatch")
    if stage3_manifest.get("review_gate", {}).get("stage_4_unlocked") is not True:
        raise Stage4PreflightError("stage-3 review gate has not unlocked stage 4")
    if (
        stage3_manifest.get("review_gate", {}).get("status")
        != "plan_approved_for_curve_compilation"
    ):
        raise Stage4PreflightError("stage-3 plans are not approved for compilation")
    stage2_rows = {
        row["prototype_id"]: row for row in stage2_manifest["profiles"]
    }
    tasks = stage3_manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 15:
        raise Stage4PreflightError("stage-3 inventory is not exactly fifteen tasks")
    matrix_tasks: list[dict[str, Any]] = []
    for row in tasks:
        if row.get("state") != "plan_approved_for_curve_compilation":
            raise Stage4PreflightError(
                f'{row.get("task_id")} is not approved for curve compilation'
            )
        prototype_id = str(row["prototype_id"])
        seed = int(row["seed"])
        if prototype_id not in PROTOTYPE_IDS or seed not in SEEDS:
            raise Stage4PreflightError("stage-3 task identity is outside the matrix")
        plan_path = _child_file(
            stage3_root,
            row["dynamic_branch_plan_path"],
            f'{row["task_id"]} plan',
        )
        if _sha256(plan_path) != row["dynamic_branch_plan_sha256"]:
            raise Stage4PreflightError(f'{row["task_id"]} plan hash mismatch')
        plan = _read_json(plan_path)
        if plan.get("schema") != contract["required_input"]["plan_schema"]:
            raise Stage4PreflightError(f'{row["task_id"]} plan schema mismatch')
        if plan.get("plan_digest") != row["plan_digest"]:
            raise Stage4PreflightError(f'{row["task_id"]} plan digest mismatch')
        review_path = _child_file(
            stage3_root,
            row["plan_review_path"],
            f'{row["task_id"]} review',
        )
        if _sha256(review_path) != row["plan_review_sha256"]:
            raise Stage4PreflightError(f'{row["task_id"]} review hash mismatch')
        review = _read_json(review_path)
        if (
            review.get("status")
            != contract["required_input"]["required_plan_review_state"]
            or review.get("stage_4_unlocked") is not True
        ):
            raise Stage4PreflightError(f'{row["task_id"]} review has not unlocked stage 4')
        analysis_row = stage2_rows[prototype_id]
        analysis_path = _child_file(
            stage2_root,
            analysis_row["prototype_analysis_path"],
            f"{prototype_id} analysis",
        )
        if _sha256(analysis_path) != analysis_row["prototype_analysis_sha256"]:
            raise Stage4PreflightError(f"{prototype_id} analysis hash mismatch")
        analysis = _read_json(analysis_path)
        if (
            analysis.get("analysis_digest")
            != plan["input_refs"]["prototype_analysis_digest"]
        ):
            raise Stage4PreflightError(
                f"{prototype_id} analysis/plan digest mismatch"
            )
        matrix_tasks.append(
            {
                "task_id": row["task_id"],
                "prototype_id": prototype_id,
                "family_id": row["family_id"],
                "seed": seed,
                "raw_curve_candidate_index": 1,
                "state": "approved_ready_to_compile",
                "stage3_plan_path": plan_path.relative_to(REPO_ROOT).as_posix(),
                "stage3_plan_sha256": _sha256(plan_path),
                "stage3_plan_digest": plan["plan_digest"],
                "prototype_analysis_path": analysis_path.relative_to(
                    REPO_ROOT
                ).as_posix(),
                "prototype_analysis_sha256": _sha256(analysis_path),
                "prototype_analysis_digest": analysis["analysis_digest"],
                "expected_output_directory": f"{prototype_id}/seed_{seed}",
                "expected_output_artifacts": list(
                    contract["output"]["required_artifacts_per_task"]
                ),
                "validation_guided_retry_allowed": False,
                "automatic_repair_allowed": False,
            }
        )
    expected_ids = [
        f"{prototype_id}__seed_{seed}__raw_1"
        for prototype_id in PROTOTYPE_IDS
        for seed in SEEDS
    ]
    if [task["task_id"] for task in matrix_tasks] != expected_ids:
        raise Stage4PreflightError("stage-4 task order/id matrix is not canonical")
    task_matrix: dict[str, Any] = {
        "schema": "dynamic_branch_stage4_task_matrix_v1",
        "curve_contract_id": contract["contract_id"],
        "prototype_ids": list(PROTOTYPE_IDS),
        "seeds": list(SEEDS),
        "task_count": len(matrix_tasks),
        "raw_curve_candidate_count_per_task": 1,
        "tasks": matrix_tasks,
        "stage_boundary": {
            "curve_compilation_started": False,
            "topology_changes_started": False,
            "leaves_buds_or_curl_heads_started": False,
        },
    }
    task_matrix["task_matrix_digest"] = _canonical_digest(task_matrix)
    readiness: dict[str, Any] = {
        "schema": "dynamic_branch_stage4_readiness_v1",
        "ready": True,
        "blockers": [],
        "prototype_count": len(PROTOTYPE_IDS),
        "seed_count": len(SEEDS),
        "task_count": len(matrix_tasks),
        "stage3_review_state": "plan_approved_for_curve_compilation",
        "stage3_approved_plan_count": 15,
        "candidate_policy": dict(contract["candidate_policy"]),
        "provenance": {
            "stage4_curve_contract_sha256": _sha256(CONTRACT_PATH),
            "stage2_manifest_sha256": _sha256(stage2_manifest_path),
            "stage3_manifest_sha256": _sha256(stage3_manifest_path),
        },
    }
    readiness["readiness_digest"] = _canonical_digest(readiness)
    return readiness, task_matrix


def run(
    stage2_root: Path = DEFAULT_STAGE2_ROOT,
    stage3_root: Path = DEFAULT_STAGE3_ROOT,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    if output.exists():
        raise Stage4PreflightError(
            f"stage-4 preflight output already exists and will not be overwritten: {output}"
        )
    readiness, task_matrix = build_readiness(stage2_root, stage3_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".dynamic_branch_stage4_preflight_", dir=output.parent)
    )
    try:
        readiness_path = temporary / "stage4_readiness.json"
        matrix_path = temporary / "stage4_task_matrix.json"
        _write_json(readiness_path, readiness)
        _write_json(matrix_path, task_matrix)
        manifest = {
            "schema": "dynamic_branch_stage4_preflight_manifest_v1",
            "ready": True,
            "stage4_readiness_path": readiness_path.name,
            "stage4_readiness_sha256": _sha256(readiness_path),
            "stage4_task_matrix_path": matrix_path.name,
            "stage4_task_matrix_sha256": _sha256(matrix_path),
            "task_matrix_digest": task_matrix["task_matrix_digest"],
            "task_count": task_matrix["task_count"],
            "provenance": readiness["provenance"],
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2-root", type=Path, default=DEFAULT_STAGE2_ROOT)
    parser.add_argument("--stage3-root", type=Path, default=DEFAULT_STAGE3_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = run(args.stage2_root, args.stage3_root, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
