#!/usr/bin/env python3
"""Record the user's explicit visual rejection of all stage-4 v1 candidates."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_curves_v1"
)


class Stage4V1RejectionError(RuntimeError):
    pass


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage4V1RejectionError(f"JSON root is not an object: {path}")
    return value


def _atomic_write(path: Path, value: object) -> None:
    handle, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(handle)
    temporary = Path(name)
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def run(
    root: Path = DEFAULT_ROOT,
    *,
    reviewer: str = "user",
    note: str = (
        "User visually rejected stage 4 v1 because the outputs were near-straight "
        "single curves rather than complete dynamic BranchUnits."
    ),
) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = _read(manifest_path)
    if manifest.get("schema") != "dynamic_branch_stage4_curve_manifest_v1":
        raise Stage4V1RejectionError("stage-4 v1 manifest schema mismatch")
    reviewed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    updated = 0
    for task in manifest["tasks"]:
        review_relative = task.get("original_visual_review_path")
        if not review_relative:
            continue
        review_path = (root / review_relative).resolve()
        if root.resolve() not in review_path.parents:
            raise Stage4V1RejectionError("review path escapes stage-4 v1 root")
        review = _read(review_path)
        review["status"] = "original_rejected"
        review["reviewer"] = reviewer
        review["reviewed_at"] = reviewed_at
        review["notes"] = [note]
        review["editor_unlocked"] = False
        _atomic_write(review_path, review)
        task["state"] = "original_rejected"
        task["visual_rejection_reason"] = "near_straight_incomplete_branchunit"
        updated += 1
    manifest["review_gate"] = {
        "status": "original_curve_review_rejected",
        "pending_review_count": 0,
        "rejected_count": updated,
        "compilation_failure_count": manifest.get("failure_count", 0),
        "numeric_checks_cannot_auto_approve_visual_gate": True,
        "editor_unlocked": False,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "note": note,
    }
    manifest["superseded_by"] = {
        "contract_id": "dynamic_branchunit_hierarchical_curve_compilation_stage4_v2",
        "reason": "v1 omitted complete BranchUnit topology and visible curve shaping",
    }
    _atomic_write(manifest_path, manifest)
    return {
        "root": str(root),
        "updated_review_count": updated,
        "status": manifest["review_gate"]["status"],
        "reviewed_at": reviewed_at,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--reviewer", default="user")
    parser.add_argument(
        "--note",
        default=(
            "User visually rejected stage 4 v1 because the outputs were near-straight "
            "single curves rather than complete dynamic BranchUnits."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    print(
        json.dumps(
            run(args.root, reviewer=args.reviewer, note=args.note),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
