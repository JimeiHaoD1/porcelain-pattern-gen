#!/usr/bin/env python3
"""Generate and render the immutable fifteen-task stage-3 branch-only plan set."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from dynamic_branch_plan import PlanningFailure, generate_dynamic_branch_plan
from render_dynamic_branch_plan import render_contact_sheet, render_png, render_svg


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
DEFAULT_PREFLIGHT_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3_preflight_v3"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3_plans_v3"
)
IMPLEMENTATION_CONTRACT_PATH = DYNAMIC_DIR / "IMPLEMENTATION_CONTRACT.json"
STAGE3_CONTRACT_PATH = DYNAMIC_DIR / "STAGE3_PLAN_CONTRACT.json"
STAGE1_MANIFEST_PATH = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1" / "manifest.json"
)
STAGE2_MANIFEST_PATH = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1" / "manifest.json"
)
STAGE25_MANIFEST_PATH = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage25_morphology_v1"
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


class Stage3PlanningError(RuntimeError):
    """Raised when the frozen launch matrix cannot be executed faithfully."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage3PlanningError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage3PlanningError(f"JSON root is not an object: {path}")
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


def _verify_embedded_digest(value: Mapping[str, Any], key: str, label: str) -> None:
    expected = value.get(key)
    if not isinstance(expected, str) or not expected:
        raise Stage3PlanningError(f"{label} does not contain {key}")
    digest_source = dict(value)
    digest_source.pop(key, None)
    if _canonical_digest(digest_source) != expected:
        raise Stage3PlanningError(f"{label} embedded digest mismatch")


def _repo_file(relative: object, label: str) -> Path:
    path = (REPO_ROOT / Path(str(relative))).resolve()
    root = REPO_ROOT.resolve()
    if root != path and root not in path.parents:
        raise Stage3PlanningError(f"{label} path escapes repository root: {relative}")
    if not path.is_file():
        raise Stage3PlanningError(f"{label} is missing: {path}")
    return path


def _verify_preflight(
    preflight_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_path = preflight_root / "manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != "dynamic_branch_stage3_preflight_manifest_v3":
        raise Stage3PlanningError("stage 3 preflight manifest schema mismatch")
    if manifest.get("ready") is not True or manifest.get("task_count") != 15:
        raise Stage3PlanningError("stage 3 preflight is not ready for all fifteen tasks")

    readiness_path = preflight_root / str(manifest.get("stage3_readiness_path", ""))
    task_matrix_path = preflight_root / str(manifest.get("stage3_task_matrix_path", ""))
    for path, expected, label in (
        (
            readiness_path,
            manifest.get("stage3_readiness_sha256"),
            "stage 3 readiness",
        ),
        (
            task_matrix_path,
            manifest.get("stage3_task_matrix_sha256"),
            "stage 3 task matrix",
        ),
    ):
        if not path.is_file() or _sha256(path) != expected:
            raise Stage3PlanningError(f"{label} file/hash mismatch")

    readiness = _read_json(readiness_path)
    task_matrix = _read_json(task_matrix_path)
    if readiness.get("schema") != "dynamic_branch_stage3_readiness_v3":
        raise Stage3PlanningError("stage 3 readiness schema mismatch")
    if readiness.get("ready") is not True or readiness.get("blockers") != []:
        raise Stage3PlanningError("stage 3 readiness contains blockers")
    if task_matrix.get("schema") != "dynamic_branch_stage3_task_matrix_v3":
        raise Stage3PlanningError("stage 3 task matrix schema mismatch")
    _verify_embedded_digest(readiness, "readiness_digest", "stage 3 readiness")
    _verify_embedded_digest(task_matrix, "task_matrix_digest", "stage 3 task matrix")
    if task_matrix["task_matrix_digest"] != manifest.get("task_matrix_digest"):
        raise Stage3PlanningError("preflight/task matrix digest mismatch")

    expected_provenance = {
        "implementation_contract_sha256": _sha256(IMPLEMENTATION_CONTRACT_PATH),
        "stage3_plan_contract_sha256": _sha256(STAGE3_CONTRACT_PATH),
        "stage1_manifest_sha256": _sha256(STAGE1_MANIFEST_PATH),
        "stage2_manifest_sha256": _sha256(STAGE2_MANIFEST_PATH),
        "stage25_manifest_sha256": _sha256(STAGE25_MANIFEST_PATH),
    }
    if manifest.get("provenance") != expected_provenance:
        raise Stage3PlanningError("preflight provenance has drifted from current inputs")
    if readiness.get("provenance") != expected_provenance:
        raise Stage3PlanningError("readiness provenance has drifted from current inputs")

    plan_contract = _read_json(STAGE3_CONTRACT_PATH)
    if plan_contract.get("schema") != "dynamic_branch_stage3_plan_contract_v1":
        raise Stage3PlanningError("stage 3 plan contract schema mismatch")
    if plan_contract["output"].get("curve_geometry_present") is not False:
        raise Stage3PlanningError("stage 3 contract unexpectedly permits curve geometry")
    if tuple(task_matrix.get("prototype_ids", [])) != PROTOTYPE_IDS:
        raise Stage3PlanningError("task matrix prototype order mismatch")
    if tuple(task_matrix.get("seeds", [])) != SEEDS:
        raise Stage3PlanningError("task matrix seed order mismatch")
    tasks = task_matrix.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 15:
        raise Stage3PlanningError("task matrix does not contain exactly fifteen tasks")
    expected_ids = [
        f"{prototype_id}__seed_{seed}__raw_1"
        for prototype_id in PROTOTYPE_IDS
        for seed in SEEDS
    ]
    if [task.get("task_id") for task in tasks] != expected_ids:
        raise Stage3PlanningError("task matrix task order/id mismatch")
    if any(task.get("state") != "ready_not_generated" for task in tasks):
        raise Stage3PlanningError("task matrix contains a task that is not launch-ready")
    if any(task.get("raw_candidate_index") != 1 for task in tasks):
        raise Stage3PlanningError("task matrix violates the one-raw-plan policy")
    if any(task.get("validation_guided_retry_allowed") is not False for task in tasks):
        raise Stage3PlanningError("task matrix unexpectedly permits guided retries")
    return manifest, readiness, task_matrix, plan_contract


def _load_input_profiles(
    readiness: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    rows = readiness.get("input_profiles")
    if not isinstance(rows, list) or len(rows) != len(PROTOTYPE_IDS):
        raise Stage3PlanningError("readiness input profile inventory is incomplete")
    profiles: dict[str, dict[str, Any]] = {}
    for expected_id, row in zip(PROTOTYPE_IDS, rows):
        if not isinstance(row, dict) or row.get("prototype_id") != expected_id:
            raise Stage3PlanningError("readiness input profile order/id mismatch")
        if row.get("analysis_review_state") != "analysis_approved":
            raise Stage3PlanningError(f"{expected_id} analysis is no longer approved")
        if row.get("morphology_review_state") != "morphology_approved":
            raise Stage3PlanningError(f"{expected_id} morphology is no longer approved")
        strict_path = _repo_file(row.get("strict_p0_path"), f"{expected_id} StrictP0")
        analysis_path = _repo_file(
            row.get("prototype_analysis_path"),
            f"{expected_id} PrototypeAnalysis",
        )
        morphology_path = _repo_file(
            row.get("morphology_profile_path"),
            f"{expected_id} MorphologyProfile",
        )
        strict = _read_json(strict_path)
        analysis = _read_json(analysis_path)
        morphology = _read_json(morphology_path)
        if strict.get("prototype_id") != expected_id:
            raise Stage3PlanningError(f"{expected_id} StrictP0 identity mismatch")
        if analysis.get("prototype_id") != expected_id:
            raise Stage3PlanningError(f"{expected_id} analysis identity mismatch")
        if morphology.get("prototype_id") != expected_id:
            raise Stage3PlanningError(f"{expected_id} morphology identity mismatch")
        if analysis.get("strict_p0_digest") != row.get("strict_p0_digest"):
            raise Stage3PlanningError(f"{expected_id} StrictP0 digest chain mismatch")
        if analysis.get("analysis_digest") != row.get("prototype_analysis_digest"):
            raise Stage3PlanningError(f"{expected_id} analysis digest mismatch")
        if morphology.get("morphology_digest") != row.get("morphology_digest"):
            raise Stage3PlanningError(f"{expected_id} morphology digest mismatch")
        if (
            morphology.get("source_stage2_analysis_digest")
            != row.get("prototype_analysis_digest")
        ):
            raise Stage3PlanningError(f"{expected_id} analysis/morphology chain mismatch")
        family_id = morphology["classification"]["flower_branch_relation"]["family_id"]
        if family_id != row.get("family_id"):
            raise Stage3PlanningError(f"{expected_id} morphology family mismatch")
        profiles[expected_id] = {
            "row": row,
            "strict_path": strict_path,
            "analysis_path": analysis_path,
            "morphology_path": morphology_path,
            "analysis": analysis,
            "morphology": morphology,
        }
    return profiles


def _input_snapshot(
    task: Mapping[str, Any],
    profile: Mapping[str, Any],
    plan_contract: Mapping[str, Any],
) -> dict[str, Any]:
    row = profile["row"]
    return {
        "schema": "dynamic_branch_stage3_input_snapshot_v3",
        "task_id": task["task_id"],
        "prototype_id": task["prototype_id"],
        "family_id": task["family_id"],
        "seed": task["seed"],
        "raw_candidate_index": task["raw_candidate_index"],
        "plan_contract_id": plan_contract["contract_id"],
        "plan_contract_sha256": _sha256(STAGE3_CONTRACT_PATH),
        "inputs": {
            "strict_p0_path": row["strict_p0_path"],
            "strict_p0_sha256": _sha256(profile["strict_path"]),
            "strict_p0_digest": row["strict_p0_digest"],
            "prototype_analysis_path": row["prototype_analysis_path"],
            "prototype_analysis_sha256": _sha256(profile["analysis_path"]),
            "prototype_analysis_digest": row["prototype_analysis_digest"],
            "morphology_profile_path": row["morphology_profile_path"],
            "morphology_profile_sha256": _sha256(profile["morphology_path"]),
            "morphology_digest": row["morphology_digest"],
        },
        "candidate_policy": {
            "one_raw_plan": True,
            "validation_guided_retry_allowed": False,
            "validation_guided_resample_allowed": False,
            "automatic_repair_allowed": False,
            "automatic_deletion_allowed": False,
        },
        "initial_layout_constraints": plan_contract[
            "initial_layout_constraints"
        ],
        "scope": {
            "branch_skeleton_only": True,
            "directional_layout_only": True,
            "branch_shape_simulation_present": False,
            "curve_compilation_deferred": True,
            "leaves_in_current_or_later_scope": False,
            "buds_in_current_or_later_scope": False,
            "curl_heads_in_current_or_later_scope": False,
            "terminal_intent_means_branch_tip_direction_only": True,
        },
    }


def _pending_review(plan: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "dynamic_branch_plan_review_v3",
        "task_id": plan["task_id"],
        "prototype_id": plan["prototype_id"],
        "seed": plan["seed"],
        "plan_digest": plan["plan_digest"],
        "status": "plan_pending_review",
        "allowed_terminal_states": list(contract["review"]["allowed_terminal_states"]),
        "criteria": list(contract["review"]["criteria"]),
        "visual_gate_required": True,
        "numeric_checks_cannot_auto_approve": True,
        "reviewer": None,
        "reviewed_at": None,
        "notes": [],
        "stage_4_unlocked": False,
        "stage_4_scope_if_approved": "branch_curve_compilation_only",
        "leaves_buds_or_curl_heads_in_project_scope": False,
    }


def _failure_review(task: Mapping[str, Any], failure: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "dynamic_branch_plan_review_v3",
        "task_id": task["task_id"],
        "prototype_id": task["prototype_id"],
        "seed": task["seed"],
        "plan_digest": None,
        "status": "planning_failed",
        "failure_code": failure["code"],
        "visual_gate_required": True,
        "reviewer": None,
        "reviewed_at": None,
        "notes": ["Single-forward planning failure preserved; no retry was attempted."],
        "stage_4_unlocked": False,
        "leaves_buds_or_curl_heads_in_project_scope": False,
    }


def run(
    preflight_root: Path = DEFAULT_PREFLIGHT_ROOT,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Execute the frozen matrix once and stop at the visual plan review gate."""

    if output.exists():
        raise Stage3PlanningError(
            f"stage 3 output already exists and will not be overwritten: {output}"
        )
    preflight_manifest, readiness, task_matrix, contract = _verify_preflight(
        preflight_root
    )
    profiles = _load_input_profiles(readiness)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".dynamic_branch_stage3_plans_", dir=output.parent)
    )
    task_rows: list[dict[str, Any]] = []
    all_pngs: list[Path] = []
    prototype_pngs: dict[str, list[Path]] = {
        prototype_id: [] for prototype_id in PROTOTYPE_IDS
    }
    try:
        for task in task_matrix["tasks"]:
            prototype_id = str(task["prototype_id"])
            seed = int(task["seed"])
            profile = profiles[prototype_id]
            case_dir = temporary / str(task["expected_output_directory"])
            case_dir.mkdir(parents=True, exist_ok=False)
            snapshot_path = case_dir / "stage3_input_snapshot.json"
            _write_json(snapshot_path, _input_snapshot(task, profile, contract))
            try:
                plan = generate_dynamic_branch_plan(
                    profile["analysis"],
                    profile["morphology"],
                    contract,
                    seed=seed,
                    raw_candidate_index=int(task["raw_candidate_index"]),
                )
            except PlanningFailure as exc:
                failure = exc.as_dict()
                failure.update(
                    {
                        "task_id": task["task_id"],
                        "prototype_id": prototype_id,
                        "family_id": task["family_id"],
                        "seed": seed,
                        "raw_candidate_index": task["raw_candidate_index"],
                        "branch_skeleton_only": True,
                    }
                )
                failure_path = case_dir / "planning_failure.json"
                review_path = case_dir / "plan_review.json"
                _write_json(failure_path, failure)
                _write_json(review_path, _failure_review(task, failure))
                task_rows.append(
                    {
                        "task_id": task["task_id"],
                        "prototype_id": prototype_id,
                        "family_id": task["family_id"],
                        "seed": seed,
                        "state": "planning_failed",
                        "output_directory": task["expected_output_directory"],
                        "stage3_input_snapshot_path": snapshot_path.relative_to(
                            temporary
                        ).as_posix(),
                        "stage3_input_snapshot_sha256": _sha256(snapshot_path),
                        "planning_failure_path": failure_path.relative_to(
                            temporary
                        ).as_posix(),
                        "planning_failure_sha256": _sha256(failure_path),
                        "plan_review_path": review_path.relative_to(temporary).as_posix(),
                        "plan_review_sha256": _sha256(review_path),
                        "retry_count": 0,
                    }
                )
                continue

            plan_path = case_dir / "dynamic_branch_plan.json"
            svg_path = case_dir / "dynamic_branch_plan.svg"
            png_path = case_dir / "dynamic_branch_plan.png"
            review_path = case_dir / "plan_review.json"
            _write_json(plan_path, plan)
            render_svg(profile["analysis"], plan, svg_path)
            render_png(profile["analysis"], plan, png_path)
            _write_json(review_path, _pending_review(plan, contract))
            all_pngs.append(png_path)
            prototype_pngs[prototype_id].append(png_path)
            task_rows.append(
                {
                    "task_id": task["task_id"],
                    "prototype_id": prototype_id,
                    "family_id": task["family_id"],
                    "seed": seed,
                    "state": "plan_pending_review",
                    "output_directory": task["expected_output_directory"],
                    "branch_unit_count": len(plan["branch_units"]),
                    "plan_digest": plan["plan_digest"],
                    "stage3_input_snapshot_path": snapshot_path.relative_to(
                        temporary
                    ).as_posix(),
                    "stage3_input_snapshot_sha256": _sha256(snapshot_path),
                    "dynamic_branch_plan_path": plan_path.relative_to(
                        temporary
                    ).as_posix(),
                    "dynamic_branch_plan_sha256": _sha256(plan_path),
                    "dynamic_branch_plan_svg_path": svg_path.relative_to(
                        temporary
                    ).as_posix(),
                    "dynamic_branch_plan_svg_sha256": _sha256(svg_path),
                    "dynamic_branch_plan_png_path": png_path.relative_to(
                        temporary
                    ).as_posix(),
                    "dynamic_branch_plan_png_sha256": _sha256(png_path),
                    "plan_review_path": review_path.relative_to(temporary).as_posix(),
                    "plan_review_sha256": _sha256(review_path),
                    "retry_count": 0,
                }
            )

        contact_sheets: list[dict[str, Any]] = []
        for prototype_id in PROTOTYPE_IDS:
            pngs = prototype_pngs[prototype_id]
            if not pngs:
                continue
            path = temporary / prototype_id / "prototype_plan_contact_sheet.png"
            render_contact_sheet(pngs, path, columns=3)
            contact_sheets.append(
                {
                    "scope": prototype_id,
                    "path": path.relative_to(temporary).as_posix(),
                    "sha256": _sha256(path),
                    "image_count": len(pngs),
                }
            )
        global_sheet_path: Path | None = None
        if all_pngs:
            global_sheet_path = temporary / "stage3_plan_contact_sheet.png"
            render_contact_sheet(all_pngs, global_sheet_path, columns=3)
            contact_sheets.append(
                {
                    "scope": "all_five_prototypes",
                    "path": global_sheet_path.relative_to(temporary).as_posix(),
                    "sha256": _sha256(global_sheet_path),
                    "image_count": len(all_pngs),
                }
            )

        success_count = sum(row["state"] == "plan_pending_review" for row in task_rows)
        failure_count = sum(row["state"] == "planning_failed" for row in task_rows)
        manifest = {
            "schema": "dynamic_branch_stage3_plan_manifest_v3",
            "plan_schema": contract["output"]["schema"],
            "plan_contract_id": contract["contract_id"],
            "prototype_ids": list(PROTOTYPE_IDS),
            "seeds": list(SEEDS),
            "task_count": len(task_rows),
            "success_count": success_count,
            "failure_count": failure_count,
            "all_tasks_preserved": len(task_rows) == 15,
            "raw_plan_count_per_successful_task": 1,
            "tasks": task_rows,
            "contact_sheets": contact_sheets,
            "review_gate": {
                "status": "plan_review_pending",
                "pending_review_count": success_count,
                "planning_failure_count": failure_count,
                "all_fifteen_tasks_require_terminal_review_state": True,
                "stage_4_requires_at_least_one_approved_plan_per_prototype": True,
                "numeric_checks_cannot_auto_approve_visual_gate": True,
                "stage_4_unlocked": False,
            },
            "policy": {
                "single_forward_plan": True,
                "validation_guided_retry_used": False,
                "validation_guided_resample_used": False,
                "automatic_repair_used": False,
                "automatic_deletion_used": False,
                "failed_tasks_count_toward_inventory": True,
            },
            "project_scope": {
                "branch_skeleton_only": True,
                "directional_layout_only": True,
                "branch_shape_simulation_present": False,
                "leaves_in_current_or_later_scope": False,
                "buds_in_current_or_later_scope": False,
                "curl_heads_in_current_or_later_scope": False,
                "terminal_intent_means_branch_tip_direction_only": True,
            },
            "revision": {
                "version": 3,
                "predecessor_output": (
                    "artifacts/runs/dynamic_branch_stage3_plans_v2"
                ),
                "predecessor_preserved": True,
                "reasons": [
                    "sw3_terminal_support_must_route_below_the_flower_and_contact_its_underside",
                    "ordinary_units_must_depart_immediately_toward_free_space",
                    "stage3_preview_controls_direction_distance_and_position_not_branch_shape",
                    "segment_crossings_must_be_detected_as_hard_failures",
                ],
            },
            "stage_scope": {
                "completed": [
                    "role_density_field_derivation",
                    "complete_branchunit_candidate_enumeration",
                    "unit_level_symbolic_clearance",
                    "minimum_periodic_root_spacing_enforcement",
                    "local_direction_difference_enforcement",
                    "one_root_per_density_bin_enforcement",
                    "immediate_outward_departure_enforcement",
                    "parent_backbone_clearance_enforcement",
                    "sw3_remote_below_flower_underside_support_enforcement",
                    "exact_symbolic_polyline_crossing_detection",
                    "global_branchunit_set_selection",
                    "immutable_symbolic_plan_emission",
                    "non_curve_plan_rendering",
                ],
                "not_started": [
                    "branch_curve_compilation",
                    "curve_geometry_validation",
                    "editor_integration",
                ],
            },
            "provenance": {
                "preflight_manifest_sha256": _sha256(
                    preflight_root / "manifest.json"
                ),
                "preflight_task_matrix_digest": task_matrix["task_matrix_digest"],
                **preflight_manifest["provenance"],
                "planner_source_sha256": _sha256(
                    DYNAMIC_DIR / "dynamic_branch_plan.py"
                ),
                "renderer_source_sha256": _sha256(
                    DYNAMIC_DIR / "render_dynamic_branch_plan.py"
                ),
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
    parser.add_argument("--preflight-root", type=Path, default=DEFAULT_PREFLIGHT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = run(args.preflight_root, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage3PlanningError as exc:
        raise SystemExit(f"stage 3 planning error: {exc}") from exc
