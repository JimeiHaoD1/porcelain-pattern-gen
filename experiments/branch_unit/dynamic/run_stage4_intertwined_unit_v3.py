#!/usr/bin/env python3
"""Generate the formal 5x3 long-sweep BranchUnit stage-4 v3 package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from dynamic_branch_plan_v4 import generate_dynamic_branch_plan_v4
from dynamic_branch_unit_curve_v3 import (
    compile_dynamic_branch_units_v3,
    diagnose_dynamic_branch_units_v3,
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
STAGE2_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
)
MORPHOLOGY_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
)
PLAN_CONTRACT_PATH = DYNAMIC_DIR / "STAGE3_PLAN_CONTRACT.json"
CURVE_CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_INTERTWINED_UNIT_CONTRACT_V3.json"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage4_intertwined_units_v3"
)
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
SEEDS = (4101, 4102, 4103)


class Stage4IntertwinedRunError(RuntimeError):
    """Formal package launch or integrity error."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage4IntertwinedRunError(
            f"cannot read JSON {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise Stage4IntertwinedRunError(
            f"JSON root is not an object: {path}"
        )
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _assert_gate(
    manifest: Mapping[str, Any],
    *,
    expected_schema: str,
    status: str,
    unlock_key: str,
    label: str,
) -> None:
    if manifest.get("schema") != expected_schema:
        raise Stage4IntertwinedRunError(
            f"{label} manifest schema mismatch"
        )
    gate = manifest.get("review_gate", {})
    if gate.get("status") != status or gate.get(unlock_key) is not True:
        raise Stage4IntertwinedRunError(
            f"{label} review gate is not approved"
        )


def _input_rows(
    manifest: Mapping[str, Any],
    *,
    row_key: str,
) -> dict[str, Mapping[str, Any]]:
    rows = manifest.get(row_key)
    if not isinstance(rows, list):
        raise Stage4IntertwinedRunError(
            f"manifest field {row_key} is not a list"
        )
    result = {
        str(row["prototype_id"]): row
        for row in rows
    }
    if tuple(result) != PROTOTYPE_IDS:
        raise Stage4IntertwinedRunError(
            f"manifest field {row_key} prototype order mismatch"
        )
    return result


def _review(
    candidate: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "dynamic_branch_intertwined_visual_review_v3",
        "candidate_id": candidate["candidate_id"],
        "candidate_digest": candidate["candidate_digest"],
        "prototype_id": candidate["prototype_id"],
        "seed": candidate["seed"],
        "status": contract["review"]["initial_state"],
        "criteria": list(contract["review"]["criteria"]),
        "diagnostic_issue_count": diagnostics["issue_count"],
        "numeric_checks_cannot_auto_approve": True,
        "reviewer": None,
        "reviewed_at": None,
        "notes": [],
        "editor_unlocked": False,
    }


def _task_row(
    *,
    case_dir: Path,
    temporary: Path,
    plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    files = {
        path.name: {
            "path": _relative(path, temporary),
            "sha256": _sha256(path),
        }
        for path in sorted(case_dir.iterdir())
        if path.is_file()
    }
    trough_support_count = sum(
        unit["root_interval_ref"].get("kind")
        == "sw1_trough_support_band"
        for unit in plan["branch_units"]
    )
    return {
        "task_id": candidate["task_id"],
        "prototype_id": candidate["prototype_id"],
        "family_id": candidate["classification"][
            "flower_branch_relation"
        ]["family_id"],
        "seed": candidate["seed"],
        "state": "original_pending_visual_review",
        "branch_unit_count": diagnostics["branch_unit_count"],
        "level_counts": dict(diagnostics["level_counts"]),
        "curve_count": diagnostics["curve_count"],
        "cubic_segment_count": diagnostics["cubic_segment_count"],
        "diagnostic_issue_count": diagnostics["issue_count"],
        "crossing_count": diagnostics["curve_curve_crossing_count"],
        "periodic_repeat_crossing_count": diagnostics[
            "repeat_crossing_count"
        ],
        "wrong_flower_entry_count": diagnostics[
            "wrong_flower_entry_count"
        ],
        "non_root_backbone_crossing_count": diagnostics[
            "non_root_backbone_crossing_count"
        ],
        "near_straight_curve_count": diagnostics[
            "near_straight_curve_count"
        ],
        "sw1_trough_support_count": trough_support_count,
        "plan_digest": plan["plan_digest"],
        "candidate_digest": candidate["candidate_digest"],
        "retry_count": 0,
        "automatic_repair_used": False,
        "automatic_deletion_used": False,
        "files": files,
    }


def run(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    if output.exists():
        raise Stage4IntertwinedRunError(
            f"formal output already exists and will not be overwritten: {output}"
        )
    stage2_manifest = _read_json(STAGE2_ROOT / "manifest.json")
    morphology_manifest = _read_json(MORPHOLOGY_ROOT / "manifest.json")
    _assert_gate(
        stage2_manifest,
        expected_schema="dynamic_branch_stage2_analysis_manifest_v1",
        status="analysis_approved",
        unlock_key="stage_3_unlocked",
        label="stage 2",
    )
    _assert_gate(
        morphology_manifest,
        expected_schema="dynamic_branch_stage25_morphology_manifest_v1",
        status="morphology_approved",
        unlock_key="stage_3_unlocked",
        label="stage 2.5",
    )
    analysis_rows = _input_rows(stage2_manifest, row_key="profiles")
    morphology_rows = _input_rows(
        morphology_manifest,
        row_key="profiles",
    )
    plan_contract = _read_json(PLAN_CONTRACT_PATH)
    curve_contract = _read_json(CURVE_CONTRACT_PATH)
    if plan_contract.get("schema") != "dynamic_branch_stage3_plan_contract_v1":
        raise Stage4IntertwinedRunError("stage-3 plan contract mismatch")
    if (
        curve_contract.get("schema")
        != "dynamic_branch_stage4_intertwined_unit_contract_v3"
    ):
        raise Stage4IntertwinedRunError(
            "stage-4 intertwined contract mismatch"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=".dynamic_branch_stage4_intertwined_v3_",
            dir=output.parent,
        )
    )
    tasks: list[dict[str, Any]] = []
    originals: list[Path] = []
    triples: list[Path] = []
    prototype_originals: dict[str, list[Path]] = {
        prototype_id: [] for prototype_id in PROTOTYPE_IDS
    }
    prototype_triples: dict[str, list[Path]] = {
        prototype_id: [] for prototype_id in PROTOTYPE_IDS
    }
    try:
        for prototype_id in PROTOTYPE_IDS:
            analysis_path = (
                STAGE2_ROOT
                / str(
                    analysis_rows[prototype_id][
                        "prototype_analysis_path"
                    ]
                )
            )
            morphology_path = (
                MORPHOLOGY_ROOT
                / str(
                    morphology_rows[prototype_id][
                        "morphology_profile_path"
                    ]
                )
            )
            if _sha256(analysis_path) != analysis_rows[prototype_id][
                "prototype_analysis_sha256"
            ]:
                raise Stage4IntertwinedRunError(
                    f"{prototype_id} analysis hash mismatch"
                )
            if _sha256(morphology_path) != morphology_rows[prototype_id][
                "morphology_profile_sha256"
            ]:
                raise Stage4IntertwinedRunError(
                    f"{prototype_id} morphology hash mismatch"
                )
            analysis = _read_json(analysis_path)
            morphology = _read_json(morphology_path)
            for seed in SEEDS:
                case_dir = (
                    temporary / prototype_id / f"seed_{seed}"
                )
                case_dir.mkdir(parents=True, exist_ok=False)
                plan = generate_dynamic_branch_plan_v4(
                    analysis,
                    morphology,
                    plan_contract,
                    seed=seed,
                )
                candidate = compile_dynamic_branch_units_v3(
                    analysis,
                    plan,
                    curve_contract,
                )
                diagnostics = diagnose_dynamic_branch_units_v3(
                    analysis,
                    plan,
                    candidate,
                    curve_contract,
                )
                if diagnostics["issue_count"]:
                    raise Stage4IntertwinedRunError(
                        f"{candidate['task_id']} has "
                        f"{diagnostics['issue_count']} diagnostic issues"
                    )
                plan_path = case_dir / "dynamic_branch_plan_v4.json"
                candidate_path = (
                    case_dir / "dynamic_branch_intertwined_unit_v3.json"
                )
                diagnostics_path = (
                    case_dir / "intertwined_unit_diagnostics_v3.json"
                )
                snapshot_path = case_dir / "input_snapshot_v3.json"
                review_path = case_dir / "original_visual_review_v3.json"
                original_svg = case_dir / "original_intertwined_unit.svg"
                original_png = case_dir / "original_intertwined_unit.png"
                triple_svg = (
                    case_dir / "three_repeat_intertwined_unit.svg"
                )
                triple_png = (
                    case_dir / "three_repeat_intertwined_unit.png"
                )
                _write_json(plan_path, plan)
                _write_json(candidate_path, candidate)
                _write_json(diagnostics_path, diagnostics)
                _write_json(
                    snapshot_path,
                    {
                        "schema": "dynamic_branch_stage4_v3_input_snapshot_v1",
                        "prototype_id": prototype_id,
                        "seed": seed,
                        "analysis_path": analysis_path.relative_to(
                            REPO_ROOT
                        ).as_posix(),
                        "analysis_sha256": _sha256(analysis_path),
                        "morphology_path": morphology_path.relative_to(
                            REPO_ROOT
                        ).as_posix(),
                        "morphology_sha256": _sha256(morphology_path),
                        "plan_contract_sha256": _sha256(
                            PLAN_CONTRACT_PATH
                        ),
                        "curve_contract_sha256": _sha256(
                            CURVE_CONTRACT_PATH
                        ),
                        "stage3_revision_reason": (
                            "restore long fixed-baseline sweep logic, "
                            "SW1 trough support, shared-flow children, "
                            "and non-crossing intertwined organization"
                        ),
                    },
                )
                _write_json(
                    review_path,
                    _review(candidate, diagnostics, curve_contract),
                )
                render_original_svg(
                    analysis,
                    candidate,
                    diagnostics,
                    original_svg,
                )
                render_original_png(
                    analysis,
                    candidate,
                    diagnostics,
                    original_png,
                )
                render_three_repeat_svg(
                    analysis,
                    candidate,
                    diagnostics,
                    triple_svg,
                )
                render_three_repeat_png(
                    analysis,
                    candidate,
                    diagnostics,
                    triple_png,
                )
                originals.append(original_png)
                triples.append(triple_png)
                prototype_originals[prototype_id].append(original_png)
                prototype_triples[prototype_id].append(triple_png)
                tasks.append(
                    _task_row(
                        case_dir=case_dir,
                        temporary=temporary,
                        plan=plan,
                        candidate=candidate,
                        diagnostics=diagnostics,
                    )
                )
                print(
                    f"{candidate['task_id']}: "
                    f"{diagnostics['level_counts']} PASS",
                    flush=True,
                )

        for prototype_id in PROTOTYPE_IDS:
            render_contact_sheet(
                prototype_originals[prototype_id],
                temporary
                / prototype_id
                / "original_seed_contact_sheet.png",
                columns=3,
            )
            render_contact_sheet(
                prototype_triples[prototype_id],
                temporary
                / prototype_id
                / "three_repeat_seed_contact_sheet.png",
                columns=3,
            )
        render_contact_sheet(
            originals,
            temporary / "original_contact_sheet.png",
            columns=3,
        )
        render_contact_sheet(
            triples,
            temporary / "three_repeat_contact_sheet.png",
            columns=3,
        )

        level_totals = {
            level: sum(task["level_counts"][level] for task in tasks)
            for level in ("L1", "L2", "L3")
        }
        manifest = {
            "schema": "dynamic_branch_stage4_intertwined_manifest_v3",
            "contract_id": curve_contract["contract_id"],
            "prototype_ids": list(PROTOTYPE_IDS),
            "seeds": list(SEEDS),
            "task_count": len(tasks),
            "tasks": tasks,
            "totals": {
                "branch_unit_count": sum(
                    task["branch_unit_count"] for task in tasks
                ),
                "level_counts": level_totals,
                "curve_count": sum(
                    task["curve_count"] for task in tasks
                ),
                "cubic_segment_count": sum(
                    task["cubic_segment_count"] for task in tasks
                ),
                "diagnostic_issue_count": sum(
                    task["diagnostic_issue_count"] for task in tasks
                ),
                "crossing_count": sum(
                    task["crossing_count"] for task in tasks
                ),
                "periodic_repeat_crossing_count": sum(
                    task["periodic_repeat_crossing_count"]
                    for task in tasks
                ),
                "wrong_flower_entry_count": sum(
                    task["wrong_flower_entry_count"] for task in tasks
                ),
                "non_root_backbone_crossing_count": sum(
                    task["non_root_backbone_crossing_count"]
                    for task in tasks
                ),
                "near_straight_curve_count": sum(
                    task["near_straight_curve_count"] for task in tasks
                ),
            },
            "sw1_acceptance": {
                "proto_sw_1_1_unit_count_per_seed": 6,
                "proto_sw_1_3_unit_count_per_seed": 5,
                "trough_support_count": sum(
                    task["sw1_trough_support_count"]
                    for task in tasks
                ),
            },
            "generation_policy": {
                "single_raw_candidate_per_task": True,
                "global_forward_variant_selection": True,
                "validation_guided_retry_used": False,
                "automatic_repair_used": False,
                "automatic_deletion_used": False,
                "unregistered_crossing_allowed": False,
            },
            "review_gate": {
                "status": "original_pending_visual_review",
                "all_fifteen_numeric_diagnostics_clear": True,
                "numeric_checks_cannot_auto_approve_visual_gate": True,
                "editor_unlocked": False,
            },
            "stage_boundary": dict(curve_contract["stage_boundary"]),
            "original_contact_sheet_path": "original_contact_sheet.png",
            "three_repeat_contact_sheet_path": (
                "three_repeat_contact_sheet.png"
            ),
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, output)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args()
    manifest = run(args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "task_count": manifest["task_count"],
                "totals": manifest["totals"],
                "review_gate": manifest["review_gate"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
