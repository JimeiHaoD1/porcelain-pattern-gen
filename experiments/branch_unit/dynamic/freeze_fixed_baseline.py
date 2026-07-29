#!/usr/bin/env python3
"""Freeze and verify the existing fixed-depth 7/12/2 BranchUnit baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_ID = "fixed_depth_7_12_2_v23"
PLAN_ID = "proto_sw_1_3_J0c_true_lateral_units_7_12_2_v21"
PROTOTYPE_ID = "proto_sw_1_3"
SEEDS = (4101, 4102, 4103)
SOURCE_RUN = REPO_ROOT / "artifacts" / "runs" / "_scratch_whole_local_true_lateral_n12_v23"
FROZEN_ROOT = REPO_ROOT / "artifacts" / "frozen_baselines" / BASELINE_ID
PROFILE = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "run57_reproduction"
    / "01_skeleton_analysis"
    / PROTOTYPE_ID
    / "skeleton_profile.json"
)

SOURCE_SNAPSHOT_FILES = (
    REPO_ROOT / "experiments" / "branch_unit" / "whole_local_branch.py",
    REPO_ROOT / "experiments" / "branch_unit" / "run_whole_local_n12_dev.py",
    REPO_ROOT / "experiments" / "branch_unit" / "multibranch_l.py",
    REPO_ROOT / "experiments" / "branch_unit" / "l_core.py",
)
DOCUMENTATION_FILES = (
    REPO_ROOT / "experiments" / "branch_unit" / "WHOLE_LOCAL_N12_DEV_PROTOCOL.md",
    REPO_ROOT / "experiments" / "branch_unit" / "FIXED_DEPTH_BRANCHUNIT_GENERATION_METHOD.md",
)
OUTPUT_FILES = (
    "contact_sheet.png",
    "contact_sheet_debug.png",
    "contact_sheet_units.png",
    "manifest.json",
    "mount_position_chart.png",
    "proofs.json",
    "record_4101.json",
    "record_4102.json",
    "record_4103.json",
    "seed_4101.png",
    "seed_4101_debug.png",
    "seed_4101_units.png",
    "seed_4102.png",
    "seed_4102_debug.png",
    "seed_4102_units.png",
    "seed_4103.png",
    "seed_4103_debug.png",
    "seed_4103_units.png",
)


class FreezeError(RuntimeError):
    """Raised when the baseline cannot be safely frozen or verified."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FreezeError(f"JSON root is not an object: {path}")
    return value


def _preflight() -> dict[str, Any]:
    required = [
        *SOURCE_SNAPSHOT_FILES,
        *DOCUMENTATION_FILES,
        PROFILE,
        *(SOURCE_RUN / name for name in OUTPUT_FILES),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FreezeError(f"missing fixed baseline files: {missing}")
    run_manifest = _load_json(SOURCE_RUN / "manifest.json")
    if run_manifest.get("plan_id") != PLAN_ID:
        raise FreezeError("fixed run plan_id does not match the preregistered baseline")
    if run_manifest.get("prototype_id") != PROTOTYPE_ID:
        raise FreezeError("fixed run prototype_id is not proto_sw_1_3")
    if run_manifest.get("standard_proofs_pass") is not True:
        raise FreezeError("fixed run proof suite is not marked passed")
    seed_rows = run_manifest.get("seeds")
    if not isinstance(seed_rows, list):
        raise FreezeError("fixed run seed rows are missing")
    if tuple(int(row["seed"]) for row in seed_rows) != SEEDS:
        raise FreezeError("fixed run seeds are not exactly 4101, 4102, 4103")
    if any(row.get("valid") is not True or row.get("issues") for row in seed_rows):
        raise FreezeError("one or more fixed run seeds failed validation")
    return run_manifest


def _copy_entry(
    source: Path,
    frozen_path: Path,
    *,
    role: str,
) -> dict[str, Any]:
    frozen_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, frozen_path)
    source_hash = sha256_file(source)
    frozen_hash = sha256_file(frozen_path)
    if source_hash != frozen_hash:
        raise FreezeError(f"copy hash mismatch: {source}")
    return {
        "role": role,
        "source_path": _repo_relative(source),
        "frozen_path": frozen_path.relative_to(frozen_path.parents[1]).as_posix(),
        "size_bytes": frozen_path.stat().st_size,
        "sha256": frozen_hash,
    }


def _snapshot_readme() -> str:
    return f"""# Frozen fixed BranchUnit baseline

Baseline: `{BASELINE_ID}`

- prototype: `{PROTOTYPE_ID}`;
- topology: `7 L1 / 12 L2 / 2 L3`;
- seeds: `4101`, `4102`, `4103`;
- strict paired-comparison scope: `{PROTOTYPE_ID}` only;
- generalized five-prototype fixed baseline: not claimed.

The snapshot contains recovery copies of the fixed implementation, its exact
input profile, all v23 output artifacts, and the development protocol. Run the
dynamic module's `freeze_fixed_baseline.py --verify --check-sources --replay`
command to verify integrity and deterministic geometry replay.
"""


def create_snapshot(target: Path = FROZEN_ROOT) -> dict[str, Any]:
    run_manifest = _preflight()
    if target.exists():
        raise FreezeError(f"freeze target already exists and will not be overwritten: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{BASELINE_ID}_", dir=target.parent))
    entries: list[dict[str, Any]] = []
    try:
        for source in SOURCE_SNAPSHOT_FILES:
            entries.append(
                _copy_entry(
                    source,
                    temporary / "source_snapshot" / source.name,
                    role="fixed_source",
                )
            )
        for source in DOCUMENTATION_FILES:
            entries.append(
                _copy_entry(
                    source,
                    temporary / "documentation" / source.name,
                    role="fixed_documentation",
                )
            )
        entries.append(
            _copy_entry(
                PROFILE,
                temporary / "input" / "skeleton_profile.json",
                role="fixed_input",
            )
        )
        for name in OUTPUT_FILES:
            entries.append(
                _copy_entry(
                    SOURCE_RUN / name,
                    temporary / "outputs" / name,
                    role="fixed_output",
                )
            )

        expected_replay = {
            str(row["seed"]): {
                "geometry_hash": str(row["geometry_hash"]),
                "plan_digest": str(row["plan_digest"]),
                "valid": bool(row["valid"]),
                "issues": list(row["issues"]),
            }
            for row in run_manifest["seeds"]
        }
        manifest = {
            "schema": "frozen_fixed_branchunit_baseline_v1",
            "baseline_id": BASELINE_ID,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "prototype_id": PROTOTYPE_ID,
            "plan_id": PLAN_ID,
            "topology": {"L1": 7, "L2": 12, "L3": 2},
            "seeds": list(SEEDS),
            "comparison_contract": {
                "strict_paired_comparison_prototypes": [PROTOTYPE_ID],
                "cross_prototype_fixed_baseline_claimed": False,
                "generalized_fixed_topology_baseline_in_scope": False,
            },
            "recovery_contract": {
                "source_run": _repo_relative(SOURCE_RUN),
                "snapshot_is_overwrite_protected_by_creator": True,
                "current_sources_must_match_at_stage_1_completion": True,
            },
            "environment_at_freeze": {
                "python": sys.version,
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
            },
            "expected_replay": expected_replay,
            "files": sorted(entries, key=lambda row: (row["role"], row["frozen_path"])),
        }
        (temporary / "README.md").write_text(_snapshot_readme(), encoding="utf-8", newline="\n")
        (temporary / "freeze_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest


def verify_snapshot(
    target: Path = FROZEN_ROOT,
    *,
    check_sources: bool = False,
) -> dict[str, Any]:
    manifest_path = target / "freeze_manifest.json"
    manifest = _load_json(manifest_path)
    if manifest.get("schema") != "frozen_fixed_branchunit_baseline_v1":
        raise FreezeError("unexpected freeze manifest schema")
    if manifest.get("baseline_id") != BASELINE_ID:
        raise FreezeError("unexpected baseline id")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise FreezeError("freeze manifest has no file inventory")

    checked = 0
    source_checked = 0
    for row in entries:
        frozen = target / str(row["frozen_path"])
        if not frozen.is_file():
            raise FreezeError(f"frozen file missing: {frozen}")
        if frozen.stat().st_size != int(row["size_bytes"]):
            raise FreezeError(f"frozen file size changed: {frozen}")
        if sha256_file(frozen) != row["sha256"]:
            raise FreezeError(f"frozen file hash changed: {frozen}")
        checked += 1
        if check_sources:
            source = REPO_ROOT / str(row["source_path"])
            if not source.is_file():
                raise FreezeError(f"current fixed source missing: {source}")
            if sha256_file(source) != row["sha256"]:
                raise FreezeError(f"current fixed source diverged from freeze: {source}")
            source_checked += 1
    return {
        "baseline_id": BASELINE_ID,
        "snapshot_verified": True,
        "files_checked": checked,
        "current_sources_checked": source_checked,
    }


def repair_manifest_paths(target: Path = FROZEN_ROOT) -> dict[str, Any]:
    """Repair the one known creator bug that persisted its temporary directory."""

    manifest_path = target / "freeze_manifest.json"
    manifest = _load_json(manifest_path)
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise FreezeError("freeze manifest has no file inventory")
    repaired = 0
    for row in entries:
        raw = PurePosixPath(str(row["frozen_path"]))
        parts = raw.parts
        if parts and parts[0].startswith(f".{BASELINE_ID}_"):
            if len(parts) < 2:
                raise FreezeError(f"invalid temporary frozen path: {raw}")
            raw = PurePosixPath(*parts[1:])
            row["frozen_path"] = raw.as_posix()
            repaired += 1
        if raw.is_absolute() or ".." in raw.parts:
            raise FreezeError(f"unsafe frozen path in manifest: {raw}")
        frozen = target / raw.as_posix()
        if (
            not frozen.is_file()
            or frozen.stat().st_size != int(row["size_bytes"])
            or sha256_file(frozen) != row["sha256"]
        ):
            raise FreezeError(f"cannot prove repaired frozen path: {frozen}")
    if repaired:
        temporary = target / ".freeze_manifest.repair.tmp"
        if temporary.exists():
            raise FreezeError(f"repair temporary file already exists: {temporary}")
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, manifest_path)
    return {
        "baseline_id": BASELINE_ID,
        "manifest_paths_repaired": repaired,
    }


def replay_snapshot(target: Path = FROZEN_ROOT) -> dict[str, Any]:
    manifest = _load_json(target / "freeze_manifest.json")
    source_dir = target / "source_snapshot"
    profile = target / "input" / "skeleton_profile.json"
    replay_script = r"""
import json
import sys
from pathlib import Path

source_dir = Path(sys.argv[1])
profile_path = Path(sys.argv[2])
sys.path.insert(0, str(source_dir))
import whole_local_branch as core

profile = json.loads(profile_path.read_text(encoding="utf-8"))
p0 = core.strip_profile(profile)
rows = {}
for seed in core.DEV_SEEDS:
    result = core.build_j0a(p0, seed)
    validation = core.validate_result(p0, result)
    rows[str(seed)] = {
        "geometry_hash": result.geometry_hash,
        "plan_digest": result.plan.digest,
        "valid": validation["valid"],
        "issues": validation["issues"],
    }
print(json.dumps(rows, sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", replay_script, str(source_dir), str(profile)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise FreezeError(f"frozen replay failed: {completed.stderr.strip()}")
    try:
        actual = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise FreezeError(f"frozen replay returned invalid JSON: {completed.stdout}") from exc
    expected = manifest.get("expected_replay")
    if actual != expected:
        raise FreezeError(f"frozen replay mismatch: expected={expected}, actual={actual}")
    return {
        "baseline_id": BASELINE_ID,
        "replay_verified": True,
        "seeds": list(SEEDS),
        "expected_replay": actual,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true", help="create the recovery snapshot once")
    parser.add_argument("--verify", action="store_true", help="verify the frozen file inventory")
    parser.add_argument("--check-sources", action="store_true", help="also compare current fixed sources")
    parser.add_argument("--replay", action="store_true", help="replay frozen geometry and compare hashes")
    parser.add_argument(
        "--repair-manifest",
        action="store_true",
        help="repair the known temporary-directory prefix from an early stage-0 snapshot",
    )
    parser.add_argument("--target", type=Path, default=FROZEN_ROOT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.create and not args.verify and not args.replay and not args.repair_manifest:
        args.verify = True
    results: dict[str, Any] = {}
    if args.create:
        results["create"] = create_snapshot(args.target)
    if args.repair_manifest:
        results["repair_manifest"] = repair_manifest_paths(args.target)
    if args.verify:
        results["verify"] = verify_snapshot(args.target, check_sources=args.check_sources)
    if args.replay:
        results["replay"] = replay_snapshot(args.target)
    print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FreezeError as exc:
        raise SystemExit(f"fixed baseline freeze error: {exc}") from exc
