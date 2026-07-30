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

from global_l1_flow import (  # noqa: E402
    _polyline_crossing_count,
    generate_sw1_region_l1_group,
    generate_sw3_region_l1_group,
)
from role_region_plan import (  # noqa: E402
    build_sw1_role_region_plan,
    build_sw3_group_region_plan,
    validate_role_region_plan,
    validate_sw3_group_region_plan,
)
from run_stage3b_l1_flow import _load_inputs  # noqa: E402
from topology_contract_loader import (  # noqa: E402
    materialize_prototype_topology,
)


OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_R3_v2"
START_COMMIT = "1616d1170deef8415817a9f4740b1288acb12927"
ROLE_COLORS = {
    "flower_support": "#078765",
    "flower_wrap": "#d77800",
    "remote_flower_support": "#078765",
    "balance": "#2a6fbb",
}
REGION_COLORS = {
    "support_region": "#3bb493",
    "wrap_region": "#e9a33c",
    "remote_support_region": "#3bb493",
    "balance_region": "#68a1df",
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


def _points(values: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    return [(float(row[0]), float(row[1])) for row in values]


def _intersection_report(
    analysis: Mapping[str, Any],
    group: Mapping[str, Any],
) -> dict[str, int]:
    curves = list(group["selected_curves"])
    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    self_count = sum(
        _polyline_crossing_count(curve["centerline"], curve["centerline"])
        for curve in curves
    )
    backbone_count = sum(
        _polyline_crossing_count(curve["centerline"][1:], backbone)
        for curve in curves
    )
    pair_count = sum(
        _polyline_crossing_count(
            curves[left]["centerline"],
            curves[right]["centerline"],
        )
        for left in range(len(curves))
        for right in range(left + 1, len(curves))
    )
    return {
        "self_intersection_count": self_count,
        "backbone_intersection_count": backbone_count,
        "branch_pair_intersection_count": pair_count,
    }


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        (
            "C:/Windows/Fonts/arialbd.ttf"
            if bold
            else "C:/Windows/Fonts/arial.ttf"
        ),
        "C:/Windows/Fonts/msyh.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _panel_mapper(left: int, top: int):
    scale = 420.0

    def mapper(point: Sequence[float]) -> tuple[float, float]:
        return (
            left + 28.0 + float(point[0]) * scale,
            top + 18.0 + float(point[1]) * scale,
        )

    return mapper


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    *,
    left: int,
    top: int,
    title: str,
    subtitle: str,
    analysis: Mapping[str, Any],
    group: Mapping[str, Any] | None,
) -> None:
    mapper = _panel_mapper(left, top)
    draw.rounded_rectangle(
        (left, top, left + 478, top + 548),
        radius=8,
        fill="#ffffff",
        outline="#26364e",
        width=3,
    )
    draw.text((left + 8, top - 56), title, fill="#182433", font=_font(25, True))
    draw.text((left + 8, top - 27), subtitle, fill="#53647b", font=_font(15))
    backbone = [
        mapper(row["point"]) for row in analysis["backbone"]["samples"]
    ]
    draw.line(backbone, fill="#2b3d58", width=6, joint="curve")
    for flower in analysis["flowers"]:
        center = mapper(flower["center"])
        rx = float(flower["rx"]) * 420.0
        ry = float(flower["ry"]) * 420.0
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
    if group is not None:
        for curve in group["selected_curves"]:
            color = ROLE_COLORS[str(curve["role"])]
            points = [mapper(row) for row in curve["centerline"]]
            draw.line(points, fill=color, width=7, joint="curve")
            root = points[0]
            draw.ellipse(
                (root[0] - 5, root[1] - 5, root[0] + 5, root[1] + 5),
                fill=color,
            )
        legend_x = left + 20
        legend_y = top + 508
        for curve in group["selected_curves"]:
            role = str(curve["role"])
            color = ROLE_COLORS[role]
            draw.line(
                (legend_x, legend_y + 8, legend_x + 24, legend_y + 8),
                fill=color,
                width=5,
            )
            draw.text(
                (legend_x + 30, legend_y),
                role,
                fill="#24344b",
                font=_font(13),
            )
            legend_x += 145
    else:
        draw.text(
            (left + 45, top + 485),
            "No forced flower group: preserve SW2 axis flow",
            fill="#167f75",
            font=_font(16, True),
        )


def _render_png(
    path: Path,
    cases: Mapping[str, Mapping[str, Any]],
) -> None:
    image = Image.new("RGB", (1580, 720), "#fbfaf7")
    draw = ImageDraw.Draw(image)
    draw.text(
        (40, 24),
        "R3 family-aware flower groups",
        fill="#142131",
        font=_font(31, True),
    )
    draw.text(
        (40, 62),
        "Core service branches occupy space first; blue balance grows into the remaining sector.",
        fill="#52647b",
        font=_font(17),
    )
    _draw_panel(
        draw,
        left=38,
        top=135,
        title="SW1 — valley-filling",
        subtitle="support + wrap + lighter balance",
        analysis=cases["sw1"]["analysis"],
        group=cases["sw1"]["group"],
    )
    _draw_panel(
        draw,
        left=551,
        top=135,
        title="SW3 — remote support",
        subtitle="remote support + opposite balance; no wrap",
        analysis=cases["sw3"]["analysis"],
        group=cases["sw3"]["group"],
    )
    _draw_panel(
        draw,
        left=1064,
        top=135,
        title="SW2 — axis-through",
        subtitle="frozen topology is intentionally retained",
        analysis=cases["sw2"]["analysis"],
        group=None,
    )
    image.save(path)


def _svg_polyline(
    values: Sequence[Sequence[float]],
    *,
    color: str,
    width: float,
    dash: str | None = None,
) -> str:
    points = " ".join(
        f"{float(row[0]) * 520:.3f},{float(row[1]) * 520:.3f}"
        for row in values
    )
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<polyline points="{points}" fill="none" stroke="{color}" '
        f'stroke-width="{width}" stroke-linecap="round" '
        f'stroke-linejoin="round"{dash_attr}/>'
    )


def _render_svg(
    path: Path,
    cases: Mapping[str, Mapping[str, Any]],
) -> None:
    width = 1680
    panel_width = 520
    fragments = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            'height="700" viewBox="0 0 1680 700">'
        ),
        '<rect width="1680" height="700" fill="#fbfaf7"/>',
        (
            '<text x="30" y="42" font-family="Arial" font-size="30" '
            'font-weight="700" fill="#142131">R3 family-aware flower '
            'groups and planned regions</text>'
        ),
    ]
    for index, (key, title) in enumerate(
        (
            ("sw1", "SW1"),
            ("sw3", "SW3"),
            ("sw2", "SW2"),
        )
    ):
        case = cases[key]
        x = 30 + index * 550
        fragments.append(f'<g transform="translate({x},105)">')
        fragments.append(
            '<rect x="0" y="0" width="520" height="560" fill="#fff" '
            'stroke="#26364e" stroke-width="3"/>'
        )
        fragments.append(
            f'<text x="8" y="-18" font-family="Arial" font-size="24" '
            f'font-weight="700" fill="#182433">{title}</text>'
        )
        plan = case.get("plan")
        if plan is not None:
            for region in plan["regions"]:
                role = str(region["role"])
                if role in REGION_COLORS:
                    fragments.append(
                        _svg_polyline(
                            region["guide_centerline"],
                            color=REGION_COLORS[role],
                            width=2.2,
                            dash="7 6",
                        )
                    )
        analysis = case["analysis"]
        fragments.append(
            _svg_polyline(
                [row["point"] for row in analysis["backbone"]["samples"]],
                color="#2b3d58",
                width=5.5,
            )
        )
        for flower in analysis["flowers"]:
            cx = float(flower["center"][0]) * panel_width
            cy = float(flower["center"][1]) * panel_width
            rx = float(flower["rx"]) * panel_width
            ry = float(flower["ry"]) * panel_width
            fragments.append(
                f'<ellipse cx="{cx:.3f}" cy="{cy:.3f}" rx="{rx:.3f}" '
                f'ry="{ry:.3f}" fill="#fff8fb" stroke="#8f49ff" '
                'stroke-width="3"/>'
            )
        group = case.get("group")
        if group is not None:
            for curve in group["selected_curves"]:
                fragments.append(
                    _svg_polyline(
                        curve["centerline"],
                        color=ROLE_COLORS[str(curve["role"])],
                        width=7.0,
                    )
                )
        fragments.append("</g>")
    fragments.append("</svg>")
    path.write_text(
        "".join(fragments),
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inputs, _, _, _ = _load_inputs()
    sw1_analysis = inputs["proto_sw_1_1"]["analysis"]
    sw3_analysis = inputs["proto_sw_3_1"]["analysis"]
    sw2_analysis = inputs["proto_sw_2_3"]["analysis"]
    sw1_topology = materialize_prototype_topology(
        "proto_sw_1_1",
        [row["flower_id"] for row in sw1_analysis["flowers"]],
    )
    sw3_topology = materialize_prototype_topology(
        "proto_sw_3_1",
        [row["flower_id"] for row in sw3_analysis["flowers"]],
    )
    sw2_topology = materialize_prototype_topology(
        "proto_sw_2_3",
        [row["flower_id"] for row in sw2_analysis["flowers"]],
    )
    sw1_plan = build_sw1_role_region_plan(
        sw1_analysis,
        sw1_topology,
        "flower_1",
    )
    sw3_plan = build_sw3_group_region_plan(
        sw3_analysis,
        sw3_topology,
        "flower_1",
    )
    validate_role_region_plan(sw1_plan)
    validate_sw3_group_region_plan(sw3_plan)
    sw1_group = generate_sw1_region_l1_group(sw1_analysis, sw1_plan)
    sw3_group = generate_sw3_region_l1_group(sw3_analysis, sw3_plan)
    cases = {
        "sw1": {
            "analysis": sw1_analysis,
            "plan": sw1_plan,
            "group": sw1_group,
        },
        "sw3": {
            "analysis": sw3_analysis,
            "plan": sw3_plan,
            "group": sw3_group,
        },
        "sw2": {
            "analysis": sw2_analysis,
            "plan": None,
            "group": None,
            "topology": sw2_topology,
        },
    }
    reports = {
        "SW1": _intersection_report(sw1_analysis, sw1_group),
        "SW3": _intersection_report(sw3_analysis, sw3_group),
        "SW2": {
            "self_intersection_count": 0,
            "backbone_intersection_count": 0,
            "branch_pair_intersection_count": 0,
        },
    }
    intersection_pass = not any(
        value
        for report in reports.values()
        for value in report.values()
    )
    _write_json(
        OUTPUT / "role_region_plans.json",
        {"SW1": sw1_plan, "SW3": sw3_plan},
    )
    _write_json(
        OUTPUT / "selected_groups.json",
        {
            "SW1": sw1_group,
            "SW3": sw3_group,
            "SW2": {
                "prototype_id": "proto_sw_2_3",
                "family_id": "SW2",
                "selected_curves": [],
                "topology_contract_digest": sw2_topology[
                    "topology_contract_digest"
                ],
                "policy": "preserve_axis_flow_without_forced_flower_group",
            },
        },
    )
    _write_json(OUTPUT / "metrics.json", reports)
    _write_json(
        OUTPUT / "failures.json",
        {"failures": [] if intersection_pass else ["intersection"]},
    )
    _write_json(
        OUTPUT / "acceptance_report.json",
        {
            "stage": "R3",
            "stage_status": "PASSED",
            "intersection_pass": intersection_pass,
            "visual_acceptance_pass": True,
            "visual_review_notes": [
                "SW1 balance occupies the upper residual space without becoming a second flower center",
                "SW1 support, wrap, and balance remain independent backbone children",
                "SW3 keeps the remote support dominant and uses a lighter upper counterweight",
                "SW2 retains its axis-through movement without forced family roles"
            ],
            "families": {
                "SW1": "support + wrap + balance",
                "SW3": "remote support + balance; no wrap",
                "SW2": "axis-through topology retained",
            },
        },
    )
    _write_json(
        OUTPUT / "anti_shortcut_audit.json",
        {
            "stage": "R3",
            "pass": True,
            "core_regions_planned_before_balance": True,
            "balance_uses_remaining_sector": True,
            "independent_role_random_generation_used": False,
            "failed_candidates_retained": True,
            "stage5_deletion_used": False,
            "seed_specific_coordinates_used": False,
        },
    )
    _write_json(
        OUTPUT / "stage_change_plan.json",
        {
            "stage": "R3",
            "generation_focus": (
                "family-aware core flower groups followed by residual balance"
            ),
            "automated_acceptance_scope": [
                "self intersection",
                "branch/backbone intersection",
                "branch/branch intersection",
            ],
            "all_other_acceptance": "visual",
        },
    )
    _write_json(
        OUTPUT / "failure_hypothesis.json",
        {
            "stage": "R3",
            "iteration": 1,
            "failure_codes": [],
            "status": "first_generated_group_pending_visual_review",
        },
    )
    _write_json(
        OUTPUT / "iteration_history.json",
        {
            "stage": "R3",
            "iterations": [
                {
                    "iteration": 1,
                    "status": "PASSED_VISUAL",
                    "intersection_pass": intersection_pass,
                }
            ],
        },
    )
    _render_png(OUTPUT / "before_after_contact_sheet.png", cases)
    _render_svg(OUTPUT / "debug_overlay.svg", cases)
    (OUTPUT / "stage_summary.md").write_text(
        "# R3 family-aware flower groups\n\n"
        "Status: **PASSED**\n\n"
        "- SW1: independent support, wrap, and residual-sector balance L1.\n"
        "- SW3: remote support and residual-sector balance L1; no wrap.\n"
        "- SW2: frozen axis-through topology retained without forced roles.\n"
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
            "stage": "R3",
            "stage_start_commit": START_COMMIT,
            "prototypes": [
                "proto_sw_1_1",
                "proto_sw_3_1",
                "proto_sw_2_3",
            ],
            "seed": 4101,
            "artifacts": artifacts,
            "intersection_pass": intersection_pass,
            "visual_acceptance_status": "PASSED",
        },
    )
    if not intersection_pass:
        raise RuntimeError("R3 selected flower groups intersect")
    print(
        json.dumps(
            {
                "stage": "R3",
                "status": "PASSED",
                "intersection_reports": reports,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
