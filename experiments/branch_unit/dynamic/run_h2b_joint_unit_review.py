#!/usr/bin/env python3
"""Compare sequential and joint sparse-L2 selection on frozen H2-A cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from render_stage5_global_selection import render_global_selection
from stage5_global_unit_selection import (
    build_conflict_graph,
    candidate_pair_crossings,
    select_global_units,
    validate_global_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
H2A_RUN = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_h2a_soft_density_review_v3"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_h2b_joint_unit_review_v2"
)
OLD_CONTRACT_PATH = DYNAMIC_DIR / "STAGE5E_L2_SPARSE_SELECTION_CONTRACT_V1.json"
JOINT_CONTRACT_PATH = DYNAMIC_DIR / "STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json"
EDITOR_L2_PRIOR_PATH = DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json"

PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
DENSITY_LEVELS = ("simple", "medium", "rich")


class H2BReviewError(RuntimeError):
    """The H2-B review could not be produced from frozen H2-A inputs."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise H2BReviewError(f"JSON root must be an object: {path}")
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
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _prototype_label(prototype_id: str) -> str:
    return {
        "proto_sw_1_1": "SW1-1",
        "proto_sw_1_3": "SW1-3",
        "proto_sw_2_3": "SW2-3",
        "proto_sw_3_1": "SW3-1",
        "proto_sw_3_2": "SW3-2",
    }[prototype_id]


def _selected_crossing_count(
    selection: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
) -> int:
    selected = list(selection["selected_candidates"])
    repeat_shifts = [
        float(value) for value in conflict_graph["repeat_shifts_checked"]
    ]
    return sum(
        len(candidate_pair_crossings(first, second, repeat_shifts))
        for index, first in enumerate(selected)
        for second in selected[index + 1 :]
    )


def _selection_by_lane(selection: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate["source_lane_id"]): candidate
        for candidate in selection["selected_candidates"]
    }


def _selection_l2_count(selection: Mapping[str, Any]) -> int:
    return sum(
        sum(
            1
            for curve in candidate["curves"]
            if curve.get("level") == "L2"
        )
        for candidate in selection["selected_candidates"]
    )


def _crop_plot(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGB")
    return image.crop((8, 80, image.width - 8, image.height - 40))


def _render_joint_sheet(
    rows: Mapping[str, Sequence[tuple[Path, Mapping[str, Any]]]],
    output: Path,
    *,
    title: str,
) -> None:
    cell_width = 610
    cell_height = 340
    left_margin = 105
    top_margin = 92
    canvas = Image.new(
        "RGB",
        (
            left_margin + len(DENSITY_LEVELS) * cell_width,
            top_margin + len(PROTOTYPE_IDS) * cell_height,
        ),
        "#f2f0e9",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 10), title, fill="#17242d", font=_font(25, bold=True))
    for column, density in enumerate(DENSITY_LEVELS):
        draw.text(
            (left_margin + column * cell_width + 14, 53),
            density,
            fill="#374750",
            font=_font(17, bold=True),
        )
    for row_index, prototype_id in enumerate(PROTOTYPE_IDS):
        draw.text(
            (15, top_margin + row_index * cell_height + 18),
            _prototype_label(prototype_id),
            fill="#17242d",
            font=_font(18, bold=True),
        )
        cells = list(rows[prototype_id])
        if len(cells) != len(DENSITY_LEVELS):
            raise H2BReviewError(f"incomplete H2-B row: {prototype_id}")
        for column, (path, summary) in enumerate(cells):
            x0 = left_margin + column * cell_width
            y0 = top_margin + row_index * cell_height
            draw.rectangle(
                (x0 + 4, y0 + 4, x0 + cell_width - 5, y0 + cell_height - 5),
                outline="#c5cdd2",
                width=2,
            )
            draw.text(
                (x0 + 14, y0 + 9),
                (
                    f"L1={summary['lane_count']}  "
                    f"升级 lane={summary['upgrade_count']}  "
                    f"L2={summary['l2_count']}"
                ),
                fill="#374750",
                font=_font(15, bold=True),
            )
            image = _crop_plot(path)
            image.thumbnail(
                (cell_width - 20, cell_height - 52),
                Image.Resampling.LANCZOS,
            )
            canvas.paste(
                image,
                (
                    x0 + (cell_width - image.width) // 2,
                    y0 + 43 + (cell_height - 48 - image.height) // 2,
                ),
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def _render_old_new_sheet(
    rows: Mapping[
        str,
        Sequence[tuple[Path, Path, Mapping[str, Any]]],
    ],
    output: Path,
) -> None:
    cell_width = 760
    cell_height = 310
    half_width = cell_width // 2
    left_margin = 105
    top_margin = 100
    canvas = Image.new(
        "RGB",
        (
            left_margin + len(DENSITY_LEVELS) * cell_width,
            top_margin + len(PROTOTYPE_IDS) * cell_height,
        ),
        "#f2f0e9",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (18, 10),
        "H2-B 同一 Stage4 库存与冲突图：旧顺序升级 vs 新联合选择",
        fill="#17242d",
        font=_font(24, bold=True),
    )
    for column, density in enumerate(DENSITY_LEVELS):
        draw.text(
            (left_margin + column * cell_width + 14, 50),
            f"{density}   左：旧 / 右：新",
            fill="#374750",
            font=_font(16, bold=True),
        )
    for row_index, prototype_id in enumerate(PROTOTYPE_IDS):
        draw.text(
            (15, top_margin + row_index * cell_height + 18),
            _prototype_label(prototype_id),
            fill="#17242d",
            font=_font(18, bold=True),
        )
        cells = list(rows[prototype_id])
        for column, (old_path, new_path, summary) in enumerate(cells):
            x0 = left_margin + column * cell_width
            y0 = top_margin + row_index * cell_height
            draw.rectangle(
                (x0 + 4, y0 + 4, x0 + cell_width - 5, y0 + cell_height - 5),
                outline="#c5cdd2",
                width=2,
            )
            draw.line(
                (x0 + half_width, y0 + 32, x0 + half_width, y0 + cell_height - 7),
                fill="#c5cdd2",
                width=2,
            )
            draw.text(
                (x0 + 12, y0 + 8),
                (
                    f"旧 L2={summary['old_l2_count']} / "
                    f"新 L2={summary['new_l2_count']} / "
                    f"changed lanes={summary['changed_lane_count']}"
                ),
                fill="#374750",
                font=_font(14, bold=True),
            )
            for half, path in enumerate((old_path, new_path)):
                image = _crop_plot(path)
                image.thumbnail(
                    (half_width - 18, cell_height - 48),
                    Image.Resampling.LANCZOS,
                )
                canvas.paste(
                    image,
                    (
                        x0 + half * half_width + (half_width - image.width) // 2,
                        y0 + 37 + (cell_height - 42 - image.height) // 2,
                    ),
                )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def run(output_dir: Path) -> None:
    if output_dir.exists():
        raise H2BReviewError(f"output directory already exists: {output_dir}")
    for path in (H2A_RUN, OLD_CONTRACT_PATH, JOINT_CONTRACT_PATH, EDITOR_L2_PRIOR_PATH):
        if not path.exists():
            raise H2BReviewError(f"missing H2-B input: {path}")
    old_contract = _read_json(OLD_CONTRACT_PATH)
    joint_contract = _read_json(JOINT_CONTRACT_PATH)
    editor_l2_prior = _read_json(EDITOR_L2_PRIOR_PATH)
    output_dir.mkdir(parents=True)

    joint_rows: dict[str, list[tuple[Path, Mapping[str, Any]]]] = {
        value: [] for value in PROTOTYPE_IDS
    }
    triple_rows: dict[str, list[tuple[Path, Mapping[str, Any]]]] = {
        value: [] for value in PROTOTYPE_IDS
    }
    comparison_rows: dict[
        str,
        list[tuple[Path, Path, Mapping[str, Any]]],
    ] = {value: [] for value in PROTOTYPE_IDS}
    cases: list[dict[str, Any]] = []
    changed_case_count = 0
    total_crossings = 0

    for prototype_id in PROTOTYPE_IDS:
        for density_level in DENSITY_LEVELS:
            source_dir = H2A_RUN / prototype_id / density_level
            analysis = _read_json(source_dir / "prototype_analysis_variant.json")
            flower_mount_plan = _read_json(source_dir / "flower_mount_plan.json")
            l1_plan = _read_json(source_dir / "global_l1_flow_plan.json")
            inventory = _read_json(source_dir / "unit_candidate_inventory.json")
            if (
                l1_plan.get("schema") != "dynamic_branch_global_l1_flow_plan_v3"
                or inventory.get("source_plan_id") != l1_plan.get("plan_id")
            ):
                raise H2BReviewError(
                    f"H2-B source is not Stage3B V3: {prototype_id} {density_level}"
                )

            conflict_graph = build_conflict_graph(
                inventory,
                joint_contract,
                editor_l2_prior,
            )
            old_selection = select_global_units(
                inventory,
                conflict_graph,
                old_contract,
            )
            joint_selection = select_global_units(
                inventory,
                conflict_graph,
                joint_contract,
            )
            validate_global_selection(old_selection, conflict_graph)
            validate_global_selection(joint_selection, conflict_graph)
            crossings = _selected_crossing_count(
                joint_selection,
                conflict_graph,
            )
            if crossings:
                raise H2BReviewError(
                    f"joint selection crosses: {prototype_id} {density_level}"
                )
            total_crossings += crossings

            old_by_lane = _selection_by_lane(old_selection)
            joint_by_lane = _selection_by_lane(joint_selection)
            changed_lane_ids = sorted(
                lane_id
                for lane_id in old_by_lane
                if old_by_lane[lane_id]["candidate_id"]
                != joint_by_lane[lane_id]["candidate_id"]
            )
            if changed_lane_ids:
                changed_case_count += 1
            case_dir = output_dir / prototype_id / density_level
            case_dir.mkdir(parents=True)
            graph_path = case_dir / "candidate_conflict_graph.json"
            old_path = case_dir / "old_sequential_selection.json"
            joint_path = case_dir / "joint_selection.json"
            old_png = case_dir / "old_sequential.png"
            joint_png = case_dir / "joint_single.png"
            triple_png = case_dir / "joint_triple.png"
            _write_json(graph_path, conflict_graph)
            _write_json(old_path, old_selection)
            _write_json(joint_path, joint_selection)
            render_global_selection(
                analysis,
                inventory,
                conflict_graph,
                old_selection,
                old_png,
                triple_repeat=False,
                flower_mount_plan=flower_mount_plan,
            )
            render_global_selection(
                analysis,
                inventory,
                conflict_graph,
                joint_selection,
                joint_png,
                triple_repeat=False,
                flower_mount_plan=flower_mount_plan,
            )
            render_global_selection(
                analysis,
                inventory,
                conflict_graph,
                joint_selection,
                triple_png,
                triple_repeat=True,
                flower_mount_plan=flower_mount_plan,
            )

            trace = joint_selection["solver_trace"]
            summary = {
                "lane_count": int(joint_selection["lane_count"]),
                "upgrade_count": int(trace["achieved_upgrade_count"]),
                "l2_count": int(trace["selected_l2_count"]),
                "old_l2_count": _selection_l2_count(old_selection),
                "new_l2_count": _selection_l2_count(joint_selection),
                "changed_lane_count": len(changed_lane_ids),
            }
            joint_rows[prototype_id].append((joint_png, summary))
            triple_rows[prototype_id].append((triple_png, summary))
            comparison_rows[prototype_id].append(
                (old_png, joint_png, summary)
            )
            cases.append(
                {
                    "prototype_id": prototype_id,
                    "density_level": density_level,
                    "source_h2a_inventory": str(
                        source_dir / "unit_candidate_inventory.json"
                    ),
                    "same_inventory_for_old_and_new": True,
                    "same_conflict_graph_for_old_and_new": True,
                    "old_selected_candidate_ids": old_selection[
                        "selected_candidate_ids"
                    ],
                    "joint_selected_candidate_ids": joint_selection[
                        "selected_candidate_ids"
                    ],
                    "changed_lane_ids": changed_lane_ids,
                    "old_l2_count": summary["old_l2_count"],
                    "joint_l2_count": summary["new_l2_count"],
                    "joint_solver_trace": trace,
                    "joint_crossing_count": crossings,
                    "paths": {
                        "conflict_graph": str(graph_path),
                        "old_selection": str(old_path),
                        "joint_selection": str(joint_path),
                        "old_single": str(old_png),
                        "joint_single": str(joint_png),
                        "joint_triple": str(triple_png),
                    },
                }
            )

    if changed_case_count == 0:
        raise H2BReviewError(
            "joint selector did not change any real H2-A case"
        )
    joint_sheet = output_dir / "h2b_joint_full_structure_contact_sheet.png"
    triple_sheet = output_dir / "h2b_joint_triple_repeat_contact_sheet.png"
    comparison_sheet = output_dir / "h2b_old_vs_joint_contact_sheet.png"
    _render_joint_sheet(
        joint_rows,
        joint_sheet,
        title="H2-B 联合 BranchUnit 选择：五原型 × 三密度",
    )
    _render_joint_sheet(
        triple_rows,
        triple_sheet,
        title="H2-B 联合 BranchUnit 选择：三周期正式结构",
    )
    _render_old_new_sheet(comparison_rows, comparison_sheet)
    _write_json(
        output_dir / "manifest.json",
        {
            "schema": "dynamic_branch_h2b_joint_unit_review_manifest_v2",
            "status": "VISUAL_REVIEW_PENDING",
            "source_h2a_run": str(H2A_RUN),
            "old_selection_contract": str(OLD_CONTRACT_PATH),
            "joint_selection_contract": str(JOINT_CONTRACT_PATH),
            "case_count": len(cases),
            "changed_case_count": changed_case_count,
            "total_joint_crossing_count": total_crossings,
            "same_inventory_and_conflict_graph_comparison": True,
            "visual_approval_is_not_automatic": True,
            "contact_sheets": {
                "joint_full_structure": str(joint_sheet),
                "joint_triple_repeat": str(triple_sheet),
                "old_vs_joint": str(comparison_sheet),
            },
            "cases": cases,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the H2-B joint BranchUnit review."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    args = parser.parse_args()
    run(args.output_dir.resolve())
    print(f"H2-B joint review written to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
