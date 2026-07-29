#!/usr/bin/env python3
"""Verify stage-3 gates and materialize the immutable 15-task launch matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
DEFAULT_STAGE1_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
)
DEFAULT_STAGE2_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
)
DEFAULT_STAGE25_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3_preflight_v3"
)
IMPLEMENTATION_CONTRACT_PATH = DYNAMIC_DIR / "IMPLEMENTATION_CONTRACT.json"
STAGE3_CONTRACT_PATH = DYNAMIC_DIR / "STAGE3_PLAN_CONTRACT.json"
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
SEEDS = (4101, 4102, 4103)


class Stage3PreflightError(RuntimeError):
    """Raised when stage 3 is not safe to start."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage3PreflightError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage3PreflightError(f"JSON root is not an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rows_by_id(rows: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != len(PROTOTYPE_IDS):
        raise Stage3PreflightError(f"{label} profile inventory is incomplete")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise Stage3PreflightError(f"{label} profile row is invalid")
        prototype_id = str(row.get("prototype_id", ""))
        if prototype_id in by_id or prototype_id not in PROTOTYPE_IDS:
            raise Stage3PreflightError(f"{label} prototype id is invalid: {prototype_id}")
        by_id[prototype_id] = row
    if tuple(by_id) != PROTOTYPE_IDS:
        raise Stage3PreflightError(f"{label} profile order is not canonical")
    return by_id


def _artifact_file(root: Path, relative: object, label: str) -> Path:
    path = (root / Path(str(relative))).resolve()
    resolved_root = root.resolve()
    if resolved_root not in path.parents:
        raise Stage3PreflightError(f"{label} path escapes artifact root: {relative}")
    if not path.is_file():
        raise Stage3PreflightError(f"{label} is missing: {path}")
    return path


def _verify_hash(path: Path, expected: object, label: str) -> None:
    if _sha256(path) != expected:
        raise Stage3PreflightError(f"{label} hash mismatch")


def _verify_contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    implementation = _read_json(IMPLEMENTATION_CONTRACT_PATH)
    plan_contract = _read_json(STAGE3_CONTRACT_PATH)
    if implementation.get("schema") != "dynamic_branch_implementation_contract_v1":
        raise Stage3PreflightError("implementation contract schema mismatch")
    if plan_contract.get("schema") != "dynamic_branch_stage3_plan_contract_v1":
        raise Stage3PreflightError("stage 3 plan contract schema mismatch")
    if tuple(implementation["visual_acceptance"]["prototype_ids"]) != PROTOTYPE_IDS:
        raise Stage3PreflightError("implementation prototype order mismatch")
    if tuple(implementation["visual_acceptance"]["seeds"]) != SEEDS:
        raise Stage3PreflightError("implementation seed order mismatch")
    task_matrix = plan_contract.get("task_matrix", {})
    if tuple(task_matrix.get("prototype_ids", [])) != PROTOTYPE_IDS:
        raise Stage3PreflightError("stage 3 contract prototype order mismatch")
    if tuple(task_matrix.get("seeds", [])) != SEEDS:
        raise Stage3PreflightError("stage 3 contract seed order mismatch")
    expected_task_count = len(PROTOTYPE_IDS) * len(SEEDS)
    if task_matrix.get("expected_task_count") != expected_task_count:
        raise Stage3PreflightError("stage 3 expected task count mismatch")
    candidate_policy = implementation["candidate_policy"]
    stage3_policy = plan_contract["candidate_and_failure_policy"]
    if candidate_policy["raw_candidate_count_per_prototype_seed"] != 1:
        raise Stage3PreflightError("implementation raw candidate count must be one")
    if task_matrix["raw_candidate_count_per_prototype_seed"] != 1:
        raise Stage3PreflightError("stage 3 raw candidate count must be one")
    for key in (
        "validation_guided_retry_allowed",
        "validation_guided_resample_allowed",
        "automatic_repair_allowed",
        "automatic_deletion_allowed",
    ):
        if candidate_policy[key] is not False or stage3_policy[key] is not False:
            raise Stage3PreflightError(f"stage 3 policy must keep {key}=false")
    if plan_contract["output"]["curve_geometry_present"] is not False:
        raise Stage3PreflightError("stage 3 output must not contain curve geometry")
    if plan_contract["structural_primitive"][
        "independent_curve_as_primary_primitive_allowed"
    ] is not False:
        raise Stage3PreflightError("independent curves cannot be the stage 3 primitive")
    return implementation, plan_contract


def _verify_gate(
    manifest: Mapping[str, Any],
    *,
    expected_status: str,
    label: str,
) -> None:
    gate = manifest.get("review_gate")
    if not isinstance(gate, Mapping):
        raise Stage3PreflightError(f"{label} review gate is missing")
    if gate.get("status") != expected_status:
        raise Stage3PreflightError(
            f"{label} review gate is {gate.get('status')}, expected {expected_status}"
        )
    if gate.get("stage_3_unlocked") is not True:
        raise Stage3PreflightError(f"{label} has not unlocked stage 3")
    if not str(gate.get("reviewer", "")).strip():
        raise Stage3PreflightError(f"{label} reviewer provenance is missing")
    if not str(gate.get("reviewed_at", "")).strip():
        raise Stage3PreflightError(f"{label} review timestamp is missing")


def build_readiness(
    stage1_root: Path = DEFAULT_STAGE1_ROOT,
    stage2_root: Path = DEFAULT_STAGE2_ROOT,
    stage25_root: Path = DEFAULT_STAGE25_ROOT,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate all inputs and return readiness, task matrix, and provenance."""

    implementation, plan_contract = _verify_contracts()
    stage1_manifest_path = stage1_root / "manifest.json"
    stage2_manifest_path = stage2_root / "manifest.json"
    stage25_manifest_path = stage25_root / "manifest.json"
    stage1_manifest = _read_json(stage1_manifest_path)
    stage2_manifest = _read_json(stage2_manifest_path)
    stage25_manifest = _read_json(stage25_manifest_path)
    if stage1_manifest.get("schema") != "dynamic_branch_stage1_input_manifest_v1":
        raise Stage3PreflightError("stage 1 manifest schema mismatch")
    if stage2_manifest.get("schema") != "dynamic_branch_stage2_analysis_manifest_v1":
        raise Stage3PreflightError("stage 2 manifest schema mismatch")
    if stage25_manifest.get("schema") != "dynamic_branch_stage25_morphology_manifest_v1":
        raise Stage3PreflightError("stage 2.5 manifest schema mismatch")
    for label, manifest in (
        ("stage 1", stage1_manifest),
        ("stage 2", stage2_manifest),
        ("stage 2.5", stage25_manifest),
    ):
        if tuple(manifest.get("prototype_ids", [])) != PROTOTYPE_IDS:
            raise Stage3PreflightError(f"{label} prototype order mismatch")
    _verify_gate(
        stage2_manifest,
        expected_status="analysis_approved",
        label="stage 2",
    )
    _verify_gate(
        stage25_manifest,
        expected_status="morphology_approved",
        label="stage 2.5",
    )
    if stage25_manifest.get("stage2_manifest_sha256") != _sha256(stage2_manifest_path):
        raise Stage3PreflightError("stage 2.5 does not reference the approved stage 2 manifest")

    stage1_rows = _rows_by_id(stage1_manifest.get("profiles"), "stage 1")
    stage2_rows = _rows_by_id(stage2_manifest.get("profiles"), "stage 2")
    stage25_rows = _rows_by_id(stage25_manifest.get("profiles"), "stage 2.5")
    input_rows: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    for prototype_id in PROTOTYPE_IDS:
        stage1_row = stage1_rows[prototype_id]
        strict_path = _artifact_file(
            stage1_root,
            stage1_row.get("strict_p0_path"),
            f"{prototype_id} StrictP0",
        )
        _verify_hash(
            strict_path,
            stage1_row.get("strict_p0_sha256"),
            f"{prototype_id} StrictP0",
        )
        strict = _read_json(strict_path)
        strict_digest = str(stage1_row.get("strict_p0_digest", ""))
        if strict.get("prototype_id") != prototype_id:
            raise Stage3PreflightError(f"{prototype_id} StrictP0 content/id mismatch")

        stage2_row = stage2_rows[prototype_id]
        analysis_path = _artifact_file(
            stage2_root,
            stage2_row.get("prototype_analysis_path"),
            f"{prototype_id} analysis",
        )
        _verify_hash(
            analysis_path,
            stage2_row.get("prototype_analysis_sha256"),
            f"{prototype_id} analysis",
        )
        analysis = _read_json(analysis_path)
        analysis_digest = str(analysis.get("analysis_digest", ""))
        if analysis.get("strict_p0_digest") != strict_digest:
            raise Stage3PreflightError(f"{prototype_id} StrictP0/analysis digest mismatch")
        analysis_review_path = _artifact_file(
            stage2_root,
            stage2_row.get("analysis_review_path"),
            f"{prototype_id} analysis review",
        )
        _verify_hash(
            analysis_review_path,
            stage2_row.get("analysis_review_sha256"),
            f"{prototype_id} analysis review",
        )
        analysis_review = _read_json(analysis_review_path)
        if analysis_review.get("status") != "analysis_approved":
            raise Stage3PreflightError(f"{prototype_id} analysis is not approved")
        if analysis_review.get("analysis_digest") != analysis_digest:
            raise Stage3PreflightError(f"{prototype_id} analysis review digest mismatch")
        if analysis_review.get("stage_3_unlocked") is not True:
            raise Stage3PreflightError(f"{prototype_id} analysis has not unlocked stage 3")

        stage25_row = stage25_rows[prototype_id]
        profile_path = _artifact_file(
            stage25_root,
            stage25_row.get("morphology_profile_path"),
            f"{prototype_id} morphology profile",
        )
        _verify_hash(
            profile_path,
            stage25_row.get("morphology_profile_sha256"),
            f"{prototype_id} morphology profile",
        )
        profile = _read_json(profile_path)
        morphology_digest = str(profile.get("morphology_digest", ""))
        if profile.get("source_stage2_analysis_digest") != analysis_digest:
            raise Stage3PreflightError(f"{prototype_id} analysis/morphology digest mismatch")
        morphology_review_path = _artifact_file(
            stage25_root,
            stage25_row.get("morphology_review_path"),
            f"{prototype_id} morphology review",
        )
        _verify_hash(
            morphology_review_path,
            stage25_row.get("morphology_review_sha256"),
            f"{prototype_id} morphology review",
        )
        morphology_review = _read_json(morphology_review_path)
        if morphology_review.get("status") != "morphology_approved":
            raise Stage3PreflightError(f"{prototype_id} morphology is not approved")
        if morphology_review.get("morphology_digest") != morphology_digest:
            raise Stage3PreflightError(f"{prototype_id} morphology review digest mismatch")
        if morphology_review.get("stage_3_unlocked") is not True:
            raise Stage3PreflightError(f"{prototype_id} morphology has not unlocked stage 3")

        relation = profile["classification"]["flower_branch_relation"]
        family_id = str(relation["family_id"])
        input_row = {
            "prototype_id": prototype_id,
            "family_id": family_id,
            "strict_p0_path": strict_path.relative_to(REPO_ROOT).as_posix(),
            "strict_p0_digest": strict_digest,
            "prototype_analysis_path": analysis_path.relative_to(REPO_ROOT).as_posix(),
            "prototype_analysis_digest": analysis_digest,
            "morphology_profile_path": profile_path.relative_to(REPO_ROOT).as_posix(),
            "morphology_digest": morphology_digest,
            "analysis_review_state": analysis_review["status"],
            "morphology_review_state": morphology_review["status"],
        }
        input_rows.append(input_row)
        for seed in SEEDS:
            tasks.append(
                {
                    "task_id": f"{prototype_id}__seed_{seed}__raw_1",
                    "prototype_id": prototype_id,
                    "family_id": family_id,
                    "seed": seed,
                    "raw_candidate_index": 1,
                    "state": "ready_not_generated",
                    "input_refs": {
                        "strict_p0_digest": strict_digest,
                        "prototype_analysis_digest": analysis_digest,
                        "morphology_digest": morphology_digest,
                    },
                    "expected_output_directory": f"{prototype_id}/seed_{seed}",
                    "expected_output_artifacts": list(
                        plan_contract["output"]["required_artifacts_per_task"]
                    ),
                    "curve_geometry_allowed": False,
                    "validation_guided_retry_allowed": False,
                }
            )

    if len(tasks) != 15 or len({task["task_id"] for task in tasks}) != 15:
        raise Stage3PreflightError("stage 3 task matrix is not exactly 15 unique tasks")
    task_matrix: dict[str, Any] = {
        "schema": "dynamic_branch_stage3_task_matrix_v3",
        "contract_id": plan_contract["contract_id"],
        "prototype_ids": list(PROTOTYPE_IDS),
        "seeds": list(SEEDS),
        "task_count": len(tasks),
        "raw_candidate_count_per_prototype_seed": 1,
        "tasks": tasks,
        "stage_boundary": {
            "plan_generation_started": False,
            "curve_compilation_started": False,
            "leaves_buds_or_curl_heads_started": False,
        },
    }
    task_matrix["task_matrix_digest"] = _canonical_digest(task_matrix)
    provenance = {
        "implementation_contract_sha256": _sha256(IMPLEMENTATION_CONTRACT_PATH),
        "stage3_plan_contract_sha256": _sha256(STAGE3_CONTRACT_PATH),
        "stage1_manifest_sha256": _sha256(stage1_manifest_path),
        "stage2_manifest_sha256": _sha256(stage2_manifest_path),
        "stage25_manifest_sha256": _sha256(stage25_manifest_path),
    }
    readiness: dict[str, Any] = {
        "schema": "dynamic_branch_stage3_readiness_v3",
        "ready": True,
        "blockers": [],
        "prototype_count": len(PROTOTYPE_IDS),
        "seed_count": len(SEEDS),
        "task_count": len(tasks),
        "raw_candidate_count_per_task": 1,
        "analysis_review_gate": "analysis_approved",
        "morphology_review_gate": "morphology_approved",
        "input_profiles": input_rows,
        "candidate_policy": copy_subset(
            implementation["candidate_policy"],
            (
                "raw_candidate_count_per_prototype_seed",
                "validation_guided_retry_allowed",
                "validation_guided_resample_allowed",
                "automatic_repair_allowed",
                "automatic_deletion_allowed",
                "planning_failures_must_be_preserved",
            ),
        ),
        "stage_boundary": {
            "stage_3_ready": True,
            "stage_3_plan_generation_started": False,
            "stage_4_curve_compilation_started": False,
        },
        "provenance": provenance,
    }
    readiness["readiness_digest"] = _canonical_digest(readiness)
    return readiness, task_matrix, provenance


def copy_subset(mapping: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: mapping[key] for key in keys}


def run(
    stage1_root: Path = DEFAULT_STAGE1_ROOT,
    stage2_root: Path = DEFAULT_STAGE2_ROOT,
    stage25_root: Path = DEFAULT_STAGE25_ROOT,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Write a read-only launch package without generating any branch plan."""

    if output.exists():
        raise Stage3PreflightError(
            f"stage 3 preflight output already exists and will not be overwritten: {output}"
        )
    readiness, task_matrix, provenance = build_readiness(
        stage1_root,
        stage2_root,
        stage25_root,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".dynamic_branch_stage3_preflight_", dir=output.parent)
    )
    try:
        readiness_path = temporary / "stage3_readiness.json"
        task_matrix_path = temporary / "stage3_task_matrix.json"
        _write_json(readiness_path, readiness)
        _write_json(task_matrix_path, task_matrix)
        manifest = {
            "schema": "dynamic_branch_stage3_preflight_manifest_v3",
            "ready": True,
            "stage3_readiness_path": readiness_path.name,
            "stage3_readiness_sha256": _sha256(readiness_path),
            "stage3_task_matrix_path": task_matrix_path.name,
            "stage3_task_matrix_sha256": _sha256(task_matrix_path),
            "task_matrix_digest": task_matrix["task_matrix_digest"],
            "task_count": task_matrix["task_count"],
            "provenance": provenance,
            "stage_scope": {
                "completed": [
                    "review_gate_verification",
                    "digest_chain_verification",
                    "stage3_contract_verification",
                    "fifteen_task_launch_matrix",
                ],
                "not_started": [
                    "candidate_slot_selection",
                    "branch_unit_plan_generation",
                    "dynamic_branch_plan_rendering",
                    "curve_compilation",
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
    parser.add_argument("--stage1-root", type=Path, default=DEFAULT_STAGE1_ROOT)
    parser.add_argument("--stage2-root", type=Path, default=DEFAULT_STAGE2_ROOT)
    parser.add_argument("--stage25-root", type=Path, default=DEFAULT_STAGE25_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = run(
        args.stage1_root,
        args.stage2_root,
        args.stage25_root,
        args.output,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage3PreflightError as exc:
        raise SystemExit(f"stage 3 preflight error: {exc}") from exc
