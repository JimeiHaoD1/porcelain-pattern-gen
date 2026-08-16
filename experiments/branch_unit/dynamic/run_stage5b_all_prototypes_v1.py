#!/usr/bin/env python3
"""Generate the five-prototype stage-5B formal L1 visual review set."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from global_l1_flow import _polylines_cross
from prototype_strategy_v1 import (
    PROTOTYPE_IDS,
    load_prototype_strategy_registry,
    resolve_prototype_strategy,
)
from render_global_l1_flow import render_png, render_svg
from run_stage3b_l1_flow import _load_inputs, generate_prototype_case


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_all_prototypes_v1"
PRODUCTION_SEED = 4101


class Stage5BAllPrototypeError(RuntimeError):
    pass


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _points(row: Mapping[str, Any]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in row["centerline"]]


def _intersection_counts(plan: Mapping[str, Any]) -> dict[str, int]:
    lanes = [_points(row) for row in plan["lanes"]]
    mounts = [
        [(float(point[0]), float(point[1])) for point in row["centerline"]]
        for row in plan["flower_mount_plan"]["mounts"]
    ]
    lane_lane = 0
    lane_mount = 0
    mount_mount = 0
    for first_index, first in enumerate(lanes):
        for second_index, second in enumerate(lanes):
            for offset in (-1.0, 0.0, 1.0):
                if second_index < first_index or (second_index == first_index and offset <= 0.0):
                    continue
                lane_lane += int(_polylines_cross(first, second, offset))
        for mount in mounts:
            lane_mount += sum(
                int(_polylines_cross(first, mount, offset))
                for offset in (-1.0, 0.0, 1.0)
            )
    for first_index, first in enumerate(mounts):
        for second_index, second in enumerate(mounts):
            for offset in (-1.0, 0.0, 1.0):
                if second_index < first_index or (second_index == first_index and offset <= 0.0):
                    continue
                mount_mount += int(_polylines_cross(first, second, offset))
    return {
        "ordinary_l1_crossing_count": lane_lane,
        "ordinary_l1_flower_mount_crossing_count": lane_mount,
        "flower_mount_crossing_count": mount_mount,
        "total_crossing_count": lane_lane + lane_mount + mount_mount,
    }


def _render_contact_sheet(
    rows: Sequence[Mapping[str, Any]],
    output: Path,
    key: str,
    title: str,
) -> None:
    cell_width, cell_height = 600, 360
    header = 88
    width, height = 3 * cell_width, header + 2 * cell_height
    sheet = Image.new("RGB", (width, height), "#f2f0ea")
    draw = ImageDraw.Draw(sheet)
    draw.text((24, 14), title, font=_font(27, bold=True), fill="#18242d")
    draw.text((24, 54), "五个原型 × seed 4101｜自动检查仅限相交｜其余等待视觉确认", font=_font(15), fill="#647078")
    for index, row in enumerate(rows):
        source = Image.open(row[key]).convert("RGB")
        try:
            resized = source.resize((cell_width, cell_height), Image.Resampling.LANCZOS)
            x = (index % 3) * cell_width
            y = header + (index // 3) * cell_height
            sheet.paste(resized, (x, y))
            label = (
                f"{row['prototype_id']}｜{row['prototype_variant_id']}｜"
                f"λ={row['physical_repeat_width_scale']:.3f}｜交叉={row['intersection_checks']['total_crossing_count']}"
            )
            draw.rectangle((x + 8, y + 8, x + 570, y + 34), fill="#f2f0eadc")
            draw.text((x + 14, y + 10), label, font=_font(13, bold=True), fill="#26343c")
        finally:
            source.close()
    sheet.save(output, "PNG", optimize=True)


def run(output: Path) -> None:
    if output.exists():
        raise Stage5BAllPrototypeError(f"output already exists: {output}")
    registry = load_prototype_strategy_registry()
    (
        inputs,
        prior,
        feedback_prior,
        curve_geometry_prior,
        contract,
        stage3_plan_contract,
        _,
    ) = _load_inputs()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage5b_all5_", dir=str(output.parent)) as directory:
        temporary = Path(directory)
        rows: list[dict[str, Any]] = []
        for prototype_id in PROTOTYPE_IDS:
            strategy = resolve_prototype_strategy({"prototype_id": prototype_id}, registry)
            result = generate_prototype_case(
                payload=inputs[prototype_id],
                prototype_strategy=strategy,
                production_seed=PRODUCTION_SEED,
                prior=prior,
                feedback_prior=feedback_prior,
                curve_geometry_prior=curve_geometry_prior,
                contract=contract,
                stage3_plan_contract=stage3_plan_contract,
                backbone_seed_override=None,
                branch_seed_override=None,
                backbone_rho=None,
            )
            case = temporary / prototype_id
            case.mkdir()
            plan = result["plan"]
            intersection_checks = _intersection_counts(plan)
            if intersection_checks["total_crossing_count"] != 0:
                raise Stage5BAllPrototypeError(
                    f"{prototype_id} formal output contains crossings: {intersection_checks}"
                )
            _write_json(case / "strict_p0_variant.json", result["variant_strict"].as_dict())
            _write_json(case / "prototype_analysis_variant.json", result["variant_analysis"])
            _write_json(case / "flower_mount_plan.json", result["flower_mount_plan"])
            _write_json(case / "global_l1_candidate_inventory.json", result["inventory"])
            _write_json(case / "global_l1_flow_plan.json", plan)
            _write_json(case / "intersection_checks.json", intersection_checks)
            single_png = case / "formal_l1_single_repeat.png"
            triple_png = case / "formal_l1_three_repeat.png"
            single_svg = case / "formal_l1_single_repeat.svg"
            triple_svg = case / "formal_l1_three_repeat.svg"
            render_png(result["variant_analysis"], plan, single_png)
            render_png(result["variant_analysis"], plan, triple_png, repeat_count=3)
            render_svg(result["variant_analysis"], plan, single_svg)
            render_svg(result["variant_analysis"], plan, triple_svg, repeat_count=3)
            rows.append(
                {
                    "prototype_id": prototype_id,
                    "family_id": strategy["family_id"],
                    "prototype_variant_id": result["variation"]["prototype_variant_id"],
                    "physical_repeat_width_scale": float(plan["repeat_layout"]["physical_repeat_width_scale"]),
                    "backbone_seed": result["backbone_seed"],
                    "branch_seed": result["branch_seed"],
                    "flower_mount_count": len(result["flower_mount_plan"]["mounts"]),
                    "ordinary_l1_count": len(plan["lanes"]),
                    "intersection_checks": intersection_checks,
                    "single_png": single_png,
                    "triple_png": triple_png,
                }
            )
        _render_contact_sheet(
            rows,
            temporary / "stage5b_all_prototypes_single_repeat.png",
            "single_png",
            "5B-5 全原型正式 L1：单周期",
        )
        _render_contact_sheet(
            rows,
            temporary / "stage5b_all_prototypes_three_repeat.png",
            "triple_png",
            "5B-5 全原型正式 L1：三周期连续性",
        )
        _write_json(
            temporary / "manifest.json",
            {
                "schema": "dynamic_branch_stage5b_all_prototypes_manifest_v1",
                "stage": "5B-5",
                "production_seed": PRODUCTION_SEED,
                "prototype_count": len(rows),
                "prototype_rows": [
                    {
                        **{key: value for key, value in row.items() if key not in {"single_png", "triple_png"}},
                        "single_png": str(row["single_png"].relative_to(temporary)).replace("\\", "/"),
                        "triple_png": str(row["triple_png"].relative_to(temporary)).replace("\\", "/"),
                    }
                    for row in rows
                ],
                "review_gate": {
                    "status": "VISUAL_REVIEW_PENDING",
                    "automatic_scope": "intersection_only",
                    "numeric_checks_cannot_approve_visual_quality": True,
                },
            },
        )
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
