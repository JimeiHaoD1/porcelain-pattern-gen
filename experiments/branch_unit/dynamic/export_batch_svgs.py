#!/usr/bin/env python3
"""Export saved batch results as vector SVG (triple repeat by default)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from render_stage4_unit_atlas import COLORS


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_DIR = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_batch_v1"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "dynamic_branch_batch_500_svg"

ROLE_COLORS = {
    "backbone": "#0000ff",
    "primary_branch": "#ff9900",
    "secondary_branch": "#00ffff",
    "flower_support": "#007800",
    "flower_anchor": "#ff0000",
    "unit_boundary": "#000000",
}

ROLE_METADATA = (
    "role_color_identity_v2: "
    "backbone=#0000ff; primary_branch=#ff9900; "
    "secondary_branch=#00ffff; flower_support=#007800; "
    "flower_anchor=#ff0000; unit_boundary=#000000(dashed). "
    "data-role is authoritative; stroke color is a visual fallback."
)


def _round(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def _point(point: Sequence[float], shift_x: float) -> str:
    return f"{_round(float(point[0]) + shift_x)},{_round(float(point[1]))}"


def _polyline(
    points: Sequence[Sequence[float]],
    shift_x: float,
) -> str:
    if len(points) < 2:
        return ""
    coordinates = " ".join(_point(point, shift_x) for point in points)
    return f'<polyline points="{coordinates}" fill="none" '


def _curve_path(curve: Mapping[str, Any], shift_x: float) -> str:
    parts: list[str] = []
    for segment in curve["cubic_segments"]:
        p0 = (float(segment["p0"][0]) + shift_x, float(segment["p0"][1]))
        p1 = (float(segment["p1"][0]) + shift_x, float(segment["p1"][1]))
        p2 = (float(segment["p2"][0]) + shift_x, float(segment["p2"][1]))
        p3 = (float(segment["p3"][0]) + shift_x, float(segment["p3"][1]))
        if not parts:
            parts.append(f"M {_point(p0, 0.0)}")
        parts.append(
            f"C {_point(p1, 0.0)} {_point(p2, 0.0)} {_point(p3, 0.0)}"
        )
    return " ".join(parts)


def render_case_svg(
    analysis: Mapping[str, Any],
    flower_mount_plan: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    repeat: str,
    palette: str,
) -> str:
    canvas_height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    shifts = (-1.0, 0.0, 1.0) if repeat == "triple" else (0.0,)
    structure_shifts = shifts
    x_min = -1.08 if repeat == "triple" else -0.18
    x_max = 2.08 if repeat == "triple" else 1.18
    view_width = x_max - x_min
    parts = [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="{_round(x_min)} 0 {_round(view_width)} '
            f'{_round(canvas_height)}" '
            f'width="{int(round(view_width * 1000))}" '
            f'height="{int(round(canvas_height * 1000))}">'
        ),
        (
            f'<rect x="{_round(x_min)}" y="0" width="{_round(view_width)}" '
            f'height="{_round(canvas_height)}" fill="{COLORS["background"]}"/>'
        ),
        f"<metadata>{ROLE_METADATA}</metadata>",
    ]

    def stroke_style(role: str, dashed: bool = False) -> str:
        color = (
            ROLE_COLORS[role]
            if palette == "role"
            else {
                "backbone": COLORS["ink"],
                "primary_branch": COLORS["l1"],
                "secondary_branch": COLORS["l2"],
                "flower_support": COLORS["flower_support"],
                "flower_anchor": COLORS["flower"],
                "unit_boundary": COLORS["grid"],
            }[role]
        )
        dash = ' stroke-dasharray="0.012 0.008"' if dashed else ""
        return f'stroke="{color}"{dash}'

    parts.append('<g data-role="unit_boundary">')
    for boundary_x in range(int(min(shifts)), int(max(shifts)) + 2):
        parts.append(
            '<line '
            f'x1="{_round(boundary_x)}" y1="0" '
            f'x2="{_round(boundary_x)}" y2="{_round(canvas_height)}" '
            + stroke_style("unit_boundary", dashed=True)
            + ' stroke-width="0.004"/>'
        )
    parts.append("</g>")

    parts.append('<g data-role="backbone">')
    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    for shift_x in structure_shifts:
        color = (
            ROLE_COLORS["backbone"]
            if palette == "role"
            else (COLORS["ink"] if shift_x == 0.0 else COLORS["ghost"])
        )
        width = 0.014 if shift_x == 0.0 else 0.007
        polyline = _polyline(backbone, shift_x)
        parts.append(
            polyline
            + f'stroke="{color}" stroke-width="{_round(width)}" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )
    parts.append("</g>")

    parts.append('<g data-role="flower_support">')
    for shift_x in shifts:
        for mount in flower_mount_plan.get("mounts", []):
            polyline = _polyline(mount["centerline"], shift_x)
            parts.append(
                polyline
                + stroke_style("flower_support")
                + ' '
                'stroke-width="0.010" stroke-linejoin="round" '
                'stroke-linecap="round" '
                f'data-flower-id="{mount.get("flower_id", "")}"/>'
            )
    parts.append("</g>")

    parts.append('<g data-role="flower_anchor">')
    for shift_x in shifts:
        for flower in analysis["flowers"]:
            center_x = float(flower["center"][0]) + shift_x
            center_y = float(flower["center"][1])
            rx = float(flower["rx"])
            ry = float(flower["ry"])
            parts.append(
                '<ellipse '
                f'cx="{_round(center_x)}" cy="{_round(center_y)}" '
                f'rx="{_round(rx)}" ry="{_round(ry)}" '
                f'fill="{COLORS["flower_fill"]}" '
                + stroke_style("flower_anchor")
                + ' stroke-width="0.006" '
                f'data-flower-id="{flower.get("flower_id", "")}"/>'
            )
    parts.append("</g>")

    if selection["feasible"]:
        parts.append('<g data-role="branches">')
        for shift_x in shifts:
            for candidate in selection["selected_candidates"]:
                for curve in candidate["curves"]:
                    role = (
                        "primary_branch"
                        if curve["level"] == "L1"
                        else "secondary_branch"
                    )
                    color = (
                        ROLE_COLORS[role]
                        if palette == "role"
                        else COLORS[str(curve["level"]).lower()]
                    )
                    width = 0.010 if curve["level"] == "L1" else 0.007
                    path = _curve_path(curve, shift_x)
                    if palette == "presentation":
                        parts.append(
                            f'<path d="{path}" fill="none" '
                            'stroke="#ffffff" '
                            f'stroke-width="{_round(width + 0.007)}" '
                            'stroke-linejoin="round" stroke-linecap="round"/>'
                        )
                    parts.append(
                        f'<path d="{path}" fill="none" '
                        + f'stroke="{color}" '
                        + f'stroke-width="{_round(width)}" '
                        'stroke-linejoin="round" stroke-linecap="round" '
                        f'data-role="{role}" '
                        f'data-level="{curve.get("level", "")}" '
                        f'data-curve-id="{curve.get("curve_id", "")}" '
                        f'data-parent-curve-id="{curve.get("parent_curve_id", "")}" '
                        f'data-lane-id="{candidate.get("source_lane_id", "")}" '
                        f'data-unit-id="{candidate.get("candidate_id", "")}"/>'
                    )
        parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


def run(source_dir: Path, output_dir: Path, repeat: str, palette: str) -> int:
    if repeat not in {"single", "triple"}:
        raise SystemExit("--repeat must be single or triple")
    if palette not in {"role", "presentation"}:
        raise SystemExit("--palette must be role or presentation")
    output_dir.mkdir(parents=True, exist_ok=True)
    exported = 0
    skipped = 0
    for case_manifest in sorted(source_dir.glob("*/seed_*/case_manifest.json")):
        case_dir = case_manifest.parent
        analysis_path = case_dir / "prototype_analysis_variant.json"
        mounts_path = case_dir / "flower_mount_plan.json"
        selection_path = case_dir / "global_unit_selection.json"
        if not (
            analysis_path.is_file()
            and mounts_path.is_file()
            and selection_path.is_file()
        ):
            skipped += 1
            continue
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        mounts = json.loads(mounts_path.read_text(encoding="utf-8"))
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        prototype_id = str(selection["prototype_id"])
        seed = str(case_manifest.parent.name).replace("seed_", "")
        svg = render_case_svg(
            analysis,
            mounts,
            selection,
            repeat=repeat,
            palette=palette,
        )
        (output_dir / f"{prototype_id}__seed_{seed}.svg").write_text(
            svg,
            encoding="utf-8",
            newline="\n",
        )
        exported += 1
    print(f"exported={exported} skipped={skipped} output={output_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export saved batch results as SVG."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--repeat", choices=("single", "triple"), default="triple")
    parser.add_argument(
        "--palette",
        choices=("role", "presentation"),
        default="role",
    )
    args = parser.parse_args()
    return run(args.source_dir, args.output_dir, args.repeat, args.palette)


if __name__ == "__main__":
    raise SystemExit(main())
