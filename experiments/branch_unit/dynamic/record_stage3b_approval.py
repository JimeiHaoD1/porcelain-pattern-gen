#!/usr/bin/env python3
"""Record the explicit human approval of the immutable stage-3B L1 package."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STAGE3B_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3b_global_l1_flow_v1"
)
DEFAULT_OUTPUT = DEFAULT_STAGE3B_ROOT / "stage3b_approval.json"
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
SEEDS = (4101, 4102, 4103)


class Stage3BApprovalError(RuntimeError):
    """The approval cannot be bound to the complete immutable input package."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage3BApprovalError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def approve(
    stage3b_root: Path = DEFAULT_STAGE3B_ROOT,
    output: Path = DEFAULT_OUTPUT,
    *,
    reviewer: str,
    note: str,
    approved_at: str | None = None,
) -> dict[str, Any]:
    reviewer = reviewer.strip()
    note = note.strip()
    if not reviewer or not note:
        raise Stage3BApprovalError("reviewer and approval note must be non-empty")
    if output.exists():
        raise Stage3BApprovalError(f"approval record already exists: {output}")

    manifest_path = stage3b_root / "manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != "dynamic_branch_stage3b_l1_flow_manifest_v1":
        raise Stage3BApprovalError("stage-3B manifest schema mismatch")
    if tuple(manifest.get("prototype_ids", ())) != PROTOTYPE_IDS:
        raise Stage3BApprovalError("stage-3B prototype inventory/order mismatch")
    if tuple(manifest.get("seeds", ())) != SEEDS:
        raise Stage3BApprovalError("stage-3B seed inventory/order mismatch")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 15:
        raise Stage3BApprovalError("stage-3B must contain exactly fifteen tasks")
    if manifest.get("success_count") != 15 or manifest.get("failure_count") != 0:
        raise Stage3BApprovalError("stage-3B is not a complete successful package")
    if any(row.get("state") != "l1_flow_pending_visual_review" for row in tasks):
        raise Stage3BApprovalError("stage-3B task states are not reviewable")
    expected = [(prototype_id, seed) for prototype_id in PROTOTYPE_IDS for seed in SEEDS]
    actual = [(row.get("prototype_id"), row.get("seed")) for row in tasks]
    if actual != expected:
        raise Stage3BApprovalError("stage-3B task launch matrix mismatch")

    frozen_tasks: list[dict[str, Any]] = []
    for row in tasks:
        plan_file = row.get("files", {}).get("global_l1_flow_plan.json", {})
        plan_path = stage3b_root / str(plan_file.get("path", ""))
        if not plan_path.is_file() or _sha256(plan_path) != plan_file.get("sha256"):
            raise Stage3BApprovalError(f'{row.get("task_id")} plan file/hash mismatch')
        plan = _read_json(plan_path)
        if plan.get("plan_digest") != row.get("plan_digest"):
            raise Stage3BApprovalError(f'{row.get("task_id")} plan digest mismatch')
        if plan.get("diagnostics", {}).get("hard_issue_count") != 0:
            raise Stage3BApprovalError(f'{row.get("task_id")} has hard issues')
        frozen_tasks.append(
            {
                "task_id": row["task_id"],
                "prototype_id": row["prototype_id"],
                "seed": row["seed"],
                "plan_path": str(plan_path.relative_to(stage3b_root)).replace("\\", "/"),
                "plan_sha256": _sha256(plan_path),
                "plan_digest": plan["plan_digest"],
                "lane_count": len(plan["lanes"]),
            }
        )

    record = {
        "schema": "dynamic_branch_stage3b_approval_v1",
        "status": "l1_flow_approved_for_unit_generation",
        "source": "explicit_user_confirmation",
        "reviewer": reviewer,
        "reviewed_at": approved_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": note,
        "stage4_unlocked": True,
        "stage3b_manifest_path": "manifest.json",
        "stage3b_manifest_sha256": _sha256(manifest_path),
        "approved_task_count": len(frozen_tasks),
        "approved_tasks": frozen_tasks,
        "approval_scope": {
            "l1_root_role_target_corridor_and_geometry": "approved_and_immutable",
            "l2_l3_geometry": "not_reviewed_in_stage3b",
            "whole_composition_unit_selection": "not_reviewed_in_stage3b",
        },
    }
    _write_json_exclusive(output, record)
    return record


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage3b-root", type=Path, default=DEFAULT_STAGE3B_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--approved-at")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    record = approve(
        args.stage3b_root.resolve(),
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
    except Stage3BApprovalError as exc:
        raise SystemExit(f"stage-3B approval error: {exc}") from exc
