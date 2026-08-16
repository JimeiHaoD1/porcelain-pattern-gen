#!/usr/bin/env python3
"""Compare SW1-3 compact root rhythm before and after residual-arc planning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont

from global_l1_flow import _polylines_cross


REPO_ROOT = Path(__file__).resolve().parents[3]
BEFORE = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_all_prototypes_v1" / "proto_sw_1_3"
AFTER = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_sw13_root_spread_v1" / "proto_sw_1_3" / "seed_4101"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_sw13_root_spread_review_v1"


class RootSpreadReviewError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RootSpreadReviewError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size) if path.is_file() else ImageFont.load_default()


def _points(row: Mapping[str, Any]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in row["centerline"]]


def _crossing_count(plan: Mapping[str, Any]) -> int:
    lanes = [_points(row) for row in plan["lanes"]]
    mounts = [_points(row) for row in plan["flower_mount_plan"]["mounts"]]
    total = 0
    for first_index, first in enumerate(lanes):
        for second_index, second in enumerate(lanes):
            for offset in (-1.0, 0.0, 1.0):
                if second_index < first_index or (second_index == first_index and offset <= 0.0):
                    continue
                total += int(_polylines_cross(first, second, offset))
        for mount in mounts:
            total += sum(int(_polylines_cross(first, mount, offset)) for offset in (-1.0, 0.0, 1.0))
    return total


def run(output: Path) -> None:
    if output.exists():
        raise RootSpreadReviewError(f"output already exists: {output}")
    output.mkdir(parents=True)
    before_plan = _read_json(BEFORE / "global_l1_flow_plan.json")
    after_plan = _read_json(AFTER / "global_l1_flow_plan.json")
    before_roots = [round(float(row["root_s"]), 6) for row in before_plan["lanes"]]
    after_roots = [round(float(row["root_s"]), 6) for row in after_plan["lanes"]]
    before_image = Image.open(BEFORE / "formal_l1_single_repeat.png").convert("RGB")
    after_image = Image.open(AFTER / "l1_flow.png").convert("RGB")
    try:
        width = 1500
        cell_width = width // 2
        cell_height = round(before_image.height * cell_width / before_image.width)
        header = 92
        sheet = Image.new("RGB", (width, header + cell_height), "#f2f0ea")
        draw = ImageDraw.Draw(sheet)
        draw.text((24, 14), "SW1-3 紧凑变体：普通 L1 根位分散修正", font=_font(27, bold=True), fill="#18242d")
        draw.text((24, 54), "左：编辑器旧间距旋转　右：扣除花枝占位后的剩余合法弧段分配", font=_font(15), fill="#647078")
        for index, (image, label, roots) in enumerate(
            ((before_image, "修正前", before_roots), (after_image, "修正后", after_roots))
        ):
            resized = image.resize((cell_width, cell_height), Image.Resampling.LANCZOS)
            sheet.paste(resized, (index * cell_width, header))
            draw.rectangle((index * cell_width + 10, header + 8, index * cell_width + 730, header + 40), fill="#f2f0eae8")
            draw.text((index * cell_width + 18, header + 11), f"{label}｜普通根位 {roots}", font=_font(14, bold=True), fill="#26343c")
        sheet.save(output / "sw13_root_spread_before_after.png", "PNG", optimize=True)
    finally:
        before_image.close()
        after_image.close()
    _write_json(
        output / "review.json",
        {
            "schema": "dynamic_branch_stage5b_sw13_root_spread_review_v1",
            "stage": "5B-5-retry",
            "prototype_id": "proto_sw_1_3",
            "prototype_variant_id": "compact",
            "before_root_s": before_roots,
            "after_root_s": after_roots,
            "root_rhythm_source_after": after_plan["root_rhythm"]["source"],
            "residual_ranges_after": after_plan["root_rhythm"]["residual_ranges"],
            "intersection_count_after": _crossing_count(after_plan),
            "review_gate": {
                "status": "VISUAL_REVIEW_PENDING",
                "automatic_scope": "intersection_only",
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.output.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
