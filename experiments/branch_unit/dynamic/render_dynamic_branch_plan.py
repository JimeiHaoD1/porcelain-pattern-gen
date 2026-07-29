#!/usr/bin/env python3
"""Render stage-3 symbolic DynamicBranchPlan previews (never curve geometry)."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
PLOT_BOX = (46, 78, 1195, 940)
INFO_BOX = (1215, 78, 1568, 940)
X_MIN = -0.28
X_MAX = 1.28

COLORS = {
    "background": "#f3f1eb",
    "panel": "#ffffff",
    "ink": "#17212a",
    "muted": "#68747e",
    "grid": "#cbd2d7",
    "ghost": "#b2bac1",
    "backbone": "#18232c",
    "density_low": "#d9ede3",
    "density_high": "#3f9a6e",
    "flower_fill": "#fff8fb",
    "flower": "#b12f70",
    "reserve": "#e8a6ca",
    "primary_left": "#148c70",
    "primary_right": "#2b69bd",
    "support": "#dd7907",
    "terminal_support": "#8b4fb4",
    "occupancy": "#5c7d91",
    "danger": "#c43b37",
}


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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


def _scale(analysis: Mapping[str, Any]) -> float:
    left, top, right, bottom = PLOT_BOX
    return min(
        (right - left - 56) / (X_MAX - X_MIN),
        (bottom - top - 78) / (_local_height(analysis) + 0.10),
    )


def _xy(
    analysis: Mapping[str, Any],
    point: Sequence[float],
    *,
    offset: float = 0.0,
) -> tuple[float, float]:
    left, top, right, bottom = PLOT_BOX
    scale = _scale(analysis)
    used_width = (X_MAX - X_MIN) * scale
    used_height = (_local_height(analysis) + 0.10) * scale
    plot_left = left + 28 + 0.5 * ((right - left - 56) - used_width)
    plot_top = top + 44 + 0.5 * ((bottom - top - 62) - used_height)
    return (
        plot_left + (float(point[0]) + offset - X_MIN) * scale,
        plot_top + (float(point[1]) + 0.05) * scale,
    )


def _svg_points(
    analysis: Mapping[str, Any],
    points: Iterable[Sequence[float]],
    *,
    offset: float = 0.0,
) -> str:
    return " ".join(
        f"{x:.2f},{y:.2f}"
        for x, y in (_xy(analysis, point, offset=offset) for point in points)
    )


def _unit_color(unit: Mapping[str, Any]) -> str:
    role = str(unit["structural_role"])
    if role == "flower_support":
        return COLORS["support"]
    if role == "terminal_flower_support":
        return COLORS["terminal_support"]
    side = str(unit["root_interval_ref"].get("side_id", "left_normal"))
    return COLORS["primary_left"] if side == "left_normal" else COLORS["primary_right"]


def _symbolic_path(unit: Mapping[str, Any]) -> list[tuple[float, float]]:
    return [
        tuple(float(value) for value in point)
        for point in unit["directional_layout_intent"]["path_points"]
    ]


def _sample_path(
    analysis: Mapping[str, Any],
    start_s: float,
    end_s: float,
) -> list[Sequence[float]]:
    return [
        row["point"]
        for row in analysis["backbone"]["samples"]
        if start_s - 1e-9 <= float(row["s"]) <= end_s + 1e-9
    ]


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[float, float]],
    *,
    color: str,
    width: int,
) -> None:
    if len(points) < 2:
        return
    draw.line(points, fill=color, width=width, joint="curve")
    start, end = points[-2], points[-1]
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 12
    draw.polygon(
        [
            end,
            (
                end[0] - size * math.cos(angle - 0.55),
                end[1] - size * math.sin(angle - 0.55),
            ),
            (
                end[0] - size * math.cos(angle + 0.55),
                end[1] - size * math.sin(angle + 0.55),
            ),
        ],
        fill=color,
    )


def _wrapped_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        proposal = current + character
        if current and draw.textbbox((0, 0), proposal, font=font)[2] > max_width:
            lines.append(current)
            current = character
        else:
            current = proposal
    if current:
        lines.append(current)
    return lines


def render_png(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    output: Path,
) -> None:
    """Render a human-reviewable symbolic plan."""

    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(PLOT_BOX, 17, fill=COLORS["panel"], outline=COLORS["grid"], width=2)
    draw.rounded_rectangle(INFO_BOX, 17, fill=COLORS["panel"], outline=COLORS["grid"], width=2)
    draw.text(
        (48, 20),
        f'阶段3 v3 · 方向布局示意 · {plan["prototype_id"]} · seed {plan["seed"]}',
        font=_font(25, bold=True),
        fill=COLORS["ink"],
    )
    draw.text(
        (1310, 27),
        "方向 / 距离 / 位置 · 非枝形",
        font=_font(15, bold=True),
        fill=COLORS["danger"],
    )

    for x_value in (0.0, 1.0):
        draw.line(
            [
                _xy(analysis, (x_value, 0.0)),
                _xy(analysis, (x_value, _local_height(analysis))),
            ],
            fill=COLORS["grid"],
            width=2,
        )
    samples = [row["point"] for row in analysis["backbone"]["samples"]]
    for offset in (-1.0, 1.0):
        draw.line(
            [_xy(analysis, point, offset=offset) for point in samples],
            fill=COLORS["ghost"],
            width=4,
            joint="curve",
        )

    # Role/density field is a planning input, not selected branch geometry.
    for density_bin in plan["role_density_field"]["bins"]:
        path = _sample_path(
            analysis,
            float(density_bin["s_range"][0]),
            float(density_bin["s_range"][1]),
        )
        if len(path) < 2:
            continue
        alpha = round(45 + 130 * float(density_bin["target_density"]))
        draw.line(
            [_xy(analysis, point) for point in path],
            fill=(63, 154, 110, alpha),
            width=17,
            joint="curve",
        )

    scale = _scale(analysis)
    for flower in analysis["flowers"]:
        cx, cy = _xy(analysis, flower["center"])
        protection_rx = float(flower["protection_rx"]) * scale
        protection_ry = float(flower["protection_ry"]) * scale
        draw.ellipse(
            (
                cx - protection_rx,
                cy - protection_ry,
                cx + protection_rx,
                cy + protection_ry,
            ),
            fill=(232, 166, 202, 60),
            outline=COLORS["reserve"],
            width=3,
        )

    draw.line(
        [_xy(analysis, point) for point in samples],
        fill="#ffffff",
        width=13,
        joint="curve",
    )
    draw.line(
        [_xy(analysis, point) for point in samples],
        fill=COLORS["backbone"],
        width=7,
        joint="curve",
    )

    # Corridors are clearance envelopes, never a preview of branch thickness.
    for unit in plan["branch_units"]:
        points = [_xy(analysis, point) for point in _symbolic_path(unit)]
        radius = float(unit["occupancy_envelope"]["radius"]) * scale
        draw.line(
            points,
            fill=(92, 125, 145, 34),
            width=max(7, round(radius * 1.35)),
            joint="curve",
        )
    for unit in plan["branch_units"]:
        color = _unit_color(unit)
        points = [_xy(analysis, point) for point in _symbolic_path(unit)]
        _draw_arrow(draw, points, color=color, width=5)
        root_x, root_y = points[0]
        draw.ellipse(
            (root_x - 15, root_y - 15, root_x + 15, root_y + 15),
            fill=color,
            outline="#ffffff",
            width=3,
        )
        label = str(unit["branch_unit_id"])
        bbox = draw.textbbox((0, 0), label, font=_font(11, bold=True))
        draw.text(
            (
                root_x - (bbox[2] - bbox[0]) / 2,
                root_y - (bbox[3] - bbox[1]) / 2 - 1,
            ),
            label,
            font=_font(11, bold=True),
            fill="#ffffff",
        )

    for flower in analysis["flowers"]:
        cx, cy = _xy(analysis, flower["center"])
        rx = float(flower["rx"]) * scale
        ry = float(flower["ry"]) * scale
        draw.ellipse(
            (cx - rx, cy - ry, cx + rx, cy + ry),
            fill=COLORS["flower_fill"],
            outline=COLORS["flower"],
            width=4,
        )
        label = str(flower["flower_id"])
        bbox = draw.textbbox((0, 0), label, font=_font(14, bold=True))
        draw.text(
            (cx - (bbox[2] - bbox[0]) / 2, cy - 8),
            label,
            font=_font(14, bold=True),
            fill=COLORS["flower"],
        )

    x = INFO_BOX[0] + 20
    y = INFO_BOX[1] + 20
    max_width = INFO_BOX[2] - INFO_BOX[0] - 40
    relation = plan["classification"]["flower_branch_relation"]
    draw.text((x, y), str(relation["label_zh"]), font=_font(21, bold=True), fill=COLORS["ink"])
    y += 38
    draw.text((x, y), str(relation["family_id"]), font=_font(12), fill=COLORS["muted"])
    y += 35
    summary_rows = [
        ("任务", str(plan["task_id"])),
        ("枝组数量", str(len(plan["branch_units"]))),
        ("实例疏密", str(plan["instance_priors"]["density_class"])),
        (
            "最小根部间距",
            str(plan["global_selection"]["objective"]["minimum_root_spacing"]),
        ),
        (
            "邻近最大方向差",
            f'{plan["global_selection"]["objective"]["maximum_local_direction_difference"]}°',
        ),
        (
            "意图折线最小净距",
            str(
                plan["global_selection"]["objective"][
                    "minimum_symbolic_intent_clearance"
                ]
            ),
        ),
        ("全局可行组合", str(plan["global_selection"]["valid_set_count"])),
        ("全局得分", str(plan["global_selection"]["objective"]["total"])),
    ]
    for label, value in summary_rows:
        draw.text((x, y), label, font=_font(13), fill=COLORS["muted"])
        draw.text(
            (INFO_BOX[2] - 20, y),
            value,
            anchor="ra",
            font=_font(13, bold=True),
            fill=COLORS["ink"],
        )
        y += 29
    y += 10
    draw.text((x, y), "选中枝组", font=_font(17, bold=True), fill=COLORS["ink"])
    y += 30
    for unit in plan["branch_units"]:
        relations = unit["flower_relation_intents"]
        target = f' → {relations[0]["flower_id"]}' if relations else ""
        children = unit["child_rhythm_envelope"]
        reach = unit["primary_sweep_intent"]["length_hint"]
        reach_text = (
            f"  reach {reach:.3f}"
            if unit["structural_role"] == "terminal_flower_support"
            else ""
        )
        text = (
            f'{unit["branch_unit_id"]}  {unit["structural_role"]}{target}  '
            f'child {children["minimum_child_count"]}–{children["maximum_child_count"]}'
            f"{reach_text}"
        )
        for line in _wrapped_lines(draw, text, _font(12), max_width):
            draw.text((x, y), line, font=_font(12), fill=_unit_color(unit))
            y += 21
        y += 3
    y += 8
    draw.text((x, y), "家族硬约束", font=_font(17, bold=True), fill=COLORS["ink"])
    y += 29
    for invariant in plan["family_invariants"]:
        for index, line in enumerate(
            _wrapped_lines(draw, str(invariant), _font(12), max_width - 18)
        ):
            draw.text(
                (x, y),
                ("• " if index == 0 else "  ") + line,
                font=_font(12),
                fill=COLORS["muted"],
            )
            y += 20
        y += 2

    draw.text(
        (58, 960),
        "细透明带＝无交叉安全走廊　直线/折线箭头＝方向、距离、位置　圆点＝主藤挂接点",
        font=_font(13),
        fill=COLORS["muted"],
    )
    draw.text(
        (1545, 960),
        "不模拟枝形 · 不允许交叉 · 无末端内容",
        anchor="ra",
        font=_font(14, bold=True),
        fill=COLORS["danger"],
    )
    image.save(output, "PNG", optimize=True)


def render_svg(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    output: Path,
) -> None:
    """Render the same review layers as inspectable SVG groups."""

    samples = [row["point"] for row in analysis["backbone"]["samples"]]
    scale = _scale(analysis)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}">'
        ),
        "<defs>",
        (
            '<marker id="unit-arrow" markerWidth="8" markerHeight="8" refX="7" '
            'refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="context-stroke"/></marker>'
        ),
        "</defs>",
        f'<rect width="100%" height="100%" fill="{COLORS["background"]}"/>',
        (
            f'<rect x="{PLOT_BOX[0]}" y="{PLOT_BOX[1]}" width="{PLOT_BOX[2]-PLOT_BOX[0]}" '
            f'height="{PLOT_BOX[3]-PLOT_BOX[1]}" rx="17" fill="{COLORS["panel"]}" '
            f'stroke="{COLORS["grid"]}" stroke-width="2"/>'
        ),
        (
            f'<rect x="{INFO_BOX[0]}" y="{INFO_BOX[1]}" width="{INFO_BOX[2]-INFO_BOX[0]}" '
            f'height="{INFO_BOX[3]-INFO_BOX[1]}" rx="17" fill="{COLORS["panel"]}" '
            f'stroke="{COLORS["grid"]}" stroke-width="2"/>'
        ),
        (
            f'<text x="48" y="48" font-family="Microsoft YaHei, sans-serif" font-size="25" '
            f'font-weight="700" fill="{COLORS["ink"]}">阶段3 v3 · 方向布局示意 · '
            f'{html.escape(str(plan["prototype_id"]))} · seed {plan["seed"]}</text>'
        ),
        (
            f'<text x="1540" y="46" text-anchor="end" font-family="Microsoft YaHei, sans-serif" '
            f'font-size="15" font-weight="700" fill="{COLORS["danger"]}">方向 / 距离 / 位置 · 非枝形</text>'
        ),
    ]
    parts.append('<g data-layer="periodic-frame">')
    for x_value in (0.0, 1.0):
        top = _xy(analysis, (x_value, 0.0))
        bottom = _xy(analysis, (x_value, _local_height(analysis)))
        parts.append(
            f'<line x1="{top[0]:.2f}" y1="{top[1]:.2f}" x2="{bottom[0]:.2f}" '
            f'y2="{bottom[1]:.2f}" stroke="{COLORS["grid"]}" stroke-width="2"/>'
        )
    parts.append("</g>")
    parts.append('<g data-layer="role-density-field">')
    for density_bin in plan["role_density_field"]["bins"]:
        path = _sample_path(
            analysis,
            float(density_bin["s_range"][0]),
            float(density_bin["s_range"][1]),
        )
        if len(path) >= 2:
            opacity = 0.18 + 0.48 * float(density_bin["target_density"])
            parts.append(
                f'<polyline points="{_svg_points(analysis, path)}" fill="none" '
                f'stroke="{COLORS["density_high"]}" stroke-width="17" '
                f'opacity="{opacity:.3f}" stroke-linecap="round"/>'
            )
    parts.append("</g>")
    parts.append('<g data-layer="flower-reserves">')
    for flower in analysis["flowers"]:
        cx, cy = _xy(analysis, flower["center"])
        parts.append(
            f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" '
            f'rx="{float(flower["protection_rx"]) * scale:.2f}" '
            f'ry="{float(flower["protection_ry"]) * scale:.2f}" '
            f'fill="{COLORS["reserve"]}" fill-opacity="0.24" '
            f'stroke="{COLORS["reserve"]}" stroke-width="3"/>'
        )
    parts.append("</g>")
    parts.append('<g data-layer="backbone">')
    parts.append(
        f'<polyline points="{_svg_points(analysis, samples)}" fill="none" stroke="#ffffff" '
        'stroke-width="13" stroke-linejoin="round"/>'
    )
    parts.append(
        f'<polyline points="{_svg_points(analysis, samples)}" fill="none" '
        f'stroke="{COLORS["backbone"]}" stroke-width="7" stroke-linejoin="round"/>'
    )
    parts.append("</g>")
    parts.append(
        '<g data-layer="occupancy-envelopes" data-geometry="directional_clearance_corridor">'
    )
    for unit in plan["branch_units"]:
        points = _symbolic_path(unit)
        width = max(
            7.0,
            float(unit["occupancy_envelope"]["radius"]) * scale * 1.35,
        )
        parts.append(
            f'<polyline points="{_svg_points(analysis, points)}" fill="none" '
            f'stroke="{COLORS["occupancy"]}" stroke-width="{width:.2f}" '
            'opacity="0.14" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    parts.append("</g>")
    parts.append(
        '<g data-layer="branchunit-intents" data-geometry="directional_layout_not_branch_shape">'
    )
    for unit in plan["branch_units"]:
        color = _unit_color(unit)
        points = _symbolic_path(unit)
        parts.append(
            f'<polyline points="{_svg_points(analysis, points)}" fill="none" '
            f'stroke="{color}" stroke-width="5" stroke-linecap="round" '
            'stroke-linejoin="round" marker-end="url(#unit-arrow)"/>'
        )
    parts.append("</g>")
    parts.append('<g data-layer="flower-relation-intents">')
    for unit in plan["branch_units"]:
        for relation in unit["flower_relation_intents"]:
            parts.append(
                f'<metadata data-unit="{html.escape(str(unit["branch_unit_id"]))}" '
                f'data-flower="{html.escape(str(relation["flower_id"]))}" '
                f'data-relation="{html.escape(str(relation["relation"]))}"/>'
            )
    parts.append("</g>")
    parts.append('<g data-layer="unit-labels">')
    for unit in plan["branch_units"]:
        root = unit["occupancy_envelope"]["start"]
        x, y = _xy(analysis, root)
        color = _unit_color(unit)
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="15" fill="{color}" '
            'stroke="#ffffff" stroke-width="3"/>'
        )
        parts.append(
            f'<text x="{x:.2f}" y="{y + 4:.2f}" text-anchor="middle" '
            'font-family="Microsoft YaHei, sans-serif" font-size="11" font-weight="700" '
            f'fill="#ffffff">{html.escape(str(unit["branch_unit_id"]))}</text>'
        )
    parts.append("</g>")
    parts.append('<g data-layer="flowers">')
    for flower in analysis["flowers"]:
        cx, cy = _xy(analysis, flower["center"])
        parts.append(
            f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{float(flower["rx"]) * scale:.2f}" '
            f'ry="{float(flower["ry"]) * scale:.2f}" fill="{COLORS["flower_fill"]}" '
            f'stroke="{COLORS["flower"]}" stroke-width="4"/>'
        )
        parts.append(
            f'<text x="{cx:.2f}" y="{cy + 5:.2f}" text-anchor="middle" '
            'font-family="Microsoft YaHei, sans-serif" font-size="14" font-weight="700" '
            f'fill="{COLORS["flower"]}">{html.escape(str(flower["flower_id"]))}</text>'
        )
    parts.append("</g>")
    relation = plan["classification"]["flower_branch_relation"]
    parts.extend(
        [
            '<g data-layer="plan-summary">',
            (
                f'<text x="1235" y="122" font-family="Microsoft YaHei, sans-serif" '
                f'font-size="21" font-weight="700" fill="{COLORS["ink"]}">'
                f'{html.escape(str(relation["label_zh"]))}</text>'
            ),
            (
                f'<text x="1235" y="152" font-family="Microsoft YaHei, sans-serif" '
                f'font-size="13" fill="{COLORS["muted"]}">{html.escape(str(relation["family_id"]))}</text>'
            ),
            (
                f'<text x="1235" y="195" font-family="Microsoft YaHei, sans-serif" '
                f'font-size="14" fill="{COLORS["ink"]}">枝组数量：{len(plan["branch_units"])}</text>'
            ),
            (
                f'<text x="1235" y="225" font-family="Microsoft YaHei, sans-serif" '
                f'font-size="14" fill="{COLORS["ink"]}">最小根部间距：'
                f'{plan["global_selection"]["objective"]["minimum_root_spacing"]}</text>'
            ),
            (
                f'<text x="1235" y="255" font-family="Microsoft YaHei, sans-serif" '
                f'font-size="14" fill="{COLORS["ink"]}">邻近最大方向差：'
                f'{plan["global_selection"]["objective"]["maximum_local_direction_difference"]}°</text>'
            ),
            (
                f'<text x="1235" y="285" font-family="Microsoft YaHei, sans-serif" '
                f'font-size="14" fill="{COLORS["ink"]}">意图折线最小净距：'
                f'{plan["global_selection"]["objective"]["minimum_symbolic_intent_clearance"]}</text>'
            ),
            (
                f'<text x="1235" y="315" font-family="Microsoft YaHei, sans-serif" '
                f'font-size="14" fill="{COLORS["ink"]}">可行组合：'
                f'{plan["global_selection"]["valid_set_count"]}</text>'
            ),
            (
                f'<text x="1235" y="345" font-family="Microsoft YaHei, sans-serif" '
                f'font-size="14" fill="{COLORS["ink"]}">全局得分：'
                f'{plan["global_selection"]["objective"]["total"]}</text>'
            ),
            "</g>",
            (
                f'<text x="58" y="970" font-family="Microsoft YaHei, sans-serif" font-size="13" '
                f'fill="{COLORS["muted"]}">细透明带＝无交叉安全走廊　直线/折线箭头＝方向、距离、位置　'
                '圆点＝主藤挂接点</text>'
            ),
            (
                f'<text x="1545" y="970" text-anchor="end" '
                'font-family="Microsoft YaHei, sans-serif" font-size="14" font-weight="700" '
                f'fill="{COLORS["danger"]}">不模拟枝形 · 不允许交叉 · 无末端内容</text>'
            ),
            "</svg>",
        ]
    )
    output.write_text("\n".join(parts) + "\n", encoding="utf-8", newline="\n")


def render_contact_sheet(
    png_paths: Sequence[Path],
    output: Path,
    *,
    columns: int,
    thumb_width: int = 800,
    thumb_height: int = 500,
) -> None:
    """Combine plan previews for seed and cross-prototype comparison."""

    if not png_paths:
        raise ValueError("at least one plan PNG is required")
    rows = math.ceil(len(png_paths) / columns)
    sheet = Image.new(
        "RGB",
        (thumb_width * columns, thumb_height * rows),
        COLORS["background"],
    )
    for index, path in enumerate(png_paths):
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
