#!/usr/bin/env python3
"""Build the first five coarse structural annotations for visual review.

The files remain ordinary layered SVGs that can be edited in Inkscape.  This
script deliberately records only the topology needed by HierBranchNet:
backbone, generation-1/2 branches, repeat boundaries, and flower relations.
It does not trace decorative outlines.
"""

from __future__ import annotations

import csv
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PILOT_ROOT = ROOT / "data" / "annotations" / "pilot_20"
SVG_DIR = PILOT_ROOT / "svg"

COLORS = {
    "boundary": "#000000",
    "backbone": "#0000FF",
    "primary": "#FF9900",
    "secondary": "#00B7C7",
    "tertiary": "#7A3DB8",
    "leaf": "#00FF00",
    "support": "#007800",
    "wrap": "#FFFF00",
    "flower": "#FF0000",
}


def branch(
    element_id: str,
    layer: str,
    d: str,
    generation: int,
    parent: str,
    *,
    confidence: str = "high",
    note: str = "",
) -> dict[str, str | int]:
    return {
        "shape": "path",
        "id": element_id,
        "layer": layer,
        "d": d,
        "role": "scroll_branch",
        "generation": generation,
        "parent": parent,
        "family": "scroll_swollen",
        "confidence": confidence,
        "note": note,
    }


def flower_support(
    element_id: str,
    d: str,
    parent: str,
    target: str,
    *,
    confidence: str = "high",
) -> dict[str, str]:
    return {
        "shape": "path",
        "id": element_id,
        "layer": "support",
        "d": d,
        "role": "flower_support",
        "parent": parent,
        "target": target,
        "confidence": confidence,
    }


def wrap_flower(
    element_id: str,
    d: str,
    parent: str,
    target: str,
    *,
    confidence: str = "high",
) -> dict[str, str]:
    return {
        "shape": "path",
        "id": element_id,
        "layer": "wrap",
        "d": d,
        "role": "wrap_flower",
        "parent": parent,
        "target": target,
        "confidence": confidence,
    }


def flower(
    element_id: str,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    *,
    confidence: str = "high",
) -> dict[str, str | float]:
    return {
        "shape": "ellipse",
        "id": element_id,
        "layer": "flower",
        "role": "flower_anchor",
        "cx": cx,
        "cy": cy,
        "rx": rx,
        "ry": ry,
        "confidence": confidence,
    }


PILOTS: dict[str, dict] = {
    "pilot_001": {
        "size": (696, 106),
        "boundaries": (225, 457),
        "confidence": "high",
        "summary": "Low continuous vine; one complete repeat with two primary scroll axes and one flower support.",
        "backbone": (
            "M 0,82 C 35,82 60,88 94,88 "
            "C 126,88 156,82 184,73 C 200,70 214,77 229,80 "
            "C 260,83 294,88 326,88 C 354,87 389,79 416,72 "
            "C 432,69 448,76 461,80 C 492,83 526,88 558,88 "
            "C 590,87 623,79 648,72 C 665,68 682,75 696,80"
        ),
        "objects": [
            branch(
                "primary_scroll_001_a",
                "primary",
                "M 326,88 C 300,65 276,38 246,38 C 238,40 235,51 238,60",
                1,
                "backbone_001",
                note="left/up primary axis of the complete middle repeat",
            ),
            branch(
                "primary_scroll_001_b",
                "primary",
                "M 326,88 C 332,58 341,31 358,28 C 372,27 381,38 372,46 C 365,54 360,59 356,61",
                1,
                "backbone_001",
                note="right/up primary axis of the complete middle repeat",
            ),
            branch(
                "secondary_scroll_001_a",
                "secondary",
                "M 238,60 C 246,50 257,49 263,55 C 267,61 260,67 254,64",
                2,
                "primary_scroll_001_a",
            ),
            branch(
                "secondary_scroll_001_b",
                "secondary",
                "M 356,61 C 345,58 343,52 348,47 C 353,42 361,44 363,50",
                2,
                "primary_scroll_001_b",
            ),
            flower_support(
                "flower_support_001",
                "M 416,72 C 423,66 428,58 433,52",
                "backbone_001",
                "flower_anchor_001",
            ),
            flower("flower_anchor_001", 433, 52, 17, 22),
        ],
    },
    "pilot_002": {
        "size": (700, 93),
        "boundaries": (226, 456),
        "confidence": "high",
        "summary": "Low continuous vine; broad leaf outlines compressed into two primary axes and two diagnostic curls.",
        "backbone": (
            "M 0,82 C 24,82 48,84 72,85 C 102,85 128,81 154,80 "
            "C 181,79 204,80 228,80 C 253,81 278,84 302,85 "
            "C 330,85 358,81 384,80 C 410,79 434,80 458,80 "
            "C 483,81 507,84 532,85 C 560,85 589,81 614,80 "
            "C 646,79 673,80 700,80"
        ),
        "objects": [
            branch(
                "primary_scroll_002_long",
                "primary",
                "M 384,80 C 354,64 347,43 320,31 C 287,20 253,35 228,59",
                1,
                "backbone_001",
                note="long upper sweep; not the two edges of the broad leaf",
            ),
            branch(
                "primary_scroll_002_inner",
                "primary",
                "M 384,80 C 350,70 325,50 301,50 C 279,51 260,65 244,77",
                1,
                "backbone_001",
                note="inner leaf/scroll axis",
            ),
            branch(
                "secondary_scroll_002_upper",
                "secondary",
                "M 341,51 C 338,40 340,32 351,32 C 361,32 364,42 356,48",
                2,
                "primary_scroll_002_long",
            ),
            branch(
                "secondary_scroll_002_inner",
                "secondary",
                "M 324,59 C 316,55 307,56 304,62 C 301,68 309,72 315,68",
                2,
                "primary_scroll_002_inner",
            ),
            flower_support(
                "flower_support_002",
                "M 384,80 C 401,74 414,59 429,47",
                "backbone_001",
                "flower_anchor_002",
            ),
            flower("flower_anchor_002", 429, 47, 18, 21),
        ],
    },
    "pilot_003": {
        "size": (536, 101),
        "boundaries": (75, 377),
        "confidence": "medium_high",
        "summary": "One broad U-shaped vine period with two flower relations; decorative double outlines are omitted.",
        "backbone": (
            "M 75,3 C 101,4 111,23 121,52 C 135,87 169,98 210,97 "
            "C 252,97 281,77 294,45 C 305,17 322,3 344,3 "
            "C 357,3 369,8 377,15"
        ),
        "objects": [
            branch(
                "primary_scroll_003_left",
                "primary",
                "M 121,52 C 128,31 140,19 156,18",
                1,
                "backbone_001",
            ),
            branch(
                "primary_scroll_003_pendant",
                "primary",
                "M 158,92 C 177,84 192,70 208,62",
                1,
                "backbone_001",
                note="supporting axis before the semantic flower-support terminal",
            ),
            branch(
                "primary_scroll_003_upright",
                "primary",
                "M 292,50 C 304,58 317,54 329,47",
                1,
                "backbone_001",
                confidence="medium",
            ),
            branch(
                "primary_scroll_003_inner",
                "primary",
                "M 254,91 C 264,80 269,70 269,59",
                1,
                "backbone_001",
                confidence="medium",
            ),
            branch(
                "secondary_scroll_003_left",
                "secondary",
                "M 156,18 C 167,8 179,10 179,20 C 179,29 167,31 163,23 C 160,18 164,15 169,16",
                2,
                "primary_scroll_003_left",
            ),
            flower_support(
                "flower_support_003_pendant",
                "M 208,62 C 210,63 212,64 214,64",
                "primary_scroll_003_pendant",
                "flower_anchor_003_pendant",
            ),
            flower_support(
                "flower_support_003_upright",
                "M 329,47 C 331,46 333,45 335,44",
                "primary_scroll_003_upright",
                "flower_anchor_003_upright",
                confidence="medium",
            ),
            wrap_flower(
                "wrap_flower_003_pendant",
                "M 208,62 C 197,79 230,83 238,61",
                "primary_scroll_003_pendant",
                "flower_anchor_003_pendant",
                confidence="medium",
            ),
            flower("flower_anchor_003_pendant", 214, 64, 13, 16),
            flower("flower_anchor_003_upright", 335, 44, 11, 14, confidence="medium"),
        ],
    },
    "pilot_004": {
        "size": (613, 68),
        "boundaries": (104, 247),
        "confidence": "medium",
        "summary": "Minimal ambiguous sample: one wave segment, two primary axes, one diagnostic volute, no flower labels.",
        "backbone": (
            "M 104,47 C 126,56 145,48 158,31 C 170,16 188,11 203,20 "
            "C 218,30 226,47 247,47"
        ),
        "objects": [
            branch(
                "primary_scroll_004_volute",
                "primary",
                "M 158,31 C 153,19 161,11 174,11",
                1,
                "backbone_001",
                confidence="medium",
            ),
            branch(
                "primary_scroll_004_leaf_axis",
                "primary",
                "M 203,20 C 214,25 222,34 226,43",
                1,
                "backbone_001",
                confidence="medium",
            ),
            branch(
                "secondary_scroll_004_volute",
                "secondary",
                "M 174,11 C 188,10 195,20 191,29 C 187,38 174,37 171,29 C 169,23 176,19 181,23",
                2,
                "primary_scroll_004_volute",
                confidence="medium",
            ),
        ],
    },
    "pilot_005": {
        "size": (777, 177),
        "boundaries": (126, 650),
        "confidence": "medium",
        "summary": "Silver/ambiguous sample: the continuous vine is partly inferred through occluded band forms; keep outside the first gold set until human approval.",
        "backbone": (
            "M 126,174 C 144,170 158,164 171,157 C 193,137 205,122 217,108 "
            "C 236,83 251,70 267,59 C 285,47 298,40 311,35 "
            "C 330,26 348,20 365,17 C 384,13 403,14 423,14 "
            "C 442,15 458,23 471,34 C 486,47 495,62 501,78 "
            "C 510,94 519,112 526,124 C 538,143 555,154 574,158 "
            "C 593,164 611,169 623,168 C 635,168 644,166 650,163"
        ),
        "objects": [
            branch(
                "primary_scroll_005_left_flower",
                "primary",
                "M 126,174 C 112,150 101,132 93,124",
                1,
                "backbone_001",
                confidence="medium",
            ),
            branch(
                "secondary_scroll_005_left_a",
                "secondary",
                "M 93,124 C 72,110 49,87 34,84 C 21,82 20,96 31,101",
                2,
                "primary_scroll_005_left_flower",
                confidence="medium",
            ),
            branch(
                "secondary_scroll_005_left_b",
                "secondary",
                "M 93,124 C 115,112 139,97 158,96 C 171,95 174,107 164,113",
                2,
                "primary_scroll_005_left_flower",
                confidence="medium",
            ),
            flower_support(
                "flower_support_005_left",
                "M 93,124 C 93,119 93,114 93,109",
                "primary_scroll_005_left_flower",
                "flower_anchor_005_left",
                confidence="medium",
            ),
            branch(
                "primary_scroll_005_center_flower",
                "primary",
                "M 501,78 C 500,120 476,154 455,154 C 430,168 405,170 387,135",
                1,
                "backbone_001",
                confidence="medium",
                note="inferred lower return path toward the central flower",
            ),
            branch(
                "secondary_scroll_005_center_a",
                "secondary",
                "M 387,135 C 360,120 326,95 300,102 C 288,106 291,118 302,118",
                2,
                "primary_scroll_005_center_flower",
                confidence="medium",
            ),
            branch(
                "secondary_scroll_005_center_b",
                "secondary",
                "M 387,135 C 408,128 424,117 435,112 C 446,107 451,116 445,123",
                2,
                "primary_scroll_005_center_flower",
                confidence="medium",
            ),
            flower_support(
                "flower_support_005_center",
                "M 387,135 C 386,120 386,105 386,92",
                "primary_scroll_005_center_flower",
                "flower_anchor_005_center",
                confidence="medium",
            ),
            branch(
                "primary_scroll_005_right_flower",
                "primary",
                "M 650,163 C 642,153 636,146 632,142",
                1,
                "backbone_001",
                confidence="medium",
            ),
            branch(
                "secondary_scroll_005_right_a",
                "secondary",
                "M 632,142 C 610,125 580,102 556,99 C 543,97 540,108 551,113",
                2,
                "primary_scroll_005_right_flower",
                confidence="medium",
            ),
            branch(
                "secondary_scroll_005_right_b",
                "secondary",
                "M 632,142 C 648,129 662,111 670,97 C 675,86 686,88 688,99",
                2,
                "primary_scroll_005_right_flower",
                confidence="medium",
            ),
            flower_support(
                "flower_support_005_right",
                "M 632,142 C 626,131 622,120 620,109",
                "primary_scroll_005_right_flower",
                "flower_anchor_005_right",
                confidence="medium",
            ),
            flower("flower_anchor_005_left", 93, 109, 17, 22, confidence="medium"),
            flower("flower_anchor_005_center", 386, 92, 18, 24, confidence="medium"),
            flower("flower_anchor_005_right", 620, 109, 17, 22, confidence="medium"),
        ],
    },
}


LAYER_INFO = {
    "boundary": ("01 Unit boundary | black dashed", COLORS["boundary"]),
    "backbone": ("02 Backbone | blue", COLORS["backbone"]),
    "primary": ("04 Primary branch | orange", COLORS["primary"]),
    "secondary": ("05 Secondary branch | cyan", COLORS["secondary"]),
    "tertiary": ("06 Tertiary branch | purple", COLORS["tertiary"]),
    "leaf": ("07 Leaf guide | green", COLORS["leaf"]),
    "support": ("08 Flower support | dark green", COLORS["support"]),
    "wrap": ("09 Wrap flower | yellow", COLORS["wrap"]),
    "flower": ("10 Flower anchor | red", COLORS["flower"]),
}


def attrs_text(attrs: dict[str, object]) -> str:
    return " ".join(f'{key}="{escape(str(value), quote=True)}"' for key, value in attrs.items())


def render_object(obj: dict, stroke_widths: dict[str, float]) -> str:
    layer = str(obj["layer"])
    common: dict[str, object] = {
        "id": obj["id"],
        "inkscape:label": obj["id"],
        "data-role": obj["role"],
        "data-confidence": obj.get("confidence", "high"),
    }
    if obj.get("generation") is not None:
        common["data-generation"] = obj["generation"]
    if obj.get("parent"):
        common["data-parent-id"] = obj["parent"]
    if obj.get("family"):
        common["data-terminal-family"] = obj["family"]
    if obj.get("target"):
        common["data-target-flower-id"] = obj["target"]
    if obj.get("note"):
        common["data-annotation-note"] = obj["note"]

    if obj["shape"] == "ellipse":
        common.update(
            {
                "cx": obj["cx"],
                "cy": obj["cy"],
                "rx": obj["rx"],
                "ry": obj["ry"],
                "fill": "none",
                "stroke": LAYER_INFO[layer][1],
                "stroke-width": f'{stroke_widths[layer]:.2f}',
                "vector-effect": "non-scaling-stroke",
            }
        )
        return f"    <ellipse {attrs_text(common)} />"

    common.update(
        {
            "d": obj["d"],
            "fill": "none",
            "stroke": LAYER_INFO[layer][1],
            "stroke-width": f'{stroke_widths[layer]:.2f}',
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
            "vector-effect": "non-scaling-stroke",
        }
    )
    return f"    <path {attrs_text(common)} />"


def build_svg(sample_id: str, config: dict) -> str:
    width, height = config["size"]
    left, right = config["boundaries"]
    scale = max(0.75, min(1.25, height / 100.0))
    stroke_widths = {
        "boundary": 1.6 * scale,
        "backbone": 4.8 * scale,
        "primary": 4.0 * scale,
        "secondary": 3.2 * scale,
        "tertiary": 2.7 * scale,
        "leaf": 2.6 * scale,
        "support": 3.6 * scale,
        "wrap": 4.1 * scale,
        "flower": 3.6 * scale,
    }

    by_layer: dict[str, list[dict]] = {name: [] for name in LAYER_INFO}
    by_layer["boundary"] = [
        {
            "shape": "path",
            "id": "unit_boundary_left",
            "layer": "boundary",
            "role": "unit_boundary",
            "d": f"M {left},0 V {height}",
            "side": "left",
            "confidence": "high",
        },
        {
            "shape": "path",
            "id": "unit_boundary_right",
            "layer": "boundary",
            "role": "unit_boundary",
            "d": f"M {right},0 V {height}",
            "side": "right",
            "confidence": "high",
        },
    ]
    by_layer["backbone"] = [
        {
            "shape": "path",
            "id": "backbone_001",
            "layer": "backbone",
            "role": "backbone",
            "d": config["backbone"],
            "family": "scroll_swollen",
            "confidence": config["confidence"],
            "note": "structural centerline, not an outline trace",
        }
    ]
    for obj in config["objects"]:
        by_layer[str(obj["layer"])].append(obj)

    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        '<svg xmlns="http://www.w3.org/2000/svg"',
        '     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"',
        '     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"',
        f'     width="{width}" height="{height}" viewBox="0 0 {width} {height}" version="1.1"',
        f'     data-sample-id="{sample_id}" data-annotation-spec="chanzhi_v3"',
        f'     data-annotation-confidence="{config["confidence"]}">',
        f'  <title>{sample_id} coarse structural annotation v3</title>',
        f'  <desc>{escape(config["summary"])} Source image is faded only for overlay readability.</desc>',
        f'  <metadata id="metadata1">sample={sample_id}; profile=scroll_swollen; purpose=HierBranchNet pilot visual review; human_structure_approved=false</metadata>',
        f'  <sodipodi:namedview id="namedview1" pagecolor="#d7d7d7" bordercolor="#666666" inkscape:document-units="px" showgrid="false" />',
        '  <g id="layer_source_image" inkscape:groupmode="layer" inkscape:label="00 Source image (locked)" sodipodi:insensitive="true">',
        f'    <rect id="page_background" x="0" y="0" width="{width}" height="{height}" fill="#FFFFFF" />',
        f'    <image id="source_image" x="0" y="0" width="{width}" height="{height}" href="../images/{sample_id}.png" preserveAspectRatio="none" opacity="0.52" />',
        '  </g>',
    ]

    for layer_name in LAYER_INFO:
        label, _ = LAYER_INFO[layer_name]
        lines.append(f'  <g id="layer_{layer_name}" inkscape:groupmode="layer" inkscape:label="{escape(label)}">')
        for obj in by_layer[layer_name]:
            rendered = render_object(obj, stroke_widths)
            if layer_name == "boundary":
                rendered = rendered.replace(
                    'stroke-linejoin="round"',
                    f'stroke-linejoin="round" stroke-dasharray="{5.0*scale:.2f},{4.0*scale:.2f}" data-boundary-side="{obj["side"]}"',
                )
            lines.append(rendered)
        lines.append("  </g>")

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def update_manifest() -> None:
    manifest = PILOT_ROOT / "manifest.csv"
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys()) if rows else []
    for row in rows:
        sample_id = row.get("sample_id", "")
        if sample_id not in PILOTS:
            continue
        confidence = PILOTS[sample_id]["confidence"]
        row["terminal_family"] = "scroll_swollen"
        existing = [part for part in row.get("notes", "").split(";") if part]
        additions = ["annotated_v1", f"confidence={confidence}", "awaiting_human_review"]
        row["notes"] = ";".join(dict.fromkeys(existing + additions))
        row["human_structure_approved"] = "false"
        row["visual_approved"] = "false"
    with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def write_notes() -> None:
    notes = PILOT_ROOT / "pilot_5_annotation_notes.md"
    text = """# Pilot 001-005 粗结构标注说明

这 5 张只标注 HierBranchNet 所需的粗拓扑，不描花瓣、叶瓣、双线轮廓、线宽变化和扫描噪声。

| 样本 | 结构判断 | 置信度 | 当前用途 |
|---|---|---|---|
| pilot_001 | 低位主藤 + 2 条一级卷枝 + 2 条必要二级卷草 + 1 个花位/托枝 | 高 | 可作为常规试标 |
| pilot_002 | 低位主藤 + 宽叶压缩出的 2 条一级轴 + 2 条必要卷草 + 1 个花位/托枝 | 高 | 可作为常规试标 |
| pilot_003 | 宽 U 形主藤 + 4 条一级轴 + 1 条二级卷草 + 2 个花位，其中 1 个有抱花关系 | 中高 | 可用于检验复杂花枝关系 |
| pilot_004 | 1 个波状主藤周期 + 2 条一级轴 + 1 条二级卷草，无花位 | 中 | 用于检验极简/低置信度样本 |
| pilot_005 | 遮挡下推断的连续主藤 + 3 组花枝与二级卷草 | 中 | silver/ambiguous；用户确认前不进第一批金标 |

统一约束：子枝从父线附近起生；代数固定为 backbone → generation 1 → generation 2；花位是语义锚点，不是花瓣外接框；重复边界取同相位位置；不依据对称性补造被裁切细节。

验收时优先看三件事：蓝色主藤是否符合整体走势、橙/青分支是否真从父线生长、红色花位与深绿托枝是否表达真实挂接关系。自动质检只验证格式和几何约束，不能替代视觉判断。
"""
    notes.write_text(text, encoding="utf-8")


def write_review_sheet() -> None:
    """Create a vector review sheet that references the five rendered overlays."""
    artifact_dir = ROOT / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    output = artifact_dir / "pilot_5_annotation_review.svg"
    panels = [
        ("pilot_001", "高置信度｜简单卷草 + 单花位", 110, 274),
        ("pilot_002", "高置信度｜宽叶压缩为结构轴", 434, 239),
        ("pilot_003", "中高置信度｜复杂花枝与抱花关系", 723, 339),
        ("pilot_004", "中置信度｜极简无花样本", 1112, 200),
        ("pilot_005", "中置信度 silver｜主藤含推断，暂不进金标", 1362, 410),
    ]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="1900" height="1840" viewBox="0 0 1900 1840">',
        '  <rect width="1900" height="1840" fill="#F5F6F8"/>',
        '  <text x="50" y="48" font-family="Microsoft YaHei, sans-serif" font-size="30" font-weight="700" fill="#20242A">5 张粗结构试标｜等待人工审查</text>',
        '  <text x="50" y="82" font-family="Microsoft YaHei, sans-serif" font-size="18" fill="#515862">只看中心线拓扑，不追踪花瓣、叶瓣或双线轮廓</text>',
    ]
    legend = [
        ("#0000FF", "主藤"),
        ("#FF9900", "一级分支"),
        ("#00B7C7", "二级卷草"),
        ("#007800", "承花枝"),
        ("#FFFF00", "抱花关系"),
        ("#FF0000", "花位"),
        ("#000000", "重复边界"),
    ]
    x = 850
    for color, label in legend:
        dash = ' stroke-dasharray="7,5"' if label == "重复边界" else ""
        lines.append(f'  <path d="M {x},42 H {x+34}" stroke="{color}" stroke-width="5"{dash}/>' )
        lines.append(f'  <text x="{x+42}" y="48" font-family="Microsoft YaHei, sans-serif" font-size="17" fill="#343A40">{label}</text>')
        x += 135
    for sample_id, label, label_y, image_height in panels:
        image_y = label_y + 30
        lines.extend(
            [
                f'  <text x="50" y="{label_y+20}" font-family="Microsoft YaHei, sans-serif" font-size="22" font-weight="700" fill="#20242A">{sample_id}</text>',
                f'  <text x="190" y="{label_y+20}" font-family="Microsoft YaHei, sans-serif" font-size="18" fill="#666E78">{label}</text>',
                f'  <rect x="48" y="{image_y-2}" width="1804" height="{image_height+4}" rx="5" fill="#FFFFFF" stroke="#C9CDD2" stroke-width="2"/>',
                f'  <image x="50" y="{image_y}" width="1800" height="{image_height}" href="../data/annotations/pilot_20/previews/{sample_id}_overlay.png" preserveAspectRatio="none"/>',
            ]
        )
    lines.append("</svg>")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    SVG_DIR.mkdir(parents=True, exist_ok=True)
    for sample_id, config in PILOTS.items():
        output = SVG_DIR / f"{sample_id}_annotation_v3.svg"
        output.write_text(build_svg(sample_id, config), encoding="utf-8")
        print(output)
    update_manifest()
    write_notes()
    write_review_sheet()


if __name__ == "__main__":
    main()
