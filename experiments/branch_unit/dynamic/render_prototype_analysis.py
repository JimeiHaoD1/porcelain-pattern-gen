#!/usr/bin/env python3
"""Render stage-2 PrototypeAnalysis as reviewable SVG and PNG overlays."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
PLOT_LEFT = 72
PLOT_TOP = 104
PLOT_RIGHT = 1190
PLOT_BOTTOM = 932
X_MIN = -0.32
X_MAX = 1.32

COLORS = {
    "background": "#f8f7f2",
    "panel": "#ffffff",
    "ink": "#182028",
    "muted": "#64717d",
    "grid": "#ccd4da",
    "ghost": "#a8b1b9",
    "blank_fill": "#bfe8d0",
    "blank_stroke": "#5aa879",
    "candidate": "#0b9a5a",
    "crowded": "#db4b47",
    "reserve_fill": "#efb6d5",
    "reserve_stroke": "#b33272",
    "zone_fill": "#f2a0a0",
    "zone_stroke": "#b62929",
    "left_arrow": "#168bb8",
    "right_arrow": "#e08627",
    "peak": "#d64141",
    "trough": "#376bc4",
    "turn": "#9255b5",
    "flower_link": "#8b4770",
}


def _local_height(analysis: Mapping[str, Any]) -> float:
    return float(analysis["coordinate_system"]["canvas_bounds"][3])


def _scale(analysis: Mapping[str, Any]) -> float:
    height = _local_height(analysis)
    return min(
        (PLOT_RIGHT - PLOT_LEFT) / (X_MAX - X_MIN),
        (PLOT_BOTTOM - PLOT_TOP) / (height + 0.10),
    )


def _xy(
    analysis: Mapping[str, Any],
    point: Sequence[float],
    *,
    offset: float = 0.0,
) -> tuple[float, float]:
    scale = _scale(analysis)
    height = _local_height(analysis)
    used_height = (height + 0.10) * scale
    top = PLOT_TOP + 0.5 * ((PLOT_BOTTOM - PLOT_TOP) - used_height)
    return (
        PLOT_LEFT + (float(point[0]) + offset - X_MIN) * scale,
        top + (float(point[1]) + 0.05) * scale,
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


def _range_rows(
    analysis: Mapping[str, Any],
    region: Mapping[str, Any],
) -> Iterable[list[dict[str, Any]]]:
    side_id = str(region["side_id"])
    probes = analysis["space_analysis"]["probes"]
    for start, end in region["s_ranges"]:
        yield [
            row
            for row in probes
            if row["side_id"] == side_id
            and float(start) - 1e-9 <= float(row["s"]) <= float(end) + 1e-9
        ]


def _region_polygons(
    analysis: Mapping[str, Any],
    region: Mapping[str, Any],
) -> Iterable[list[Sequence[float]]]:
    for rows in _range_rows(analysis, region):
        if len(rows) < 2:
            continue
        roots = [row["root"] for row in rows]
        targets = [row["target"] for row in rows]
        yield [*roots, *reversed(targets)]


def _region_backbone_paths(
    analysis: Mapping[str, Any],
    region: Mapping[str, Any],
) -> Iterable[list[Sequence[float]]]:
    samples = analysis["backbone"]["samples"]
    for start, end in region["s_ranges"]:
        rows = [
            row["point"]
            for row in samples
            if float(start) - 1e-9 <= float(row["s"]) <= float(end) + 1e-9
        ]
        if len(rows) >= 2:
            yield rows


def _region_side_paths(
    analysis: Mapping[str, Any],
    region: Mapping[str, Any],
    *,
    offset: float,
) -> Iterable[list[tuple[float, float]]]:
    for rows in _range_rows(analysis, region):
        if len(rows) < 2:
            continue
        yield [
            (
                float(row["root"][0]) + float(row["direction"][0]) * offset,
                float(row["root"][1]) + float(row["direction"][1]) * offset,
            )
            for row in rows
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


def _svg_ellipse(
    analysis: Mapping[str, Any],
    center: Sequence[float],
    rx: float,
    ry: float,
    *,
    offset: float = 0.0,
    attrs: str = "",
) -> str:
    cx, cy = _xy(analysis, center, offset=offset)
    scale = _scale(analysis)
    return (
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx * scale:.2f}" '
        f'ry="{ry * scale:.2f}" {attrs}/>'
    )


def render_svg(analysis: Mapping[str, Any], output: Path) -> None:
    """Write a layered vector overlay for human stage-2 review."""

    prototype_id = html.escape(str(analysis["prototype_id"]))
    summary = {
        "Peaks/troughs": (
            sum(row["kind"] == "peak" for row in analysis["backbone"]["extrema"]),
            sum(row["kind"] == "trough" for row in analysis["backbone"]["extrema"]),
        ),
        "Turns / long slopes": (
            len(analysis["backbone"]["turns"]),
            len(analysis["backbone"]["long_slopes"]),
        ),
        "Blank / crowded": (
            len(analysis["space_analysis"]["continuous_blank_regions"]),
            len(analysis["space_analysis"]["crowded_regions"]),
        ),
        "Candidate L1 regions": (
            len(analysis["candidate_l1_attachment_regions"]),
            "",
        ),
        "Seam pos / tangent": (
            f'{analysis["repeat_seam"]["position_gap"]:.3f}',
            f'{analysis["repeat_seam"]["tangent_mismatch_degrees"]:.1f} deg',
        ),
    }
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
            f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">'
        ),
        "<defs>",
        (
            '<marker id="arrow-left" markerWidth="7" markerHeight="7" refX="6" '
            'refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" '
            f'fill="{COLORS["left_arrow"]}"/></marker>'
        ),
        (
            '<marker id="arrow-right" markerWidth="7" markerHeight="7" refX="6" '
            'refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" '
            f'fill="{COLORS["right_arrow"]}"/></marker>'
        ),
        "</defs>",
        f'<rect width="100%" height="100%" fill="{COLORS["background"]}"/>',
        (
            f'<rect x="44" y="74" width="1180" height="884" rx="18" '
            f'fill="{COLORS["panel"]}" stroke="{COLORS["grid"]}"/>'
        ),
        (
            f'<rect x="1242" y="74" width="326" height="884" rx="18" '
            f'fill="{COLORS["panel"]}" stroke="{COLORS["grid"]}"/>'
        ),
        (
            f'<text x="48" y="46" font-family="Arial, sans-serif" font-size="25" '
            f'font-weight="700" fill="{COLORS["ink"]}">PrototypeAnalysis · {prototype_id}</text>'
        ),
        (
            f'<text x="1565" y="44" text-anchor="end" font-family="Arial, sans-serif" '
            f'font-size="14" fill="{COLORS["muted"]}">STAGE 2 · REVIEW PENDING</text>'
        ),
    ]

    # Repeat boundaries and ghost copies establish the periodic reading first.
    parts.append('<g data-layer="periodic-frame">')
    for x_value in (0.0, 1.0):
        top = _xy(analysis, (x_value, 0.0))
        bottom = _xy(analysis, (x_value, _local_height(analysis)))
        parts.append(
            f'<line x1="{top[0]:.2f}" y1="{top[1]:.2f}" '
            f'x2="{bottom[0]:.2f}" y2="{bottom[1]:.2f}" '
            f'stroke="{COLORS["grid"]}" stroke-width="2" stroke-dasharray="7 7"/>'
        )
    parts.append("</g>")

    samples = [row["point"] for row in analysis["backbone"]["samples"]]
    parts.append('<g data-layer="ghost-repeats" opacity="0.43">')
    for offset in analysis["repeat_seam"]["ghost_offsets"]:
        parts.append(
            f'<polyline points="{_svg_points(analysis, samples, offset=float(offset))}" '
            f'fill="none" stroke="{COLORS["ghost"]}" stroke-width="5"/>'
        )
        for flower in analysis["flowers"]:
            parts.append(
                _svg_ellipse(
                    analysis,
                    flower["center"],
                    float(flower["protection_rx"]),
                    float(flower["protection_ry"]),
                    offset=float(offset),
                    attrs=(
                        f'fill="none" stroke="{COLORS["ghost"]}" '
                        'stroke-width="2" stroke-dasharray="5 5"'
                    ),
                )
            )
    parts.append("</g>")

    parts.append('<g data-layer="continuous-blank-regions">')
    for region in analysis["space_analysis"]["continuous_blank_regions"]:
        for polygon in _region_polygons(analysis, region):
            parts.append(
                f'<polygon points="{_svg_points(analysis, polygon)}" '
                f'fill="{COLORS["blank_fill"]}" fill-opacity="0.43" '
                f'stroke="{COLORS["blank_stroke"]}" stroke-width="1.5"/>'
            )
    parts.append("</g>")

    parts.append('<g data-layer="prohibited-regions">')
    for region in analysis["space_analysis"]["prohibited_regions"]:
        geometry = region["geometry"]
        if geometry["type"] == "ellipse":
            parts.append(
                _svg_ellipse(
                    analysis,
                    geometry["center"],
                    float(geometry["rx"]),
                    float(geometry["ry"]),
                    attrs=(
                        f'fill="{COLORS["reserve_fill"]}" fill-opacity="0.38" '
                        f'stroke="{COLORS["reserve_stroke"]}" stroke-width="2.4" '
                        'stroke-dasharray="8 5"'
                    ),
                )
            )
        else:
            parts.append(
                f'<polygon points="{_svg_points(analysis, geometry["points"])}" '
                f'fill="{COLORS["zone_fill"]}" fill-opacity="0.42" '
                f'stroke="{COLORS["zone_stroke"]}" stroke-width="2.4"/>'
            )
    parts.append("</g>")

    parts.append('<g data-layer="space-probes">')
    probes = analysis["space_analysis"]["probes"]
    for row in probes:
        if int(row["sample_index"]) % 8 != 0:
            continue
        root = _xy(analysis, row["root"])
        target = _xy(analysis, row["target"])
        is_left = row["side_id"] == "left_normal"
        color = COLORS["left_arrow"] if is_left else COLORS["right_arrow"]
        marker = "arrow-left" if is_left else "arrow-right"
        parts.append(
            f'<line x1="{root[0]:.2f}" y1="{root[1]:.2f}" '
            f'x2="{target[0]:.2f}" y2="{target[1]:.2f}" '
            f'stroke="{color}" stroke-width="2" opacity="0.72" '
            f'marker-end="url(#{marker})"/>'
        )
    parts.append("</g>")

    parts.append('<g data-layer="flower-relations">')
    for flower in analysis["flowers"]:
        start = _xy(analysis, flower["nearest_backbone_point"])
        end = _xy(analysis, flower["center"])
        parts.append(
            f'<line x1="{start[0]:.2f}" y1="{start[1]:.2f}" '
            f'x2="{end[0]:.2f}" y2="{end[1]:.2f}" '
            f'stroke="{COLORS["flower_link"]}" stroke-width="2" stroke-dasharray="4 4"/>'
        )
        parts.append(
            _svg_ellipse(
                analysis,
                flower["center"],
                float(flower["rx"]),
                float(flower["ry"]),
                attrs=(
                    f'fill="#fff7fb" stroke="{COLORS["reserve_stroke"]}" stroke-width="3"'
                ),
            )
        )
        cx, cy = _xy(analysis, flower["center"])
        parts.append(
            f'<text x="{cx:.2f}" y="{cy + 5:.2f}" text-anchor="middle" '
            f'font-family="Arial, sans-serif" font-size="15" font-weight="700" '
            f'fill="{COLORS["reserve_stroke"]}">{html.escape(str(flower["flower_id"]))}</text>'
        )
    parts.append("</g>")

    parts.append('<g data-layer="backbone">')
    parts.append(
        f'<polyline points="{_svg_points(analysis, samples)}" fill="none" '
        f'stroke="#ffffff" stroke-width="11" stroke-linejoin="round"/>'
    )
    parts.append(
        f'<polyline points="{_svg_points(analysis, samples)}" fill="none" '
        f'stroke="{COLORS["ink"]}" stroke-width="6" stroke-linejoin="round"/>'
    )
    parts.append("</g>")

    parts.append('<g data-layer="long-slopes">')
    for slope in analysis["backbone"]["long_slopes"]:
        path = _sample_path(
            analysis,
            float(slope["start_s"]),
            float(slope["end_s"]),
        )
        if len(path) < 2:
            continue
        parts.append(
            f'<polyline points="{_svg_points(analysis, path)}" fill="none" '
            'stroke="#b59a37" stroke-width="3" stroke-dasharray="8 6" '
            'stroke-linecap="round"/>'
        )
    parts.append("</g>")

    parts.append('<g data-layer="crowded-regions">')
    for region in analysis["space_analysis"]["crowded_regions"]:
        for path in _region_side_paths(analysis, region, offset=0.014):
            parts.append(
                f'<polyline points="{_svg_points(analysis, path)}" fill="none" '
                f'stroke="{COLORS["crowded"]}" stroke-width="8" '
                'stroke-linecap="round" stroke-dasharray="5 6"/>'
            )
    parts.append("</g>")

    parts.append('<g data-layer="candidate-l1-regions">')
    for index, region in enumerate(
        analysis["candidate_l1_attachment_regions"],
        start=1,
    ):
        for path in _region_side_paths(analysis, region, offset=0.019):
            parts.append(
                f'<polyline points="{_svg_points(analysis, path)}" fill="none" '
                f'stroke="{COLORS["candidate"]}" stroke-width="8" '
                'stroke-linecap="round" opacity="0.9"/>'
            )
        root = region["best_root"]
        direction = region["best_direction"]
        label_point = (
            float(root[0]) + float(direction[0]) * 0.025,
            float(root[1]) + float(direction[1]) * 0.025,
        )
        label = _xy(analysis, label_point)
        parts.append(
            f'<circle cx="{label[0]:.2f}" cy="{label[1]:.2f}" r="13" '
            f'fill="{COLORS["candidate"]}" stroke="#ffffff" stroke-width="3"/>'
        )
        parts.append(
            f'<text x="{label[0]:.2f}" y="{label[1] + 5:.2f}" text-anchor="middle" '
            'font-family="Arial, sans-serif" font-size="12" font-weight="700" '
            f'fill="#ffffff">A{index}</text>'
        )
    parts.append("</g>")

    parts.append('<g data-layer="child-continuation-space">')
    for index, region in enumerate(
        analysis["candidate_l1_attachment_regions"],
        start=1,
    ):
        root = region["best_root"]
        direction = region["best_direction"]
        continuation_start = (
            float(root[0]) + float(direction[0]) * 0.05,
            float(root[1]) + float(direction[1]) * 0.05,
        )
        start = _xy(analysis, continuation_start)
        end = _xy(analysis, region["best_target"])
        parts.append(
            f'<line x1="{start[0]:.2f}" y1="{start[1]:.2f}" '
            f'x2="{end[0]:.2f}" y2="{end[1]:.2f}" '
            f'stroke="{COLORS["candidate"]}" stroke-width="15" opacity="0.13" '
            'stroke-linecap="round"/>'
        )
        parts.append(
            f'<line x1="{start[0]:.2f}" y1="{start[1]:.2f}" '
            f'x2="{end[0]:.2f}" y2="{end[1]:.2f}" '
            f'stroke="{COLORS["candidate"]}" stroke-width="2.5" opacity="0.72" '
            'stroke-dasharray="5 5"/>'
        )
        tx = start[0] * 0.38 + end[0] * 0.62
        ty = start[1] * 0.38 + end[1] * 0.62
        parts.append(
            f'<text x="{tx:.2f}" y="{ty - 6:.2f}" text-anchor="middle" '
            'font-family="Arial, sans-serif" font-size="12" font-weight="700" '
            f'fill="{COLORS["candidate"]}">child≤L{region["maximum_child_level_supported"]}</text>'
        )
    parts.append("</g>")

    parts.append('<g data-layer="backbone-landmarks">')
    for feature in analysis["backbone"]["extrema"]:
        x, y = _xy(analysis, feature["point"])
        color = COLORS["peak"] if feature["kind"] == "peak" else COLORS["trough"]
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="8" fill="{color}" '
            'stroke="#ffffff" stroke-width="3"/>'
        )
        parts.append(
            f'<text x="{x + 10:.2f}" y="{y - 9:.2f}" font-family="Arial, sans-serif" '
            f'font-size="13" font-weight="700" fill="{color}">'
            f'{html.escape(str(feature["feature_id"]))}</text>'
        )
    for feature in analysis["backbone"]["turns"]:
        x, y = _xy(analysis, feature["point"])
        parts.append(
            f'<rect x="{x - 7:.2f}" y="{y - 7:.2f}" width="14" height="14" '
            f'transform="rotate(45 {x:.2f} {y:.2f})" fill="{COLORS["turn"]}" '
            'stroke="#ffffff" stroke-width="2"/>'
        )
    parts.append("</g>")

    parts.extend(
        [
            (
                f'<text x="1272" y="116" font-family="Arial, sans-serif" font-size="20" '
                f'font-weight="700" fill="{COLORS["ink"]}">Analysis summary</text>'
            )
        ]
    )
    y_value = 154
    for label, values in summary.items():
        display = f"{values[0]} / {values[1]}" if values[1] != "" else str(values[0])
        parts.append(
            f'<text x="1272" y="{y_value}" font-family="Arial, sans-serif" '
            f'font-size="14" fill="{COLORS["muted"]}">{html.escape(label)}</text>'
        )
        parts.append(
            f'<text x="1538" y="{y_value}" text-anchor="end" '
            f'font-family="Arial, sans-serif" font-size="15" font-weight="700" '
            f'fill="{COLORS["ink"]}">{html.escape(display)}</text>'
        )
        y_value += 39

    legend = [
        ("blank", COLORS["blank_fill"], "continuous blank"),
        ("candidate", COLORS["candidate"], "candidate L1 interval"),
        ("crowded", COLORS["crowded"], "crowded / narrow"),
        ("reserve", COLORS["reserve_fill"], "flower reserve"),
        ("left", COLORS["left_arrow"], "left-normal probe"),
        ("right", COLORS["right_arrow"], "right-normal probe"),
    ]
    parts.append(
        f'<text x="1272" y="394" font-family="Arial, sans-serif" font-size="20" '
        f'font-weight="700" fill="{COLORS["ink"]}">Legend</text>'
    )
    y_value = 432
    for _, color, label in legend:
        parts.append(
            f'<rect x="1272" y="{y_value - 13}" width="24" height="14" rx="3" fill="{color}"/>'
        )
        parts.append(
            f'<text x="1308" y="{y_value}" font-family="Arial, sans-serif" '
            f'font-size="14" fill="{COLORS["ink"]}">{html.escape(label)}</text>'
        )
        y_value += 35
    parts.extend(
        [
            (
                f'<text x="1272" y="696" font-family="Arial, sans-serif" font-size="20" '
                f'font-weight="700" fill="{COLORS["ink"]}">Review gate</text>'
            ),
            (
                f'<text x="1272" y="732" font-family="Arial, sans-serif" font-size="14" '
                f'fill="{COLORS["muted"]}">Geometry computed.</text>'
            ),
            (
                f'<text x="1272" y="758" font-family="Arial, sans-serif" font-size="14" '
                f'fill="{COLORS["muted"]}">Visual approval required.</text>'
            ),
            (
                f'<text x="1272" y="810" font-family="Arial, sans-serif" font-size="15" '
                f'font-weight="700" fill="{COLORS["crowded"]}">No slots. No plan. No curves.</text>'
            ),
            (
                f'<text x="48" y="986" font-family="Arial, sans-serif" font-size="13" '
                f'fill="{COLORS["muted"]}">Ghost repeats at x−1 and x+1 · horizontal seam is periodic, not a wall</text>'
            ),
            "</svg>",
        ]
    )
    output.write_text("\n".join(parts) + "\n", encoding="utf-8", newline="\n")


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _draw_polyline(
    draw: ImageDraw.ImageDraw,
    analysis: Mapping[str, Any],
    points: Sequence[Sequence[float]],
    *,
    fill: str,
    width: int,
    offset: float = 0.0,
) -> None:
    if len(points) >= 2:
        draw.line(
            [_xy(analysis, point, offset=offset) for point in points],
            fill=fill,
            width=width,
            joint="curve",
        )


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    color: str,
) -> None:
    draw.line([start, end], fill=color, width=2)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 8
    wing_1 = (
        end[0] - size * math.cos(angle - 0.55),
        end[1] - size * math.sin(angle - 0.55),
    )
    wing_2 = (
        end[0] - size * math.cos(angle + 0.55),
        end[1] - size * math.sin(angle + 0.55),
    )
    draw.polygon([end, wing_1, wing_2], fill=color)


def render_png(analysis: Mapping[str, Any], output: Path) -> None:
    """Write a raster twin of the SVG overlay for contact-sheet review."""

    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((44, 74, 1224, 958), 18, fill=COLORS["panel"], outline=COLORS["grid"])
    draw.rounded_rectangle((1242, 74, 1568, 958), 18, fill=COLORS["panel"], outline=COLORS["grid"])
    draw.text(
        (48, 22),
        f'PrototypeAnalysis · {analysis["prototype_id"]}',
        font=_font(25, bold=True),
        fill=COLORS["ink"],
    )
    draw.text(
        (1310, 26),
        "STAGE 2 · REVIEW PENDING",
        font=_font(14),
        fill=COLORS["muted"],
    )
    for x_value in (0.0, 1.0):
        top = _xy(analysis, (x_value, 0.0))
        bottom = _xy(analysis, (x_value, _local_height(analysis)))
        draw.line([top, bottom], fill=COLORS["grid"], width=2)

    samples = [row["point"] for row in analysis["backbone"]["samples"]]
    for offset in analysis["repeat_seam"]["ghost_offsets"]:
        _draw_polyline(
            draw,
            analysis,
            samples,
            fill=COLORS["ghost"],
            width=5,
            offset=float(offset),
        )

    for region in analysis["space_analysis"]["continuous_blank_regions"]:
        for polygon in _region_polygons(analysis, region):
            draw.polygon(
                [_xy(analysis, point) for point in polygon],
                fill=(191, 232, 208, 112),
                outline=COLORS["blank_stroke"],
            )

    scale = _scale(analysis)
    for region in analysis["space_analysis"]["prohibited_regions"]:
        geometry = region["geometry"]
        if geometry["type"] == "ellipse":
            center = _xy(analysis, geometry["center"])
            rx = float(geometry["rx"]) * scale
            ry = float(geometry["ry"]) * scale
            draw.ellipse(
                (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry),
                fill=(239, 182, 213, 92),
                outline=COLORS["reserve_stroke"],
                width=3,
            )
        else:
            draw.polygon(
                [_xy(analysis, point) for point in geometry["points"]],
                fill=(242, 160, 160, 105),
                outline=COLORS["zone_stroke"],
            )

    for row in analysis["space_analysis"]["probes"]:
        if int(row["sample_index"]) % 8 != 0:
            continue
        color = (
            COLORS["left_arrow"]
            if row["side_id"] == "left_normal"
            else COLORS["right_arrow"]
        )
        _draw_arrow(draw, _xy(analysis, row["root"]), _xy(analysis, row["target"]), color)

    for flower in analysis["flowers"]:
        start = _xy(analysis, flower["nearest_backbone_point"])
        end = _xy(analysis, flower["center"])
        draw.line([start, end], fill=COLORS["flower_link"], width=2)
        cx, cy = end
        rx = float(flower["rx"]) * scale
        ry = float(flower["ry"]) * scale
        draw.ellipse(
            (cx - rx, cy - ry, cx + rx, cy + ry),
            fill="#fff7fb",
            outline=COLORS["reserve_stroke"],
            width=3,
        )
        label = str(flower["flower_id"])
        bbox = draw.textbbox((0, 0), label, font=_font(15, bold=True))
        draw.text(
            (cx - (bbox[2] - bbox[0]) / 2, cy - 8),
            label,
            font=_font(15, bold=True),
            fill=COLORS["reserve_stroke"],
        )

    _draw_polyline(draw, analysis, samples, fill="#ffffff", width=11)
    _draw_polyline(draw, analysis, samples, fill=COLORS["ink"], width=6)

    for slope in analysis["backbone"]["long_slopes"]:
        path = _sample_path(
            analysis,
            float(slope["start_s"]),
            float(slope["end_s"]),
        )
        _draw_polyline(draw, analysis, path, fill="#b59a37", width=3)

    for region in analysis["space_analysis"]["crowded_regions"]:
        for path in _region_side_paths(analysis, region, offset=0.014):
            _draw_polyline(draw, analysis, path, fill=COLORS["crowded"], width=8)

    for index, region in enumerate(analysis["candidate_l1_attachment_regions"], start=1):
        for path in _region_side_paths(analysis, region, offset=0.019):
            _draw_polyline(draw, analysis, path, fill=COLORS["candidate"], width=8)
        root = region["best_root"]
        direction = region["best_direction"]
        label_point = (
            float(root[0]) + float(direction[0]) * 0.025,
            float(root[1]) + float(direction[1]) * 0.025,
        )
        x, y = _xy(analysis, label_point)
        draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=COLORS["candidate"], outline="#ffffff", width=3)
        label = f"A{index}"
        bbox = draw.textbbox((0, 0), label, font=_font(12, bold=True))
        draw.text(
            (x - (bbox[2] - bbox[0]) / 2, y - 7),
            label,
            font=_font(12, bold=True),
            fill="#ffffff",
        )

    for region in analysis["candidate_l1_attachment_regions"]:
        root = region["best_root"]
        direction = region["best_direction"]
        continuation_start = (
            float(root[0]) + float(direction[0]) * 0.05,
            float(root[1]) + float(direction[1]) * 0.05,
        )
        start = _xy(analysis, continuation_start)
        end = _xy(analysis, region["best_target"])
        draw.line([start, end], fill=(11, 154, 90, 80), width=15)
        draw.line([start, end], fill=(11, 154, 90, 185), width=2)
        label = f'child<=L{region["maximum_child_level_supported"]}'
        x = start[0] * 0.38 + end[0] * 0.62
        y = start[1] * 0.38 + end[1] * 0.62
        bbox = draw.textbbox((0, 0), label, font=_font(12, bold=True))
        draw.text(
            (x - (bbox[2] - bbox[0]) / 2, y - 17),
            label,
            font=_font(12, bold=True),
            fill=COLORS["candidate"],
        )

    for feature in analysis["backbone"]["extrema"]:
        x, y = _xy(analysis, feature["point"])
        color = COLORS["peak"] if feature["kind"] == "peak" else COLORS["trough"]
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color, outline="#ffffff", width=3)
        draw.text((x + 10, y - 22), feature["feature_id"], font=_font(13, bold=True), fill=color)
    for feature in analysis["backbone"]["turns"]:
        x, y = _xy(analysis, feature["point"])
        draw.polygon([(x, y - 9), (x + 9, y), (x, y + 9), (x - 9, y)], fill=COLORS["turn"], outline="#ffffff")

    summary_lines = [
        "Analysis summary",
        f'Peaks / troughs   {sum(r["kind"] == "peak" for r in analysis["backbone"]["extrema"])} / {sum(r["kind"] == "trough" for r in analysis["backbone"]["extrema"])}',
        f'Turns / slopes     {len(analysis["backbone"]["turns"])} / {len(analysis["backbone"]["long_slopes"])}',
        f'Blank / crowded    {len(analysis["space_analysis"]["continuous_blank_regions"])} / {len(analysis["space_analysis"]["crowded_regions"])}',
        f'L1 intervals       {len(analysis["candidate_l1_attachment_regions"])}',
        f'Seam gap           {analysis["repeat_seam"]["position_gap"]:.3f}',
        f'Seam tangent       {analysis["repeat_seam"]["tangent_mismatch_degrees"]:.1f} deg',
        "",
        "Legend",
        "Green fill: blank",
        "Green line: L1 interval",
        "Red line: crowded",
        "Pink: flower reserve",
        "Blue/orange: two sides",
        "",
        "REVIEW GATE",
        "Geometry computed.",
        "Visual approval required.",
        "",
        "No slots.",
        "No plan.",
        "No curves.",
    ]
    y = 106
    for index, line in enumerate(summary_lines):
        if line in {"Analysis summary", "Legend", "REVIEW GATE"}:
            font = _font(20, bold=True)
            fill = COLORS["ink"]
            y += 10 if index else 0
        elif line in {"No slots.", "No plan.", "No curves."}:
            font = _font(15, bold=True)
            fill = COLORS["crowded"]
        else:
            font = _font(14)
            fill = COLORS["muted"]
        draw.text((1272, y), line, font=font, fill=fill)
        y += 32 if line else 18

    draw.text(
        (48, 972),
        "Ghost repeats at x-1 and x+1 · horizontal seam is periodic, not a wall",
        font=_font(13),
        fill=COLORS["muted"],
    )
    image.save(output, "PNG", optimize=True)


def render_contact_sheet(
    png_paths: Sequence[Path],
    output: Path,
    *,
    columns: int = 2,
) -> None:
    """Combine five review images without discarding their individual files."""

    if not png_paths:
        raise ValueError("at least one PNG is required")
    thumb_width = 800
    thumb_height = 500
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
        x = (index % columns) * thumb_width
        y = (index // columns) * thumb_height
        sheet.paste(thumbnail, (x, y))
    sheet.save(output, "PNG", optimize=True)
