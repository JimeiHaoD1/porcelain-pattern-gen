#!/usr/bin/env python3
"""Record the explicit visual rejection of the stage-5 whole compositions."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage5_global_unit_selection_v1"
)
DEFAULT_OUTPUT = DEFAULT_ROOT / "stage5_visual_rejection.json"


class Stage5VisualRejectionError(RuntimeError):
    """The rejection cannot be bound to the formal stage-5 package."""


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5VisualRejectionError(
            f"JSON root is not an object: {path}"
        )
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_exclusive(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def reject(
    root: Path = DEFAULT_ROOT,
    output: Path = DEFAULT_OUTPUT,
    *,
    reviewer: str,
    note: str,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = _read(manifest_path)
    if manifest.get("schema") != (
        "dynamic_branch_stage5_global_selection_manifest_v1"
    ):
        raise Stage5VisualRejectionError("stage-5 manifest schema mismatch")
    if output.exists():
        raise Stage5VisualRejectionError(
            f"visual rejection already exists: {output}"
        )
    contact_path = root / manifest["contact_sheet"]["path"]
    if _sha256(contact_path) != manifest["contact_sheet"]["sha256"]:
        raise Stage5VisualRejectionError("stage-5 contact sheet hash mismatch")

    record = {
        "schema": "dynamic_branch_stage5_visual_rejection_v1",
        "status": "whole_composition_visually_rejected",
        "source": "explicit_user_review",
        "reviewer": reviewer,
        "reviewed_at": reviewed_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": note,
        "stage5_manifest_path": "manifest.json",
        "stage5_manifest_sha256": _sha256(manifest_path),
        "reviewed_contact_sheet_path": manifest["contact_sheet"]["path"],
        "reviewed_contact_sheet_sha256": _sha256(contact_path),
        "stage6_unlocked": False,
        "editor_unlocked": False,
        "core_judgment": (
            "The outputs satisfy branching, repetition, and avoidance checks "
            "but do not form role-readable continuous-scroll vine organization."
        ),
        "global_failure_categories": [
            "hard_or_t_shaped_branch_mounts",
            "role_labels_without_role_specific_geometry",
            "floating_flowers_without_growth_relation",
            "excessive_vertical_growth_breaks_horizontal_repeat",
            "weak_l1_l2_l3_scale_hierarchy",
            "mechanical_fork_and_tendril_endings",
            "unplanned_density_distribution",
            "missing_root_bend_settle_curvature_sequence",
            "non_seam_branches_escape_composition_envelope",
        ],
        "prototype_priority": [
            {
                "prototype_id": "proto_sw_3_1",
                "priority": 1,
                "decision": (
                    "Keep as simplified baseline; add one support relation "
                    "and one short flower-wrap relation."
                ),
            },
            {
                "prototype_id": "proto_sw_1_1",
                "priority": 2,
                "decision": (
                    "Keep backbone continuity; replace outward escaping branches."
                ),
            },
            {
                "prototype_id": "proto_sw_3_2",
                "priority": 3,
                "decision": (
                    "Replace vertical fence-like branches with oblique return arcs."
                ),
            },
            {
                "prototype_id": "proto_sw_2_3",
                "priority": 4,
                "decision": (
                    "Rebalance upper and lower structure and remove aimless drops."
                ),
            },
            {
                "prototype_id": "proto_sw_1_3",
                "priority": 5,
                "decision": (
                    "Reject local parameter tuning; rebuild role layout."
                ),
            },
        ],
        "required_revision": {
            "resume_from": "global_role_aware_l1_planning",
            "do_not_continue_to_stage6": True,
            "do_not_fix_in_stage5_selector": True,
            "flower_core_relations": [
                "support",
                "wrap",
                "short_balance",
            ],
            "branch_questions": [
                "where_does_it_grow_from",
                "which_object_does_it_serve",
                "where_does_it_settle",
            ],
            "curve_phases": [
                "root",
                "bend",
                "settle",
            ],
        },
    }
    _write_exclusive(output, record)
    return record


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reviewer", default="user")
    parser.add_argument("--note", required=True)
    parser.add_argument("--reviewed-at")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    record = reject(
        args.root.resolve(),
        args.output.resolve(),
        reviewer=args.reviewer,
        note=args.note,
        reviewed_at=args.reviewed_at,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage5VisualRejectionError as exc:
        raise SystemExit(f"stage-5 visual rejection error: {exc}") from exc
