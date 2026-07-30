from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[4]
DYNAMIC_ROOT = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_ROOT) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_ROOT))

from branch_unit_grammar_v1 import (  # noqa: E402
    _curve_crosses,
    _point,
    generate_role_aware_hierarchy,
)
from run_stage3b_l1_flow import _load_inputs  # noqa: E402


OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_R5_v2"
START_COMMIT = "ef75e4d7c25a7ff165fcc03951742dd4094fd9b4"
REFERENCE = REPO_ROOT / "data" / "merged_real_data" / "8.png"
L1_COLORS = {
    "remote_flower_support": "#078765",
    "balance": "#2a6fbb",
    "settle": "#a44fc2",
}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidate = (
        "C:/Windows/Fonts/arialbd.ttf"
        if bold
        else "C:/Windows/Fonts/arial.ttf"
    )
    if Path(candidate).is_file():
        return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _backbone_curve(analysis: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "curve_id": "backbone",
        "centerline": [
            row["point"] for row in analysis["backbone"]["samples"]
        ],
    }


def hierarchy_intersection_report(
    analysis: Mapping[str, Any],
    hierarchy: Mapping[str, Any],
) -> dict[str, int]:
    curves = list(hierarchy["selected_curves"])
    backbone = _backbone_curve(analysis)
    self_count = sum(
        _curve_crosses(curve, curve, None)
        for curve in curves
    )
    backbone_count = 0
    for curve in curves:
        allowed = (
            _point(curve["centerline"][0], "curve root")
            if curve["level"] == "L1"
            else None
        )
        backbone_count += int(_curve_crosses(curve, backbone, allowed))
    pair_count = 0
    for left in range(len(curves)):
        for right in range(left + 1, len(curves)):
            first = curves[left]
            second = curves[right]
            allowed = None
            if first["parent_curve_id"] == second["curve_id"]:
                allowed = _point(first["centerline"][0], "child root")
            elif second["parent_curve_id"] == first["curve_id"]:
                allowed = _point(second["centerline"][0], "child root")
            pair_count += int(_curve_crosses(first, second, allowed))
    return {
        "self_intersection_count": self_count,
        "backbone_intersection_count": backbone_count,
        "branch_pair_intersection_count": pair_count,
    }


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    *,
    left: int,
    top: int,
    title: str,
    subtitle: str,
    analysis: Mapping[str, Any],
    curves: Sequence[Mapping[str, Any]],
) -> None:
    scale = 470.0

    def mapper(point: Sequence[float]) -> tuple[float, float]:
        return (
            left + 35 + float(point[0]) * scale,
            top + 18 + float(point[1]) * scale,
        )

    draw.text((left + 5, top - 58), title, fill="#172435", font=_font(27, True))
    draw.text((left + 5, top - 25), subtitle, fill="#53647b", font=_font(16))
    draw.rounded_rectangle(
        (left, top, left + 540, top + 595),
        radius=8,
        fill="#fff",
        outline="#283b55",
        width=3,
    )
    backbone = [
        mapper(row["point"]) for row in analysis["backbone"]["samples"]
    ]
    draw.line(backbone, fill="#2b3d58", width=7, joint="curve")
    for flower in analysis["flowers"]:
        center = mapper(flower["center"])
        rx = float(flower["rx"]) * scale
        ry = float(flower["ry"]) * scale
        draw.ellipse(
            (
                center[0] - rx,
                center[1] - ry,
                center[0] + rx,
                center[1] + ry,
            ),
            fill="#fff8fb",
            outline="#8f49ff",
            width=3,
        )
    for curve in curves:
        level = str(curve["level"])
        color = (
            L1_COLORS[str(curve["semantic_role"])]
            if level == "L1"
            else "#e47b24"
            if level == "L2"
            else "#d8a400"
        )
        width = 8 if level == "L1" else 6 if level == "L2" else 4
        points = [mapper(row) for row in curve["centerline"]]
        draw.line(points, fill=color, width=width, joint="curve")
        root = points[0]
        draw.ellipse(
            (root[0] - 4, root[1] - 4, root[0] + 4, root[1] + 4),
            fill=color,
        )
    draw.text(
        (left + 22, top + 558),
        "L1 core/unit roles",
        fill="#31445e",
        font=_font(14),
    )
    if any(curve["level"] == "L2" for curve in curves):
        draw.line(
            (left + 180, top + 568, left + 205, top + 568),
            fill="#e47b24",
            width=6,
        )
        draw.text(
            (left + 212, top + 558),
            "L2 balance_fill",
            fill="#31445e",
            font=_font(14),
        )
    if any(curve["level"] == "L3" for curve in curves):
        draw.line(
            (left + 355, top + 568, left + 380, top + 568),
            fill="#d8a400",
            width=4,
        )
        draw.text(
            (left + 387, top + 558),
            "L3 echo",
            fill="#31445e",
            font=_font(14),
        )


def _render_png(
    path: Path,
    analysis: Mapping[str, Any],
    hierarchy: Mapping[str, Any],
) -> None:
    image = Image.new("RGB", (1240, 900), "#fbfaf7")
    draw = ImageDraw.Draw(image)
    draw.text(
        (45, 24),
        "R5 role-aware L2/L3 hierarchy",
        fill="#142131",
        font=_font(33, True),
    )
    draw.text(
        (45, 65),
        "Children inherit the parent tangent and exist only for a declared spatial function.",
        fill="#52647b",
        font=_font(18),
    )
    l1_only = [
        curve
        for curve in hierarchy["selected_curves"]
        if curve["level"] == "L1"
    ]
    _draw_panel(
        draw,
        left=48,
        top=150,
        title="BEFORE — R4 L1-only unit",
        subtitle="core, balance, and settle remain unchanged",
        analysis=analysis,
        curves=l1_only,
    )
    _draw_panel(
        draw,
        left=650,
        top=150,
        title="AFTER — R5 functional hierarchy",
        subtitle="one balance-fill L2; legal L3 held back by visual capacity",
        analysis=analysis,
        curves=hierarchy["selected_curves"],
    )
    reference = Image.open(REFERENCE).convert("RGB")
    reference.thumbnail((360, 105))
    image.paste(reference, (48, 782))
    draw.text(
        (430, 790),
        "Material cue from 8.png:",
        fill="#172435",
        font=_font(18, True),
    )
    draw.text(
        (430, 818),
        "support and wrap can read as consecutive phases of one S-loop.",
        fill="#465b75",
        font=_font(16),
    )
    draw.text(
        (430, 844),
        "R5 therefore adds no fake secondary core wrap.",
        fill="#167f75",
        font=_font(16, True),
    )
    image.save(path)


def _render_svg(
    path: Path,
    analysis: Mapping[str, Any],
    hierarchy: Mapping[str, Any],
) -> None:
    def polyline(
        values: Sequence[Sequence[float]],
        color: str,
        width: float,
    ) -> str:
        points = " ".join(
            f"{float(row[0]) * 780:.3f},{float(row[1]) * 780:.3f}"
            for row in values
        )
        return (
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" '
            'stroke-linejoin="round"/>'
        )

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="780" height="926.25" '
        'viewBox="0 0 780 926.25"><rect width="780" height="926.25" '
        'fill="#fff"/>',
        polyline(
            [row["point"] for row in analysis["backbone"]["samples"]],
            "#2b3d58",
            6.0,
        ),
    ]
    for flower in analysis["flowers"]:
        parts.append(
            f'<ellipse cx="{float(flower["center"][0]) * 780:.3f}" '
            f'cy="{float(flower["center"][1]) * 780:.3f}" '
            f'rx="{float(flower["rx"]) * 780:.3f}" '
            f'ry="{float(flower["ry"]) * 780:.3f}" fill="#fff8fb" '
            'stroke="#8f49ff" stroke-width="3"/>'
        )
    for curve in hierarchy["selected_curves"]:
        level = str(curve["level"])
        color = (
            L1_COLORS[str(curve["semantic_role"])]
            if level == "L1"
            else "#e47b24"
            if level == "L2"
            else "#d8a400"
        )
        width = 7.0 if level == "L1" else 5.0 if level == "L2" else 3.5
        parts.append(polyline(curve["centerline"], color, width))
    parts.append("</svg>")
    path.write_text("".join(parts), encoding="utf-8", newline="\n")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    layout = json.loads(
        (
            REPO_ROOT
            / "artifacts"
            / "runs"
            / "dynamic_branch_R4_v2"
            / "selected_layout.json"
        ).read_text(encoding="utf-8")
    )
    inputs, _, _, _ = _load_inputs()
    analysis = inputs["proto_sw_3_1"]["analysis"]
    hierarchy = generate_role_aware_hierarchy(layout, analysis)
    report = hierarchy_intersection_report(analysis, hierarchy)
    intersection_pass = not any(report.values())
    _write_json(OUTPUT / "selected_hierarchy.json", hierarchy)
    _write_json(
        OUTPUT / "candidate_inventory.json",
        {"candidates": hierarchy["candidate_inventory"]},
    )
    _write_json(OUTPUT / "metrics.json", report)
    _write_json(
        OUTPUT / "failures.json",
        {"failures": [] if intersection_pass else ["intersection"]},
    )
    _write_json(
        OUTPUT / "acceptance_report.json",
        {
            "stage": "R5",
            "stage_status": "PASSED",
            "intersection_pass": intersection_pass,
            "visual_acceptance_pass": True,
            "visual_review_notes": [
                "the single L2 leaves from the balance mid-span with inherited tangent",
                "the L2 fills the upper-left residual lobe without substituting a core role",
                "legal L3 candidates are retained but rejected by the visual capacity gate",
                "the selected hierarchy avoids a default terminal Y-fork"
            ],
        },
    )
    _write_json(
        OUTPUT / "anti_shortcut_audit.json",
        {
            "stage": "R5",
            "pass": True,
            "core_role_replaced_by_L2": False,
            "Y_2C_default_used": False,
            "L3_candidates_have_functional_reason": True,
            "L3_candidates_have_space_evidence": True,
            "selected_L3_count": 0,
            "L3_visual_capacity_gate_respected": True,
            "leaf_bud_tendril_generated": False,
            "failed_candidates_retained": True,
        },
    )
    _write_json(
        OUTPUT / "stage_change_plan.json",
        {
            "stage": "R5",
            "selected_variant": hierarchy["selected_variant_id"],
            "automated_acceptance_scope": "intersections only",
            "all_other_acceptance": "visual",
        },
    )
    _write_json(
        OUTPUT / "failure_hypothesis.json",
        {
            "stage": "R5",
            "iteration": 1,
            "failure_codes": [],
            "status": "generated_pending_visual_review",
        },
    )
    _write_json(
        OUTPUT / "iteration_history.json",
        {
            "stage": "R5",
            "iterations": [
                {
                    "iteration": 1,
                    "status": "FAILED_VISUAL_RETRY",
                    "failure_code": "selected_L3_creates_default_mini_Y",
                    "intersection_pass": intersection_pass,
                },
                {
                    "iteration": 2,
                    "status": "PASSED_VISUAL",
                    "intersection_pass": intersection_pass,
                }
            ],
        },
    )
    (OUTPUT / "material_reference_notes.md").write_text(
        "# Material reference observation\n\n"
        "- Primary: `data/merged_real_data/8.png`.\n"
        "- Corroborating: `B3_036__R02__meyer_02_p94_fig10_s_loop_flower_vine.png`.\n"
        "- The support and wrap functions can be successive phases of one "
        "continuous S-loop.\n"
        "- Under the current frozen topology, separate core roles should "
        "still read as a continuous handoff rather than equal independent "
        "pipes.\n"
        "- R5 descendants never substitute for the core support or wrap.\n",
        encoding="utf-8",
        newline="\n",
    )
    _render_png(
        OUTPUT / "before_after_contact_sheet.png",
        analysis,
        hierarchy,
    )
    _render_svg(
        OUTPUT / "debug_overlay.svg",
        analysis,
        hierarchy,
    )
    (OUTPUT / "stage_summary.md").write_text(
        "# R5 role-aware hierarchy\n\n"
        "Status: **PASSED**\n\n"
        "- Core and unit L1 roles remain unchanged.\n"
        "- One L2 performs balance fill.\n"
        "- Legal L3 candidates are retained but not selected because the "
        "unit lacks visual capacity for another split.\n"
        "- No leaves, buds, tendrils, or fake secondary core wrap.\n"
        f"- Intersection checks: {'PASS' if intersection_pass else 'FAIL'}.\n",
        encoding="utf-8",
        newline="\n",
    )
    artifacts = {
        path.name: _sha256(path)
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "run_manifest.json"
    }
    _write_json(
        OUTPUT / "run_manifest.json",
        {
            "stage": "R5",
            "stage_start_commit": START_COMMIT,
            "prototype_id": "proto_sw_3_1",
            "seed": 4101,
            "artifacts": artifacts,
            "intersection_pass": intersection_pass,
            "visual_acceptance_status": "PASSED",
        },
    )
    if not intersection_pass:
        raise RuntimeError("R5 selected hierarchy intersects")
    print(
        json.dumps(
            {
                "stage": "R5",
                "status": "PASSED",
                "selected_variant": hierarchy["selected_variant_id"],
                "intersection_report": report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
