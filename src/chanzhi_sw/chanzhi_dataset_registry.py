#!/usr/bin/env python3
"""Register the outcome of manual candidate screening without mutating images.

The review directory is treated as user-owned state: missing image files mean
"rejected" and present image files mean "kept".  This module only reads that
directory.  Final manifests are written to a separate output directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
REQUIRED_COLUMNS = {
    "review_no",
    "review_file",
    "previous_tier",
    "original_relative_path",
    "original_full_path",
    "bytes",
    "sha256",
}
ADDITION_COLUMNS = {
    "review_file",
    "sample_origin",
    "source_reference",
    "source_parent_id",
    "notes",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"review manifest not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError(f"review manifest missing columns: {', '.join(missing)}")
        rows = [dict(row) for row in reader]
    names = [row["review_file"] for row in rows]
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate review_file entries: {', '.join(duplicates)}")
    return rows


def _read_additions_manifest(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"additions manifest not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        missing = sorted(ADDITION_COLUMNS - columns)
        if missing:
            raise ValueError(f"additions manifest missing columns: {', '.join(missing)}")
        rows = [dict(row) for row in reader]
    names = [row["review_file"] for row in rows]
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate additions entries: {', '.join(duplicates)}")
    return {row["review_file"]: row for row in rows}


def _source_group(row: dict[str, str]) -> str:
    relative = row.get("original_relative_path", "").replace("\\", "/")
    return relative.split("/", 1)[0] if relative else "unknown"


def _image_files(review_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in review_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def _count(rows: Iterable[dict[str, object]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(key, "unknown")) for row in rows).items()))


def scan_review_directory(
    review_dir: Path,
    manifest_path: Path | None = None,
    *,
    additions_manifest_path: Path | None = None,
    verify_hashes: bool = True,
) -> dict[str, object]:
    """Return a read-only snapshot of the current manual screening state."""

    review_dir = review_dir.resolve()
    if not review_dir.is_dir():
        raise NotADirectoryError(f"review directory not found: {review_dir}")
    manifest_path = (manifest_path or review_dir / "review_manifest.csv").resolve()
    rows = _read_manifest(manifest_path)
    addition_metadata = _read_additions_manifest(additions_manifest_path)
    expected = {row["review_file"]: row for row in rows}
    current_paths = _image_files(review_dir)
    current = {path.name: path for path in current_paths}

    kept: list[dict[str, object]] = []
    deleted: list[dict[str, object]] = []
    modified: list[dict[str, object]] = []
    hash_groups: dict[str, list[str]] = defaultdict(list)

    for name, row in expected.items():
        base = {
            "review_no": int(row["review_no"]),
            "review_file": name,
            "previous_tier": row["previous_tier"],
            "source_group": _source_group(row),
            "original_relative_path": row["original_relative_path"],
            "original_full_path": row["original_full_path"],
            "expected_sha256": row["sha256"].upper(),
            "sample_origin": "real_lineart",
            "source_reference": row["original_full_path"] or row["original_relative_path"],
        }
        path = current.get(name)
        if path is None:
            deleted.append(base)
            continue

        actual_hash = _sha256(path) if verify_hashes else row["sha256"].upper()
        entry = {
            **base,
            "screening_status": "kept_original",
            "provenance_status": "known",
            "review_path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "sha256": actual_hash,
        }
        hash_groups[actual_hash].append(name)
        if verify_hashes and actual_hash != row["sha256"].upper():
            entry["screening_status"] = "kept_modified"
            entry["provenance_status"] = "known_source_modified_content"
            modified.append(entry)
        kept.append(entry)

    added: list[dict[str, object]] = []
    for name, path in current.items():
        if name in expected:
            continue
        metadata = addition_metadata.get(name, {})
        sample_origin = metadata.get("sample_origin", "").strip()
        source_reference = metadata.get("source_reference", "").strip()
        provenance_complete = bool(sample_origin and source_reference)
        added.append({
            "review_no": "",
            "review_file": name,
            "previous_tier": "U",
            "source_group": "user_added",
            "original_relative_path": "",
            "original_full_path": "",
            "expected_sha256": "",
            "screening_status": "added",
            "provenance_status": "known" if provenance_complete else "pending",
            "sample_origin": sample_origin,
            "source_reference": source_reference,
            "source_parent_id": metadata.get("source_parent_id", "").strip(),
            "notes": metadata.get("notes", "").strip(),
            "review_path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path) if verify_hashes else "",
        })
    for entry in added:
        digest = str(entry["sha256"])
        if digest:
            hash_groups[digest].append(str(entry["review_file"]))
    duplicate_groups = [
        {"sha256": digest, "review_files": sorted(names)}
        for digest, names in sorted(hash_groups.items())
        if len(names) > 1
    ]
    kept.sort(key=lambda row: (int(row["review_no"]), str(row["review_file"])))
    deleted.sort(key=lambda row: (int(row["review_no"]), str(row["review_file"])))

    current_candidates = [*kept, *added]
    pending_added = [entry for entry in added if entry["provenance_status"] == "pending"]
    stale_addition_records = sorted(name for name in addition_metadata if name not in current)
    attention = {
        "modified_images": modified,
        "added_images_requiring_provenance": pending_added,
        "stale_addition_records": stale_addition_records,
    }
    issues = {
        "duplicate_content_groups": duplicate_groups,
    }
    valid = not duplicate_groups
    ready_to_finalize = valid and not pending_added
    return {
        "schema": "chanzhi_screening_snapshot_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "review_dir": str(review_dir),
        "source_manifest": str(manifest_path),
        "read_only_scan": True,
        "verify_hashes": verify_hashes,
        "valid": valid,
        "ready_to_finalize": ready_to_finalize,
        "counts": {
            "manifest_total": len(rows),
            "current_images": len(current_candidates),
            "kept_from_manifest": len(kept),
            "kept_original": len(kept) - len(modified),
            "kept_modified": len(modified),
            "added": len(added),
            "added_with_provenance": len(added) - len(pending_added),
            "added_pending_provenance": len(pending_added),
            "deleted": len(deleted),
            "duplicate_content_groups": len(duplicate_groups),
        },
        "kept_by_previous_tier": _count(current_candidates, "previous_tier"),
        "kept_by_source_group": _count(current_candidates, "source_group"),
        "kept": current_candidates,
        "deleted": deleted,
        "attention": attention,
        "issues": issues,
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_snapshot(
    snapshot: dict[str, object],
    output_dir: Path,
    *,
    allow_incomplete: bool = False,
) -> dict[str, str]:
    """Write manifests outside the review directory; never mutate candidates."""

    output_dir = output_dir.resolve()
    review_dir = Path(str(snapshot["review_dir"])).resolve()
    if output_dir == review_dir or review_dir in output_dir.parents:
        raise ValueError("output directory must be outside the review directory")
    if not snapshot.get("valid", False):
        raise ValueError("cannot write an invalid screening snapshot")
    if not snapshot.get("ready_to_finalize", False) and not allow_incomplete:
        raise ValueError(
            "screening snapshot still needs provenance; use allow_incomplete only for interim artifacts"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "screening_summary.json"
    kept_path = output_dir / "kept_candidates.csv"
    deleted_path = output_dir / "deleted_candidates.csv"
    summary_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(kept_path, list(snapshot["kept"]))
    _write_csv(deleted_path, list(snapshot["deleted"]))
    return {
        "summary": str(summary_path),
        "kept_manifest": str(kept_path),
        "deleted_manifest": str(deleted_path),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only registration of manually screened Chanzhi candidates."
    )
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--additions-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--skip-hash", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero while added images still need provenance metadata.",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Write interim artifacts even while added-image provenance is pending.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the summary and never write registration artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    snapshot = scan_review_directory(
        args.review_dir,
        args.manifest,
        additions_manifest_path=args.additions_manifest,
        verify_hashes=not args.skip_hash,
    )
    compact = {
        key: snapshot[key]
        for key in (
            "schema",
            "generated_at_utc",
            "review_dir",
            "read_only_scan",
            "valid",
            "ready_to_finalize",
            "counts",
            "kept_by_previous_tier",
            "kept_by_source_group",
            "attention",
            "issues",
        )
    }
    if args.dry_run:
        print(json.dumps(compact, ensure_ascii=False, indent=2))
    else:
        if args.output_dir is None:
            raise SystemExit("--output-dir is required unless --dry-run is used")
        artifacts = write_snapshot(
            snapshot,
            args.output_dir,
            allow_incomplete=args.allow_incomplete,
        )
        compact["artifacts"] = artifacts
        print(json.dumps(compact, ensure_ascii=False, indent=2))
    if not snapshot["valid"]:
        return 1
    if args.strict and not snapshot["ready_to_finalize"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
