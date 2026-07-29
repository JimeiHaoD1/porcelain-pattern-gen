#!/usr/bin/env python3
"""Record explicit human approval for stage 2 and stage 2.5 review gates."""

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
DEFAULT_STAGE2_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
)
DEFAULT_STAGE25_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
)
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)


class ApprovalError(RuntimeError):
    """Raised when review provenance is incomplete or unsafe to promote."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApprovalError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ApprovalError(f"JSON root is not an object: {path}")
    return value


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _rows_by_id(
    rows: object,
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != len(PROTOTYPE_IDS):
        raise ApprovalError(f"{label} profile inventory is incomplete")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ApprovalError(f"{label} profile row is invalid")
        prototype_id = str(row.get("prototype_id", ""))
        if prototype_id in by_id or prototype_id not in PROTOTYPE_IDS:
            raise ApprovalError(f"{label} profile id is invalid: {prototype_id}")
        by_id[prototype_id] = row
    if tuple(by_id) != PROTOTYPE_IDS:
        raise ApprovalError(f"{label} profile order is not canonical")
    return by_id


def _resolved_child(root: Path, relative: object, label: str) -> Path:
    path = (root / Path(str(relative))).resolve()
    resolved_root = root.resolve()
    if resolved_root not in path.parents:
        raise ApprovalError(f"{label} path escapes its artifact root: {relative}")
    if not path.is_file():
        raise ApprovalError(f"{label} file is missing: {path}")
    return path


def _approved_review(
    review: Mapping[str, Any],
    *,
    expected_schema: str,
    expected_prototype_id: str,
    expected_digest_key: str,
    expected_digest: str,
    approved_state: str,
    reviewer: str,
    approved_at: str,
    note: str,
) -> dict[str, Any]:
    if review.get("schema") != expected_schema:
        raise ApprovalError(
            f"{expected_prototype_id} review schema mismatch: {review.get('schema')}"
        )
    if review.get("prototype_id") != expected_prototype_id:
        raise ApprovalError(f"{expected_prototype_id} review content/id mismatch")
    if review.get(expected_digest_key) != expected_digest:
        raise ApprovalError(f"{expected_prototype_id} review digest binding mismatch")
    current = str(review.get("status", ""))
    if current not in {
        "analysis_pending_review",
        "analysis_needs_revision",
        "morphology_pending_review",
        "morphology_needs_revision",
    }:
        raise ApprovalError(
            f"{expected_prototype_id} review cannot be promoted from {current}"
        )
    updated = copy.deepcopy(dict(review))
    notes = updated.get("notes", [])
    if not isinstance(notes, list):
        raise ApprovalError(f"{expected_prototype_id} review notes must be an array")
    updated["status"] = approved_state
    updated["reviewer"] = reviewer
    updated["reviewed_at"] = approved_at
    updated["notes"] = [*notes, note]
    updated["stage_3_unlocked"] = True
    return updated


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
        raise ApprovalError(f"review approval transaction failed: {exc}") from exc
    finally:
        for temporary in staged.values():
            if temporary.exists():
                temporary.unlink()


def approve(
    stage2_root: Path = DEFAULT_STAGE2_ROOT,
    stage25_root: Path = DEFAULT_STAGE25_ROOT,
    *,
    reviewer: str,
    note: str,
    approved_at: str | None = None,
) -> dict[str, Any]:
    """Promote all five linked reviews and update both manifests atomically."""

    reviewer = reviewer.strip()
    note = note.strip()
    if not reviewer:
        raise ApprovalError("reviewer must be non-empty")
    if not note:
        raise ApprovalError("approval note must be non-empty")
    timestamp = approved_at or datetime.now().astimezone().isoformat(timespec="seconds")

    stage2_manifest_path = stage2_root / "manifest.json"
    stage25_manifest_path = stage25_root / "manifest.json"
    stage2_manifest = _read_json(stage2_manifest_path)
    stage25_manifest = _read_json(stage25_manifest_path)
    if stage2_manifest.get("schema") != "dynamic_branch_stage2_analysis_manifest_v1":
        raise ApprovalError("stage 2 manifest schema mismatch")
    if stage25_manifest.get("schema") != "dynamic_branch_stage25_morphology_manifest_v1":
        raise ApprovalError("stage 2.5 manifest schema mismatch")
    if tuple(stage2_manifest.get("prototype_ids", [])) != PROTOTYPE_IDS:
        raise ApprovalError("stage 2 prototype order mismatch")
    if tuple(stage25_manifest.get("prototype_ids", [])) != PROTOTYPE_IDS:
        raise ApprovalError("stage 2.5 prototype order mismatch")

    stage2_rows = _rows_by_id(stage2_manifest.get("profiles"), label="stage 2")
    stage25_rows = _rows_by_id(stage25_manifest.get("profiles"), label="stage 2.5")
    updates: dict[Path, dict[str, Any]] = {}

    for prototype_id in PROTOTYPE_IDS:
        stage2_row = stage2_rows[prototype_id]
        analysis_path = _resolved_child(
            stage2_root,
            stage2_row.get("prototype_analysis_path"),
            f"{prototype_id} analysis",
        )
        if _sha256(analysis_path) != stage2_row.get("prototype_analysis_sha256"):
            raise ApprovalError(f"{prototype_id} stage 2 analysis hash mismatch")
        analysis = _read_json(analysis_path)
        analysis_digest = str(analysis.get("analysis_digest", ""))
        if not analysis_digest:
            raise ApprovalError(f"{prototype_id} analysis digest is missing")
        analysis_review_path = _resolved_child(
            stage2_root,
            stage2_row.get("analysis_review_path"),
            f"{prototype_id} analysis review",
        )
        if _sha256(analysis_review_path) != stage2_row.get("analysis_review_sha256"):
            raise ApprovalError(f"{prototype_id} analysis review hash mismatch")
        approved_analysis_review = _approved_review(
            _read_json(analysis_review_path),
            expected_schema="dynamic_branch_analysis_review_v1",
            expected_prototype_id=prototype_id,
            expected_digest_key="analysis_digest",
            expected_digest=analysis_digest,
            approved_state="analysis_approved",
            reviewer=reviewer,
            approved_at=timestamp,
            note=note,
        )
        updates[analysis_review_path] = approved_analysis_review
        stage2_row["analysis_review_sha256"] = _sha256_bytes(
            _json_bytes(approved_analysis_review)
        )
        stage2_row["review_status"] = "analysis_approved"

        stage25_row = stage25_rows[prototype_id]
        profile_path = _resolved_child(
            stage25_root,
            stage25_row.get("morphology_profile_path"),
            f"{prototype_id} morphology profile",
        )
        if _sha256(profile_path) != stage25_row.get("morphology_profile_sha256"):
            raise ApprovalError(f"{prototype_id} morphology profile hash mismatch")
        profile = _read_json(profile_path)
        morphology_digest = str(profile.get("morphology_digest", ""))
        if morphology_digest != stage25_row.get("morphology_digest"):
            raise ApprovalError(f"{prototype_id} morphology digest mismatch")
        if profile.get("source_stage2_analysis_digest") != analysis_digest:
            raise ApprovalError(f"{prototype_id} stage 2/2.5 digest chain mismatch")
        morphology_review_path = _resolved_child(
            stage25_root,
            stage25_row.get("morphology_review_path"),
            f"{prototype_id} morphology review",
        )
        if _sha256(morphology_review_path) != stage25_row.get(
            "morphology_review_sha256"
        ):
            raise ApprovalError(f"{prototype_id} morphology review hash mismatch")
        approved_morphology_review = _approved_review(
            _read_json(morphology_review_path),
            expected_schema="dynamic_branch_morphology_review_v1",
            expected_prototype_id=prototype_id,
            expected_digest_key="morphology_digest",
            expected_digest=morphology_digest,
            approved_state="morphology_approved",
            reviewer=reviewer,
            approved_at=timestamp,
            note=note,
        )
        updates[morphology_review_path] = approved_morphology_review
        stage25_row["morphology_review_sha256"] = _sha256_bytes(
            _json_bytes(approved_morphology_review)
        )
        stage25_row["review_status"] = "morphology_approved"

    stage2_manifest["review_gate"] = {
        "status": "analysis_approved",
        "all_five_visual_reviews_required": True,
        "stage_3_unlocked": True,
        "reviewer": reviewer,
        "reviewed_at": timestamp,
    }
    stage2_manifest["approval"] = {
        "source": "explicit_user_confirmation",
        "reviewer": reviewer,
        "reviewed_at": timestamp,
        "note": note,
    }
    stage2_manifest_bytes = _json_bytes(stage2_manifest)
    updates[stage2_manifest_path] = stage2_manifest

    stage25_manifest["stage2_manifest_sha256"] = _sha256_bytes(stage2_manifest_bytes)
    stage25_manifest["review_gate"] = {
        "status": "morphology_approved",
        "all_five_visual_reviews_required": True,
        "stage_3_unlocked": True,
        "reviewer": reviewer,
        "reviewed_at": timestamp,
    }
    stage25_manifest["approval"] = {
        "source": "explicit_user_confirmation",
        "reviewer": reviewer,
        "reviewed_at": timestamp,
        "note": note,
    }
    updates[stage25_manifest_path] = stage25_manifest
    _replace_json_transaction(updates)

    return {
        "schema": "dynamic_branch_stage25_approval_result_v1",
        "prototype_ids": list(PROTOTYPE_IDS),
        "analysis_review_state": "analysis_approved",
        "morphology_review_state": "morphology_approved",
        "stage_3_unlocked": True,
        "reviewer": reviewer,
        "reviewed_at": timestamp,
        "updated_file_count": len(updates),
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2-root", type=Path, default=DEFAULT_STAGE2_ROOT)
    parser.add_argument("--stage25-root", type=Path, default=DEFAULT_STAGE25_ROOT)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--approved-at")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    result = approve(
        args.stage2_root,
        args.stage25_root,
        reviewer=args.reviewer,
        note=args.note,
        approved_at=args.approved_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApprovalError as exc:
        raise SystemExit(f"stage 2.5 approval error: {exc}") from exc

