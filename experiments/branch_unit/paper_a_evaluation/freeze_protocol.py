#!/usr/bin/env python3
"""Freeze the Paper A Chapter 4 case matrices and metric parameters."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "protocol"
DEFAULT_REFERENCE_DIR = REPO_ROOT / "data" / "annotation"

PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
VARIANT_IDS = ("expanded", "compact", "swept")
DENSITY_LEVELS = ("simple", "medium", "rich")
MATRIX_A_SEEDS = tuple(range(200000, 200010))
MATRIX_B_SEEDS = tuple(range(200000, 200010))
MATRIX_C_SEED_START = 100000
MATRIX_C_REPLICATES_PER_CELL = 2

CASE_FIELDS = (
    "case_id",
    "matrix_id",
    "rq_use",
    "prototype_id",
    "backbone_variant",
    "density_level",
    "replicate",
    "production_seed",
    "backbone_seed",
    "flower_seed",
    "branch_seed",
    "unit_seed",
    "backbone_seed_source",
    "flower_seed_source",
    "branch_seed_source",
    "unit_seed_source",
    "allocation_rule",
)


class ProtocolFreezeError(RuntimeError):
    """The frozen protocol cannot be created without ambiguity."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProtocolFreezeError(f"JSON root must be an object: {path}")
    return value


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]], fields: Sequence[str]) -> None:
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _seed_domains(production_seed: int) -> dict[str, int]:
    if str(DYNAMIC_DIR) not in sys.path:
        sys.path.insert(0, str(DYNAMIC_DIR))
    from backbone_variation_v1 import split_generation_seeds

    return split_generation_seeds(production_seed)


def _production_cell(prototype_id: str, production_seed: int) -> tuple[str, str]:
    if str(DYNAMIC_DIR) not in sys.path:
        sys.path.insert(0, str(DYNAMIC_DIR))
    from run_batch_generation import production_cell

    return production_cell(prototype_id, production_seed)


def _case_row(
    *,
    case_id: str,
    matrix_id: str,
    rq_use: str,
    prototype_id: str,
    backbone_variant: str,
    density_level: str,
    replicate: int,
    production_seed: int,
    domains: Mapping[str, int],
    sources: Mapping[str, int],
    allocation_rule: str,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "matrix_id": matrix_id,
        "rq_use": rq_use,
        "prototype_id": prototype_id,
        "backbone_variant": backbone_variant,
        "density_level": density_level,
        "replicate": replicate,
        "production_seed": production_seed,
        "backbone_seed": domains["backbone_seed"],
        "flower_seed": domains["flower_seed"],
        "branch_seed": domains["branch_seed"],
        "unit_seed": domains["unit_seed"],
        "backbone_seed_source": sources["backbone_seed"],
        "flower_seed_source": sources["flower_seed"],
        "branch_seed_source": sources["branch_seed"],
        "unit_seed_source": sources["unit_seed"],
        "allocation_rule": allocation_rule,
    }


def build_matrix_a() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for prototype_id in PROTOTYPE_IDS:
        for replicate, production_seed in enumerate(MATRIX_A_SEEDS, start=1):
            domains = _seed_domains(production_seed)
            sources = {name: production_seed for name in domains}
            for variant in VARIANT_IDS:
                for density in DENSITY_LEVELS:
                    rows.append(
                        _case_row(
                            case_id=f"A{len(rows) + 1:03d}",
                            matrix_id="A",
                            rq_use="RQ1;RQ3_BACKBONE;RQ3_DENSITY;RQ4_GENERATED",
                            prototype_id=prototype_id,
                            backbone_variant=variant,
                            density_level=density,
                            replicate=replicate,
                            production_seed=production_seed,
                            domains=domains,
                            sources=sources,
                            allocation_rule=(
                                "production seeds 200000-200009; explicit variant and "
                                "density overrides; four domain seeds paired within replicate"
                            ),
                        )
                    )
    return rows


def build_matrix_b() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    fixed = _seed_domains(MATRIX_B_SEEDS[0])
    for prototype_id in PROTOTYPE_IDS:
        for replicate, variable_seed in enumerate(MATRIX_B_SEEDS, start=1):
            variable = _seed_domains(variable_seed)
            domains = {
                "backbone_seed": fixed["backbone_seed"],
                "flower_seed": fixed["flower_seed"],
                "branch_seed": variable["branch_seed"],
                "unit_seed": variable["unit_seed"],
            }
            sources = {
                "backbone_seed": MATRIX_B_SEEDS[0],
                "flower_seed": MATRIX_B_SEEDS[0],
                "branch_seed": variable_seed,
                "unit_seed": variable_seed,
            }
            rows.append(
                _case_row(
                    case_id=f"B{len(rows) + 1:03d}",
                    matrix_id="B",
                    rq_use="RQ3_SEED",
                    prototype_id=prototype_id,
                    backbone_variant="expanded",
                    density_level="medium",
                    replicate=replicate,
                    production_seed=MATRIX_B_SEEDS[0],
                    domains=domains,
                    sources=sources,
                    allocation_rule=(
                        "backbone and flower domains fixed from seed 200000; branch and "
                        "unit domains paired from seeds 200000-200009"
                    ),
                )
            )
    return rows


def _matrix_c_seeds(prototype_id: str) -> dict[tuple[str, str], list[int]]:
    cells = [(variant, density) for variant in VARIANT_IDS for density in DENSITY_LEVELS]
    chosen = {cell: [] for cell in cells}
    seed = MATRIX_C_SEED_START
    while any(len(values) < MATRIX_C_REPLICATES_PER_CELL for values in chosen.values()):
        cell = _production_cell(prototype_id, seed)
        if len(chosen[cell]) < MATRIX_C_REPLICATES_PER_CELL:
            chosen[cell].append(seed)
        seed += 1
        if seed - MATRIX_C_SEED_START > 1_000_000:
            raise ProtocolFreezeError(f"cannot fill Matrix-C cells for {prototype_id}")
    return chosen


def build_matrix_c() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for prototype_id in PROTOTYPE_IDS:
        chosen = _matrix_c_seeds(prototype_id)
        for variant in VARIANT_IDS:
            for density in DENSITY_LEVELS:
                for replicate, production_seed in enumerate(chosen[(variant, density)], start=1):
                    domains = _seed_domains(production_seed)
                    sources = {name: production_seed for name in domains}
                    rows.append(
                        _case_row(
                            case_id=f"C{len(rows) + 1:03d}",
                            matrix_id="C",
                            rq_use="RQ2;RQ4_HUMAN_POOL",
                            prototype_id=prototype_id,
                            backbone_variant=variant,
                            density_level=density,
                            replicate=replicate,
                            production_seed=production_seed,
                            domains=domains,
                            sources=sources,
                            allocation_rule=(
                                "first two production seeds at or after 100000 naturally "
                                "assigned to each prototype x variant x density cell"
                            ),
                        )
                    )
    return rows


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def build_reference_manifest(reference_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for svg_path in sorted(reference_dir.glob("*.svg"), key=lambda item: item.name.lower()):
        root = ET.parse(svg_path).getroot()
        elements = list(root.iter())
        paths = [item for item in elements if _local_name(item.tag) == "path"]
        images = [item for item in elements if _local_name(item.tag) == "image"]
        rows.append(
            {
                "reference_id": f"REAL_{len(rows) + 1:02d}",
                "source_file": str(svg_path.resolve()),
                "width": root.attrib.get("width", ""),
                "height": root.attrib.get("height", ""),
                "view_box": root.attrib.get("viewBox", ""),
                "total_path_count": len(paths),
                "embedded_image_count": len(images),
                "data_role_count": sum("data-role" in item.attrib for item in paths),
                "data_parent_count": sum(
                    ("data-parent-id" in item.attrib) or ("data-parent-curve-id" in item.attrib)
                    for item in paths
                ),
                "used_for_rule_or_parameter_calibration": "UNKNOWN_REQUIRES_AUDIT",
                "role_review_status": "PENDING_MANUAL_ROLE_REVIEW",
                "parent_relation_status": "PENDING_PARENT_INFERENCE",
                "evaluation_eligible": "PENDING",
                "exclusion_reason": "",
            }
        )
    if not rows:
        raise ProtocolFreezeError(f"no SVG references found in {reference_dir}")
    return rows


def build_metric_parameters() -> list[dict[str, object]]:
    stage3 = _read_json(DYNAMIC_DIR / "STAGE3B_L1_FLOW_CONTRACT_V3.json")
    stage4 = _read_json(DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json")
    stage5 = _read_json(DYNAMIC_DIR / "STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json")
    editor = _read_json(DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json")
    rows: list[dict[str, object]] = []

    def add(parameter: str, value: object, unit: str, source: str, notes: str) -> None:
        rows.append(
            {
                "parameter": parameter,
                "value": value,
                "unit": unit,
                "source": source,
                "notes": notes,
            }
        )

    add("geometry_epsilon", 1e-10, "normalized coordinate", "active geometry code", "orientation and intersection epsilon")
    add("attachment_tolerance", 2e-6, "normalized coordinate", "independent evaluator policy", "legal shared-root attachment window")
    add("parent_junction_exclusion_tolerance", 1e-7, "normalized coordinate", "branch_unit_grammar_v1.py", "ignore only curve intersections whose two segments both contain the legal parent-child junction")
    add("l1_backbone_root_exclusion_min_points", 4, "polyline points", "global_l1_flow.py", "minimum L1 prefix excluded from non-root backbone evaluation")
    add("l1_backbone_root_exclusion_fraction", 0.16, "polyline fraction", "global_l1_flow.py", "L1 prefix excluded from non-root backbone evaluation")
    add("l2_backbone_contact_tolerance", 0.001, "normalized coordinate", "branch_unit_grammar_v1.py", "descendant-to-backbone contact threshold")
    add("ordinary_flower_root_exclusion_points", 3, "polyline points", "global_l1_flow.py", "upstream L1 flower-reserve root exclusion")
    add("flower_region_intrusion_epsilon", 2e-6, "ellipse equation", "flower_mounting_v1.py", "inside reserve when value < 1-epsilon")
    add("parallel_resample_count", 48, "samples per curve", "independent evaluator policy", "co-travel measurement only")
    add("backbone_seam_position_tolerance", 1e-3, "normalized coordinate", "run_stage5f_full_integration.py", "period position closure")
    add("backbone_seam_tangent_dot_min", 0.999, "cosine", "run_stage5f_full_integration.py", "period tangent continuity")
    add("occupancy_radius", stage4["geometry"]["occupancy_radius"], "normalized coordinate", "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json", "per-curve occupancy radius")
    add("l2_mount_fraction_min", stage4["geometry"]["mount_fraction_range"][0], "parent arc fraction", "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json", "legal child mount window")
    add("l2_mount_fraction_max", stage4["geometry"]["mount_fraction_range"][1], "parent arc fraction", "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json", "legal child mount window")
    add("minimum_sibling_mount_separation", stage4["geometry"]["minimum_sibling_mount_separation"], "parent arc fraction", "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json", "paired child mount exclusion")
    add("repeat_shifts_checked", ";".join(str(value) for value in stage5["hard_constraints"]["repeat_shifts_checked"]), "period widths", "STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json", "crossing and clearance checks")
    add("stage5_search_node_limit", stage5["bounded_search"]["node_limit"], "nodes", "STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json", "bounded joint search budget")

    density = stage3["planning_policy"]["soft_density_objective"]
    for level, value in density["target_quantiles"].items():
        add(f"density_target_quantile.{level}", value, "quantile", "STAGE3B_L1_FLOW_CONTRACT_V3.json", "soft resource target")
    for component, value in density["resource_component_weights"].items():
        add(f"density_resource_weight.{component}", value, "weight", "STAGE3B_L1_FLOW_CONTRACT_V3.json", "soft density resource")
    add("density_fit_bandwidth_fraction", density["fit_bandwidth_fraction"], "fraction", "STAGE3B_L1_FLOW_CONTRACT_V3.json", "Gaussian density fit")
    add("density_minimum_fit_bandwidth", density["minimum_fit_bandwidth"], "normalized resource", "STAGE3B_L1_FLOW_CONTRACT_V3.json", "Gaussian density fit floor")

    occupancy_diameter = 2.0 * float(stage4["geometry"]["occupancy_radius"])
    profile_by_prototype: dict[str, str] = {}
    strategy = _read_json(DYNAMIC_DIR / "PROTOTYPE_STRATEGY_REGISTRY_V1.json")
    for prototype_id, prototype in strategy.get("strategies", {}).items():
        profile_by_prototype[str(prototype_id)] = str(
            prototype["branchunit_profile"]["editor_l2_profile_key"]
        )
    for prototype_id in PROTOTYPE_IDS:
        profile_key = profile_by_prototype.get(prototype_id, prototype_id)
        profile = editor["profiles"].get(profile_key)
        if not isinstance(profile, dict):
            raise ProtocolFreezeError(f"missing editor L2 profile for {prototype_id}: {profile_key}")
        q10 = float(profile["nonparent_curve_clearance_unit_ratio"]["q10"])
        add(
            f"minimum_full_unit_clearance.{prototype_id}",
            max(occupancy_diameter, q10),
            "normalized coordinate",
            "Stage4 occupancy diameter and EDITOR_L2_PLACEMENT_PRIOR_V1 q10",
            f"max({occupancy_diameter}, {q10}) using profile {profile_key}",
        )
    return rows


def build_protocol(case_rows: Sequence[Mapping[str, object]], reference_rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    matrix_counts = {
        matrix_id: sum(row["matrix_id"] == matrix_id for row in case_rows)
        for matrix_id in ("A", "B", "C")
    }
    return {
        "schema": "paper_a_chapter4_protocol_v1",
        "status": "FROZEN_INPUTS_PENDING_EXECUTION",
        "production_code_modified": False,
        "formal_method": {
            "name": "Ours",
            "stage3b_contract_id": "soft_density_global_l1_flow_v3",
            "stage4_contract_id": "edit_feedback_sparse_branchunit_grammar_v2",
            "stage5_contract_id": "stage5e_joint_sparse_local_l2_selection_v2",
        },
        "baselines": {
            "IndependentCurve": "same V3 ordinary candidate inventory; rank individual scores and take Ours L1 count; L1-only",
            "FixedSlot": "legacy ordinary fixed slots only; current supports frozen; match Ours L1 count; no repair or resample",
            "LocalGreedy": "same Stage3B plan and Stage4 inventory as Ours; L1-first irreversible sequential L2 upgrades",
        },
        "matrices": matrix_counts,
        "planned_case_rows": len(case_rows),
        "reference_svg_count": len(reference_rows),
        "stimulus_seed": 20260822,
        "failure_policy": "keep every planned case in the denominator; do not replace seeds",
        "visual_policy": "mechanical checks do not constitute user visual approval",
    }


def freeze(output_dir: Path, reference_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = (
        output_dir / "frozen_cases.csv",
        output_dir / "reference_manifest.csv",
        output_dir / "metric_parameters.csv",
        output_dir / "protocol.json",
    )
    existing = [path for path in targets if path.exists()]
    if existing:
        raise ProtocolFreezeError(
            "refusing to overwrite frozen protocol files: " + ", ".join(str(path) for path in existing)
        )

    case_rows = build_matrix_a() + build_matrix_b() + build_matrix_c()
    if len(case_rows) != 590 or len({row["case_id"] for row in case_rows}) != 590:
        raise ProtocolFreezeError("frozen case table must contain 590 unique case IDs")
    reference_rows = build_reference_manifest(reference_dir)
    metric_rows = build_metric_parameters()
    protocol = build_protocol(case_rows, reference_rows)

    _write_csv(targets[0], case_rows, CASE_FIELDS)
    _write_csv(targets[1], reference_rows, tuple(reference_rows[0]))
    _write_csv(targets[2], metric_rows, ("parameter", "value", "unit", "source", "notes"))
    _write_json(targets[3], protocol)
    return protocol


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    args = parser.parse_args()
    protocol = freeze(args.output_dir.resolve(), args.reference_dir.resolve())
    print(json.dumps(protocol, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
