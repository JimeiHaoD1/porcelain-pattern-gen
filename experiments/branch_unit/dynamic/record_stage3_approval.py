#!/usr/bin/env python3
"""Record explicit user approval of stage-3 plans for curve compilation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STAGE3_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3_plans_v3"
)


class Stage3ApprovalError(RuntimeError):
    """Raised when stage-3 review records cannot be promoted safely."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage3ApprovalError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage3ApprovalError(f"JSON root is not an object: {path}")
    return value


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _child_file(root: Path, relative: object, label: str) -> Path:
    path = (root / Path(str(relative))).resolve()
    resolved_root = root.resolve()
    if resolved_root not in path.parents:
        raise Stage3ApprovalError(f"{label} path escapes stage-3 root")
    if not path.is_file():
        raise Stage3ApprovalError(f"{label} is missing: {path}")
    return path


def _replace_json_transaction(updates: Mapping[Path, Mapping[str, Any]]) -> None:
    originals = {path: path.read_bytes() for path in updates}
    staged: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for path, value in updates.items():
            descriptor, name = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
            )
            os.close(descriptor)
            temporary = Path(name)
            temporary.write_bytes(_json_bytes(value))
            staged[path] = temporary
        for path, temporary in staged.items():
            os.replace(temporary, path)
            replaced.append(path)
    except Exception as exc:
        for path in reversed(replaced):
            descriptor, name = tempfile.mkstemp(
                prefix=f".{path.name}.rollback.",
                suffix=".tmp",
                dir=path.parent,
            )
            os.close(descriptor)
            rollback = Path(name)
            rollback.write_bytes(originals[path])
            os.replace(rollback, path)
        raise Stage3ApprovalError(
            f"stage-3 approval transaction failed: {exc}"
        ) from exc
    finally:
        for temporary in staged.values():
            if temporary.exists():
                temporary.unlink()


def approve(
    stage3_root: Path = DEFAULT_STAGE3_ROOT,
    *,
    reviewer: str,
    note: str,
    approved_at: str | None = None,
) -> dict[str, Any]:
    """Approve all preserved v3 plans and unlock stage-4 compilation."""

    reviewer = reviewer.strip()
    note = note.strip()
    if not reviewer or not note:
        raise Stage3ApprovalError("reviewer and approval note must be non-empty")
    timestamp = approved_at or datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    manifest_path = stage3_root / "manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != "dynamic_branch_stage3_plan_manifest_v3":
        raise Stage3ApprovalError("stage-3 manifest schema mismatch")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 15:
        raise Stage3ApprovalError("stage-3 manifest must preserve fifteen tasks")
    if any(row.get("state") != "plan_pending_review" for row in tasks):
        raise Stage3ApprovalError(
            "all stage-3 tasks must be pending review before batch approval"
        )

    updated_manifest = copy.deepcopy(manifest)
    updates: dict[Path, dict[str, Any]] = {}
    for row in updated_manifest["tasks"]:
        plan_path = _child_file(
            stage3_root,
            row["dynamic_branch_plan_path"],
            f'{row["task_id"]} plan',
        )
        if _sha256(plan_path) != row["dynamic_branch_plan_sha256"]:
            raise Stage3ApprovalError(f'{row["task_id"]} plan hash mismatch')
        plan = _read_json(plan_path)
        if plan.get("plan_digest") != row.get("plan_digest"):
            raise Stage3ApprovalError(f'{row["task_id"]} plan digest mismatch')
        review_path = _child_file(
            stage3_root,
            row["plan_review_path"],
            f'{row["task_id"]} review',
        )
        if _sha256(review_path) != row["plan_review_sha256"]:
            raise Stage3ApprovalError(f'{row["task_id"]} review hash mismatch')
        review = _read_json(review_path)
        if review.get("schema") != "dynamic_branch_plan_review_v3":
            raise Stage3ApprovalError(f'{row["task_id"]} review schema mismatch')
        if review.get("plan_digest") != plan["plan_digest"]:
            raise Stage3ApprovalError(f'{row["task_id"]} review binding mismatch')
        if review.get("status") != "plan_pending_review":
            raise Stage3ApprovalError(f'{row["task_id"]} review is not pending')
        updated_review = copy.deepcopy(review)
        updated_review["status"] = "plan_approved_for_curve_compilation"
        updated_review["reviewer"] = reviewer
        updated_review["reviewed_at"] = timestamp
        updated_review["notes"] = [*updated_review.get("notes", []), note]
        updated_review["stage_4_unlocked"] = True
        updates[review_path] = updated_review
        row["state"] = "plan_approved_for_curve_compilation"
        row["plan_review_sha256"] = _sha256_bytes(
            _json_bytes(updated_review)
        )

    updated_manifest["review_gate"] = {
        "status": "plan_approved_for_curve_compilation",
        "approved_plan_count": 15,
        "pending_review_count": 0,
        "planning_failure_count": 0,
        "all_fifteen_tasks_require_terminal_review_state": True,
        "numeric_checks_cannot_auto_approve_visual_gate": True,
        "stage_4_unlocked": True,
        "reviewer": reviewer,
        "reviewed_at": timestamp,
    }
    updated_manifest["approval"] = {
        "source": "explicit_user_instruction_to_continue_to_stage4",
        "reviewer": reviewer,
        "reviewed_at": timestamp,
        "note": note,
    }
    updates[manifest_path] = updated_manifest
    _replace_json_transaction(updates)
    return {
        "schema": "dynamic_branch_stage3_approval_result_v1",
        "approved_plan_count": 15,
        "review_state": "plan_approved_for_curve_compilation",
        "stage_4_unlocked": True,
        "reviewer": reviewer,
        "reviewed_at": timestamp,
        "updated_file_count": len(updates),
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage3-root", type=Path, default=DEFAULT_STAGE3_ROOT)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--approved-at")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    result = approve(
        args.stage3_root,
        reviewer=args.reviewer,
        note=args.note,
        approved_at=args.approved_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
