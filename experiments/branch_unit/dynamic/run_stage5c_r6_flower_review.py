#!/usr/bin/env python3
"""Generate the R6 SW3 flower-placement review through the formal Unit chain."""

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
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage5c_r6_flower_review_v1"
)
STAGE4_CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json"
STAGE5C_CONTRACT_PATH = (
    DYNAMIC_DIR / "STAGE5C_R6_L1_ONLY_SELECTION_CONTRACT_V1.json"
)
EDITOR_L2_PRIOR_PATH = DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json"

PROTOTYPE_IDS = ("proto_sw_3_1", "proto_sw_3_2")
CASE_SPECS = (
    ("baseline", 0, 0.0),
    ("flower_seed_11", 11, None),
    ("flower_seed_23", 23, None),
    ("flower_seed_29", 29, None),
)
PRODUCTION_SEED = 4101
BACKBONE_SEED = 1658046696
BRANCH_SEED = 3594281359
UNIT_SEED = 49789125


class R6FlowerReviewError(RuntimeError):
    """The R6 review cannot be produced through the formal chain."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise R6FlowerReviewError(f"JSON root must be an object: {path}")
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


def _render_labeled_sheet(
    image_rows: Mapping[str, Sequence[Path]],
    output: Path,
    *,
    title: str,
) -> None:
    column_labels = ("baseline", "flower seed 11", "flower seed 23", "flower seed 29")
    cell_width = 650
    cell_height = 430
    left_margin = 105
    top_margin = 92
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
            (left_margin + column * cell_width + 16, 51),
            label,
            fill="#374750",
            font=_font(18, bold=True),
        )
    for row, prototype_id in enumerate(PROTOTYPE_IDS):
        label = "SW3-1" if prototype_id.endswith("3_1") else "SW3-2"
        draw.text(
            (15, top_margin + row * cell_height + 18),
            label,
            fill="#17242d",
            font=_font(20, bold=True),
        )
        paths = list(image_rows[prototype_id])
        if len(paths) != len(column_labels):
            raise R6FlowerReviewError(f"R6 sheet row is incomplete: {prototype_id}")
        for column, path in enumerate(paths):
            with Image.open(path) as source:
                image = source.convert("RGB")
            image.thumbnail((cell_width - 18, cell_height - 18), Image.Resampling.LANCZOS)
            x0 = left_margin + column * cell_width
            y0 = top_margin + row * cell_height
            x = x0 + (cell_width - image.width) // 2
            y = y0 + (cell_height - image.height) // 2
            canvas.paste(image, (x, y))
            draw.rectangle(
                (x0 + 4, y0 + 4, x0 + cell_width - 5, y0 + cell_height - 5),
                outline="#c5cdd2",
                width=2,
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def _selected_pair_mechanics(
    selection: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
) -> dict[str, Any]:
    selected = selection["selected_candidates"]
    repeat_shifts = [float(value) for value in conflict_graph["repeat_shifts_checked"]]
    required_clearance = float(conflict_graph["minimum_descendant_clearance"])
    crossing_count = 0
    clearance_violation_count = 0
    minimum_clearance = float("inf")
    checked_pair_count = 0
    for index, first in enumerate(selected):
        for second in selected[index + 1 :]:
            checked_pair_count += 1
            crossing_count += len(
                candidate_pair_crossings(first, second, repeat_shifts)
            )
            clearance = candidate_pair_minimum_clearance(
                first,
                second,
                repeat_shifts,
            )
            minimum_clearance = min(minimum_clearance, clearance)
            if clearance < required_clearance - 1e-9:
                clearance_violation_count += 1
    return {
        "checked_selected_pair_count": checked_pair_count,
        "curve_crossing_count": crossing_count,
        "near_clearance_violation_count": clearance_violation_count,
        "minimum_selected_pair_clearance": (
            round(minimum_clearance, 9)
            if minimum_clearance != float("inf")
            else None
        ),
        "required_pair_clearance": round(required_clearance, 9),
    }


def run(output: Path) -> None:
    if output.exists():
        raise R6FlowerReviewError(f"output already exists: {output}")
    for path in (
        STAGE4_CONTRACT_PATH,
        STAGE5C_CONTRACT_PATH,
        EDITOR_L2_PRIOR_PATH,
    ):
        if not path.is_file():
            raise R6FlowerReviewError(f"missing R6 input: {path}")

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
    stage5c_contract = _read_json(STAGE5C_CONTRACT_PATH)
    editor_l2_prior = _read_json(EDITOR_L2_PRIOR_PATH)
    registry = load_prototype_strategy_registry()
    strategies = {
        prototype_id: resolve_prototype_strategy(
            {"prototype_id": prototype_id},
            registry,
        )
        for prototype_id in PROTOTYPE_IDS
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage5c_r6_", dir=output.parent) as directory:
        temporary = Path(directory)
        debug_rows: dict[str, list[Path]] = {value: [] for value in PROTOTYPE_IDS}
        formal_rows: dict[str, list[Path]] = {value: [] for value in PROTOTYPE_IDS}
        task_rows: list[dict[str, Any]] = []
        total_crossings = 0
        total_clearance_violations = 0

        for prototype_id in PROTOTYPE_IDS:
            for case_label, flower_seed, flower_rho in CASE_SPECS:
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
                    flower_seed_override=flower_seed,
                    branch_seed_override=BRANCH_SEED,
                    unit_seed_override=UNIT_SEED,
                    backbone_rho=None,
                    flower_rho=flower_rho,
                )
                analysis = result["variant_analysis"]
                plan = result["plan"]
                flower_mount_plan = result["flower_mount_plan"]

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
                    stage5c_contract,
                    editor_l2_prior,
                )
                selection = select_global_units(
                    unit_inventory,
                    conflict_graph,
                    stage5c_contract,
                )
                validate_global_selection(selection, conflict_graph)
                if not selection["feasible"]:
                    raise R6FlowerReviewError(
                        f"no legal L1-only composition: {prototype_id} {case_label}"
                    )

                lane_by_id = {str(lane["slot_id"]): lane for lane in plan["lanes"]}
                for candidate in selection["selected_candidates"]:
                    if (
                        candidate["hierarchy"]["l2_count"] != 0
                        or candidate["hierarchy"]["l3_count"] != 0
                        or any(curve["level"] != "L1" for curve in candidate["curves"])
                    ):
                        raise R6FlowerReviewError("formal selection is not actual L1-only")
                    if len(candidate["curves"]) != 1 or candidate["curves"][0][
                        "cubic_segments"
                    ] != lane_by_id[str(candidate["source_lane_id"])]["segments"]:
                        raise R6FlowerReviewError(
                            "formal Unit did not preserve the selected ordinary L1"
                        )

                mechanics = _selected_pair_mechanics(selection, conflict_graph)
                total_crossings += int(mechanics["curve_crossing_count"])
                total_clearance_violations += int(
                    mechanics["near_clearance_violation_count"]
                )

                case = temporary / prototype_id / case_label
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
                _write_json(paths["strict_p0_variant.json"], result["variant_strict"].as_dict())
                _write_json(paths["prototype_analysis_variant.json"], analysis)
                _write_json(paths["flower_layout_plan.json"], result["flower_layout_plan"])
                _write_json(paths["flower_mount_plan.json"], flower_mount_plan)
                _write_json(paths["global_l1_flow_plan.json"], plan)
                _write_json(paths["global_l1_candidate_inventory.json"], result["inventory"])
                _write_json(paths["unit_candidate_inventory.json"], unit_inventory)
                _write_json(paths["candidate_conflict_graph.json"], conflict_graph)
                _write_json(paths["global_unit_selection.json"], selection)
                render_l1_png(analysis, plan, paths["structure_debug.png"], debug=True)
                render_global_selection(
                    analysis,
                    unit_inventory,
                    conflict_graph,
                    selection,
                    paths["formal_l1_only.png"],
                    triple_repeat=False,
                    flower_mount_plan=flower_mount_plan,
                )
                debug_rows[prototype_id].append(paths["structure_debug.png"])
                formal_rows[prototype_id].append(paths["formal_l1_only.png"])

                upper_count = sum(
                    float(lane["target"][1]) < float(lane["root"][1])
                    for lane in plan["lanes"]
                )
                task_rows.append(
                    {
                        "prototype_id": prototype_id,
                        "case": case_label,
                        "production_seed": PRODUCTION_SEED,
                        "backbone_seed": BACKBONE_SEED,
                        "flower_seed": flower_seed,
                        "flower_rho": flower_rho,
                        "branch_seed": BRANCH_SEED,
                        "unit_seed": UNIT_SEED,
                        "ordinary_l1_count": len(plan["lanes"]),
                        "upper_ordinary_l1_count": upper_count,
                        "lower_ordinary_l1_count": len(plan["lanes"]) - upper_count,
                        "flower_centers": [
                            flower["center"] for flower in analysis["flowers"]
                        ],
                        "flower_support_roots": [
                            mount["root_s"] for mount in flower_mount_plan["mounts"]
                        ],
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
                            name: str(path.relative_to(temporary)).replace("\\", "/")
                            for name, path in paths.items()
                        },
                    }
                )

        debug_sheet = temporary / "r6_color_structure_contact_sheet.png"
        formal_sheet = temporary / "r6_formal_l1_only_contact_sheet.png"
        _render_labeled_sheet(
            debug_rows,
            debug_sheet,
            title="R6: flower placement -> support branch -> ordinary L1 (structure view)",
        )
        _render_labeled_sheet(
            formal_rows,
            formal_sheet,
            title="R6: formal Stage4/Stage5 output (actual L1-only Units)",
        )
        manifest = {
            "schema": "dynamic_branch_stage5c_r6_flower_review_manifest_v1",
            "scope": "SW3 flower-placement propagation through formal L1-only Unit output",
            "prototype_order": list(PROTOTYPE_IDS),
            "case_order": [row[0] for row in CASE_SPECS],
            "fixed_seed_domains": {
                "production_seed": PRODUCTION_SEED,
                "backbone_seed": BACKBONE_SEED,
                "branch_seed": BRANCH_SEED,
                "unit_seed": UNIT_SEED,
            },
            "stage5_selection_contract": str(STAGE5C_CONTRACT_PATH),
            "production_chain": [
                "backbone_variant",
                "flower_layout_and_mount",
                "common_pool_ordinary_l1_selection",
                "stage4_unit_candidate_inventory",
                "stage5_actual_l1_only_global_selection",
                "formal_render",
            ],
            "stage_boundaries": {
                "5d_density_or_count_policy_added": False,
                "5e_opposed_fork_generation_added": False,
                "leaves_or_swollen_rhizomes_generated": False,
                "stage4_l2_candidates_may_exist_but_are_not_formally_selected": True,
            },
            "mechanical_summary": {
                "selected_curve_crossing_count": total_crossings,
                "selected_near_clearance_violation_count": total_clearance_violations,
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
        temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.output.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
