#!/usr/bin/env python3
"""Generate the Stage-5D ordinary-L1 density review through the formal chain."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from branch_unit_grammar_v1 import (
    generate_unit_candidate_inventory,
    validate_unit_candidate_inventory,
)
from prototype_strategy_v1 import (
    load_prototype_strategy_registry,
    resolve_prototype_strategy,
)
from render_global_l1_flow import render_png as render_l1_png
from render_stage5_global_selection import render_global_selection
from run_stage3b_l1_flow import _load_inputs, generate_prototype_case
from stage5_global_unit_selection import (
    build_conflict_graph,
    candidate_pair_crossings,
    candidate_pair_minimum_clearance,
    select_global_units,
    validate_global_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage5d_density_review_v1"
)
STAGE4_CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json"
STAGE5D_CONTRACT_PATH = (
    DYNAMIC_DIR / "STAGE5D_L1_ONLY_SELECTION_CONTRACT_V1.json"
)
EDITOR_L2_PRIOR_PATH = DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json"

PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
DENSITY_LEVELS = ("simple", "medium", "rich")
PRODUCTION_SEED = 4101
BACKBONE_SEED = 1658046696
FLOWER_SEED = 0
FLOWER_RHO = 0.0
BRANCH_SEED = 3594281359
UNIT_SEED = 49789125


class Stage5DDensityReviewError(RuntimeError):
    """The 5D review cannot be produced through the formal chain."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5DDensityReviewError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    path = Path(
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"
    )
    if not path.is_file():
        return ImageFont.load_default()
    return ImageFont.truetype(str(path), size)


def _prototype_label(prototype_id: str) -> str:
    return {
        "proto_sw_1_1": "SW1-1",
        "proto_sw_1_3": "SW1-3",
        "proto_sw_2_3": "SW2-3",
        "proto_sw_3_1": "SW3-1",
        "proto_sw_3_2": "SW3-2",
    }[prototype_id]


def _render_labeled_sheet(
    image_rows: Mapping[str, Sequence[tuple[Path, int]]],
    output: Path,
    *,
    title: str,
) -> None:
    column_labels = ("simple / 简", "medium / 中", "rich / 繁")
    cell_width = 620
    cell_height = 380
    image_label_height = 30
    left_margin = 108
    top_margin = 96
    canvas = Image.new(
        "RGB",
        (
            left_margin + len(column_labels) * cell_width,
            top_margin + len(PROTOTYPE_IDS) * cell_height,
        ),
        "#f1efe9",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 10), title, fill="#17242d", font=_font(25, bold=True))
    for column, label in enumerate(column_labels):
        draw.text(
            (left_margin + column * cell_width + 16, 53),
            label,
            fill="#374750",
            font=_font(18, bold=True),
        )
    for row, prototype_id in enumerate(PROTOTYPE_IDS):
        draw.text(
            (15, top_margin + row * cell_height + 18),
            _prototype_label(prototype_id),
            fill="#17242d",
            font=_font(19, bold=True),
        )
        cells = list(image_rows[prototype_id])
        if len(cells) != len(column_labels):
            raise Stage5DDensityReviewError(
                f"5D sheet row is incomplete: {prototype_id}"
            )
        for column, (path, ordinary_count) in enumerate(cells):
            x0 = left_margin + column * cell_width
            y0 = top_margin + row * cell_height
            draw.rectangle(
                (x0 + 4, y0 + 4, x0 + cell_width - 5, y0 + cell_height - 5),
                outline="#c5cdd2",
                width=2,
            )
            draw.text(
                (x0 + 16, y0 + 9),
                f"ordinary L1 = {ordinary_count}",
                fill="#374750",
                font=_font(16, bold=True),
            )
            with Image.open(path) as source:
                image = source.convert("RGB")
            image.thumbnail(
                (cell_width - 18, cell_height - image_label_height - 18),
                Image.Resampling.LANCZOS,
            )
            x = x0 + (cell_width - image.width) // 2
            image_area_top = y0 + image_label_height
            image_area_height = cell_height - image_label_height
            y = image_area_top + (image_area_height - image.height) // 2
            canvas.paste(image, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def _candidate_pool_basis(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return candidate data independent of which rows the selector annotated."""

    ignored = {
        "selected",
        "selected_l1_id",
        "slot_id",
        "legacy_identity_alias",
    }
    rows: list[dict[str, Any]] = []
    for candidate in inventory["candidates"]:
        rows.append(
            {
                key: value
                for key, value in candidate.items()
                if key not in ignored
            }
        )
    return sorted(rows, key=lambda row: str(row["candidate_id"]))


def _selected_pair_mechanics(
    selection: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
) -> dict[str, Any]:
    """Independently recompute base and periodic selected-curve mechanics."""

    selected = list(selection["selected_candidates"])
    repeat_shifts = [
        float(value) for value in conflict_graph["repeat_shifts_checked"]
    ]
    base_shifts = [value for value in repeat_shifts if abs(value) <= 1e-12]
    periodic_shifts = [value for value in repeat_shifts if abs(value) > 1e-12]
    if not base_shifts or not periodic_shifts:
        raise Stage5DDensityReviewError(
            "5D mechanics require both canonical and periodic repeat shifts"
        )
    required_clearance = float(conflict_graph["minimum_descendant_clearance"])

    base_crossings = 0
    periodic_crossings = 0
    base_clearance_violations = 0
    periodic_clearance_violations = 0
    minimum_base_clearance = float("inf")
    minimum_periodic_clearance = float("inf")
    checked_distinct_pair_count = 0

    for index, first in enumerate(selected):
        for second in selected[index + 1 :]:
            checked_distinct_pair_count += 1
            base_crossings += len(
                candidate_pair_crossings(first, second, base_shifts)
            )
            periodic_crossings += len(
                candidate_pair_crossings(first, second, periodic_shifts)
            )
            base_clearance = candidate_pair_minimum_clearance(
                first,
                second,
                base_shifts,
            )
            periodic_clearance = candidate_pair_minimum_clearance(
                first,
                second,
                periodic_shifts,
            )
            minimum_base_clearance = min(
                minimum_base_clearance,
                base_clearance,
            )
            minimum_periodic_clearance = min(
                minimum_periodic_clearance,
                periodic_clearance,
            )
            if base_clearance < required_clearance - 1e-9:
                base_clearance_violations += 1
            if periodic_clearance < required_clearance - 1e-9:
                periodic_clearance_violations += 1

    for candidate in selected:
        periodic_crossings += len(
            candidate_pair_crossings(candidate, candidate, periodic_shifts)
        )
        periodic_clearance = candidate_pair_minimum_clearance(
            candidate,
            candidate,
            periodic_shifts,
        )
        minimum_periodic_clearance = min(
            minimum_periodic_clearance,
            periodic_clearance,
        )
        if periodic_clearance < required_clearance - 1e-9:
            periodic_clearance_violations += 1

    total_crossings = base_crossings + periodic_crossings
    total_clearance_violations = (
        base_clearance_violations + periodic_clearance_violations
    )
    return {
        "checked_distinct_selected_pair_count": checked_distinct_pair_count,
        "checked_periodic_self_pair_count": len(selected),
        "base_curve_crossing_count": base_crossings,
        "periodic_curve_crossing_count": periodic_crossings,
        "curve_crossing_count": total_crossings,
        "base_near_clearance_violation_count": base_clearance_violations,
        "periodic_near_clearance_violation_count": (
            periodic_clearance_violations
        ),
        "near_clearance_violation_count": total_clearance_violations,
        "minimum_base_selected_clearance": (
            round(minimum_base_clearance, 9)
            if minimum_base_clearance != float("inf")
            else None
        ),
        "minimum_periodic_selected_clearance": (
            round(minimum_periodic_clearance, 9)
            if minimum_periodic_clearance != float("inf")
            else None
        ),
        "required_pair_clearance": round(required_clearance, 9),
    }


def _assert_actual_l1_only_selection(
    plan: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> None:
    lanes = list(plan["lanes"])
    selected = list(selection["selected_candidates"])
    if len(selected) != len(lanes):
        raise Stage5DDensityReviewError(
            "formal Stage5 selection does not contain one Unit per ordinary L1"
        )
    lane_by_id = {str(lane["slot_id"]): lane for lane in lanes}
    if {str(row["source_lane_id"]) for row in selected} != set(lane_by_id):
        raise Stage5DDensityReviewError(
            "formal Stage5 selection does not preserve the Stage3 lane set"
        )
    for candidate in selected:
        curves = list(candidate["curves"])
        hierarchy = candidate["hierarchy"]
        if (
            hierarchy["l2_count"] != 0
            or hierarchy["l3_count"] != 0
            or len(curves) != 1
            or curves[0]["level"] != "L1"
        ):
            raise Stage5DDensityReviewError(
                "formal Stage5 selection is not actual L1-only"
            )
        lane = lane_by_id[str(candidate["source_lane_id"])]
        if curves[0]["cubic_segments"] != lane["segments"]:
            raise Stage5DDensityReviewError(
                "formal Unit changed the selected Stage3 ordinary L1 curve"
            )


def run(output_dir: Path) -> None:
    if output_dir.exists():
        raise Stage5DDensityReviewError(
            f"output directory already exists: {output_dir}"
        )
    for path in (
        STAGE4_CONTRACT_PATH,
        STAGE5D_CONTRACT_PATH,
        EDITOR_L2_PRIOR_PATH,
    ):
        if not path.is_file():
            raise Stage5DDensityReviewError(f"missing 5D input: {path}")

    (
        inputs,
        prior,
        feedback_prior,
        curve_geometry_prior,
        stage3b_contract,
        stage3_plan_contract,
        provenance,
    ) = _load_inputs()
    stage4_contract = _read_json(STAGE4_CONTRACT_PATH)
    stage5d_contract = _read_json(STAGE5D_CONTRACT_PATH)
    editor_l2_prior = _read_json(EDITOR_L2_PRIOR_PATH)
    registry = load_prototype_strategy_registry()
    strategies = {
        prototype_id: resolve_prototype_strategy(
            {"prototype_id": prototype_id},
            registry,
        )
        for prototype_id in PROTOTYPE_IDS
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="stage5d_density_",
        dir=output_dir.parent,
    ) as directory:
        temporary = Path(directory)
        debug_rows: dict[str, list[tuple[Path, int]]] = {
            value: [] for value in PROTOTYPE_IDS
        }
        formal_rows: dict[str, list[tuple[Path, int]]] = {
            value: [] for value in PROTOTYPE_IDS
        }
        task_rows: list[dict[str, Any]] = []
        invariant_rows: list[dict[str, Any]] = []
        total_crossings = 0
        total_clearance_violations = 0

        for prototype_id in PROTOTYPE_IDS:
            frozen_structure: dict[str, Any] | None = None
            frozen_candidate_pool: list[dict[str, Any]] | None = None
            frozen_resolved_domain: dict[str, int] | None = None
            level_counts: dict[str, int] = {}
            level_root_sets: dict[str, list[float]] = {}

            for density_level in DENSITY_LEVELS:
                result = generate_prototype_case(
                    payload=inputs[prototype_id],
                    prototype_strategy=strategies[prototype_id],
                    production_seed=PRODUCTION_SEED,
                    prior=prior,
                    feedback_prior=feedback_prior,
                    curve_geometry_prior=curve_geometry_prior,
                    contract=stage3b_contract,
                    stage3_plan_contract=stage3_plan_contract,
                    backbone_seed_override=BACKBONE_SEED,
                    flower_seed_override=FLOWER_SEED,
                    branch_seed_override=BRANCH_SEED,
                    unit_seed_override=UNIT_SEED,
                    backbone_rho=None,
                    flower_rho=FLOWER_RHO,
                    ordinary_density_level_override=density_level,
                )
                analysis = result["variant_analysis"]
                plan = result["plan"]
                flower_mount_plan = result["flower_mount_plan"]
                strict_value = result["variant_strict"].as_dict()
                inventory = result["inventory"]

                resolved_domain = {
                    str(key): int(value)
                    for key, value in plan["solver"][
                        "resolved_ordinary_l1_count_domain"
                    ].items()
                }
                if density_level not in resolved_domain:
                    raise Stage5DDensityReviewError(
                        f"resolved density domain lacks {density_level}: {prototype_id}"
                    )
                ordinary_count = len(plan["lanes"])
                flower_support_count = len(flower_mount_plan["mounts"])
                expected_count = resolved_domain[density_level]
                if ordinary_count != expected_count:
                    raise Stage5DDensityReviewError(
                        "selected ordinary L1 count does not match the resolved "
                        f"density domain: {prototype_id} {density_level}"
                    )
                if (
                    plan["count_derivation"]["ordinary_density_level"]
                    != density_level
                    or plan["count_derivation"]["ordinary_density_source"]
                    != "explicit_review_override"
                ):
                    raise Stage5DDensityReviewError(
                        "5D review override was not consumed by the formal selector"
                    )
                count_derivation = plan["count_derivation"]
                if (
                    int(count_derivation["required_support_count"])
                    != flower_support_count
                    or int(count_derivation["selected_l1_count"])
                    != ordinary_count + flower_support_count
                ):
                    raise Stage5DDensityReviewError(
                        "flower supports were not independently excluded from the "
                        f"ordinary-L1 density count: {prototype_id} {density_level}"
                    )

                structure_basis = {
                    "backbone": strict_value["backbone"],
                    "flowers": strict_value["flowers"],
                    "flower_mounts": flower_mount_plan["mounts"],
                }
                candidate_pool_basis = _candidate_pool_basis(inventory)
                if frozen_structure is None:
                    frozen_structure = structure_basis
                    frozen_candidate_pool = candidate_pool_basis
                    frozen_resolved_domain = resolved_domain
                else:
                    if structure_basis != frozen_structure:
                        raise Stage5DDensityReviewError(
                            "backbone, flowers, or mounts changed across 5D levels: "
                            f"{prototype_id}"
                        )
                    if candidate_pool_basis != frozen_candidate_pool:
                        raise Stage5DDensityReviewError(
                            "common candidate-pool base geometry changed across 5D "
                            f"levels: {prototype_id}"
                        )
                    if resolved_domain != frozen_resolved_domain:
                        raise Stage5DDensityReviewError(
                            f"resolved density domain changed across levels: {prototype_id}"
                        )
                level_counts[density_level] = ordinary_count
                level_root_sets[density_level] = sorted(
                    round(float(lane["root_s"]), 9) for lane in plan["lanes"]
                )

                unit_inventory = generate_unit_candidate_inventory(
                    plan,
                    analysis,
                    prior,
                    stage4_contract,
                    editor_l2_prior,
                )
                validate_unit_candidate_inventory(unit_inventory, stage4_contract)
                conflict_graph = build_conflict_graph(
                    unit_inventory,
                    stage5d_contract,
                    editor_l2_prior,
                )
                selection = select_global_units(
                    unit_inventory,
                    conflict_graph,
                    stage5d_contract,
                )
                validate_global_selection(selection, conflict_graph)
                if not selection["feasible"]:
                    raise Stage5DDensityReviewError(
                        f"no legal formal L1-only composition: "
                        f"{prototype_id} {density_level}"
                    )
                _assert_actual_l1_only_selection(plan, selection)

                mechanics = _selected_pair_mechanics(selection, conflict_graph)
                if (
                    mechanics["curve_crossing_count"] != 0
                    or mechanics["near_clearance_violation_count"] != 0
                ):
                    raise Stage5DDensityReviewError(
                        "formal selected L1 set failed independent crossing or "
                        f"clearance checks: {prototype_id} {density_level}"
                    )
                total_crossings += int(mechanics["curve_crossing_count"])
                total_clearance_violations += int(
                    mechanics["near_clearance_violation_count"]
                )

                case = temporary / prototype_id / density_level
                case.mkdir(parents=True)
                paths = {
                    "strict_p0_variant.json": case / "strict_p0_variant.json",
                    "prototype_analysis_variant.json": case
                    / "prototype_analysis_variant.json",
                    "flower_layout_plan.json": case / "flower_layout_plan.json",
                    "flower_mount_plan.json": case / "flower_mount_plan.json",
                    "global_l1_flow_plan.json": case / "global_l1_flow_plan.json",
                    "global_l1_candidate_inventory.json": case
                    / "global_l1_candidate_inventory.json",
                    "unit_candidate_inventory.json": case
                    / "unit_candidate_inventory.json",
                    "candidate_conflict_graph.json": case
                    / "candidate_conflict_graph.json",
                    "global_unit_selection.json": case
                    / "global_unit_selection.json",
                    "structure_debug.png": case / "structure_debug.png",
                    "formal_l1_only.png": case / "formal_l1_only.png",
                }
                _write_json(paths["strict_p0_variant.json"], strict_value)
                _write_json(paths["prototype_analysis_variant.json"], analysis)
                _write_json(
                    paths["flower_layout_plan.json"],
                    result["flower_layout_plan"],
                )
                _write_json(paths["flower_mount_plan.json"], flower_mount_plan)
                _write_json(paths["global_l1_flow_plan.json"], plan)
                _write_json(
                    paths["global_l1_candidate_inventory.json"],
                    inventory,
                )
                _write_json(paths["unit_candidate_inventory.json"], unit_inventory)
                _write_json(paths["candidate_conflict_graph.json"], conflict_graph)
                _write_json(paths["global_unit_selection.json"], selection)
                render_l1_png(
                    analysis,
                    plan,
                    paths["structure_debug.png"],
                    debug=True,
                )
                render_global_selection(
                    analysis,
                    unit_inventory,
                    conflict_graph,
                    selection,
                    paths["formal_l1_only.png"],
                    triple_repeat=False,
                    flower_mount_plan=flower_mount_plan,
                )
                debug_rows[prototype_id].append(
                    (paths["structure_debug.png"], ordinary_count)
                )
                formal_rows[prototype_id].append(
                    (paths["formal_l1_only.png"], ordinary_count)
                )

                upper_count = sum(
                    float(lane["target"][1]) < float(lane["root"][1])
                    for lane in plan["lanes"]
                )
                task_rows.append(
                    {
                        "prototype_id": prototype_id,
                        "density_level": density_level,
                        "production_seed": PRODUCTION_SEED,
                        "backbone_seed": BACKBONE_SEED,
                        "flower_seed": FLOWER_SEED,
                        "flower_rho": FLOWER_RHO,
                        "branch_seed": BRANCH_SEED,
                        "unit_seed": UNIT_SEED,
                        "ordinary_l1_count": ordinary_count,
                        "selected_ordinary_l1_root_s": level_root_sets[
                            density_level
                        ],
                        "resolved_ordinary_l1_count_domain": resolved_domain,
                        "flower_support_count": flower_support_count,
                        "upper_ordinary_l1_count": upper_count,
                        "lower_ordinary_l1_count": ordinary_count - upper_count,
                        "selected_l1_only_count": selection["solver_trace"][
                            "selected_l1_only_count"
                        ],
                        "selected_l2_count": selection["solver_trace"][
                            "selected_l2_count"
                        ],
                        "selected_l3_count": selection["solver_trace"][
                            "selected_l3_count"
                        ],
                        "mechanical_checks": mechanics,
                        "files": {
                            name: str(path.relative_to(temporary)).replace(
                                "\\", "/"
                            )
                            for name, path in paths.items()
                        },
                    }
                )

            if len(set(level_counts.values())) != len(DENSITY_LEVELS):
                raise Stage5DDensityReviewError(
                    f"simple/medium/rich did not resolve to distinct counts: {prototype_id}"
                )
            invariant_rows.append(
                {
                    "prototype_id": prototype_id,
                    "backbone_equal_across_density_levels": True,
                    "flowers_equal_across_density_levels": True,
                    "flower_mounts_equal_across_density_levels": True,
                    "candidate_pool_base_geometry_equal_across_density_levels": True,
                    "resolved_domain_equal_across_density_levels": True,
                    "ordinary_l1_counts": level_counts,
                    "ordinary_l1_root_sets": level_root_sets,
                    "simple_to_medium_is_not_append_only": not set(
                        level_root_sets["simple"]
                    ).issubset(level_root_sets["medium"]),
                    "medium_to_rich_is_not_append_only": not set(
                        level_root_sets["medium"]
                    ).issubset(level_root_sets["rich"]),
                }
            )

        debug_sheet = temporary / "stage5d_color_structure_contact_sheet.png"
        formal_sheet = temporary / "stage5d_formal_l1_only_contact_sheet.png"
        _render_labeled_sheet(
            debug_rows,
            debug_sheet,
            title=(
                "Stage 5D: fixed backbone/flowers, ordinary-L1 density variation "
                "(structure view)"
            ),
        )
        _render_labeled_sheet(
            formal_rows,
            formal_sheet,
            title=(
                "Stage 5D: formal Stage4/Stage5 output "
                "(actual L1-only Units)"
            ),
        )
        manifest = {
            "schema": "dynamic_branch_stage5d_density_review_manifest_v1",
            "scope": (
                "all five SW prototypes under controlled simple/medium/rich "
                "ordinary-L1 density variation"
            ),
            "prototype_order": list(PROTOTYPE_IDS),
            "density_level_order": list(DENSITY_LEVELS),
            "fixed_seed_domains": {
                "production_seed": PRODUCTION_SEED,
                "backbone_seed": BACKBONE_SEED,
                "flower_seed": FLOWER_SEED,
                "flower_rho": FLOWER_RHO,
                "branch_seed": BRANCH_SEED,
                "unit_seed": UNIT_SEED,
            },
            "only_changed_input": "ordinary_density_level_override",
            "stage5_selection_contract": str(STAGE5D_CONTRACT_PATH),
            "production_chain": [
                "fixed_backbone_variant",
                "fixed_flower_layout_and_mount",
                "common_pool_ordinary_l1_density_selection",
                "stage4_unit_candidate_inventory",
                "stage5_actual_l1_only_global_selection",
                "formal_render",
            ],
            "stage_boundaries": {
                "5d_ordinary_l1_density_policy_consumed": True,
                "flower_support_excluded_from_density_count": True,
                "5e_opposed_fork_generation_added": False,
                "leaves_or_swollen_rhizomes_generated": False,
                "stage4_l2_candidates_may_exist_but_are_not_formally_selected": True,
            },
            "invariance_checks": invariant_rows,
            "mechanical_summary": {
                "selected_curve_crossing_count": total_crossings,
                "selected_near_clearance_violation_count": (
                    total_clearance_violations
                ),
            },
            "review_gate": {
                "status": "VISUAL_REVIEW_PENDING",
                "numeric_checks_cannot_auto_approve_visual_gate": True,
            },
            "contact_sheets": {
                "color_structure": debug_sheet.name,
                "formal_l1_only": formal_sheet.name,
            },
            "provenance": provenance,
            "tasks": task_rows,
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.replace(output_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    args = parser.parse_args()
    run(args.output_dir.resolve())
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
