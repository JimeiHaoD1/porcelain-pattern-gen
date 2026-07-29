#!/usr/bin/env python3
"""Materialize StrictP0 v2 inputs for the five preregistered SW prototypes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from strict_p0_v2 import SCHEMA, load_strict_p0_v2


REPO_ROOT = Path(__file__).resolve().parents[3]
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
DEFAULT_INPUT_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "run57_reproduction" / "01_skeleton_analysis"
)
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
CONTRACT_PATH = Path(__file__).with_name("IMPLEMENTATION_CONTRACT.json")


class Stage1Error(RuntimeError):
    """Raised when the complete five-prototype stage cannot be materialized."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage1Error(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage1Error(f"JSON root is not an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run(
    input_root: Path = DEFAULT_INPUT_ROOT,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    if output.exists():
        raise Stage1Error(f"stage 1 output already exists and will not be overwritten: {output}")
    contract = _read_json(CONTRACT_PATH)
    if contract.get("schema") != "dynamic_branch_implementation_contract_v1":
        raise Stage1Error("implementation contract schema mismatch")
    expected_ids = tuple(contract["visual_acceptance"]["prototype_ids"])
    if expected_ids != PROTOTYPE_IDS:
        raise Stage1Error("implementation contract prototype order mismatch")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".dynamic_branch_stage1_", dir=output.parent))
    rows: list[dict[str, Any]] = []
    try:
        for prototype_id in PROTOTYPE_IDS:
            profile_path = input_root / prototype_id / "skeleton_profile.json"
            profile = _read_json(profile_path)
            strict = load_strict_p0_v2(profile)
            if strict.prototype_id != prototype_id:
                raise Stage1Error(
                    f"profile directory/id mismatch: {prototype_id} != {strict.prototype_id}"
                )
            case_dir = temporary / prototype_id
            case_dir.mkdir(parents=True)
            strict_path = case_dir / "strict_p0_v2.json"
            _write_json(strict_path, strict.as_dict())
            rows.append(
                {
                    "prototype_id": prototype_id,
                    "source_profile": profile_path.resolve().relative_to(REPO_ROOT.resolve()).as_posix(),
                    "source_profile_sha256": _sha256(profile_path),
                    "strict_p0_path": f"{prototype_id}/strict_p0_v2.json",
                    "strict_p0_sha256": _sha256(strict_path),
                    "strict_p0_digest": strict.digest,
                    "flower_count": len(strict.flowers),
                    "backbone_sample_count": len(strict.backbone_samples),
                    "structure_protection_zone_count": len(strict.structure_protection_zones),
                    "local_repeat_x_range": list(strict.frame.local_repeat_x_range),
                    "local_canvas_bounds": list(strict.frame.local_canvas_bounds),
                }
            )
        manifest = {
            "schema": "dynamic_branch_stage1_input_manifest_v1",
            "strict_p0_schema": SCHEMA,
            "implementation_contract": CONTRACT_PATH.name,
            "implementation_contract_sha256": _sha256(CONTRACT_PATH),
            "prototype_ids": list(PROTOTYPE_IDS),
            "prototype_count": len(rows),
            "profiles": rows,
            "stage_scope": {
                "completed": [
                    "strict_p0_v2_whitelist",
                    "repeat_local_coordinate_mapping",
                    "five_sw_profile_materialization",
                ],
                "not_started": [
                    "prototype_analysis",
                    "candidate_slots",
                    "dynamic_branch_plan",
                    "curve_compilation",
                    "candidate_validation",
                    "editor_v2",
                ],
            },
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = run(args.input_root, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage1Error as exc:
        raise SystemExit(f"stage 1 input error: {exc}") from exc
