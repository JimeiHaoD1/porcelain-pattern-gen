#!/usr/bin/env python3
"""Generate the Stage-5F full-integration review through the formal chain."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw

from backbone_variation_v1 import split_generation_seeds
from branch_unit_grammar_v1 import (
    _segments_intersect,
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
from run_stage5e_l2_sparse_review import (
    L2_ATTACHMENT_TOLERANCE,
    _check_frozen_l1_invariance,
    _check_l2_real_attachment,
    _font,
    _prototype_label,
    _selected_pair_mechanics,
)
from stage5_global_unit_selection import (
    build_conflict_graph,
    select_global_units,
    validate_global_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage5f_full_integration_v1"
)
STAGE4_CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json"
STAGE5E_CONTRACT_PATH = (
    DYNAMIC_DIR / "STAGE5E_L2_SPARSE_SELECTION_CONTRACT_V1.json"
)
EDITOR_L2_PRIOR_PATH = DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json"

PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
PRODUCTION_SEEDS = (4101, 5321, 7777)
BACKBONE_PERIOD_TOLERANCE = 1e-3


class Stage5FFullIntegrationError(RuntimeError):
    """The 5F review cannot be produced through the formal chain."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5FFullIntegrationError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _check_backbone_periodic_continuity(
    strict_frame: Mapping[str, Any],
    backbone: Mapping[str, Any],
) -> dict[str, Any]:
    """Independently verify backbone period continuity and local non-crossing."""

    repeat_range = strict_frame["local"]["repeat_x_range"]
    repeat_width = float(repeat_range[1]) - float(repeat_range[0])
    samples = list(backbone["arc_samples"])
    first = samples[0]
    last = samples[-1]
    first_point = tuple(float(value) for value in first["point"])
    last_point = tuple(float(value) for value in last["point"])
    seam_error = max(
        abs(last_point[0] - (first_point[0] + repeat_width)),
        abs(last_point[1] - first_point[1]),
    )
    first_tangent = tuple(float(value) for value in first["tangent"])
    last_tangent = tuple(float(value) for value in last["tangent"])
    tangent_dot = (
        first_tangent[0] * last_tangent[0]
        + first_tangent[1] * last_tangent[1]
    )
    if seam_error > BACKBONE_PERIOD_TOLERANCE or tangent_dot < 0.999:
        raise Stage5FFullIntegrationError(
            "backbone period seam is not continuous: "
            f"seam_error={seam_error:.6g} tangent_dot={tangent_dot:.6g}"
        )
    points = [
        tuple(float(value) for value in sample["point"])
        for sample in samples
    ]
    self_crossing_count = 0
    for index in range(len(points) - 2):
        for other_index in range(index + 2, len(points) - 1):
            if _segments_intersect(
                points[index],
                points[index + 1],
                points[other_index],
                points[other_index + 1],
            ):
                self_crossing_count += 1
    if self_crossing_count:
        raise Stage5FFullIntegrationError(
            f"backbone self-crossing count={self_crossing_count}"
        )
    return {
        "seam_error": round(seam_error, 9),
        "tangent_dot": round(tangent_dot, 9),
        "self_crossing_count": self_crossing_count,
    }


def _check_flower_mount_relation(
    prototype_id: str,
    strategy: Mapping[str, Any],
    flower_layout_plan: Mapping[str, Any],
    flower_mount_plan: Mapping[str, Any],
) -> None:
    """Independently verify flowers and support mounts match the prototype."""

    family = str(flower_mount_plan["morphology_family"])
    flower_count = int(strategy["invariants"]["flower_count"])
    expected_mounts = 0 if family == "SW-2_axis_penetrating" else flower_count
    mounts = list(flower_mount_plan["mounts"])
    if len(mounts) != expected_mounts:
        raise Stage5FFullIntegrationError(
            f"flower mount count violates prototype rule: "
            f"{prototype_id} got={len(mounts)} expected={expected_mounts}"
        )
    if int(flower_mount_plan["expected_mount_count"]) != expected_mounts:
        raise Stage5FFullIntegrationError(
            f"flower mount plan declares the wrong expected count: "
            f"{prototype_id}"
        )
    if expected_mounts == 0:
        if str(flower_layout_plan["mode"]) != "fixed_prototype_relation":
            raise Stage5FFullIntegrationError(
                f"SW-2 flower layout mode is unexpected: {prototype_id}"
            )
        return
    flower_ids = {str(mount["flower_id"]) for mount in mounts}
    if len(flower_ids) != flower_count:
        raise Stage5FFullIntegrationError(
            f"flower support mounts do not cover the flower set: {prototype_id}"
        )
    if family.startswith("SW-1"):
        for mount in mounts:
            route = mount["route"]
            if (
                str(route["origin_kind"]) != "wave_trough_support"
                or "below" not in str(route["contact_side"])
            ):
                raise Stage5FFullIntegrationError(
                    f"SW-1 support relation is unexpected: {prototype_id}"
                )
        if str(flower_layout_plan["mode"]) != "fixed_prototype_relation":
            raise Stage5FFullIntegrationError(
                f"SW-1 flower layout mode is unexpected: {prototype_id}"
            )
    elif family.startswith("SW-3"):
        for mount in mounts:
            route = mount["route"]
            if (
                str(route["origin_kind"]) != "remote_tangent_extension"
                or str(route["contact_side"]) != "underside"
            ):
                raise Stage5FFullIntegrationError(
                    f"SW-3 support relation is unexpected: {prototype_id}"
                )
        if not str(flower_layout_plan["mode"]).startswith("sw3"):
            raise Stage5FFullIntegrationError(
                f"SW-3 flower layout mode is unexpected: {prototype_id}"
            )
    else:
        raise Stage5FFullIntegrationError(
            f"unknown flower morphology family: {family}"
        )


def _render_production_seed_sheet(
    image_rows: Mapping[str, Sequence[tuple[Path, Mapping[str, Any]]]],
    output: Path,
    *,
    title: str,
    caption: str,
) -> None:
    column_labels = [
        f"production_seed {PRODUCTION_SEEDS[0]}",
        f"production_seed {PRODUCTION_SEEDS[1]}",
        f"production_seed {PRODUCTION_SEEDS[2]}",
    ]
    cell_width = 620
    cell_height = 380
    image_label_height = 30
    left_margin = 112
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
    draw.text((18, 10), title, fill="#17242d", font=_font(24, bold=True))
    for column, label in enumerate(column_labels):
        draw.text(
            (left_margin + column * cell_width + 12, 53),
            label,
            fill="#374750",
            font=_font(16, bold=True),
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
            raise Stage5FFullIntegrationError(
                f"5F sheet row is incomplete: {prototype_id}"
            )
        for column, (path, summary) in enumerate(cells):
            x0 = left_margin + column * cell_width
            y0 = top_margin + row * cell_height
            draw.rectangle(
                (x0 + 4, y0 + 4, x0 + cell_width - 5, y0 + cell_height - 5),
                outline="#c5cdd2",
                width=2,
            )
            draw.text(
                (x0 + 16, y0 + 9),
                caption.format(**summary),
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


def run(output_dir: Path) -> None:
    if output_dir.exists():
        raise Stage5FFullIntegrationError(
            f"output directory already exists: {output_dir}"
        )
    for path in (
        STAGE4_CONTRACT_PATH,
        STAGE5E_CONTRACT_PATH,
        EDITOR_L2_PRIOR_PATH,
    ):
        if not path.is_file():
            raise Stage5FFullIntegrationError(f"missing 5F input: {path}")

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
    stage5e_contract = _read_json(STAGE5E_CONTRACT_PATH)
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
        prefix="stage5f_full_",
        dir=output_dir.parent,
    ) as directory:
        temporary = Path(directory)
        structure_rows: dict[str, list[tuple[Path, Mapping[str, Any]]]] = {
            value: [] for value in PROTOTYPE_IDS
        }
        formal_rows: dict[str, list[tuple[Path, Mapping[str, Any]]]] = {
            value: [] for value in PROTOTYPE_IDS
        }
        task_rows: list[dict[str, Any]] = []
        backbone_rows: list[dict[str, Any]] = []
        flower_rows: list[dict[str, Any]] = []
        variation_rows: list[dict[str, Any]] = []
        projection_events: list[dict[str, Any]] = []
        total_crossings = 0
        total_clearance_violations = 0

        for prototype_id in PROTOTYPE_IDS:
            structure_signatures: dict[int, Any] = {}

            for production_seed in PRODUCTION_SEEDS:
                result = generate_prototype_case(
                    payload=inputs[prototype_id],
                    prototype_strategy=strategies[prototype_id],
                    production_seed=production_seed,
                    prior=prior,
                    feedback_prior=feedback_prior,
                    curve_geometry_prior=curve_geometry_prior,
                    contract=stage3b_contract,
                    stage3_plan_contract=stage3_plan_contract,
                    backbone_seed_override=None,
                    flower_seed_override=None,
                    branch_seed_override=None,
                    unit_seed_override=None,
                    backbone_rho=None,
                    flower_rho=None,
                    ordinary_density_level_override=None,
                )
                derived_seeds = split_generation_seeds(production_seed)
                actual_seeds = {
                    "backbone_seed": int(result["backbone_seed"]),
                    "flower_seed": int(result["flower_seed"]),
                    "branch_seed": int(result["branch_seed"]),
                    "unit_seed": int(result["unit_seed"]),
                }
                if actual_seeds != derived_seeds:
                    raise Stage5FFullIntegrationError(
                        "production seed domains were not consumed without "
                        f"override: {prototype_id} seed={production_seed}"
                    )
                analysis = result["variant_analysis"]
                plan = result["plan"]
                flower_mount_plan = result["flower_mount_plan"]
                flower_layout_plan = result["flower_layout_plan"]
                strict_value = result["variant_strict"].as_dict()
                inventory = result["inventory"]
                if (
                    plan["count_derivation"]["ordinary_density_source"]
                    != "branch_seed"
                ):
                    raise Stage5FFullIntegrationError(
                        "5F used a density override instead of the seed-"
                        f"driven production default: {prototype_id}"
                    )
                density_level = str(
                    plan["count_derivation"]["ordinary_density_level"]
                )
                backbone_check = _check_backbone_periodic_continuity(
                    strict_value["frame"],
                    strict_value["backbone"],
                )
                _check_flower_mount_relation(
                    prototype_id,
                    strategies[prototype_id],
                    flower_layout_plan,
                    flower_mount_plan,
                )
                backbone_rows.append(
                    {
                        "prototype_id": prototype_id,
                        "production_seed": production_seed,
                        "seam_error": backbone_check["seam_error"],
                        "tangent_dot": backbone_check["tangent_dot"],
                        "backbone_self_crossing_count": backbone_check[
                            "self_crossing_count"
                        ],
                    }
                )
                flower_rows.append(
                    {
                        "prototype_id": prototype_id,
                        "production_seed": production_seed,
                        "morphology_family": flower_mount_plan[
                            "morphology_family"
                        ],
                        "flower_count": len(flower_layout_plan["final_centers"]),
                        "mount_count": len(flower_mount_plan["mounts"]),
                        "mount_relation_matches_prototype": True,
                    }
                )
                structure_signature = (
                    str(plan["prototype_variant_id"]),
                    json.dumps(
                        flower_layout_plan["final_centers"],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    tuple(
                        round(float(lane["root_s"]), 9)
                        for lane in plan["lanes"]
                    ),
                )
                structure_signatures[production_seed] = structure_signature

                unit_inventory = generate_unit_candidate_inventory(
                    plan,
                    analysis,
                    prior,
                    stage4_contract,
                    editor_l2_prior,
                )
                validate_unit_candidate_inventory(
                    unit_inventory,
                    stage4_contract,
                )
                conflict_graph = build_conflict_graph(
                    unit_inventory,
                    stage5e_contract,
                    editor_l2_prior,
                )
                selection = select_global_units(
                    unit_inventory,
                    conflict_graph,
                    stage5e_contract,
                )
                validate_global_selection(selection, conflict_graph)
                if not selection["feasible"]:
                    raise Stage5FFullIntegrationError(
                        f"no formal 5F composition: "
                        f"{prototype_id} seed={production_seed}"
                    )
                _check_frozen_l1_invariance(plan, selection)
                for candidate in selection["selected_candidates"]:
                    _check_l2_real_attachment(
                        candidate,
                        L2_ATTACHMENT_TOLERANCE,
                    )
                mechanics = _selected_pair_mechanics(
                    selection,
                    conflict_graph,
                )
                if (
                    mechanics["curve_crossing_count"] != 0
                    or mechanics["near_clearance_violation_count"] != 0
                ):
                    raise Stage5FFullIntegrationError(
                        "formal 5F selection failed independent crossing or "
                        f"clearance checks: {prototype_id} seed={production_seed}"
                    )
                total_crossings += int(mechanics["curve_crossing_count"])
                total_clearance_violations += int(
                    mechanics["near_clearance_violation_count"]
                )
                trace = selection["solver_trace"]
                if int(trace["selected_l3_count"]) != 0:
                    raise Stage5FFullIntegrationError(
                        "formal 5F selection contains L3 geometry"
                    )
                if any(
                    curve.get("level") not in {"L1", "L2"}
                    for candidate in selection["selected_candidates"]
                    for curve in candidate["curves"]
                ):
                    raise Stage5FFullIntegrationError(
                        "formal 5F selection contains non-L1/L2 curves"
                    )

                case = temporary / prototype_id / f"seed_{production_seed}"
                case.mkdir(parents=True)
                paths = {
                    "derived_seeds.json": case / "derived_seeds.json",
                    "backbone_variation.json": case
                    / "backbone_variation.json",
                    "strict_p0_variant.json": case / "strict_p0_variant.json",
                    "prototype_analysis_variant.json": case
                    / "prototype_analysis_variant.json",
                    "flower_layout_plan.json": case
                    / "flower_layout_plan.json",
                    "flower_mount_plan.json": case / "flower_mount_plan.json",
                    "global_l1_flow_plan.json": case
                    / "global_l1_flow_plan.json",
                    "global_l1_candidate_inventory.json": case
                    / "global_l1_candidate_inventory.json",
                    "unit_candidate_inventory.json": case
                    / "unit_candidate_inventory.json",
                    "candidate_conflict_graph.json": case
                    / "candidate_conflict_graph.json",
                    "global_unit_selection.json": case
                    / "global_unit_selection.json",
                    "structure_debug.png": case / "structure_debug.png",
                    "formal_single.png": case / "formal_single.png",
                    "formal_triple.png": case / "formal_triple.png",
                }
                _write_json(
                    paths["derived_seeds.json"],
                    {
                        "production_seed": production_seed,
                        **actual_seeds,
                    },
                )
                _write_json(
                    paths["backbone_variation.json"],
                    result["variation"],
                )
                _write_json(paths["strict_p0_variant.json"], strict_value)
                _write_json(paths["prototype_analysis_variant.json"], analysis)
                _write_json(
                    paths["flower_layout_plan.json"],
                    flower_layout_plan,
                )
                _write_json(
                    paths["flower_mount_plan.json"],
                    flower_mount_plan,
                )
                _write_json(paths["global_l1_flow_plan.json"], plan)
                _write_json(
                    paths["global_l1_candidate_inventory.json"],
                    inventory,
                )
                _write_json(
                    paths["unit_candidate_inventory.json"],
                    unit_inventory,
                )
                _write_json(
                    paths["candidate_conflict_graph.json"],
                    conflict_graph,
                )
                _write_json(
                    paths["global_unit_selection.json"],
                    selection,
                )
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
                    paths["formal_single.png"],
                    triple_repeat=False,
                    flower_mount_plan=flower_mount_plan,
                )
                render_global_selection(
                    analysis,
                    unit_inventory,
                    conflict_graph,
                    selection,
                    paths["formal_triple.png"],
                    triple_repeat=True,
                    flower_mount_plan=flower_mount_plan,
                )
                summary = {
                    "density": density_level,
                    "upgraded": int(trace["achieved_upgrade_count"]),
                    "l2_count": int(trace["selected_l2_count"]),
                }
                projection = result["downstream_mount_projection"]
                if projection["used"]:
                    projection_events.append(
                        {
                            "prototype_id": prototype_id,
                            "production_seed": production_seed,
                            "variant_id": plan["prototype_variant_id"],
                            "attempted_strengths": projection[
                                "attempted_strengths"
                            ],
                            "selected_strength": projection[
                                "selected_strength"
                            ],
                            "retry_count": projection["retry_count"],
                        }
                    )
                structure_rows[prototype_id].append(
                    (paths["structure_debug.png"], summary)
                )
                formal_rows[prototype_id].append(
                    (paths["formal_triple.png"], summary)
                )
                task_rows.append(
                    {
                        "prototype_id": prototype_id,
                        "production_seed": production_seed,
                        "density_level": density_level,
                        "prototype_variant_id": plan["prototype_variant_id"],
                        "backbone_seed": actual_seeds["backbone_seed"],
                        "flower_seed": actual_seeds["flower_seed"],
                        "branch_seed": actual_seeds["branch_seed"],
                        "unit_seed": actual_seeds["unit_seed"],
                        "downstream_mount_projection": projection,
                        "plan_id": plan["plan_id"],
                        "ordinary_l1_count": len(plan["lanes"]),
                        "flower_support_count": len(
                            flower_mount_plan["mounts"]
                        ),
                        "achieved_upgrade_count": int(
                            trace["achieved_upgrade_count"]
                        ),
                        "selected_l1_only_count": int(
                            trace["selected_l1_only_count"]
                        ),
                        "selected_l2_count": int(trace["selected_l2_count"]),
                        "selected_l3_count": int(trace["selected_l3_count"]),
                        "mechanical_checks": mechanics,
                        "files": {
                            name: str(path.relative_to(temporary)).replace(
                                "\\",
                                "/",
                            )
                            for name, path in paths.items()
                        },
                    }
                )

            distinct_structure_count = len(set(structure_signatures.values()))
            if distinct_structure_count < 2:
                raise Stage5FFullIntegrationError(
                    "production seeds did not change backbone, flower, or L1 "
                    f"structure: {prototype_id}"
                )
            variation_rows.append(
                {
                    "prototype_id": prototype_id,
                    "distinct_structure_signature_count": (
                        distinct_structure_count
                    ),
                    "cross_seed_structure_changed": True,
                }
            )

        structure_sheet = temporary / "stage5f_color_structure_contact_sheet.png"
        formal_sheet = temporary / "stage5f_formal_triple_contact_sheet.png"
        _render_production_seed_sheet(
            structure_rows,
            structure_sheet,
            title=(
                "Stage 5F: no-override production chain across three seeds "
                "(structure view)"
            ),
            caption="density={density}",
        )
        _render_production_seed_sheet(
            formal_rows,
            formal_sheet,
            title=(
                "Stage 5F: formal triple-repeat output across three "
                "production seeds"
            ),
            caption="upgraded={upgraded} L2={l2_count}",
        )
        manifest = {
            "schema": "dynamic_branch_stage5f_full_integration_manifest_v1",
            "scope": (
                "five SW prototypes across three production seeds through "
                "the complete no-override 5A-5F production chain"
            ),
            "prototype_order": list(PROTOTYPE_IDS),
            "production_seed_order": list(PRODUCTION_SEEDS),
            "no_stage_overrides_used": True,
            "stage5_selection_contract": str(STAGE5E_CONTRACT_PATH),
            "production_chain": [
                "5a_prototype_routing",
                "production_seed_split",
                "5b_backbone_wave_variant",
                "5c_flower_layout_and_formal_mount",
                "r0_r5_common_pool_ordinary_l1_selection",
                "5d_seed_driven_density",
                "5e_sparse_local_l2",
                "stage4_unit_inventory",
                "stage5_global_selection",
                "single_and_triple_repeat_render",
            ],
            "stage_boundaries": {
                "no_backbone_override": True,
                "no_flower_override": True,
                "no_branch_override": True,
                "no_unit_override": True,
                "no_density_override": True,
                "l3_selected_count_is_zero": True,
                "leaves_or_swollen_rhizomes_generated": False,
                "final_contract_frozen": False,
            },
            "backbone_periodic_continuity": backbone_rows,
            "flower_mount_relation": flower_rows,
            "cross_seed_structure_variation": variation_rows,
            "downstream_mount_projection_events": projection_events,
            "mechanical_summary": {
                "selected_curve_crossing_count": total_crossings,
                "selected_near_clearance_violation_count": (
                    total_clearance_violations
                ),
                "selected_l2_attachment_violation_count": 0,
                "backbone_self_crossing_count": 0,
            },
            "review_gate": {
                "status": "VISUAL_REVIEW_PENDING",
                "numeric_checks_cannot_auto_approve_visual_gate": True,
            },
            "contact_sheets": {
                "color_structure": structure_sheet.name,
                "formal_triple_repeat": formal_sheet.name,
            },
            "provenance": provenance,
            "tasks": task_rows,
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.replace(output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the Stage-5F full-integration review."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="review output directory (default: artifacts/runs/"
        "dynamic_branch_stage5f_full_integration_v1)",
    )
    args = parser.parse_args()
    try:
        run(args.output_dir)
    except Stage5FFullIntegrationError as exc:
        raise SystemExit(f"stage-5F review error: {exc}") from exc
    print(f"stage-5F full integration review written to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
