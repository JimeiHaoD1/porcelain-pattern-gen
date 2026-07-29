#!/usr/bin/env python3
"""Render stage-4 cubic Bezier branch skeleton candidates."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from dynamic_branch_curve import sample_cubics


WIDTH = 1600
HEIGHT = 1000
PLOT_BOX = (42, 76, 1198, 938)
INFO_BOX = (1218, 76, 1568, 938)
X_RANGE = (-0.28, 1.28)
COLORS = {
    "background": "#f2f0ea",
    "panel": "#ffffff",
    "ink": "#17212a",
    "muted": "#68747e",
    "grid": "#cad2d8",
    "ghost": "#b1bac2",
    "backbone": "#18232c",
    "flower_fill": "#fff8fb",
    "flower": "#b12f70",
    "reserve": "#e8a6ca",
    "primary_a": "#138a70",
    "primary_b": "#286bc0",
    "support": "#dd7907",
    "terminal_support": "#8549aa",
    "secondary": "#168f72",
    "tertiary": "#c66b15",
    "control": "#93a3ae",
    "danger": "#c43b37",
    "ok": "#287a55",
}


def _font(
    size: int,
    *,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _local_height(analysis: Mapping[str, Any]) -> float:
    return float(analysis["coordinate_system"]["canvas_bounds"][3])


def _transform(
    analysis: Mapping[str, Any],
    point: Sequence[float],
    box: Sequence[float],
    x_range: Sequence[float],
) -> tuple[float, float]:
    left, top, right, bottom = (float(value) for value in box)
    x_min, x_max = (float(value) for value in x_range)
    y_min, y_max = -0.05, _local_height(analysis) + 0.05
    scale = min(
        (right - left - 40.0) / (x_max - x_min),
        (bottom - top - 40.0) / (y_max - y_min),
    )
    used_width = (x_max - x_min) * scale
    used_height = (y_max - y_min) * scale
    origin_x = left + 20.0 + ((right - left - 40.0) - used_width) * 0.5
    origin_y = top + 20.0 + ((bottom - top - 40.0) - used_height) * 0.5
    return (
        origin_x + (float(point[0]) - x_min) * scale,
        origin_y + (float(point[1]) - y_min) * scale,
    )


def _scale(
    analysis: Mapping[str, Any],
    box: Sequence[float],
    x_range: Sequence[float],
) -> float:
    left, top, right, bottom = (float(value) for value in box)
    return min(
        (right - left - 40.0) / (float(x_range[1]) - float(x_range[0])),
        (bottom - top - 40.0) / (_local_height(analysis) + 0.10),
    )


def _curve_color(curve: Mapping[str, Any]) -> str:
    level = int(curve.get("hierarchy_level", 1))
    if level == 2:
        return COLORS["secondary"]
    if level == 3:
        return COLORS["tertiary"]
    role = str(curve["structural_role"])
    if role == "flower_support":
        return COLORS["support"]
    if role == "terminal_flower_support":
        return COLORS["terminal_support"]
    index = int(str(curve["branch_unit_id"]).replace("BU", "") or "0")
    return COLORS["primary_a"] if index % 2 else COLORS["primary_b"]


def _curve_width_pixels(curve: Mapping[str, Any], *, repeat: bool = False) -> int:
    level = int(curve.get("hierarchy_level", 1))
    widths = {1: 6, 2: 4, 3: 3}
    width = widths.get(level, 3)
    return max(2, width - 1) if repeat else width


def _stage_label(candidate: Mapping[str, Any]) -> str:
    version = candidate.get("stage4_version")
    if version == "v3_intertwined":
        return "阶段4 v3 · 长扫掠缠枝BranchUnit"
    if version == "v2":
        return "阶段4 v2 · 动态完整BranchUnit"
    return "阶段4 v1 · 贝塞尔枝条骨架"


def _sample_curve(curve: Mapping[str, Any]) -> list[tuple[float, float]]:
    return sample_cubics(
        curve["cubic_segments"],
        samples_per_cubic=72,
    )


def _draw_scene_png(
    draw: ImageDraw.ImageDraw,
    analysis: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    box: Sequence[float],
    x_range: Sequence[float],
    offsets: Sequence[float],
    show_reserves: bool,
    show_labels: bool,
) -> None:
    scale = _scale(analysis, box, x_range)
    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    for offset in offsets:
        active = abs(offset) < 1e-12 or len(offsets) == 3
        backbone_points = [
            _transform(
                analysis,
                (float(point[0]) + offset, float(point[1])),
                box,
                x_range,
            )
            for point in backbone
        ]
        draw.line(
            backbone_points,
            fill="#ffffff",
            width=12 if active else 9,
            joint="curve",
        )
        draw.line(
            backbone_points,
            fill=COLORS["backbone"] if active else COLORS["ghost"],
            width=7 if active else 4,
            joint="curve",
        )
        for flower in analysis["flowers"]:
            center = (
                float(flower["center"][0]) + offset,
                float(flower["center"][1]),
            )
            cx, cy = _transform(analysis, center, box, x_range)
            if show_reserves:
                reserve_rx = float(flower["protection_rx"]) * scale
                reserve_ry = float(flower["protection_ry"]) * scale
                draw.ellipse(
                    (
                        cx - reserve_rx,
                        cy - reserve_ry,
                        cx + reserve_rx,
                        cy + reserve_ry,
                    ),
                    fill=(232, 166, 202, 38),
                    outline=COLORS["reserve"],
                    width=2,
                )
            rx = float(flower["rx"]) * scale
            ry = float(flower["ry"]) * scale
            draw.ellipse(
                (cx - rx, cy - ry, cx + rx, cy + ry),
                fill=COLORS["flower_fill"],
                outline=COLORS["flower"] if active else COLORS["reserve"],
                width=4 if active else 2,
            )
            if show_labels and abs(offset) < 1e-12:
                label = str(flower["flower_id"])
                bounds = draw.textbbox((0, 0), label, font=_font(13, bold=True))
                draw.text(
                    (cx - (bounds[2] - bounds[0]) * 0.5, cy - 7),
                    label,
                    font=_font(13, bold=True),
                    fill=COLORS["flower"],
                )
        for curve in candidate["branch_curves"]:
            sampled = _sample_curve(curve)
            points = [
                _transform(
                    analysis,
                    (point[0] + offset, point[1]),
                    box,
                    x_range,
                )
                for point in sampled
            ]
            color = _curve_color(curve)
            curve_width = _curve_width_pixels(curve)
            draw.line(points, fill="#ffffff", width=curve_width + 5, joint="curve")
            draw.line(points, fill=color, width=curve_width, joint="curve")
            if (
                show_labels
                and abs(offset) < 1e-12
                and int(curve.get("hierarchy_level", 1)) == 1
            ):
                root_x, root_y = points[0]
                draw.ellipse(
                    (root_x - 12, root_y - 12, root_x + 12, root_y + 12),
                    fill=color,
                    outline="#ffffff",
                    width=3,
                )
                label = str(curve["branch_unit_id"])
                bounds = draw.textbbox((0, 0), label, font=_font(9, bold=True))
                draw.text(
                    (
                        root_x - (bounds[2] - bounds[0]) * 0.5,
                        root_y - (bounds[3] - bounds[1]) * 0.5 - 1,
                    ),
                    label,
                    font=_font(9, bold=True),
                    fill="#ffffff",
                )


def render_original_png(
    analysis: Mapping[str, Any],
    candidate: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    output: Path,
) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        PLOT_BOX,
        17,
        fill=COLORS["panel"],
        outline=COLORS["grid"],
        width=2,
    )
    draw.rounded_rectangle(
        INFO_BOX,
        17,
        fill=COLORS["panel"],
        outline=COLORS["grid"],
        width=2,
    )
    draw.text(
        (46, 20),
        (
            f'{_stage_label(candidate)} · {candidate["prototype_id"]} '
            f'· seed {candidate["seed"]}'
        ),
        font=_font(25, bold=True),
        fill=COLORS["ink"],
    )
    issue_count = int(diagnostics["issue_count"])
    draw.text(
        (1540, 28),
        f'原始候选 · {"无结构标记" if issue_count == 0 else f"{issue_count}项待查"}',
        anchor="ra",
        font=_font(15, bold=True),
        fill=COLORS["ok"] if issue_count == 0 else COLORS["danger"],
    )
    for x_value in (0.0, 1.0):
        top = _transform(analysis, (x_value, 0.0), PLOT_BOX, X_RANGE)
        bottom = _transform(
            analysis,
            (x_value, _local_height(analysis)),
            PLOT_BOX,
            X_RANGE,
        )
        draw.line((top, bottom), fill=COLORS["grid"], width=2)
    _draw_scene_png(
        draw,
        analysis,
        candidate,
        box=PLOT_BOX,
        x_range=X_RANGE,
        offsets=(-1.0, 1.0),
        show_reserves=False,
        show_labels=False,
    )
    _draw_scene_png(
        draw,
        analysis,
        candidate,
        box=PLOT_BOX,
        x_range=X_RANGE,
        offsets=(0.0,),
        show_reserves=True,
        show_labels=True,
    )
    relation = candidate["classification"]["flower_branch_relation"]
    x, y = INFO_BOX[0] + 18, INFO_BOX[1] + 18
    draw.text(
        (x, y),
        str(relation["label_zh"]),
        font=_font(20, bold=True),
        fill=COLORS["ink"],
    )
    y += 34
    draw.text(
        (x, y),
        str(relation["family_id"]),
        font=_font(12),
        fill=COLORS["muted"],
    )
    y += 40
    rows = [
        ("任务", candidate["task_id"]),
        ("完整Unit", diagnostics.get("branch_unit_count", "-")),
        ("L1/L2/L3", "/".join(
            str(diagnostics.get("level_counts", {}).get(level, 0))
            for level in ("L1", "L2", "L3")
        )),
        ("枝条曲线", diagnostics["curve_count"]),
        ("三次贝塞尔段", diagnostics["cubic_segment_count"]),
        ("近直线", diagnostics.get("near_straight_curve_count", "-")),
        ("曲线交叉", diagnostics["curve_curve_crossing_count"]),
        ("非根部穿主干", diagnostics["non_root_backbone_crossing_count"]),
        ("错误花区/全部问题", diagnostics.get("wrong_flower_entry_count", 0)),
        ("诊断问题", diagnostics["issue_count"]),
    ]
    for label, value in rows:
        draw.text((x, y), str(label), font=_font(13), fill=COLORS["muted"])
        draw.text(
            (INFO_BOX[2] - 18, y),
            str(value),
            anchor="ra",
            font=_font(13, bold=True),
            fill=COLORS["ink"],
        )
        y += 30
    y += 8
    draw.text((x, y), "Unit拓扑", font=_font(17, bold=True), fill=COLORS["ink"])
    y += 30
    if candidate.get("branch_units"):
        for unit in candidate["branch_units"]:
            text = (
                f'{unit["branch_unit_id"]}  '
                f'L2={unit.get("actual_l2_count", 0)}  '
                f'L3={unit.get("actual_l3_count", 0)}'
            )
            primary = next(
                curve
                for curve in candidate["branch_curves"]
                if curve["curve_id"] == unit["primary_curve_id"]
            )
            draw.text((x, y), text, font=_font(12), fill=_curve_color(primary))
            y += 24
    else:
        for curve in candidate["branch_curves"]:
            text = (
                f'{curve["branch_unit_id"]}  {curve["structural_role"]}  '
                f'{len(curve["cubic_segments"])} cubic'
            )
            draw.text((x, y), text, font=_font(12), fill=_curve_color(curve))
            y += 24
    draw.text(
        (54, 960),
        "彩色实线＝真实三次贝塞尔中心线　圆点＝主藤挂接点　浅粉圈＝花位保护区",
        font=_font(13),
        fill=COLORS["muted"],
    )
    draw.text(
        (1542, 960),
        "仅枝条 · 未自动修正 · 无叶片/芽头/卷头",
        anchor="ra",
        font=_font(14, bold=True),
        fill=COLORS["danger"],
    )
    image.save(output, "PNG", optimize=True)


def _svg_path(curve: Mapping[str, Any], offset: float) -> str:
    cubics = curve["cubic_segments"]
    first = cubics[0]
    chunks = [
        f'M {float(first["p0"][0]) + offset:.9f},{float(first["p0"][1]):.9f}'
    ]
    for cubic in cubics:
        chunks.append(
            "C "
            f'{float(cubic["p1"][0]) + offset:.9f},{float(cubic["p1"][1]):.9f} '
            f'{float(cubic["p2"][0]) + offset:.9f},{float(cubic["p2"][1]):.9f} '
            f'{float(cubic["p3"][0]) + offset:.9f},{float(cubic["p3"][1]):.9f}'
        )
    return " ".join(chunks)


def _svg_transform_path(
    analysis: Mapping[str, Any],
    curve: Mapping[str, Any],
    *,
    box: Sequence[float],
    x_range: Sequence[float],
    offset: float,
) -> str:
    parts: list[str] = []
    for cubic_index, cubic in enumerate(curve["cubic_segments"]):
        points = [
            _transform(
                analysis,
                (float(cubic[key][0]) + offset, float(cubic[key][1])),
                box,
                x_range,
            )
            for key in ("p0", "p1", "p2", "p3")
        ]
        if cubic_index == 0:
            parts.append(f"M {points[0][0]:.3f},{points[0][1]:.3f}")
        parts.append(
            f"C {points[1][0]:.3f},{points[1][1]:.3f} "
            f"{points[2][0]:.3f},{points[2][1]:.3f} "
            f"{points[3][0]:.3f},{points[3][1]:.3f}"
        )
    return " ".join(parts)


def render_original_svg(
    analysis: Mapping[str, Any],
    candidate: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    output: Path,
) -> None:
    scale = _scale(analysis, PLOT_BOX, X_RANGE)
    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    backbone_points = " ".join(
        f"{x:.3f},{y:.3f}"
        for x, y in (
            _transform(analysis, point, PLOT_BOX, X_RANGE)
            for point in backbone
        )
    )
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
            f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">'
        ),
        f'<rect width="100%" height="100%" fill="{COLORS["background"]}"/>',
        (
            f'<rect x="{PLOT_BOX[0]}" y="{PLOT_BOX[1]}" '
            f'width="{PLOT_BOX[2]-PLOT_BOX[0]}" height="{PLOT_BOX[3]-PLOT_BOX[1]}" '
            f'rx="17" fill="{COLORS["panel"]}" stroke="{COLORS["grid"]}" stroke-width="2"/>'
        ),
        (
            f'<text x="46" y="48" font-family="Microsoft YaHei, sans-serif" '
            f'font-size="25" font-weight="700" fill="{COLORS["ink"]}">'
            f'{html.escape(_stage_label(candidate))} · {html.escape(str(candidate["prototype_id"]))} '
            f'· seed {candidate["seed"]}</text>'
        ),
        '<g data-layer="backbone">',
        (
            f'<polyline points="{backbone_points}" fill="none" stroke="#ffffff" '
            'stroke-width="12" stroke-linejoin="round"/>'
        ),
        (
            f'<polyline points="{backbone_points}" fill="none" '
            f'stroke="{COLORS["backbone"]}" stroke-width="7" stroke-linejoin="round"/>'
        ),
        "</g>",
        '<g data-layer="flower-reserves">',
    ]
    for flower in analysis["flowers"]:
        cx, cy = _transform(analysis, flower["center"], PLOT_BOX, X_RANGE)
        parts.append(
            f'<ellipse cx="{cx:.3f}" cy="{cy:.3f}" '
            f'rx="{float(flower["protection_rx"]) * scale:.3f}" '
            f'ry="{float(flower["protection_ry"]) * scale:.3f}" '
            f'fill="{COLORS["reserve"]}" fill-opacity="0.18" '
            f'stroke="{COLORS["reserve"]}" stroke-width="2"/>'
        )
    parts.extend(["</g>", '<g data-layer="bezier-branch-curves">'])
    for curve in candidate["branch_curves"]:
        path = _svg_transform_path(
            analysis,
            curve,
            box=PLOT_BOX,
            x_range=X_RANGE,
            offset=0.0,
        )
        color = _curve_color(curve)
        curve_width = _curve_width_pixels(curve)
        parts.append(
            f'<path d="{path}" fill="none" stroke="#ffffff" stroke-width="{curve_width + 5}"/>'
        )
        parts.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{curve_width}" '
            f'stroke-linecap="round" data-unit="{html.escape(str(curve["branch_unit_id"]))}" '
            f'data-cubic-count="{len(curve["cubic_segments"])}"/>'
        )
    parts.extend(["</g>", '<g data-layer="flowers">'])
    for flower in analysis["flowers"]:
        cx, cy = _transform(analysis, flower["center"], PLOT_BOX, X_RANGE)
        parts.append(
            f'<ellipse cx="{cx:.3f}" cy="{cy:.3f}" '
            f'rx="{float(flower["rx"]) * scale:.3f}" '
            f'ry="{float(flower["ry"]) * scale:.3f}" '
            f'fill="{COLORS["flower_fill"]}" stroke="{COLORS["flower"]}" stroke-width="4"/>'
        )
    parts.extend(
        [
            "</g>",
            '<metadata data-stage="4" data-geometry="cubic_bezier_branch_skeleton" '
            f'data-candidate-digest="{candidate["candidate_digest"]}" '
            f'data-issue-count="{diagnostics["issue_count"]}"/>',
            (
                f'<text x="54" y="970" font-family="Microsoft YaHei, sans-serif" '
                f'font-size="13" fill="{COLORS["muted"]}">'
                "真实三次贝塞尔中心线 · 原始候选未自动修正</text>"
            ),
            "</svg>",
        ]
    )
    output.write_text("\n".join(parts) + "\n", encoding="utf-8", newline="\n")


TRIPLE_WIDTH = 1800
TRIPLE_HEIGHT = 720
TRIPLE_BOX = (28, 72, 1772, 680)
TRIPLE_RANGE = (-1.0, 2.0)


def render_three_repeat_png(
    analysis: Mapping[str, Any],
    candidate: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    output: Path,
) -> None:
    image = Image.new(
        "RGB",
        (TRIPLE_WIDTH, TRIPLE_HEIGHT),
        COLORS["background"],
    )
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        TRIPLE_BOX,
        16,
        fill=COLORS["panel"],
        outline=COLORS["grid"],
        width=2,
    )
    draw.text(
        (34, 20),
        (
            f'{_stage_label(candidate)} · 三联repeat · {candidate["prototype_id"]} '
            f'· seed {candidate["seed"]}'
        ),
        font=_font(23, bold=True),
        fill=COLORS["ink"],
    )
    draw.text(
        (1760, 28),
        f'交叉 {diagnostics["curve_curve_crossing_count"]} · 问题 {diagnostics["issue_count"]}',
        anchor="ra",
        font=_font(14, bold=True),
        fill=COLORS["ok"]
        if diagnostics["issue_count"] == 0
        else COLORS["danger"],
    )
    for x_value in (0.0, 1.0):
        top = _transform(analysis, (x_value, 0.0), TRIPLE_BOX, TRIPLE_RANGE)
        bottom = _transform(
            analysis,
            (x_value, _local_height(analysis)),
            TRIPLE_BOX,
            TRIPLE_RANGE,
        )
        draw.line((top, bottom), fill=COLORS["grid"], width=2)
    _draw_scene_png(
        draw,
        analysis,
        candidate,
        box=TRIPLE_BOX,
        x_range=TRIPLE_RANGE,
        offsets=(-1.0, 0.0, 1.0),
        show_reserves=False,
        show_labels=False,
    )
    image.save(output, "PNG", optimize=True)


def render_three_repeat_svg(
    analysis: Mapping[str, Any],
    candidate: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    output: Path,
) -> None:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{TRIPLE_WIDTH}" '
            f'height="{TRIPLE_HEIGHT}" viewBox="0 0 {TRIPLE_WIDTH} {TRIPLE_HEIGHT}">'
        ),
        f'<rect width="100%" height="100%" fill="{COLORS["background"]}"/>',
        (
            f'<text x="34" y="48" font-family="Microsoft YaHei, sans-serif" '
            f'font-size="23" font-weight="700" fill="{COLORS["ink"]}">'
            f'{html.escape(_stage_label(candidate))} · 三联repeat · {html.escape(str(candidate["prototype_id"]))} '
            f'· seed {candidate["seed"]}</text>'
        ),
        '<g data-layer="three-repeat-bezier-skeleton">',
    ]
    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    scale = _scale(analysis, TRIPLE_BOX, TRIPLE_RANGE)
    for offset in (-1.0, 0.0, 1.0):
        backbone_points = " ".join(
            f"{x:.3f},{y:.3f}"
            for x, y in (
                _transform(
                    analysis,
                    (float(point[0]) + offset, float(point[1])),
                    TRIPLE_BOX,
                    TRIPLE_RANGE,
                )
                for point in backbone
            )
        )
        parts.append(
            f'<polyline points="{backbone_points}" fill="none" '
            f'stroke="{COLORS["backbone"]}" stroke-width="6"/>'
        )
        for curve in candidate["branch_curves"]:
            path = _svg_transform_path(
                analysis,
                curve,
                box=TRIPLE_BOX,
                x_range=TRIPLE_RANGE,
                offset=offset,
            )
            curve_width = _curve_width_pixels(curve, repeat=True)
            parts.append(
                f'<path d="{path}" fill="none" stroke="{_curve_color(curve)}" '
                f'stroke-width="{curve_width}" stroke-linecap="round"/>'
            )
        for flower in analysis["flowers"]:
            cx, cy = _transform(
                analysis,
                (
                    float(flower["center"][0]) + offset,
                    float(flower["center"][1]),
                ),
                TRIPLE_BOX,
                TRIPLE_RANGE,
            )
            parts.append(
                f'<ellipse cx="{cx:.3f}" cy="{cy:.3f}" '
                f'rx="{float(flower["rx"]) * scale:.3f}" '
                f'ry="{float(flower["ry"]) * scale:.3f}" '
                f'fill="{COLORS["flower_fill"]}" stroke="{COLORS["flower"]}" '
                'stroke-width="3"/>'
            )
    parts.extend(
        [
            "</g>",
            (
                '<metadata data-stage="4" data-view="three_repeat" '
                f'data-issue-count="{diagnostics["issue_count"]}"/>'
            ),
            "</svg>",
        ]
    )
    output.write_text("\n".join(parts) + "\n", encoding="utf-8", newline="\n")


def render_contact_sheet(
    image_paths: Sequence[Path],
    output: Path,
    *,
    columns: int = 3,
    thumb_width: int = 800,
    thumb_height: int = 500,
) -> None:
    if not image_paths:
        raise ValueError("at least one curve preview is required")
    rows = math.ceil(len(image_paths) / columns)
    sheet = Image.new(
        "RGB",
        (thumb_width * columns, thumb_height * rows),
        COLORS["background"],
    )
    for index, path in enumerate(image_paths):
        with Image.open(path) as source:
            thumb = source.convert("RGB").resize(
                (thumb_width, thumb_height),
                Image.Resampling.LANCZOS,
            )
        sheet.paste(
            thumb,
            ((index % columns) * thumb_width, (index // columns) * thumb_height),
        )
    sheet.save(output, "PNG", optimize=True)
