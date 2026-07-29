#!/usr/bin/env python3
"""Render stage-2.5 morphology instructions for human visual review."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1200
SOURCE_BOX = (50, 92, 1550, 398)
PLOT_BOX = (50, 448, 1168, 1135)
INFO_BOX = (1190, 448, 1550, 1135)
X_MIN = -0.08
X_MAX = 1.08

COLORS = {
    "background": "#f3f1eb",
    "panel": "#ffffff",
    "ink": "#17212a",
    "muted": "#66737e",
    "grid": "#cbd2d7",
    "ghost": "#adb5bc",
    "backbone": "#17212a",
    "flower_fill": "#fff8fb",
    "flower": "#ad326d",
    "reserve": "#e6a6c8",
    "allowed": "#15905b",
    "semantic": "#d97706",
    "axis": "#2d63c8",
    "forbidden": "#c43b37",
    "evidence": "#6f4a8e",
}

FAMILY_TEXT = {
    "SW-1_valley_filling": {
        "binding": "谷部/谷侧枝托花，并可沿花侧包绕",
        "required": [
            "每朵花都应读成由谷部结构托住",
            "用完整枝组组织空白，不均匀撒枝",
            "花朵周围必须保留清晰呼吸圈",
        ],
        "forbidden": "禁：浮花、穿花、均匀填空",
    },
    "SW-2_axis_penetrating": {
        "binding": "花朵属于连续主轴，而不是旁贴装饰",
        "required": [
            "花前、花后仍能读出同一条主轴",
            "先建立宽阔主支枝，再安排小支枝",
            "主支枝从花朵保护区之外挂接",
        ],
        "forbidden": "禁：另插花托、旁贴花、碎枝撒点",
    },
    "SW-3_tangent_terminal": {
        "binding": "花朵是方向明确的花枝末端",
        "required": [
            "每朵花都有一条可读的末端花枝",
            "花枝起步先服从父枝切线方向",
            "次级支枝不能压过末端花枝方向",
        ],
        "forbidden": "禁：浮花、放射穿花、次枝抢主",
    },
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


def _plot_scale(analysis: Mapping[str, Any]) -> float:
    left, top, right, bottom = PLOT_BOX
    return min(
        (right - left - 70) / (X_MAX - X_MIN),
        (bottom - top - 90) / (_local_height(analysis) + 0.10),
    )


def _xy(
    analysis: Mapping[str, Any],
    point: Sequence[float],
    *,
    offset: float = 0.0,
) -> tuple[float, float]:
    left, top, right, bottom = PLOT_BOX
    scale = _plot_scale(analysis)
    used_width = (X_MAX - X_MIN) * scale
    used_height = (_local_height(analysis) + 0.10) * scale
    plot_left = left + 35 + 0.5 * ((right - left - 70) - used_width)
    plot_top = top + 48 + 0.5 * ((bottom - top - 70) - used_height)
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


def _samples(analysis: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(analysis["backbone"]["samples"])


def _sample_at_s(analysis: Mapping[str, Any], s: float) -> Mapping[str, Any]:
    wrapped = s % 1.0
    return min(
        _samples(analysis),
        key=lambda row: min(
            abs(float(row["s"]) - wrapped),
            1.0 - abs(float(row["s"]) - wrapped),
        ),
    )


def _allowed_region_paths(
    analysis: Mapping[str, Any],
) -> Iterable[list[tuple[float, float]]]:
    probes = analysis["space_analysis"]["probes"]
    for region in analysis["candidate_l1_attachment_regions"]:
        side_id = str(region["side_id"])
        for start, end in region["s_ranges"]:
            rows = [
                row
                for row in probes
                if row["side_id"] == side_id
                and float(start) - 1e-9 <= float(row["s"]) <= float(end) + 1e-9
            ]
            if len(rows) < 2:
                continue
            yield [
                (
                    float(row["root"][0]) + float(row["direction"][0]) * 0.018,
                    float(row["root"][1]) + float(row["direction"][1]) * 0.018,
                )
                for row in rows
            ]


def _ellipse_boundary_toward(
    flower: Mapping[str, Any],
    point: Sequence[float],
    *,
    outside_scale: float = 1.04,
) -> tuple[float, float]:
    center = tuple(float(v) for v in flower["center"])
    vector = (float(point[0]) - center[0], float(point[1]) - center[1])
    denominator = math.sqrt(
        (vector[0] / float(flower["rx"])) ** 2
        + (vector[1] / float(flower["ry"])) ** 2
    )
    if denominator <= 1e-9:
        return center
    return (
        center[0] + vector[0] / denominator * outside_scale,
        center[1] + vector[1] / denominator * outside_scale,
    )


def _periodic_point_near(
    point: Sequence[float],
    reference: Sequence[float],
) -> tuple[float, float]:
    x = float(point[0])
    return (
        x + round(float(reference[0]) - x),
        float(point[1]),
    )


def _semantic_guides(
    analysis: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    mode = profile["family_rule"]["visual_guide_mode"]
    guides: list[dict[str, Any]] = []
    for flower in analysis["flowers"]:
        center = tuple(float(v) for v in flower["center"])
        nearest_s = float(flower["nearest_backbone_s"])
        root = tuple(float(v) for v in flower["nearest_backbone_point"])
        if mode == "paired_flower_flank_support":
            for delta in (-0.055, 0.055):
                sample = _sample_at_s(analysis, nearest_s + delta)
                sample_point = _periodic_point_near(sample["point"], center)
                target = _ellipse_boundary_toward(flower, sample_point)
                guides.append(
                    {
                        "kind": "support",
                        "start": sample_point,
                        "end": target,
                    }
                )
        elif mode == "axis_through_flower":
            sample = _sample_at_s(analysis, nearest_s)
            tangent = tuple(float(v) for v in sample["tangent"])
            length = 0.20
            guides.append(
                {
                    "kind": "axis",
                    "start": (
                        center[0] - tangent[0] * length,
                        center[1] - tangent[1] * length,
                    ),
                    "end": (
                        center[0] + tangent[0] * length,
                        center[1] + tangent[1] * length,
                    ),
                }
            )
        elif mode == "terminal_stem_to_flower":
            candidate_roots = [
                _periodic_point_near(
                    _sample_at_s(analysis, nearest_s + delta)["point"],
                    center,
                )
                for delta in (-0.085, 0.085)
            ]
            root = max(candidate_roots, key=lambda point: math.dist(point, center))
            target = _ellipse_boundary_toward(flower, root)
            guides.append({"kind": "terminal", "start": root, "end": target})
        else:
            raise ValueError(f"unknown morphology visual guide mode: {mode}")
    return guides


def _fit_size(
    width: int,
    height: int,
    box_width: int,
    box_height: int,
) -> tuple[int, int]:
    scale = min(box_width / width, box_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


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


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str,
    width: int = 5,
    dashed: bool = False,
) -> None:
    if dashed:
        length = math.dist(start, end)
        if length > 0:
            segments = max(1, int(length / 18))
            for index in range(segments):
                if index % 2:
                    continue
                t0 = index / segments
                t1 = min(1.0, (index + 1) / segments)
                draw.line(
                    [
                        (start[0] + (end[0] - start[0]) * t0, start[1] + (end[1] - start[1]) * t0),
                        (start[0] + (end[0] - start[0]) * t1, start[1] + (end[1] - start[1]) * t1),
                    ],
                    fill=color,
                    width=width,
                )
    else:
        draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 13
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


def _profile_values(profile: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], Mapping[str, Any]]:
    relation = profile["classification"]["flower_branch_relation"]
    family_id = str(relation["family_id"])
    return family_id, relation, profile["instance_priors"]


def render_png(
    analysis: Mapping[str, Any],
    profile: Mapping[str, Any],
    source_reference: Path,
    output: Path,
) -> None:
    """Write the primary stage-2.5 review image."""

    family_id, relation, priors = _profile_values(profile)
    family_text = FAMILY_TEXT[family_id]
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text(
        (50, 24),
        f'阶段2.5 · 分支形态说明图 · {profile["prototype_id"]}',
        font=_font(27, bold=True),
        fill=COLORS["ink"],
    )
    draw.text(
        (1270, 30),
        "待人工确认",
        font=_font(17, bold=True),
        fill=COLORS["forbidden"],
    )

    draw.rounded_rectangle(SOURCE_BOX, 16, fill=COLORS["panel"], outline=COLORS["grid"], width=2)
    source_left, source_top, source_right, source_bottom = SOURCE_BOX
    draw.text(
        (source_left + 18, source_top + 12),
        "原始真实图像／标注证据",
        font=_font(16, bold=True),
        fill=COLORS["muted"],
    )
    with Image.open(source_reference) as source:
        source_rgb = source.convert("RGB")
        fitted = _fit_size(
            source_rgb.width,
            source_rgb.height,
            source_right - source_left - 40,
            source_bottom - source_top - 58,
        )
        thumb = source_rgb.resize(fitted, Image.Resampling.LANCZOS)
    paste_x = source_left + (source_right - source_left - thumb.width) // 2
    paste_y = source_top + 43 + (source_bottom - source_top - 48 - thumb.height) // 2
    image.paste(thumb, (paste_x, paste_y))

    draw.rounded_rectangle(PLOT_BOX, 16, fill=COLORS["panel"], outline=COLORS["grid"], width=2)
    draw.rounded_rectangle(INFO_BOX, 16, fill=COLORS["panel"], outline=COLORS["grid"], width=2)
    draw.text(
        (PLOT_BOX[0] + 18, PLOT_BOX[1] + 14),
        "形态意图图（箭头是语义说明，不是已选枝条）",
        font=_font(17, bold=True),
        fill=COLORS["ink"],
    )

    for x_value in (0.0, 1.0):
        draw.line(
            [_xy(analysis, (x_value, 0.0)), _xy(analysis, (x_value, _local_height(analysis)))],
            fill=COLORS["grid"],
            width=2,
        )

    samples = [row["point"] for row in _samples(analysis)]
    for offset in (-1.0, 1.0):
        draw.line(
            [_xy(analysis, point, offset=offset) for point in samples],
            fill=COLORS["ghost"],
            width=4,
            joint="curve",
        )
    for path in _allowed_region_paths(analysis):
        draw.line(
            [_xy(analysis, point) for point in path],
            fill=(21, 144, 91, 175),
            width=11,
            joint="curve",
        )

    scale = _plot_scale(analysis)
    for flower in analysis["flowers"]:
        center = _xy(analysis, flower["center"])
        protection_rx = float(flower["protection_rx"]) * scale
        protection_ry = float(flower["protection_ry"]) * scale
        draw.ellipse(
            (
                center[0] - protection_rx,
                center[1] - protection_ry,
                center[0] + protection_rx,
                center[1] + protection_ry,
            ),
            fill=(230, 166, 200, 65),
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

    for flower in analysis["flowers"]:
        center = _xy(analysis, flower["center"])
        rx = float(flower["rx"]) * scale
        ry = float(flower["ry"]) * scale
        draw.ellipse(
            (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry),
            fill=COLORS["flower_fill"],
            outline=COLORS["flower"],
            width=4,
        )
        label = str(flower["flower_id"])
        bbox = draw.textbbox((0, 0), label, font=_font(14, bold=True))
        draw.text(
            (center[0] - (bbox[2] - bbox[0]) / 2, center[1] - 9),
            label,
            font=_font(14, bold=True),
            fill=COLORS["flower"],
        )

    for guide in _semantic_guides(analysis, profile):
        color = COLORS["axis"] if guide["kind"] == "axis" else COLORS["semantic"]
        _draw_arrow(
            draw,
            _xy(analysis, guide["start"]),
            _xy(analysis, guide["end"]),
            color=color,
            dashed=guide["kind"] == "axis",
        )

    x = INFO_BOX[0] + 20
    y = INFO_BOX[1] + 18
    max_width = INFO_BOX[2] - INFO_BOX[0] - 40
    draw.text((x, y), str(relation["label_zh"]), font=_font(22, bold=True), fill=COLORS["ink"])
    y += 40
    draw.text((x, y), family_id, font=_font(13), fill=COLORS["muted"])
    y += 36
    for line in _wrapped_lines(draw, family_text["binding"], _font(16, bold=True), max_width):
        draw.text((x, y), line, font=_font(16, bold=True), fill=COLORS["semantic"])
        y += 27
    y += 12
    draw.text((x, y), "必须读出的关系", font=_font(17, bold=True), fill=COLORS["ink"])
    y += 31
    for requirement in family_text["required"]:
        for index, line in enumerate(_wrapped_lines(draw, requirement, _font(14), max_width - 22)):
            prefix = "• " if index == 0 else "  "
            draw.text((x, y), prefix + line, font=_font(14), fill=COLORS["ink"])
            y += 24
        y += 3
    y += 5
    draw.text((x, y), "该原型的实例倾向", font=_font(17, bold=True), fill=COLORS["ink"])
    y += 30
    style_lines = [
        f'疏密：{priors["density_class"]}',
        f'主支：{priors["primary_sweep_class"]}',
        f'节奏：{priors["side_rhythm"]}',
    ]
    for line in style_lines:
        for wrapped in _wrapped_lines(draw, line, _font(13), max_width):
            draw.text((x, y), wrapped, font=_font(13), fill=COLORS["muted"])
            y += 22
    y += 7
    for line in _wrapped_lines(draw, str(priors["description_zh"]), _font(14), max_width):
        draw.text((x, y), line, font=_font(14), fill=COLORS["evidence"])
        y += 24
    y += 10
    counts = priors["source_observation_counts"]
    evidence_line = (
        f'观察证据：花{counts["flower_anchor_count"]}，'
        f'枝位{counts["branch_guide_count"]}，主支{counts["primary_branch_count"]}'
    )
    for line in _wrapped_lines(draw, evidence_line, _font(13), max_width):
        draw.text((x, y), line, font=_font(13), fill=COLORS["muted"])
        y += 22
    y += 12
    for line in _wrapped_lines(draw, family_text["forbidden"], _font(14, bold=True), max_width):
        draw.text((x, y), line, font=_font(14, bold=True), fill=COLORS["forbidden"])
        y += 24

    draw.text(
        (58, 1162),
        "绿色＝允许挂接带　橙色＝花枝关系　蓝色＝贯穿轴意图　粉色＝花朵保护区",
        font=_font(14),
        fill=COLORS["muted"],
    )
    draw.text(
        (1172, 1162),
        "无槽位 · 无计划 · 无曲线",
        font=_font(15, bold=True),
        fill=COLORS["forbidden"],
    )
    image.save(output, "PNG", optimize=True)


def render_svg(
    analysis: Mapping[str, Any],
    profile: Mapping[str, Any],
    output: Path,
    *,
    source_reference_name: str = "source_reference.png",
) -> None:
    """Write a self-contained-layout SVG that references the copied source image."""

    family_id, relation, priors = _profile_values(profile)
    family_text = FAMILY_TEXT[family_id]
    samples = [row["point"] for row in _samples(analysis)]
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}">'
        ),
        "<defs>",
        (
            '<marker id="semantic-arrow" markerWidth="8" markerHeight="8" refX="7" '
            f'refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="{COLORS["semantic"]}"/></marker>'
        ),
        (
            '<marker id="axis-arrow" markerWidth="8" markerHeight="8" refX="7" '
            f'refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="{COLORS["axis"]}"/></marker>'
        ),
        "</defs>",
        f'<rect width="100%" height="100%" fill="{COLORS["background"]}"/>',
        (
            f'<text x="50" y="50" font-family="Microsoft YaHei, sans-serif" font-size="27" '
            f'font-weight="700" fill="{COLORS["ink"]}">阶段2.5 · 分支形态说明图 · '
            f'{html.escape(str(profile["prototype_id"]))}</text>'
        ),
        (
            f'<text x="1515" y="48" text-anchor="end" font-family="Microsoft YaHei, sans-serif" '
            f'font-size="17" font-weight="700" fill="{COLORS["forbidden"]}">待人工确认</text>'
        ),
        (
            f'<rect x="{SOURCE_BOX[0]}" y="{SOURCE_BOX[1]}" width="{SOURCE_BOX[2]-SOURCE_BOX[0]}" '
            f'height="{SOURCE_BOX[3]-SOURCE_BOX[1]}" rx="16" fill="{COLORS["panel"]}" '
            f'stroke="{COLORS["grid"]}" stroke-width="2"/>'
        ),
        '<g data-layer="source-reference">',
        (
            f'<text x="68" y="124" font-family="Microsoft YaHei, sans-serif" font-size="16" '
            f'font-weight="700" fill="{COLORS["muted"]}">原始真实图像／标注证据</text>'
        ),
        (
            f'<image href="{html.escape(source_reference_name)}" x="70" y="136" width="1460" '
            'height="242" preserveAspectRatio="xMidYMid meet"/>'
        ),
        "</g>",
        (
            f'<rect x="{PLOT_BOX[0]}" y="{PLOT_BOX[1]}" width="{PLOT_BOX[2]-PLOT_BOX[0]}" '
            f'height="{PLOT_BOX[3]-PLOT_BOX[1]}" rx="16" fill="{COLORS["panel"]}" '
            f'stroke="{COLORS["grid"]}" stroke-width="2"/>'
        ),
        (
            f'<rect x="{INFO_BOX[0]}" y="{INFO_BOX[1]}" width="{INFO_BOX[2]-INFO_BOX[0]}" '
            f'height="{INFO_BOX[3]-INFO_BOX[1]}" rx="16" fill="{COLORS["panel"]}" '
            f'stroke="{COLORS["grid"]}" stroke-width="2"/>'
        ),
        (
            f'<text x="68" y="482" font-family="Microsoft YaHei, sans-serif" font-size="17" '
            f'font-weight="700" fill="{COLORS["ink"]}">形态意图图（箭头是语义说明，不是已选枝条）</text>'
        ),
    ]

    parts.append('<g data-layer="allowed-attachment-regions">')
    for path in _allowed_region_paths(analysis):
        parts.append(
            f'<polyline points="{_svg_points(analysis, path)}" fill="none" '
            f'stroke="{COLORS["allowed"]}" stroke-width="11" opacity="0.72" stroke-linecap="round"/>'
        )
    parts.append("</g>")

    parts.append('<g data-layer="flower-reserve-and-prohibited-relations">')
    scale = _plot_scale(analysis)
    for flower in analysis["flowers"]:
        cx, cy = _xy(analysis, flower["center"])
        parts.append(
            f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" '
            f'rx="{float(flower["protection_rx"]) * scale:.2f}" '
            f'ry="{float(flower["protection_ry"]) * scale:.2f}" '
            f'fill="{COLORS["reserve"]}" fill-opacity="0.26" '
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

    parts.append(
        f'<g data-layer="morphology-family" data-family="{html.escape(family_id)}">'
    )
    parts.append('<g data-layer="flower-binding-intent">')
    for guide in _semantic_guides(analysis, profile):
        start = _xy(analysis, guide["start"])
        end = _xy(analysis, guide["end"])
        is_axis = guide["kind"] == "axis"
        color = COLORS["axis"] if is_axis else COLORS["semantic"]
        marker = "axis-arrow" if is_axis else "semantic-arrow"
        dash = ' stroke-dasharray="9 7"' if is_axis else ""
        parts.append(
            f'<line x1="{start[0]:.2f}" y1="{start[1]:.2f}" '
            f'x2="{end[0]:.2f}" y2="{end[1]:.2f}" stroke="{color}" '
            f'stroke-width="5"{dash} marker-end="url(#{marker})"/>'
        )
    parts.append("</g>")
    parts.append("</g>")

    x = INFO_BOX[0] + 20
    y = INFO_BOX[1] + 42
    text_rows = [
        (str(relation["label_zh"]), 22, COLORS["ink"], True),
        (family_id, 13, COLORS["muted"], False),
        (family_text["binding"], 15, COLORS["semantic"], True),
        ("必须读出的关系", 17, COLORS["ink"], True),
        *[(f"• {row}", 13, COLORS["ink"], False) for row in family_text["required"]],
        ("该原型的实例倾向", 17, COLORS["ink"], True),
        (f'疏密：{priors["density_class"]}', 13, COLORS["muted"], False),
        (f'主支：{priors["primary_sweep_class"]}', 13, COLORS["muted"], False),
        (f'节奏：{priors["side_rhythm"]}', 13, COLORS["muted"], False),
        (str(priors["description_zh"]), 13, COLORS["evidence"], False),
        (family_text["forbidden"], 13, COLORS["forbidden"], True),
    ]
    parts.append('<g data-layer="instance-priors">')
    for text, size, color, bold in text_rows:
        wrapped = [text[index : index + 22] for index in range(0, len(text), 22)] or [""]
        for row in wrapped:
            parts.append(
                f'<text x="{x}" y="{y}" font-family="Microsoft YaHei, sans-serif" '
                f'font-size="{size}" font-weight="{"700" if bold else "400"}" '
                f'fill="{color}">{html.escape(row)}</text>'
            )
            y += size + 8
        y += 8 if bold else 3
    parts.append("</g>")
    parts.extend(
        [
            (
                f'<text x="58" y="1172" font-family="Microsoft YaHei, sans-serif" font-size="14" '
                f'fill="{COLORS["muted"]}">绿色＝允许挂接带　橙色＝花枝关系　'
                '蓝色＝贯穿轴意图　粉色＝花朵保护区</text>'
            ),
            (
                f'<text x="1515" y="1172" text-anchor="end" '
                'font-family="Microsoft YaHei, sans-serif" font-size="15" font-weight="700" '
                f'fill="{COLORS["forbidden"]}">无槽位 · 无计划 · 无曲线</text>'
            ),
            "</svg>",
        ]
    )
    output.write_text("\n".join(parts) + "\n", encoding="utf-8", newline="\n")


def render_contact_sheet(
    png_paths: Sequence[Path],
    output: Path,
    *,
    columns: int = 2,
) -> None:
    """Combine all five morphology review plates at readable scale."""

    if not png_paths:
        raise ValueError("at least one PNG is required")
    thumb_width = 800
    thumb_height = 600
    rows = math.ceil(len(png_paths) / columns)
    sheet = Image.new(
        "RGB",
        (thumb_width * columns, thumb_height * rows),
        COLORS["background"],
    )
    for index, path in enumerate(png_paths):
        with Image.open(path) as source:
            thumbnail = source.convert("RGB").resize(
                (thumb_width, thumb_height),
                Image.Resampling.LANCZOS,
            )
        sheet.paste(
            thumbnail,
            ((index % columns) * thumb_width, (index // columns) * thumb_height),
        )
    sheet.save(output, "PNG", optimize=True)
