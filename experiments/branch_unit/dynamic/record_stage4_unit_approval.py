#!/usr/bin/env python3
"""Bind explicit human approval to the complete immutable stage-4 Unit pool."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STAGE4_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_unit_candidates_v1"
)
DEFAULT_OUTPUT = DEFAULT_STAGE4_ROOT / "stage4_approval.json"
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
SEEDS = (4101, 4102, 4103)


class Stage4ApprovalError(RuntimeError):
    """The stage-4 approval cannot be bound to its immutable package."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage4ApprovalError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_exclusive(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def approve(
    stage4_root: Path = DEFAULT_STAGE4_ROOT,
    output: Path = DEFAULT_OUTPUT,
    *,
    reviewer: str,
    note: str,
    approved_at: str | None = None,
) -> dict[str, Any]:
    reviewer = reviewer.strip()
    note = note.strip()
    if not reviewer or not note:
        raise Stage4ApprovalError("reviewer and approval note must be non-empty")
    if output.exists():
        raise Stage4ApprovalError(f"approval record already exists: {output}")

    manifest_path = stage4_root / "manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != "dynamic_branch_stage4_unit_candidate_manifest_v1":
        raise Stage4ApprovalError("stage-4 manifest schema mismatch")
    if tuple(manifest.get("prototype_ids", ())) != PROTOTYPE_IDS:
        raise Stage4ApprovalError("stage-4 prototype inventory/order mismatch")
    if tuple(manifest.get("seeds", ())) != SEEDS:
        raise Stage4ApprovalError("stage-4 seed inventory/order mismatch")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 15:
        raise Stage4ApprovalError("stage-4 must contain exactly fifteen tasks")
    if manifest.get("success_count") != 15 or manifest.get("failure_count") != 0:
        raise Stage4ApprovalError("stage-4 package is incomplete")

    approved_tasks: list[dict[str, Any]] = []
    for row in tasks:
        inventory_file = row.get("files", {}).get(
            "unit_candidate_inventory.json",
            {},
        )
        inventory_path = stage4_root / str(inventory_file.get("path", ""))
        if (
            not inventory_path.is_file()
            or _sha256(inventory_path) != inventory_file.get("sha256")
        ):
            raise Stage4ApprovalError(
                f'{row.get("task_id")} inventory file/hash mismatch'
            )
        inventory = _read_json(inventory_path)
        if inventory.get("inventory_digest") != row.get("inventory_digest"):
            raise Stage4ApprovalError(
                f'{row.get("task_id")} inventory digest mismatch'
            )
        if inventory.get("coverage", {}).get(
            "lanes_without_feasible_candidate"
        ):
            raise Stage4ApprovalError(
                f'{row.get("task_id")} lacks a feasible Unit in one or more lanes'
            )
        approved_tasks.append(
            {
                "task_id": row["task_id"],
                "prototype_id": row["prototype_id"],
                "seed": row["seed"],
                "inventory_path": str(
                    inventory_path.relative_to(stage4_root)
                ).replace("\\", "/"),
                "inventory_sha256": _sha256(inventory_path),
                "inventory_digest": inventory["inventory_digest"],
                "lane_count": inventory["lane_count"],
                "candidate_count": inventory["candidate_count"],
                "feasible_candidate_count": inventory[
                    "feasible_candidate_count"
                ],
            }
        )

    record = {
        "schema": "dynamic_branch_stage4_unit_candidate_approval_v1",
        "status": "unit_candidate_pool_approved_for_global_selection",
        "source": "explicit_user_confirmation",
        "reviewer": reviewer,
        "reviewed_at": approved_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": note,
        "stage5_unlocked": True,
        "stage4_manifest_path": "manifest.json",
        "stage4_manifest_sha256": _sha256(manifest_path),
        "approved_task_count": len(approved_tasks),
        "approved_tasks": approved_tasks,
        "approval_scope": {
            "complete_unit_geometry": "approved_as_stage5_selection_input",
            "stage4_candidate_pool": "approved_and_immutable",
            "whole_composition_selection": "not_yet_visually_reviewed",
        },
    }
    _write_json_exclusive(output, record)
    return record


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--approved-at")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    record = approve(
        args.stage4_root.resolve(),
        args.output.resolve(),
        reviewer=args.reviewer,
        note=args.note,
        approved_at=args.approved_at,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage4ApprovalError as exc:
        raise SystemExit(f"stage-4 approval error: {exc}") from exc
