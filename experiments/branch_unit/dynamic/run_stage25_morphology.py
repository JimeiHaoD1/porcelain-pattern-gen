#!/usr/bin/env python3
"""Materialize stage-2.5 morphology contracts and visual review plates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from branch_morphology_spec import (
    CONTRACT_SCHEMA,
    PROFILE_SCHEMA,
    load_morphology_contract,
    materialize_branch_morphology_spec,
)
from render_branch_morphology import render_contact_sheet, render_png, render_svg


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_STAGE2_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
)
DEFAULT_SOURCE_IMAGE_ROOT = (
    REPO_ROOT / "artifacts" / "analysis" / "prototype_source_images"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage25_morphology_v1"
)
CONTRACT_PATH = DYNAMIC_DIR / "MORPHOLOGY_CONTRACT.json"
IMPLEMENTATION_CONTRACT_PATH = DYNAMIC_DIR / "IMPLEMENTATION_CONTRACT.json"
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)


class Stage25Error(RuntimeError):
    """Raised when the complete morphology review package cannot be produced."""


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
        raise Stage25Error(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage25Error(f"JSON root is not an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _verify_stage2(
    stage2_root: Path,
) -> tuple[dict[str, Any], dict[str, tuple[dict[str, Any], Path]]]:
    manifest_path = stage2_root / "manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != "dynamic_branch_stage2_analysis_manifest_v1":
        raise Stage25Error("stage 2 manifest schema mismatch")
    if tuple(manifest.get("prototype_ids", [])) != PROTOTYPE_IDS:
        raise Stage25Error("stage 2 prototype order mismatch")
    rows = manifest.get("profiles")
    if not isinstance(rows, list) or len(rows) != len(PROTOTYPE_IDS):
        raise Stage25Error("stage 2 profile inventory is incomplete")

    by_id: dict[str, tuple[dict[str, Any], Path]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise Stage25Error("stage 2 profile row is invalid")
        prototype_id = str(row.get("prototype_id", ""))
        if prototype_id in by_id or prototype_id not in PROTOTYPE_IDS:
            raise Stage25Error(f"stage 2 profile id is invalid: {prototype_id}")
        relative = Path(str(row.get("prototype_analysis_path", "")))
        analysis_path = (stage2_root / relative).resolve()
        if stage2_root.resolve() not in analysis_path.parents:
            raise Stage25Error(f"stage 2 analysis path escapes root: {relative}")
        if analysis_path.parent.name != prototype_id:
            raise Stage25Error(f"stage 2 analysis path/id mismatch: {prototype_id}")
        if not analysis_path.is_file():
            raise Stage25Error(f"stage 2 analysis is missing: {analysis_path}")
        if _sha256(analysis_path) != row.get("prototype_analysis_sha256"):
            raise Stage25Error(f"stage 2 analysis hash mismatch: {prototype_id}")
        analysis = _read_json(analysis_path)
        if analysis.get("prototype_id") != prototype_id:
            raise Stage25Error(f"stage 2 analysis content/id mismatch: {prototype_id}")
        if analysis.get("analysis_core_digest") != row.get("analysis_core_digest"):
            raise Stage25Error(f"stage 2 analysis core digest mismatch: {prototype_id}")
        by_id[prototype_id] = (analysis, analysis_path)
    if tuple(by_id) != PROTOTYPE_IDS:
        raise Stage25Error("stage 2 profile rows are not in canonical order")
    return manifest, by_id


def run(
    stage2_root: Path = DEFAULT_STAGE2_ROOT,
    output: Path = DEFAULT_OUTPUT,
    source_image_root: Path = DEFAULT_SOURCE_IMAGE_ROOT,
    morphology_contract_path: Path = CONTRACT_PATH,
) -> dict[str, Any]:
    """Create all five review packages atomically and stop before stage 3."""

    if output.exists():
        raise Stage25Error(
            f"stage 2.5 output already exists and will not be overwritten: {output}"
        )
    implementation_contract = _read_json(IMPLEMENTATION_CONTRACT_PATH)
    if implementation_contract.get("schema") != "dynamic_branch_implementation_contract_v1":
        raise Stage25Error("implementation contract schema mismatch")
    if tuple(implementation_contract["visual_acceptance"]["prototype_ids"]) != PROTOTYPE_IDS:
        raise Stage25Error("implementation contract prototype order mismatch")
    raw_contract = _read_json(morphology_contract_path)
    try:
        morphology_contract = load_morphology_contract(
            raw_contract,
            expected_prototype_ids=PROTOTYPE_IDS,
        )
    except ValueError as exc:
        raise Stage25Error(f"morphology contract is invalid: {exc}") from exc
    if morphology_contract["schema"] != CONTRACT_SCHEMA:
        raise Stage25Error("morphology contract schema mismatch")
    stage2_manifest, stage2_cases = _verify_stage2(stage2_root)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".dynamic_branch_stage25_", dir=output.parent)
    )
    rows: list[dict[str, Any]] = []
    png_paths: list[Path] = []
    try:
        for prototype_id in PROTOTYPE_IDS:
            analysis, analysis_path = stage2_cases[prototype_id]
            source_image_path = source_image_root / f"{prototype_id}.source.png"
            if not source_image_path.is_file():
                raise Stage25Error(f"source reference image is missing: {source_image_path}")
            spec = materialize_branch_morphology_spec(analysis, morphology_contract)
            profile = spec.as_dict()
            if profile["review"]["status"] != "morphology_pending_review":
                raise Stage25Error(f"morphology unexpectedly bypassed review: {prototype_id}")

            case_dir = temporary / prototype_id
            case_dir.mkdir(parents=True)
            profile_path = case_dir / "morphology_profile.json"
            svg_path = case_dir / "morphology_overlay.svg"
            png_path = case_dir / "morphology_overlay.png"
            review_path = case_dir / "morphology_review.json"
            copied_source_path = case_dir / "source_reference.png"
            shutil.copy2(source_image_path, copied_source_path)
            _write_json(profile_path, profile)
            render_svg(analysis, profile, svg_path)
            render_png(analysis, profile, copied_source_path, png_path)
            _write_json(
                review_path,
                {
                    "schema": "dynamic_branch_morphology_review_v1",
                    "prototype_id": prototype_id,
                    "morphology_digest": profile["morphology_digest"],
                    "source_stage2_analysis_digest": analysis["analysis_digest"],
                    "status": "morphology_pending_review",
                    "visual_gate_required": True,
                    "criteria": profile["review"]["criteria"],
                    "reviewer": None,
                    "reviewed_at": None,
                    "notes": [],
                    "stage_3_unlocked": False,
                },
            )
            relation = profile["classification"]["flower_branch_relation"]
            rows.append(
                {
                    "prototype_id": prototype_id,
                    "family_id": relation["family_id"],
                    "family_label_zh": relation["label_zh"],
                    "morphology_digest": profile["morphology_digest"],
                    "source_stage2_analysis_path": analysis_path.relative_to(
                        REPO_ROOT
                    ).as_posix(),
                    "source_stage2_analysis_digest": analysis["analysis_digest"],
                    "morphology_profile_path": f"{prototype_id}/morphology_profile.json",
                    "morphology_profile_sha256": _sha256(profile_path),
                    "morphology_svg_path": f"{prototype_id}/morphology_overlay.svg",
                    "morphology_svg_sha256": _sha256(svg_path),
                    "morphology_png_path": f"{prototype_id}/morphology_overlay.png",
                    "morphology_png_sha256": _sha256(png_path),
                    "morphology_review_path": f"{prototype_id}/morphology_review.json",
                    "morphology_review_sha256": _sha256(review_path),
                    "source_reference_path": f"{prototype_id}/source_reference.png",
                    "source_reference_sha256": _sha256(copied_source_path),
                    "source_reference_original": source_image_path.relative_to(
                        WORKSPACE_ROOT
                    ).as_posix(),
                    "review_status": "morphology_pending_review",
                }
            )
            png_paths.append(png_path)

        contact_sheet_path = temporary / "morphology_contact_sheet.png"
        render_contact_sheet(png_paths, contact_sheet_path)
        manifest = {
            "schema": "dynamic_branch_stage25_morphology_manifest_v1",
            "morphology_profile_schema": PROFILE_SCHEMA,
            "prototype_ids": list(PROTOTYPE_IDS),
            "prototype_count": len(rows),
            "stage2_manifest_path": (
                stage2_root.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
                + "/manifest.json"
            ),
            "stage2_manifest_sha256": _sha256(stage2_root / "manifest.json"),
            "implementation_contract": IMPLEMENTATION_CONTRACT_PATH.name,
            "implementation_contract_sha256": _sha256(IMPLEMENTATION_CONTRACT_PATH),
            "morphology_contract": morphology_contract_path.name,
            "morphology_contract_sha256": _sha256(morphology_contract_path),
            "morphology_contract_id": morphology_contract["contract_id"],
            "morphology_spec_code_sha256": _sha256(
                DYNAMIC_DIR / "branch_morphology_spec.py"
            ),
            "renderer_sha256": _sha256(
                DYNAMIC_DIR / "render_branch_morphology.py"
            ),
            "profiles": rows,
            "contact_sheet_path": "morphology_contact_sheet.png",
            "contact_sheet_sha256": _sha256(contact_sheet_path),
            "input_isolation": {
                "strict_p0_modified": False,
                "stage2_analysis_opened": True,
                "source_reference_images_opened": True,
                "legacy_annotation_geometry_opened": False,
                "legacy_node_rule_used_via_curated_contract_only": True,
                "legacy_unit_type_consumed": False,
                "old_branch_geometry_consumed": False,
                "source_counts_are_evidence_priors_not_targets": True,
            },
            "classification_axes": {
                "generation_control": "flower_branch_relation",
                "research_annotation_only": "pattern_skeleton_class",
            },
            "review_gate": {
                "status": "morphology_pending_review",
                "all_five_visual_reviews_required": True,
                "stage_3_unlocked": False,
            },
            "stage_scope": {
                "completed": [
                    "three_family_flower_branch_morphology_contract",
                    "five_prototype_instance_priors",
                    "source_evidence_traceability",
                    "non_selecting_semantic_growth_guides",
                    "morphology_svg_png_review_plates",
                ],
                "not_started": [
                    "candidate_slots",
                    "dynamic_branch_plan",
                    "curve_compilation",
                    "candidate_validation",
                    "editor_v2",
                ],
            },
            "stage2_scope_preserved": stage2_manifest["stage_scope"],
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2-root", type=Path, default=DEFAULT_STAGE2_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--source-image-root",
        type=Path,
        default=DEFAULT_SOURCE_IMAGE_ROOT,
    )
    parser.add_argument(
        "--morphology-contract",
        type=Path,
        default=CONTRACT_PATH,
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = run(
        args.stage2_root,
        args.output,
        args.source_image_root,
        args.morphology_contract,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage25Error as exc:
        raise SystemExit(f"stage 2.5 morphology error: {exc}") from exc
