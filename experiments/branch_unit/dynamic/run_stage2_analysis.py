#!/usr/bin/env python3
"""Materialize planner-free PrototypeAnalysis for the five StrictP0 inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from prototype_analysis import SCHEMA, analysis_summary, analyze_prototype
from render_prototype_analysis import render_contact_sheet, render_png, render_svg
from strict_p0_v2 import (
    IGNORED_LEGACY_FIELDS,
    StrictP0V2,
    load_materialized_strict_p0_v2,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
DEFAULT_STAGE1_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage1_inputs_v1"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
)
CONTRACT_PATH = DYNAMIC_DIR / "IMPLEMENTATION_CONTRACT.json"
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)


class Stage2Error(RuntimeError):
    """Raised when a complete, verified analysis run cannot be produced."""


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
        raise Stage2Error(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage2Error(f"JSON root is not an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _verify_stage1(stage1_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest_path = stage1_root / "manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != "dynamic_branch_stage1_input_manifest_v1":
        raise Stage2Error("stage 1 manifest schema mismatch")
    if tuple(manifest.get("prototype_ids", [])) != PROTOTYPE_IDS:
        raise Stage2Error("stage 1 prototype order mismatch")
    rows = manifest.get("profiles")
    if not isinstance(rows, list) or len(rows) != len(PROTOTYPE_IDS):
        raise Stage2Error("stage 1 profile inventory is incomplete")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise Stage2Error("stage 1 profile row is invalid")
        prototype_id = str(row.get("prototype_id", ""))
        if prototype_id in by_id or prototype_id not in PROTOTYPE_IDS:
            raise Stage2Error(f"stage 1 profile id is invalid: {prototype_id}")
        by_id[prototype_id] = row
    if tuple(by_id) != PROTOTYPE_IDS:
        raise Stage2Error("stage 1 profile rows are not in canonical order")
    return manifest, by_id


def _load_case(
    stage1_root: Path,
    prototype_id: str,
    row: dict[str, Any],
) -> tuple[StrictP0V2, Path]:
    relative = Path(str(row.get("strict_p0_path", "")))
    strict_path = (stage1_root / relative).resolve()
    if stage1_root.resolve() not in strict_path.parents:
        raise Stage2Error(f"StrictP0 path escapes stage 1 root: {relative}")
    if strict_path.parent.name != prototype_id:
        raise Stage2Error(f"StrictP0 path/id mismatch for {prototype_id}")
    if not strict_path.is_file():
        raise Stage2Error(f"StrictP0 artifact is missing: {strict_path}")
    if _sha256(strict_path) != row.get("strict_p0_sha256"):
        raise Stage2Error(f"StrictP0 file hash mismatch: {prototype_id}")
    payload = _read_json(strict_path)
    forbidden = sorted(set(payload).intersection(IGNORED_LEGACY_FIELDS))
    if forbidden:
        raise Stage2Error(
            f"stage 1 StrictP0 contains forbidden legacy roots for {prototype_id}: {forbidden}"
        )
    strict = load_materialized_strict_p0_v2(payload)
    if strict.prototype_id != prototype_id:
        raise Stage2Error(f"StrictP0 content/id mismatch for {prototype_id}")
    if strict.digest != row.get("strict_p0_digest"):
        raise Stage2Error(f"StrictP0 canonical digest mismatch: {prototype_id}")
    return strict, strict_path


def run(
    stage1_root: Path = DEFAULT_STAGE1_ROOT,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Run all five analyses atomically and stop before stage 3."""

    if output.exists():
        raise Stage2Error(
            f"stage 2 output already exists and will not be overwritten: {output}"
        )
    contract = _read_json(CONTRACT_PATH)
    if contract.get("schema") != "dynamic_branch_implementation_contract_v1":
        raise Stage2Error("implementation contract schema mismatch")
    if tuple(contract["visual_acceptance"]["prototype_ids"]) != PROTOTYPE_IDS:
        raise Stage2Error("implementation contract prototype order mismatch")
    stage1_manifest, stage1_rows = _verify_stage1(stage1_root)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".dynamic_branch_stage2_", dir=output.parent)
    )
    rows: list[dict[str, Any]] = []
    png_paths: list[Path] = []
    try:
        for prototype_id in PROTOTYPE_IDS:
            strict, strict_path = _load_case(
                stage1_root,
                prototype_id,
                stage1_rows[prototype_id],
            )
            analysis = analyze_prototype(strict)
            if analysis["review"]["status"] != "analysis_pending_review":
                raise Stage2Error(f"analysis unexpectedly bypassed review: {prototype_id}")
            case_dir = temporary / prototype_id
            case_dir.mkdir(parents=True)
            analysis_path = case_dir / "prototype_analysis.json"
            svg_path = case_dir / "prototype_analysis.svg"
            png_path = case_dir / "prototype_analysis.png"
            review_path = case_dir / "analysis_review.json"
            _write_json(analysis_path, analysis)
            render_svg(analysis, svg_path)
            render_png(analysis, png_path)
            _write_json(
                review_path,
                {
                    "schema": "dynamic_branch_analysis_review_v1",
                    "prototype_id": prototype_id,
                    "analysis_digest": analysis["analysis_digest"],
                    "status": "analysis_pending_review",
                    "visual_gate_required": True,
                    "criteria": analysis["review"]["criteria"],
                    "reviewer": None,
                    "reviewed_at": None,
                    "notes": [],
                    "stage_3_unlocked": False,
                },
            )
            summary = analysis_summary(analysis)
            rows.append(
                {
                    **summary,
                    "strict_p0_path": strict_path.relative_to(REPO_ROOT).as_posix(),
                    "strict_p0_digest": strict.digest,
                    "prototype_analysis_path": (
                        f"{prototype_id}/prototype_analysis.json"
                    ),
                    "prototype_analysis_sha256": _sha256(analysis_path),
                    "analysis_svg_path": f"{prototype_id}/prototype_analysis.svg",
                    "analysis_svg_sha256": _sha256(svg_path),
                    "analysis_png_path": f"{prototype_id}/prototype_analysis.png",
                    "analysis_png_sha256": _sha256(png_path),
                    "analysis_review_path": f"{prototype_id}/analysis_review.json",
                    "analysis_review_sha256": _sha256(review_path),
                }
            )
            png_paths.append(png_path)

        contact_sheet_path = temporary / "prototype_analysis_contact_sheet.png"
        render_contact_sheet(png_paths, contact_sheet_path)
        manifest = {
            "schema": "dynamic_branch_stage2_analysis_manifest_v1",
            "prototype_analysis_schema": SCHEMA,
            "prototype_ids": list(PROTOTYPE_IDS),
            "prototype_count": len(rows),
            "stage1_manifest_path": (
                stage1_root.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
                + "/manifest.json"
            ),
            "stage1_manifest_sha256": _sha256(stage1_root / "manifest.json"),
            "implementation_contract": CONTRACT_PATH.name,
            "implementation_contract_sha256": _sha256(CONTRACT_PATH),
            "analyzer_sha256": _sha256(DYNAMIC_DIR / "prototype_analysis.py"),
            "renderer_sha256": _sha256(
                DYNAMIC_DIR / "render_prototype_analysis.py"
            ),
            "strict_p0_loader_sha256": _sha256(DYNAMIC_DIR / "strict_p0_v2.py"),
            "input_isolation": {
                "input_surface": "materialized_strict_p0_v2_only",
                "source_profiles_opened_by_stage2": False,
                "legacy_branch_roots_allowed": False,
                "forbidden_legacy_roots": list(IGNORED_LEGACY_FIELDS),
                "prototype_specific_topology_rules": False,
            },
            "profiles": rows,
            "contact_sheet_path": "prototype_analysis_contact_sheet.png",
            "contact_sheet_sha256": _sha256(contact_sheet_path),
            "review_gate": {
                "status": "analysis_pending_review",
                "all_five_visual_reviews_required": True,
                "stage_3_unlocked": False,
            },
            "stage_scope": {
                "completed": [
                    "prototype_analysis",
                    "backbone_landmarks",
                    "flower_backbone_relations_and_reserves",
                    "two_side_space_probes",
                    "continuous_blank_and_crowded_regions",
                    "candidate_l1_attachment_intervals",
                    "periodic_seam_and_ghost_repeat_analysis",
                    "analysis_svg_png_overlays",
                ],
                "not_started": [
                    "candidate_slots",
                    "dynamic_branch_plan",
                    "curve_compilation",
                    "candidate_validation",
                    "editor_v2",
                ],
            },
            "stage1_scope_preserved": stage1_manifest["stage_scope"],
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-root", type=Path, default=DEFAULT_STAGE1_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = run(args.stage1_root, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage2Error as exc:
        raise SystemExit(f"stage 2 analysis error: {exc}") from exc
