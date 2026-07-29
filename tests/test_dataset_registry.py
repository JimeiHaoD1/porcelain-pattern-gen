from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chanzhi_sw.chanzhi_dataset_registry import (  # noqa: E402
    scan_review_directory,
    write_snapshot,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _make_review_dir(tmp_path: Path) -> tuple[Path, list[dict[str, object]]]:
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    records = []
    for number, tier in ((1, "A"), (2, "B"), (3, "A")):
        name = f"{number:03d}__sample.png"
        data = f"image-{number}".encode("ascii")
        (review_dir / name).write_bytes(data)
        records.append(
            {
                "review_no": number,
                "review_file": name,
                "previous_tier": tier,
                "original_relative_path": f"source_{tier}/A_core/{name}",
                "original_full_path": f"D:/original/{name}",
                "bytes": len(data),
                "sha256": _digest(data),
            }
        )
    with (review_dir / "review_manifest.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return review_dir, records


def test_scan_treats_missing_as_deleted_without_mutating(tmp_path: Path) -> None:
    review_dir, _ = _make_review_dir(tmp_path)
    rejected = review_dir / "002__sample.png"
    rejected.unlink()

    snapshot = scan_review_directory(review_dir)

    assert snapshot["valid"] is True
    assert snapshot["counts"] == {
        "manifest_total": 3,
        "current_images": 2,
        "kept_from_manifest": 2,
        "kept_original": 2,
        "kept_modified": 0,
        "added": 0,
        "added_with_provenance": 0,
        "added_pending_provenance": 0,
        "deleted": 1,
        "duplicate_content_groups": 0,
    }
    assert [row["review_file"] for row in snapshot["deleted"]] == [
        "002__sample.png"
    ]
    assert not rejected.exists()


def test_scan_registers_added_and_modified_images_for_attention(tmp_path: Path) -> None:
    review_dir, _ = _make_review_dir(tmp_path)
    (review_dir / "001__sample.png").write_bytes(b"modified")
    (review_dir / "999__untracked.png").write_bytes(b"other")

    snapshot = scan_review_directory(review_dir)

    assert snapshot["valid"] is True
    assert snapshot["ready_to_finalize"] is False
    assert snapshot["counts"]["kept_modified"] == 1
    assert snapshot["counts"]["added"] == 1
    assert snapshot["counts"]["added_pending_provenance"] == 1
    assert snapshot["attention"]["modified_images"][0]["review_file"] == "001__sample.png"
    assert snapshot["attention"]["added_images_requiring_provenance"][0]["review_file"] == "999__untracked.png"


def test_additions_manifest_completes_provenance(tmp_path: Path) -> None:
    review_dir, _ = _make_review_dir(tmp_path)
    added_name = "999__new.png"
    (review_dir / added_name).write_bytes(b"new")
    additions = tmp_path / "additions.csv"
    with additions.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "review_file",
                "sample_origin",
                "source_reference",
                "source_parent_id",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "review_file": added_name,
                "sample_origin": "real_lineart",
                "source_reference": "https://example.test/source",
                "source_parent_id": "source_001",
                "notes": "user supplied",
            }
        )

    snapshot = scan_review_directory(
        review_dir, additions_manifest_path=additions
    )

    assert snapshot["ready_to_finalize"] is True
    assert snapshot["counts"]["added_with_provenance"] == 1
    assert snapshot["attention"]["added_images_requiring_provenance"] == []


def test_skip_hash_does_not_group_added_images_under_empty_digest(tmp_path: Path) -> None:
    review_dir, _ = _make_review_dir(tmp_path)
    (review_dir / "998__new.png").write_bytes(b"first")
    (review_dir / "999__new.png").write_bytes(b"second")

    snapshot = scan_review_directory(review_dir, verify_hashes=False)

    assert snapshot["valid"] is True
    assert snapshot["counts"]["added"] == 2
    assert snapshot["counts"]["duplicate_content_groups"] == 0


def test_write_snapshot_requires_complete_provenance_by_default(tmp_path: Path) -> None:
    review_dir, _ = _make_review_dir(tmp_path)
    (review_dir / "999__new.png").write_bytes(b"new")
    snapshot = scan_review_directory(review_dir)

    try:
        write_snapshot(snapshot, tmp_path / "registry")
    except ValueError as exc:
        assert "still needs provenance" in str(exc)
    else:
        raise AssertionError("incomplete screening snapshot should not be finalized")

    artifacts = write_snapshot(
        snapshot, tmp_path / "interim_registry", allow_incomplete=True
    )
    assert Path(artifacts["summary"]).is_file()


def test_write_snapshot_refuses_review_subdirectory(tmp_path: Path) -> None:
    review_dir, _ = _make_review_dir(tmp_path)
    snapshot = scan_review_directory(review_dir)

    try:
        write_snapshot(snapshot, review_dir / "results")
    except ValueError as exc:
        assert "outside the review directory" in str(exc)
    else:
        raise AssertionError("write_snapshot should reject review subdirectories")


def test_write_snapshot_creates_external_manifests(tmp_path: Path) -> None:
    review_dir, _ = _make_review_dir(tmp_path)
    snapshot = scan_review_directory(review_dir)
    output_dir = tmp_path / "registry"

    artifacts = write_snapshot(snapshot, output_dir)

    assert Path(artifacts["summary"]).is_file()
    assert Path(artifacts["kept_manifest"]).is_file()
    assert Path(artifacts["deleted_manifest"]).is_file()
