#!/usr/bin/env python3
"""Render a focused before/after review of SW1-3 flower-carrier growth roots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
BEFORE = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_all_prototypes_v1" / "proto_sw_1_3"
AFTER = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_sw13_flower_root_spread_v3" / "proto_sw_1_3" / "seed_4101"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_sw13_flower_root_review_v1"


class FlowerRootReviewError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FlowerRootReviewError(f"JSON root must be an object: {path}")
    return value


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size) if path.is_file() else ImageFont.load_default()


def _flower_roots(plan: dict[str, Any]) -> list[float]:
    return [round(float(row["root_s"]), 4) for row in plan["flower_mount_plan"]["mounts"]]


def run(output: Path) -> None:
    if output.exists():
        raise FlowerRootReviewError(f"output already exists: {output}")
    output.mkdir(parents=True)
    before_plan = _read_json(BEFORE / "global_l1_flow_plan.json")
    after_plan = _read_json(AFTER / "global_l1_flow_plan.json")
    before = Image.open(BEFORE / "formal_l1_single_repeat.png").convert("RGB")
    after = Image.open(AFTER / "l1_flow.png").convert("RGB")
    try:
        # The flower-carrier roots occupy the lower-centre region in the formal render.
        crop_box = (560, 520, 1020, 790)
        panel_width, panel_height = 690, 405
        header = 126
        sheet = Image.new("RGB", (panel_width * 2, header + panel_height), "#f2f0ea")
        draw = ImageDraw.Draw(sheet)
        draw.text((24, 15), "SW1-3 花朵连接枝生长根位修正", font=_font(28, bold=True), fill="#18242d")
        draw.text(
            (24, 56),
            "只比较两根橙色花枝在主干上的起生位置；普通 L1 不是本次修改对象",
            font=_font(17),
            fill="#5b6870",
        )
        for index, (source, label, roots) in enumerate(
            (
                (before, "修改前：两个花枝共根", _flower_roots(before_plan)),
                (after, "修改后：两个花枝分根", _flower_roots(after_plan)),
            )
        ):
            crop = source.crop(crop_box).resize((panel_width, panel_height), Image.Resampling.LANCZOS)
            x = index * panel_width
            sheet.paste(crop, (x, header))
            draw.rectangle((x + 10, header + 10, x + 485, header + 48), fill="#f2f0eae8")
            draw.text(
                (x + 20, header + 15),
                f"{label}｜root_s={roots}",
                font=_font(17, bold=True),
                fill="#26343c",
            )
        sheet.save(output / "sw13_flower_root_before_after.png", "PNG", optimize=True)
    finally:
        before.close()
        after.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.output.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
