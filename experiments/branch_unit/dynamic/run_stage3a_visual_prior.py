#!/usr/bin/env python3
"""Build the formal stage-3A fixed visual prior package."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont

from fixed_visual_prior import (
    build_fixed_visual_prior,
    file_sha256,
    validate_fixed_visual_prior,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
DEFAULT_BASELINE = (
    REPO_ROOT / "artifacts" / "frozen_baselines" / "fixed_depth_7_12_2_v23"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage3a_fixed_visual_prior_v1"
)
CONTRACT_PATH = DYNAMIC_DIR / "FIXED_VISUAL_PRIOR_CONTRACT_V1.json"


class Stage3AError(RuntimeError):
    """Formal stage-3A execution failed."""


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
        raise Stage3AError(f"required review font is missing: {path}")
    return ImageFont.truetype(str(path), size)


def _draw_distribution(
    draw: ImageDraw.ImageDraw,
    label: str,
    stats: Mapping[str, Any],
    y: int,
    *,
    x0: int = 360,
    x1: int = 1460,
) -> None:
    draw.text((52, y - 11), label, font=_font(18), fill="#263642")
    minimum = float(stats["min"])
    maximum = float(stats["max"])
    span = maximum - minimum
    if span <= 1e-12:
        raise Stage3AError(f"distribution {label} is degenerate")

    def position(value: float) -> float:
        return x0 + (value - minimum) / span * (x1 - x0)

    draw.line((x0, y, x1, y), fill="#a9b4bc", width=3)
    q25 = position(float(stats["q25"]))
    median = position(float(stats["median"]))
    q75 = position(float(stats["q75"]))
    draw.rectangle((q25, y - 12, q75, y + 12), fill="#b8e0d2", outline="#287b64", width=2)
    draw.line((median, y - 17, median, y + 17), fill="#123c33", width=4)
    draw.text(
        (x0, y + 18),
        f'{minimum:.3f}',
        font=_font(14),
        fill="#64717a",
        anchor="ma",
    )
    draw.text(
        (x1, y + 18),
        f'{maximum:.3f}',
        font=_font(14),
        fill="#64717a",
        anchor="ma",
    )
    draw.text(
        (median, y - 36),
        f'{float(stats["median"]):.3f}',
        font=_font(14, bold=True),
        fill="#123c33",
        anchor="ma",
    )


def _render_summary(prior: Mapping[str, Any], output: Path) -> None:
    image = Image.new("RGB", (1540, 980), "#f3f1eb")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, 1516, 956), radius=18, fill="#ffffff", outline="#c8d0d5", width=2)
    draw.text((52, 45), "阶段3A · 固定版视觉先验", font=_font(30, bold=True), fill="#17232c")
    draw.text(
        (52, 90),
        "严格配对范围：proto_sw_1_3 · seeds 4101/4102/4103 · 仅作为视觉分布先验",
        font=_font(18),
        fill="#596872",
    )

    primary = prior["statistics"]["primary_geometry"]
    descendant = prior["statistics"]["descendant_geometry"]
    root = prior["statistics"]["primary_root_rhythm"]
    rows = [
        ("L1实际长度 / repeat", primary["actual_length_repeat"]),
        ("L1入口开度 / °", primary["entry_opening_degrees"]),
        ("L1绝对转向 / °", primary["absolute_turn_degrees"]),
        ("连续根位间距 / arc", root["consecutive_mount_gap"]),
        ("子枝长度 / repeat", descendant["actual_length_repeat"]),
        ("子枝 / 父枝长度比", descendant["child_to_parent_actual_ratio"]),
        ("子枝挂接位置", descendant["mount_fraction"]),
        ("子枝控制柄比例", descendant["handle_ratio"]),
    ]
    y = 170
    for label, stats in rows:
        _draw_distribution(draw, label, stats, y)
        y += 91

    draw.text(
        (52, 910),
        "含义：绿色箱体为中间50%分布，粗线为中位数；固定数值不会直接复制到五个原型。",
        font=_font(16),
        fill="#596872",
    )
    image.save(output)


def _write_report(prior: Mapping[str, Any], output: Path) -> None:
    primary = prior["statistics"]["primary_geometry"]
    descendant = prior["statistics"]["descendant_geometry"]
    root = prior["statistics"]["primary_root_rhythm"]
    lines = [
        "# 阶段3A固定视觉先验",
        "",
        "- 严格配对原型：`proto_sw_1_3`。",
        "- 固定基线：`fixed_depth_7_12_2_v23`。",
        "- 五原型通用方式：只使用角色条件分布，不声称五原型固定基线。",
        "- 失败策略：输入、哈希、拓扑或角色不一致时直接失败。",
        "",
        "## 核心分布",
        "",
        f'- L1实际长度/repeat：`{primary["actual_length_repeat"]["min"]}`—`{primary["actual_length_repeat"]["max"]}`，中位数 `{primary["actual_length_repeat"]["median"]}`。',
        f'- 连续根位间距：`{root["consecutive_mount_gap"]["min"]}`—`{root["consecutive_mount_gap"]["max"]}`，中位数 `{root["consecutive_mount_gap"]["median"]}`。',
        f'- 子枝/父枝长度比：`{descendant["child_to_parent_actual_ratio"]["min"]}`—`{descendant["child_to_parent_actual_ratio"]["max"]}`，中位数 `{descendant["child_to_parent_actual_ratio"]["median"]}`。',
        f'- 子枝挂接位置：`{descendant["mount_fraction"]["min"]}`—`{descendant["mount_fraction"]["max"]}`，中位数 `{descendant["mount_fraction"]["median"]}`。',
        "",
        "## 后续使用边界",
        "",
        "- `proto_sw_1_3`必须保留固定版派生候选的能力。",
        "- 其他原型只能使用角色条件分布，不复制固定拓扑和固定坐标。",
        "- 禁止独立均匀随机角度、长度和挂接位置。",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def run(output: Path, baseline: Path) -> None:
    if output.exists():
        raise Stage3AError(f"formal stage-3A output already exists: {output}")
    prior = build_fixed_visual_prior(baseline, CONTRACT_PATH)
    validate_fixed_visual_prior(prior)

    temporary = Path(tempfile.mkdtemp(prefix="stage3a_", dir=str(output.parent)))
    prior_path = temporary / "fixed_visual_prior.json"
    summary_path = temporary / "fixed_visual_prior_summary.png"
    report_path = temporary / "README.md"
    baseline_sheet_path = temporary / "fixed_baseline_contact_sheet.png"
    _write_json(prior_path, prior)
    _render_summary(prior, summary_path)
    _write_report(prior, report_path)
    shutil.copy2(baseline / "outputs" / "contact_sheet.png", baseline_sheet_path)

    manifest: dict[str, Any] = {
        "schema": "dynamic_branch_stage3a_manifest_v1",
        "stage": "3A",
        "status": "fixed_visual_prior_complete",
        "paired_baseline_scope": prior["paired_baseline_scope"],
        "files": {
            path.name: {
                "sha256": file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in (prior_path, summary_path, report_path, baseline_sheet_path)
        },
        "policies": {
            "experimental_variants_created": False,
            "silent_fallback_used": False,
            "automatic_repair_used": False,
            "cross_prototype_fixed_baseline_claimed": False,
        },
        "prior_digest": prior["prior_digest"],
    }
    _write_json(temporary / "manifest.json", manifest)
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run(args.output.resolve(), args.baseline.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
