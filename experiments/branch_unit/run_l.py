#!/usr/bin/env python3
"""Generate and score the preregistered BranchUnit L-only screening run.

The causal comparison is intentionally narrow:

* L0_independent: dependent parameters are mapped independently.
* L1_coupled: the same raw random tokens and budgets are organized as a unit.

Both variants share the primary curve, geometry compiler, validator, renderer,
topology, line widths, and nominal length/ink budget.  There is no search,
repair, retry, resampling, or promotion into the mainline pipeline.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont, __version__ as PILLOW_VERSION


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from chanzhi_sw import chanzhi_skeleton_analyzer as analyzer  # noqa: E402
from l_core import (  # noqa: E402
    GEOMETRY_KERNEL_ID,
    BranchUnit,
    ChildSpec,
    ContextCurve,
    Curve,
    FlowerReserve,
    Scene,
    TerminalSpec,
    compile_primary,
    compile_unit,
    points_from,
    primary_summary,
    validate_unit,
)


PROTOTYPE_ID = "proto_sw_1_3"
REGION_ID = "growth_region_2"
EXPERIMENT_ID = "branch_unit_L_v2"
BLIND_SEED = 20260720
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "runs" / "branch_unit_l_v2"
BASELINE_ROOT = REPO_ROOT / "data" / "baselines" / "sw"
BASELINE_SVG = BASELINE_ROOT / PROTOTYPE_ID / f"{PROTOTYPE_ID}_baseline.svg"
LOCAL_CROP = (112.0, -4.0, 262.0, 160.0)
FULL_CROP = (0.0, 0.0, 256.0, 304.0)
PRIMARY_WIDTH = 3.0
CHILD_WIDTH = 1.8
TERMINAL_WIDTH = 1.05


RAW_TOKENS = (
    "main.handle",
    "main.tip",
    "child.1.mount",
    "child.1.length",
    "child.1.angle",
    "child.1.side",
    "child.1.bow",
    "child.2.mount",
    "child.2.length",
    "child.2.angle",
    "child.2.side",
    "child.2.bow",
    "terminal.length",
    "terminal.turn",
    "terminal.side",
    "terminal.bow",
)


@dataclass(frozen=True)
class TrialSpec:
    trial_id: str
    length_ratio: float
    sweep_depth: float
    child_count: int
    seed: int

    def as_dict(self) -> dict[str, object]:
        return {
            "trial_id": self.trial_id,
            "length_ratio": self.length_ratio,
            "sweep_depth": self.sweep_depth,
            "child_count": self.child_count,
            "seed": self.seed,
        }


@dataclass(frozen=True)
class NominalBudget:
    primary_length: float
    child_lengths: tuple[float, ...]
    terminal_length: float
    primary_width: float = PRIMARY_WIDTH
    child_width: float = CHILD_WIDTH
    terminal_width: float = TERMINAL_WIDTH

    @property
    def total_length(self) -> float:
        return self.primary_length + sum(self.child_lengths) + self.terminal_length

    @property
    def vector_ink(self) -> float:
        return (
            self.primary_length * self.primary_width
            + sum(self.child_lengths) * self.child_width
            + self.terminal_length * self.terminal_width
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "primary_length": round(self.primary_length, 6),
            "child_lengths": [round(value, 6) for value in self.child_lengths],
            "terminal_length": round(self.terminal_length, 6),
            "primary_width": self.primary_width,
            "child_width": self.child_width,
            "terminal_width": self.terminal_width,
            "total_length": round(self.total_length, 6),
            "vector_ink": round(self.vector_ink, 6),
        }

    @property
    def digest(self) -> str:
        return _payload_sha(self.as_dict())


TRIALS = (
    TrialSpec("L01", 0.65, 0.22, 0, 11),
    TrialSpec("L02", 0.65, 0.22, 1, 17),
    TrialSpec("L03", 0.65, 0.22, 2, 23),
    TrialSpec("L04", 0.65, 0.32, 0, 29),
    TrialSpec("L05", 0.65, 0.32, 1, 31),
    TrialSpec("L06", 0.65, 0.32, 2, 37),
    TrialSpec("L07", 0.80, 0.22, 0, 41),
    TrialSpec("L08", 0.80, 0.22, 1, 43),
    TrialSpec("L09", 0.80, 0.22, 2, 47),
    TrialSpec("L10", 0.80, 0.32, 0, 53),
    TrialSpec("L11", 0.80, 0.32, 1, 59),
    TrialSpec("L12", 0.80, 0.32, 2, 61),
)


def named_uniform(seed: int, *parts: object) -> float:
    payload = "|".join([str(seed), *(str(part) for part in parts)])
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def materialize_raw_trial(spec: TrialSpec) -> dict[str, float]:
    return {
        token: named_uniform(spec.seed, PROTOTYPE_ID, REGION_ID, spec.trial_id, token)
        for token in RAW_TOKENS
    }


def build_budget(spec: TrialSpec, raw: dict[str, float], clearance: float) -> NominalBudget:
    primary_length = clearance * spec.length_ratio
    base_ratios = {0: (), 1: (0.30,), 2: (0.30, 0.22)}[spec.child_count]
    child_lengths = [
        primary_length * base * (0.92 + 0.16 * raw[f"child.{index}.length"])
        for index, base in enumerate(base_ratios, start=1)
    ]
    terminal_length = primary_length * 0.16 * (0.94 + 0.12 * raw["terminal.length"])
    return NominalBudget(
        primary_length=primary_length,
        child_lengths=tuple(child_lengths),
        terminal_length=terminal_length,
    )


def map_l0(raw: dict[str, float], budget: NominalBudget) -> tuple[tuple[ChildSpec, ...], TerminalSpec, dict[str, object]]:
    """Map independent parameters without access to any primary summary."""

    children: list[ChildSpec] = []
    for index, target_length in enumerate(budget.child_lengths, start=1):
        children.append(
            ChildSpec(
                mount_fraction=0.28 + 0.50 * raw[f"child.{index}.mount"],
                target_length=target_length,
                turn_sign=1 if raw[f"child.{index}.side"] >= 0.5 else -1,
                angle_degrees=42.0 + 24.0 * raw[f"child.{index}.angle"],
                bow=0.12 + 0.24 * raw[f"child.{index}.bow"],
                width=budget.child_width,
            )
        )
    terminal = TerminalSpec(
        target_length=budget.terminal_length,
        turn_sign=1 if raw["terminal.side"] >= 0.5 else -1,
        angle_degrees=28.0 + 24.0 * raw["terminal.turn"],
        bow=0.12 + 0.20 * raw["terminal.bow"],
        width=budget.terminal_width,
    )
    return tuple(children), terminal, {
        "coupling_mode": "independent_parameterization",
        "primary_summary_consumed": False,
        "child_parameter_relation": "raw_token_order_no_sibling_rhythm",
        "terminal_relation": "independent_turn_sign",
        "children": [child.as_dict() for child in children],
        "terminal": terminal.as_dict(),
    }


def map_l1(
    raw: dict[str, float],
    budget: NominalBudget,
    summary: dict[str, object],
) -> tuple[tuple[ChildSpec, ...], TerminalSpec, dict[str, object]]:
    """Map the same raw tokens/budget through one BranchUnit rhythm plan."""

    count = len(budget.child_lengths)
    raw_mounts = [0.28 + 0.50 * raw[f"child.{index}.mount"] for index in range(1, count + 1)]
    mounts = sorted(raw_mounts)
    length_pool = sorted(budget.child_lengths, reverse=True)
    angle_pool = sorted(
        [42.0 + 24.0 * raw[f"child.{index}.angle"] for index in range(1, count + 1)],
        reverse=True,
    )
    bow_pool = sorted(
        [0.12 + 0.24 * raw[f"child.{index}.bow"] for index in range(1, count + 1)],
        reverse=True,
    )
    local_turns = [_local_turn_at(summary, mount) for mount in mounts]
    curvature_need_order = sorted(range(count), key=lambda slot: abs(local_turns[slot]))
    angles_by_slot = [0.0] * count
    bows_by_slot = [0.0] * count
    for pool_index, slot in enumerate(curvature_need_order):
        angles_by_slot[slot] = angle_pool[pool_index]
        bows_by_slot[slot] = bow_pool[pool_index]

    primary_turn_sign = int(summary["turn_sign"])
    if count:
        first_local_sign = 1 if local_turns[0] > 0.0 else -1 if local_turns[0] < 0.0 else primary_turn_sign
        first_outer_sign = -first_local_sign
        side_pattern = [first_outer_sign] if count == 1 else [first_outer_sign, -first_outer_sign]
    else:
        side_pattern = []
    children = tuple(
        ChildSpec(
            mount_fraction=mounts[slot],
            target_length=length_pool[slot],
            turn_sign=side_pattern[slot],
            angle_degrees=angles_by_slot[slot],
            bow=bows_by_slot[slot],
            width=budget.child_width,
        )
        for slot in range(count)
    )
    terminal = TerminalSpec(
        target_length=budget.terminal_length,
        turn_sign=primary_turn_sign,
        angle_degrees=28.0 + 24.0 * raw["terminal.turn"],
        bow=0.12 + 0.20 * raw["terminal.bow"],
        width=budget.terminal_width,
    )
    return children, terminal, {
        "coupling_mode": "unit_coupled_parameterization",
        "primary_summary_consumed": True,
        "primary_turn_sign": primary_turn_sign,
        "primary_local_turns_at_mounts": [round(value, 10) for value in local_turns],
        "child_parameter_relation": (
            "same_mount_value_set_sorted_by_arc_length_descending_length_"
            "curvature_conditioned_angle_bow_alternating_sides"
        ),
        "terminal_relation": "turn_sign_continues_primary_curvature",
        "shared_value_pools": {
            "mounts": [round(value, 6) for value in raw_mounts],
            "lengths": [round(value, 6) for value in budget.child_lengths],
            "angles": [
                round(42.0 + 24.0 * raw[f"child.{index}.angle"], 6)
                for index in range(1, count + 1)
            ],
            "bows": [
                round(0.12 + 0.24 * raw[f"child.{index}.bow"], 6)
                for index in range(1, count + 1)
            ],
        },
        "children": [child.as_dict() for child in children],
        "terminal": terminal.as_dict(),
    }


def _local_turn_at(summary: dict[str, object], fraction: float) -> float:
    samples = list(summary.get("turn_samples", []))
    if not samples:
        return float(summary.get("cumulative_turn_radians", 0.0))
    window = [
        sample
        for sample in samples
        if abs(float(sample["s"]) - fraction) <= 0.045
    ]
    if not window:
        window = [min(samples, key=lambda sample: abs(float(sample["s"]) - fraction))]
    return sum(float(sample["signed_turn_radians"]) for sample in window)


def rebuild_scene(output_dir: Path) -> tuple[Scene, dict[str, object], Path]:
    analysis_dir = output_dir / "input_analysis"
    args = argparse.Namespace(
        input_root=BASELINE_ROOT,
        output_dir=analysis_dir,
        prototype_ids=[PROTOTYPE_ID],
        repeat_index=0,
        repeat_width=256.0,
        tile_width=512,
    )
    manifest = analyzer.run(args)
    if manifest["error_count"]:
        raise RuntimeError(f"input analysis failed: {manifest['errors']}")
    profile_path = analysis_dir / PROTOTYPE_ID / "skeleton_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    return scene_from_profile(profile), profile, profile_path


def scene_from_profile(profile: dict[str, object]) -> Scene:
    regions = {str(region["region_id"]): region for region in profile["growth_regions"]}
    region = regions[REGION_ID]
    anchor_s = float(region["attach_s"])
    samples = list(profile["backbone"]["arc_samples"])
    anchor_sample = min(samples, key=lambda sample: abs(float(sample["s"]) - anchor_s))
    repeat_x_range = tuple(float(value) for value in profile["repeat_x_range"])
    backbone = ContextCurve(
        curve_id="backbone",
        role="backbone",
        width=5.0,
        points=points_from(sample["point"] for sample in samples),
    )
    guides = tuple(
        ContextCurve(
            curve_id=str(guide["guide_id"]),
            role=str(guide.get("source_role", "structural_guide")),
            width=5.0,
            points=points_from(guide["points"]),
        )
        for guide in profile["existing_guides"]
    )
    flowers = tuple(
        FlowerReserve(
            flower_id=str(flower["flower_id"]),
            center=(float(flower["center"][0]), float(flower["center"][1])),
            rx=float(flower["rx"]),
            ry=float(flower["ry"]),
        )
        for flower in profile["flowers"]
    )
    return Scene(
        prototype_id=PROTOTYPE_ID,
        repeat_x_range=(repeat_x_range[0], repeat_x_range[1]),
        canvas_height=float(profile["canvas"]["height"]),
        anchor_s=anchor_s,
        anchor_point=(float(region["attach_point"][0]), float(region["attach_point"][1])),
        anchor_tangent=(float(anchor_sample["tangent"][0]), float(anchor_sample["tangent"][1])),
        growth_direction=(float(region["growth_direction"][0]), float(region["growth_direction"][1])),
        max_clearance=float(region["max_clearance"]),
        backbone=backbone,
        guides=guides,
        flowers=flowers,
    )


def build_trial(scene: Scene, spec: TrialSpec) -> dict[str, object]:
    raw = materialize_raw_trial(spec)
    budget = build_budget(spec, raw, scene.max_clearance)
    primary = compile_primary(
        root=scene.anchor_point,
        parent_tangent=scene.anchor_tangent,
        outward=scene.growth_direction,
        target_length=budget.primary_length,
        sweep_depth=spec.sweep_depth,
        handle_u=raw["main.handle"],
        tip_u=raw["main.tip"],
        width=budget.primary_width,
    )
    summary = primary_summary(primary)
    l0_children, l0_terminal, l0_map = map_l0(raw, budget)
    l1_children, l1_terminal, l1_map = map_l1(raw, budget, summary)
    l0 = compile_unit(
        unit_id=f"{spec.trial_id}_L0_independent",
        primary=primary,
        child_specs=l0_children,
        terminal_spec=l0_terminal,
    )
    l1 = compile_unit(
        unit_id=f"{spec.trial_id}_L1_coupled",
        primary=primary,
        child_specs=l1_children,
        terminal_spec=l1_terminal,
    )
    validation_l0 = validate_unit(scene, l0, spec.child_count)
    validation_l1 = validate_unit(scene, l1, spec.child_count)
    metrics_l0 = unit_metrics(l0, validation_l0.as_dict())
    metrics_l1 = unit_metrics(l1, validation_l1.as_dict())
    fairness = fairness_metrics(l0, l1, metrics_l0, metrics_l1, budget)
    return {
        "spec": spec,
        "raw": raw,
        "raw_digest": _payload_sha(raw),
        "budget": budget,
        "primary_summary": summary,
        "L0": {"unit": l0, "mapping": l0_map, "validation": validation_l0.as_dict(), "metrics": metrics_l0},
        "L1": {"unit": l1, "mapping": l1_map, "validation": validation_l1.as_dict(), "metrics": metrics_l1},
        "fairness": fairness,
    }


def unit_metrics(unit: BranchUnit, validation: dict[str, object]) -> dict[str, object]:
    role_lengths = {
        "primary": unit.primary.length,
        "children": sum(child.length for child in unit.children),
        "terminal": unit.terminal.length,
    }
    raster_ink = raster_ink_mass(unit)
    return {
        "semantic_curve_count": unit.semantic_curve_count,
        "cubic_segment_count": unit.cubic_segment_count,
        "role_lengths": {key: round(value, 6) for key, value in role_lengths.items()},
        "total_length": round(unit.total_length, 6),
        "vector_ink": round(unit.vector_ink, 6),
        "raster_ink_mass": round(raster_ink, 6),
        "hard_valid": bool(validation["valid"]),
        "hard_failure_reasons": list(validation["issues"]),
        "geometry_hash": unit.geometry_hash,
    }


def fairness_metrics(
    l0: BranchUnit,
    l1: BranchUnit,
    metrics_l0: dict[str, object],
    metrics_l1: dict[str, object],
    budget: NominalBudget,
) -> dict[str, object]:
    total_delta = _symmetric_delta(float(metrics_l0["total_length"]), float(metrics_l1["total_length"]))
    ink_delta = _symmetric_delta(float(metrics_l0["vector_ink"]), float(metrics_l1["vector_ink"]))
    raster_delta = _symmetric_delta(float(metrics_l0["raster_ink_mass"]), float(metrics_l1["raster_ink_mass"]))
    primary_equal = l0.primary.as_dict() == l1.primary.as_dict()
    curve_count_equal = l0.semantic_curve_count == l1.semantic_curve_count
    segment_count_equal = l0.cubic_segment_count == l1.cubic_segment_count
    width_roles_l0 = [(curve.role, curve.width) for curve in l0.curves]
    width_roles_l1 = [(curve.role, curve.width) for curve in l1.curves]
    width_equal = width_roles_l0 == width_roles_l1
    budget_match = (
        primary_equal
        and curve_count_equal
        and segment_count_equal
        and width_equal
        and total_delta <= 0.03
        and ink_delta <= 0.03
        and raster_delta <= 0.05
    )
    return {
        "budget_hash": budget.digest,
        "primary_control_points_equal": primary_equal,
        "semantic_curve_count_equal": curve_count_equal,
        "cubic_segment_count_equal": segment_count_equal,
        "role_widths_equal": width_equal,
        "total_length_symmetric_delta": round(total_delta, 8),
        "vector_ink_symmetric_delta": round(ink_delta, 8),
        "raster_ink_symmetric_delta": round(raster_delta, 8),
        "thresholds": {"total_length": 0.03, "vector_ink": 0.03, "raster_ink": 0.05},
        "budget_match": budget_match,
    }


def raster_ink_mass(unit: BranchUnit) -> float:
    scale = 4
    image = Image.new("L", (256 * scale, 304 * scale), 255)
    draw = ImageDraw.Draw(image)
    for curve in unit.curves:
        points = [(round(point[0] * scale), round(point[1] * scale)) for point in curve.points(96)]
        width = max(1, round(curve.width * scale))
        _draw_rounded_line(draw, points, fill=0, width=width)
    pixels = image.getdata()
    return sum((255 - value) / 255.0 for value in pixels) / (scale * scale)


def render_unit_svg(scene: Scene, unit: BranchUnit, output_path: Path) -> None:
    x0, x1 = scene.repeat_x_range
    width = x1 - x0
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.3f} 0 {width:.3f} {scene.canvas_height:.3f}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#fffefb"/>',
        _polyline_svg(scene.backbone.points, "#aeb5bc", 3.0),
    ]
    lines.extend(_polyline_svg(guide.points, "#d5d9dd", 1.5) for guide in scene.guides)
    lines.extend(
        f'<ellipse cx="{flower.center[0]:.6f}" cy="{flower.center[1]:.6f}" '
        f'rx="{flower.rx:.6f}" ry="{flower.ry:.6f}" fill="none" stroke="#e2e4e6" '
        'stroke-width="1" stroke-dasharray="3 3"/>'
        for flower in scene.flowers
    )
    for curve in unit.curves:
        lines.append(
            f'<path d="{_curve_svg_path(curve)}" fill="none" stroke="#111820" '
            f'stroke-width="{curve.width:.3f}" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    lines.append("</svg>")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_method_panel(scene: Scene, unit: BranchUnit, label: str, *, debug: bool) -> Image.Image:
    local = render_view(scene, unit, LOCAL_CROP, (420, 460), debug=debug)
    full = render_view(scene, unit, FULL_CROP, (300, 356), debug=False)
    panel = Image.new("RGB", (444, 884), "#fffefb")
    draw = ImageDraw.Draw(panel)
    draw.rectangle((0, 0, 443, 883), outline="#d7d4cc", width=1)
    draw.text((14, 10), label, fill="#111820", font=_font(18, bold=True))
    panel.paste(local, (12, 42))
    panel.paste(full, ((444 - full.width) // 2, 516))
    return panel


def render_view(
    scene: Scene,
    unit: BranchUnit,
    crop: tuple[float, float, float, float],
    size: tuple[int, int],
    *,
    debug: bool,
) -> Image.Image:
    supersample = 3
    target_width, target_height = size
    image = Image.new("RGB", (target_width * supersample, target_height * supersample), "#fffefb")
    draw = ImageDraw.Draw(image)
    transform = _fixed_view_transform(crop, image.size)

    for flower in scene.flowers:
        center = _tx(flower.center, transform)
        scale = transform[0]
        bbox = (
            center[0] - flower.rx * scale,
            center[1] - flower.ry * scale,
            center[0] + flower.rx * scale,
            center[1] + flower.ry * scale,
        )
        draw.ellipse(bbox, fill="#fbfaf6", outline="#e1e3e5", width=max(1, round(scale * 0.6)))

    _draw_world_polyline(draw, scene.backbone.points, transform, "#aeb5bc", 3.0)
    for guide in scene.guides:
        _draw_world_polyline(draw, guide.points, transform, "#d5d9dd", 1.4)

    colors = {
        "primary_sweep": "#111820" if not debug else "#173f6d",
        "child_branch": "#111820" if not debug else "#287a55",
        "terminal": "#111820" if not debug else "#b45c22",
    }
    for curve in unit.curves:
        _draw_world_polyline(draw, curve.points(96), transform, colors[curve.role], curve.width)
        if debug:
            for cubic in curve.cubics:
                controls = [_tx(point, transform) for point in (cubic.p0, cubic.p1, cubic.p2, cubic.p3)]
                draw.line(controls, fill="#c48c9a", width=max(1, round(transform[0] * 0.45)))
                radius = max(2, round(transform[0] * 0.9))
                for point in controls:
                    draw.ellipse(
                        (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
                        fill="#a51f48",
                    )
    if debug:
        anchor = _tx(scene.anchor_point, transform)
        radius = max(3, round(transform[0] * 1.2))
        draw.ellipse((anchor[0] - radius, anchor[1] - radius, anchor[0] + radius, anchor[1] + radius), fill="#d7263d")
    return image.resize(size, Image.Resampling.LANCZOS)


def compose_pair(
    left: Image.Image,
    right: Image.Image,
    *,
    header: str,
    subheader: str = "",
) -> Image.Image:
    gap = 16
    pad = 18
    header_height = 66
    width = pad * 2 + left.width + gap + right.width
    height = pad * 2 + header_height + max(left.height, right.height)
    image = Image.new("RGB", (width, height), "#f6f4ee")
    draw = ImageDraw.Draw(image)
    draw.text((pad, 12), header, fill="#111820", font=_font(20, bold=True))
    if subheader:
        draw.text((pad, 39), subheader, fill="#66707a", font=_font(12))
    top = pad + header_height
    image.paste(left, (pad, top))
    image.paste(right, (pad + left.width + gap, top))
    return image


def write_contact_sheet(paths: Sequence[Path], output_path: Path, columns: int = 3) -> None:
    images = [Image.open(path).convert("RGB") for path in paths]
    thumb_size = (430, 454)
    thumbnails = []
    for image in images:
        copy = image.copy()
        copy.thumbnail(thumb_size, Image.Resampling.LANCZOS)
        cell = Image.new("RGB", thumb_size, "#f6f4ee")
        cell.paste(copy, ((thumb_size[0] - copy.width) // 2, (thumb_size[1] - copy.height) // 2))
        thumbnails.append(cell)
    rows = math.ceil(len(thumbnails) / columns)
    sheet = Image.new("RGB", (columns * thumb_size[0], rows * thumb_size[1]), "#ece9e1")
    for index, image in enumerate(thumbnails):
        sheet.paste(image, ((index % columns) * thumb_size[0], (index // columns) * thumb_size[1]))
    sheet.save(output_path)


def generate(output_dir: Path) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run: {output_dir}")
    output_dir.mkdir(parents=True)
    for relative in ("methods", "pairs/unblinded", "pairs/blind", "debug", "vectors"):
        (output_dir / relative).mkdir(parents=True, exist_ok=True)

    scene, profile, profile_path = rebuild_scene(output_dir)
    _validate_registered_scene(scene, profile)
    cases = [build_trial(scene, spec) for spec in TRIALS]

    method_rows: list[dict[str, object]] = []
    pair_rows: list[dict[str, object]] = []
    replay_cases: list[dict[str, object]] = []
    unblinded_paths: list[Path] = []
    for case in cases:
        spec: TrialSpec = case["spec"]
        l0: BranchUnit = case["L0"]["unit"]
        l1: BranchUnit = case["L1"]["unit"]
        for variant, label in (("L0", "L0 independent"), ("L1", "L1 coupled")):
            unit: BranchUnit = case[variant]["unit"]
            method_image = render_method_panel(scene, unit, label, debug=False)
            method_path = output_dir / "methods" / f"{spec.trial_id}_{variant}.png"
            method_image.save(method_path)
            vector_path = output_dir / "vectors" / f"{spec.trial_id}_{variant}.svg"
            render_unit_svg(scene, unit, vector_path)
            metrics = case[variant]["metrics"]
            method_rows.append(
                {
                    "trial_id": spec.trial_id,
                    "variant": variant,
                    "child_count": spec.child_count,
                    "semantic_curve_count": metrics["semantic_curve_count"],
                    "cubic_segment_count": metrics["cubic_segment_count"],
                    "primary_length": metrics["role_lengths"]["primary"],
                    "child_total_length": metrics["role_lengths"]["children"],
                    "terminal_length": metrics["role_lengths"]["terminal"],
                    "total_length": metrics["total_length"],
                    "vector_ink": metrics["vector_ink"],
                    "raster_ink_mass": metrics["raster_ink_mass"],
                    "hard_valid": metrics["hard_valid"],
                    "hard_failure_reasons": ";".join(metrics["hard_failure_reasons"]),
                    "geometry_hash": metrics["geometry_hash"],
                }
            )

        unblinded = compose_pair(
            render_method_panel(scene, l0, "L0 independent", debug=False),
            render_method_panel(scene, l1, "L1 coupled", debug=False),
            header=f"{spec.trial_id} | L0 vs L1",
            subheader=(
                f"length_ratio={spec.length_ratio:.2f}  sweep_depth={spec.sweep_depth:.2f}  "
                f"children={spec.child_count}  seed={spec.seed}"
            ),
        )
        unblinded_path = output_dir / "pairs" / "unblinded" / f"{spec.trial_id}.png"
        unblinded.save(unblinded_path)
        unblinded_paths.append(unblinded_path)
        debug = compose_pair(
            render_method_panel(scene, l0, "L0 geometry debug", debug=True),
            render_method_panel(scene, l1, "L1 geometry debug", debug=True),
            header=f"{spec.trial_id} | control geometry",
            subheader="debug only; excluded from blind review",
        )
        debug.save(output_dir / "debug" / f"{spec.trial_id}.png")

        fairness = case["fairness"]
        pair_rows.append(
            {
                "trial_id": spec.trial_id,
                "length_ratio": spec.length_ratio,
                "sweep_depth": spec.sweep_depth,
                "child_count": spec.child_count,
                "seed": spec.seed,
                "raw_random_digest": case["raw_digest"],
                "budget_hash": fairness["budget_hash"],
                "primary_control_points_equal": fairness["primary_control_points_equal"],
                "semantic_curve_count_equal": fairness["semantic_curve_count_equal"],
                "cubic_segment_count_equal": fairness["cubic_segment_count_equal"],
                "role_widths_equal": fairness["role_widths_equal"],
                "total_length_delta": fairness["total_length_symmetric_delta"],
                "vector_ink_delta": fairness["vector_ink_symmetric_delta"],
                "raster_ink_delta": fairness["raster_ink_symmetric_delta"],
                "budget_match": fairness["budget_match"],
            }
        )
        replay_cases.append(_replay_case(case))

    blind_key, blind_paths = _render_blind_pairs(scene, cases, output_dir)
    write_contact_sheet(unblinded_paths, output_dir / "contact_sheet_unblinded.png")
    write_contact_sheet(blind_paths, output_dir / "contact_sheet_blind.png")
    _write_csv(output_dir / "metrics.csv", method_rows)
    _write_csv(output_dir / "pair_metrics.csv", pair_rows)
    _write_json(output_dir / "blind_key.json", blind_key)
    _write_json(output_dir / "blind_review_template.json", _review_template(blind_key))

    replay_manifest = {
        "schema": "branch_unit_l_replay_manifest_v1",
        "experiment_id": EXPERIMENT_ID,
        "geometry_kernel_id": GEOMETRY_KERNEL_ID,
        "commands": {
            "generate_to_new_dir": (
                f'python "{Path(__file__).resolve()}" generate --output-dir '
                f'"{output_dir.with_name(output_dir.name + "_replay").resolve()}"'
            ),
            "verify_saved_geometry": (
                f'python "{Path(__file__).resolve()}" verify --run-dir "{output_dir.resolve()}"'
            ),
            "score": f'python "{Path(__file__).resolve()}" score --run-dir "{output_dir.resolve()}" --review <review.json>',
        },
        "runtime": {"python": sys.version, "pillow": PILLOW_VERSION},
        "source_files": {
            "baseline_svg": _file_record(BASELINE_SVG),
            "runner": _file_record(Path(__file__).resolve()),
            "geometry_kernel": _file_record(SCRIPT_DIR / "l_core.py"),
            "skeleton_analyzer": _file_record(Path(analyzer.__file__).resolve()),
            "svg_skeleton_io": _file_record(Path(analyzer.eng.__file__).resolve()),
            "rebuilt_profile": _file_record(profile_path),
        },
        "scene": _scene_payload(scene),
        "matrix": [spec.as_dict() for spec in TRIALS],
        "cases": replay_cases,
    }
    _write_json(output_dir / "replay_manifest.json", replay_manifest)

    all_budget_match = all(bool(case["fairness"]["budget_match"]) for case in cases)
    manifest = {
        "schema": "branch_unit_l_run_manifest_v1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "L_only_local_parameter_coordination",
        "prototype_id": PROTOTYPE_ID,
        "region_id": REGION_ID,
        "causal_question": "Does unit-coupled parameterization outperform independent parameterization under one shared geometry kernel?",
        "variants": {
            "L0": "independent_parameterization",
            "L1": "unit_coupled_parameterization",
        },
        "shared_factors": [
            "rebuilt proto_sw_1_3 scene",
            "growth_region_2 anchor",
            "two-cubic primary geometry",
            "child and terminal cubic compilers",
            "primary control points",
            "raw named random tokens",
            "identical child mount/length/angle/bow value pools",
            "topology and widths",
            "nominal length and ink budget",
            "check-only hard validator",
            "fixed renderer and crops",
        ],
        "excluded": [
            "context adaptation experiment C",
            "global rhythm experiment G",
            "candidate search",
            "beam search",
            "repair",
            "resampling",
            "failure replacement",
            "commercial model evaluation",
            "data annotation tooling",
        ],
        "generation_policy": {
            "candidate_count_per_variant_per_trial": 1,
            "retry_count": 0,
            "resample_count": 0,
            "repair_count": 0,
            "selection_count": 1,
        },
        "trial_count": len(cases),
        "child_positive_trial_count": sum(1 for spec in TRIALS if spec.child_count >= 1),
        "data_validity": {
            "all_12_pairs_generated": len(cases) == 12,
            "all_budget_match": all_budget_match,
            "visual_status": "pending_blind_review",
            "structural_valid_is_not_visual_approval": True,
        },
        "development_gates": {
            "L1_usable": {"minimum": 4, "denominator": 12},
            "L1_blind_preference_overall": {"minimum": 7, "denominator": 12},
            "L1_blind_preference_child_positive": {"minimum": 5, "denominator": 8},
            "paper_evidence": False,
        },
        "artifacts": {
            "metrics": "metrics.csv",
            "pair_metrics": "pair_metrics.csv",
            "replay_manifest": "replay_manifest.json",
            "blind_key": "blind_key.json",
            "blind_review_template": "blind_review_template.json",
            "blind_contact_sheet": "contact_sheet_blind.png",
            "unblinded_contact_sheet": "contact_sheet_unblinded.png",
            "blind_pairs": "pairs/blind",
            "unblinded_pairs": "pairs/unblinded",
            "debug": "debug",
            "vectors": "vectors",
            "artifact_hashes": "artifact_hashes.json",
        },
    }
    _write_json(output_dir / "manifest.json", manifest)
    (output_dir / "review_protocol.md").write_text(_review_protocol(), encoding="utf-8")
    (output_dir / "README.md").write_text(_run_readme(output_dir, manifest), encoding="utf-8")
    _write_json(output_dir / "artifact_hashes.json", _artifact_hash_index(output_dir))
    if not all_budget_match:
        raise RuntimeError("formal run generated, but at least one pair failed the preregistered budget check")
    return manifest


def score(run_dir: Path, review_path: Path) -> dict[str, object]:
    blind_key = json.loads((run_dir / "blind_key.json").read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if not review.get("mapping_hidden_until_review_frozen"):
        raise ValueError("review is not eligible: blind mapping was not held until judgments were frozen")
    if not str(review.get("reviewer", "")).strip() or not str(review.get("reviewed_at", "")).strip():
        raise ValueError("reviewer and reviewed_at are required")
    key_by_id = {entry["blind_id"]: entry for entry in blind_key["entries"]}
    reviews = review.get("reviews", [])
    if len(reviews) != 12 or {item.get("blind_id") for item in reviews} != set(key_by_id):
        raise ValueError("review must contain exactly one record for each of the 12 blind ids")

    rows: list[dict[str, object]] = []
    for item in reviews:
        _validate_review_record(item)
        key = key_by_id[item["blind_id"]]
        panel_to_variant = {"A": key["panel_A_variant"], "B": key["panel_B_variant"]}
        variant_to_panel = {variant: panel for panel, variant in panel_to_variant.items()}
        l0_panel = variant_to_panel["L0"]
        l1_panel = variant_to_panel["L1"]
        preference_panel = item["preference"]
        if preference_panel in {"A", "B"}:
            preference_variant = panel_to_variant[preference_panel]
        else:
            preference_variant = preference_panel
        rows.append(
            {
                "blind_id": item["blind_id"],
                "trial_id": key["trial_id"],
                "child_count": key["child_count"],
                "L0_panel": l0_panel,
                "L1_panel": l1_panel,
                "L0_visual_usable": bool(item[l0_panel]["usable"]),
                "L1_visual_usable": bool(item[l1_panel]["usable"]),
                "L0_effective_usable": bool(item[l0_panel]["usable"]) and bool(key["hard_valid"]["L0"]),
                "L1_effective_usable": bool(item[l1_panel]["usable"]) and bool(key["hard_valid"]["L1"]),
                "preference": preference_variant,
                "L0_primary_label": item[l0_panel]["primary_failure_label"],
                "L1_primary_label": item[l1_panel]["primary_failure_label"],
                "L0_secondary_labels": item[l0_panel]["secondary_failure_labels"],
                "L1_secondary_labels": item[l1_panel]["secondary_failure_labels"],
                "L0_notes": item[l0_panel]["notes"],
                "L1_notes": item[l1_panel]["notes"],
                "pair_notes": item["pair_notes"],
                "review_confidence": item["review_confidence"],
                "hard_valid": key["hard_valid"],
                "hard_failure_reasons": key["hard_failure_reasons"],
            }
        )

    l1_usable = sum(1 for row in rows if row["L1_effective_usable"])
    l0_usable = sum(1 for row in rows if row["L0_effective_usable"])
    l1_wins = sum(1 for row in rows if row["preference"] == "L1")
    l0_wins = sum(1 for row in rows if row["preference"] == "L0")
    ties = sum(1 for row in rows if row["preference"] == "tie")
    both_bad = sum(1 for row in rows if row["preference"] == "both_bad")
    child_rows = [row for row in rows if int(row["child_count"]) >= 1]
    l1_child_wins = sum(1 for row in child_rows if row["preference"] == "L1")
    gates = {
        "L1_usable_at_least_4_of_12": l1_usable >= 4,
        "L1_preferred_at_least_7_of_12": l1_wins >= 7,
        "L1_preferred_at_least_5_of_8_child_positive": l1_child_wins >= 5,
    }
    if not gates["L1_usable_at_least_4_of_12"]:
        decision = "no_go_stop_branch_unit_route"
    elif not all(gates.values()):
        decision = "inconclusive_stop_before_C"
    else:
        decision = "L_passed_discuss_C_before_any_implementation"
    summary = {
        "schema": "branch_unit_l_blind_review_summary_v1",
        "experiment_id": EXPERIMENT_ID,
        "review_source": _file_record(review_path),
        "blind_key_sha256": _sha256(run_dir / "blind_key.json"),
        "reviewer": review["reviewer"],
        "reviewed_at": review["reviewed_at"],
        "mapping_hidden_until_review_frozen": bool(review["mapping_hidden_until_review_frozen"]),
        "counts": {
            "L0_effective_usable": l0_usable,
            "L1_effective_usable": l1_usable,
            "L1_wins_overall": l1_wins,
            "L0_wins_overall": l0_wins,
            "ties": ties,
            "both_bad": both_bad,
            "L1_wins_child_positive": l1_child_wins,
            "child_positive_denominator": len(child_rows),
        },
        "gates": gates,
        "decision": decision,
        "interpretation_limit": "development screening only; not paper-level statistical evidence",
        "rows": rows,
    }
    _write_json(run_dir / "review_summary.json", summary)
    (run_dir / "failure_index.md").write_text(_failure_index(summary), encoding="utf-8")
    return summary


def verify(run_dir: Path) -> dict[str, object]:
    replay_path = run_dir / "replay_manifest.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    profile_path = run_dir / "input_analysis" / PROTOTYPE_ID / "skeleton_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    scene = scene_from_profile(profile)
    rebuilt_cases = [_replay_case(build_trial(scene, spec)) for spec in TRIALS]
    geometry_cases_exact = _payload_sha(rebuilt_cases) == _payload_sha(replay["cases"])
    matrix_exact = [spec.as_dict() for spec in TRIALS] == replay["matrix"]

    current_sources = {
        "baseline_svg": BASELINE_SVG,
        "runner": Path(__file__).resolve(),
        "geometry_kernel": SCRIPT_DIR / "l_core.py",
        "skeleton_analyzer": Path(analyzer.__file__).resolve(),
        "svg_skeleton_io": Path(analyzer.eng.__file__).resolve(),
        "rebuilt_profile": profile_path,
    }
    source_checks = {
        key: {
            "expected": replay["source_files"][key]["sha256"],
            "actual": _sha256(path),
            "match": replay["source_files"][key]["sha256"] == _sha256(path),
        }
        for key, path in current_sources.items()
    }

    artifact_index_path = run_dir / "artifact_hashes.json"
    artifact_index = json.loads(artifact_index_path.read_text(encoding="utf-8"))
    artifact_checks = []
    for record in artifact_index["files"]:
        path = run_dir / record["path"]
        actual = _sha256(path) if path.is_file() else None
        artifact_checks.append(
            {
                "path": record["path"],
                "expected": record["sha256"],
                "actual": actual,
                "match": actual == record["sha256"],
            }
        )
    all_sources_match = all(check["match"] for check in source_checks.values())
    all_artifacts_match = all(check["match"] for check in artifact_checks)
    report = {
        "schema": "branch_unit_l_verification_v1",
        "experiment_id": replay["experiment_id"],
        "matrix_exact": matrix_exact,
        "geometry_cases_exact": geometry_cases_exact,
        "all_recorded_sources_match": all_sources_match,
        "all_indexed_artifacts_match": all_artifacts_match,
        "valid": matrix_exact and geometry_cases_exact and all_sources_match and all_artifacts_match,
        "source_checks": source_checks,
        "artifact_check_count": len(artifact_checks),
        "artifact_failures": [check for check in artifact_checks if not check["match"]],
    }
    return report


def _render_blind_pairs(
    scene: Scene,
    cases: Sequence[dict[str, object]],
    output_dir: Path,
) -> tuple[dict[str, object], list[Path]]:
    ordered = sorted(
        cases,
        key=lambda case: named_uniform(BLIND_SEED, "L_blind_v1", case["spec"].trial_id, "display_order"),
    )
    entries: list[dict[str, object]] = []
    paths: list[Path] = []
    for display_index, case in enumerate(ordered, start=1):
        spec: TrialSpec = case["spec"]
        l0: BranchUnit = case["L0"]["unit"]
        l1: BranchUnit = case["L1"]["unit"]
        l0_is_a = named_uniform(BLIND_SEED, "L_blind_v1", spec.trial_id, "panel_side") < 0.5
        unit_a, unit_b = (l0, l1) if l0_is_a else (l1, l0)
        variant_a, variant_b = ("L0", "L1") if l0_is_a else ("L1", "L0")
        blind_id = f"B{display_index:02d}"
        image = compose_pair(
            render_method_panel(scene, unit_a, "A", debug=False),
            render_method_panel(scene, unit_b, "B", debug=False),
            header=f"Blind pair {blind_id}",
            subheader="Judge A/B from geometry only; method, metrics, and parameters are hidden",
        )
        path = output_dir / "pairs" / "blind" / f"{blind_id}.png"
        image.save(path)
        paths.append(path)
        entries.append(
            {
                "blind_id": blind_id,
                "trial_id": spec.trial_id,
                "child_count": spec.child_count,
                "panel_A_variant": variant_a,
                "panel_B_variant": variant_b,
                "blind_image": str(path.relative_to(output_dir)).replace("\\", "/"),
                "blind_image_sha256": _sha256(path),
                "hard_valid": {
                    "L0": bool(case["L0"]["metrics"]["hard_valid"]),
                    "L1": bool(case["L1"]["metrics"]["hard_valid"]),
                },
                "hard_failure_reasons": {
                    "L0": case["L0"]["metrics"]["hard_failure_reasons"],
                    "L1": case["L1"]["metrics"]["hard_failure_reasons"],
                },
            }
        )
    return {
        "schema": "branch_unit_l_blind_key_v1",
        "blind_seed": BLIND_SEED,
        "mapping_policy": "named_sha256_tokens_for_display_order_and_panel_side",
        "entries": entries,
    }, paths


def _review_template(blind_key: dict[str, object]) -> dict[str, object]:
    criteria = {
        "main_sweep_readable": None,
        "child_attachment_natural": None,
        "child_rhythm": None,
        "terminal_continuity": None,
        "unit_wholeness": None,
    }
    records = []
    for entry in blind_key["entries"]:
        panel = {
            "usable": None,
            "criteria": dict(criteria),
            "primary_failure_label": None,
            "secondary_failure_labels": [],
            "notes": "",
        }
        records.append(
            {
                "blind_id": entry["blind_id"],
                "A": json.loads(json.dumps(panel)),
                "B": json.loads(json.dumps(panel)),
                "preference": None,
                "review_confidence": None,
                "pair_notes": "",
            }
        )
    return {
        "schema": "branch_unit_l_blind_review_v1",
        "reviewer": "",
        "reviewed_at": "",
        "mapping_hidden_until_review_frozen": True,
        "allowed_preferences": ["A", "B", "tie", "both_bad"],
        "allowed_failure_labels": [
            "straight_stick",
            "hard_angle_bend",
            "hairlike_cluster",
            "floating_child",
            "crowded_reserve",
            "weak_hierarchy",
            "unit_success",
        ],
        "reviews": records,
    }


def _validate_review_record(item: dict[str, object]) -> None:
    if item.get("preference") not in {"A", "B", "tie", "both_bad"}:
        raise ValueError(f"invalid preference for {item.get('blind_id')}")
    confidence = item.get("review_confidence")
    confidence_valid = confidence in {"low", "medium", "high"} or (
        isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and 0.0 <= float(confidence) <= 1.0
    )
    if not confidence_valid:
        raise ValueError(f"invalid confidence for {item.get('blind_id')}")
    allowed_labels = {
        "straight_stick",
        "hard_angle_bend",
        "hairlike_cluster",
        "floating_child",
        "crowded_reserve",
        "weak_hierarchy",
        "unit_success",
    }
    for panel in ("A", "B"):
        record = item.get(panel)
        if not isinstance(record, dict) or not isinstance(record.get("usable"), bool):
            raise ValueError(f"{item.get('blind_id')} {panel} usable must be boolean")
        criteria = record.get("criteria")
        if not isinstance(criteria, dict) or any(not isinstance(value, bool) for value in criteria.values()):
            raise ValueError(f"{item.get('blind_id')} {panel} criteria must be boolean")
        label = record.get("primary_failure_label")
        if label not in allowed_labels:
            raise ValueError(f"{item.get('blind_id')} {panel} invalid label")
        if record["usable"] and label != "unit_success":
            raise ValueError(f"{item.get('blind_id')} {panel} usable requires unit_success")
        if not record["usable"] and label == "unit_success":
            raise ValueError(f"{item.get('blind_id')} {panel} failure requires a failure label")


def _replay_case(case: dict[str, object]) -> dict[str, object]:
    spec: TrialSpec = case["spec"]
    budget: NominalBudget = case["budget"]
    return {
        "trial": spec.as_dict(),
        "raw_named_random": {key: round(value, 12) for key, value in case["raw"].items()},
        "raw_random_digest": case["raw_digest"],
        "nominal_budget": budget.as_dict(),
        "budget_hash": budget.digest,
        "primary_summary": case["primary_summary"],
        "L0": {
            "variant_id": "L0_independent",
            "mapping": case["L0"]["mapping"],
            "unit": case["L0"]["unit"].as_dict(),
            "validation": case["L0"]["validation"],
            "metrics": case["L0"]["metrics"],
            "retry_count": 0,
            "resample_count": 0,
            "repair_count": 0,
            "selection_count": 1,
            "visual_status": "pending",
        },
        "L1": {
            "variant_id": "L1_coupled",
            "mapping": case["L1"]["mapping"],
            "unit": case["L1"]["unit"].as_dict(),
            "validation": case["L1"]["validation"],
            "metrics": case["L1"]["metrics"],
            "retry_count": 0,
            "resample_count": 0,
            "repair_count": 0,
            "selection_count": 1,
            "visual_status": "pending",
        },
        "fairness": case["fairness"],
    }


def _scene_payload(scene: Scene) -> dict[str, object]:
    return {
        "prototype_id": scene.prototype_id,
        "repeat_x_range": list(scene.repeat_x_range),
        "canvas_height": scene.canvas_height,
        "anchor": {
            "region_id": REGION_ID,
            "s": scene.anchor_s,
            "point": list(scene.anchor_point),
            "tangent": list(scene.anchor_tangent),
            "growth_direction": list(scene.growth_direction),
            "max_clearance": scene.max_clearance,
        },
        "context": {
            "backbone_count": 1,
            "guide_count": len(scene.guides),
            "flower_reserve_count": len(scene.flowers),
            "context_policy": "locked_backbone_guides_flower_reserves_and_repeat_bounds",
        },
    }


def _validate_registered_scene(scene: Scene, profile: dict[str, object]) -> None:
    if scene.prototype_id != PROTOTYPE_ID:
        raise ValueError("unexpected prototype")
    if abs(scene.anchor_s - 0.8375) > 1e-6:
        raise ValueError(f"registered anchor drifted: {scene.anchor_s}")
    if abs(scene.max_clearance - 86.0) > 1e-6:
        raise ValueError(f"registered clearance drifted: {scene.max_clearance}")
    if len(scene.guides) != 9 or len(scene.flowers) != 2:
        raise ValueError("registered scene context count drifted")
    if not bool(profile["qa"]["region_graph_valid"]):
        raise ValueError("rebuilt region graph is invalid")


def _review_protocol() -> str:
    return """# BranchUnit L blind review protocol

This is a development screening, not paper-level statistical evidence.

Review only `pairs/blind/B01.png` through `B12.png` or `contact_sheet_blind.png`.
Do not open `blind_key.json`, `replay_manifest.json`, `pairs/unblinded/`, `debug/`,
or the metric files until every judgment is frozen.

For A and B separately, mark usable only when all five visual conditions hold:

1. The primary sweep is dominant and readable.
2. Every child reads as growing from the primary rather than floating or forming hair.
3. Child position/length/direction has a readable rhythm; for zero-child trials this is true by construction.
4. The terminal reads as a continuous closure of the primary.
5. The whole object reads as one growth unit.

Use one primary label per panel: `unit_success` for usable results, otherwise one
of `straight_stick`, `hard_angle_bend`, `hairlike_cluster`, `floating_child`,
`crowded_reserve`, or `weak_hierarchy`.  Preserve every failure; there is no
replacement draw.

After review is frozen, run the score command.  L passes only if all three
development gates hold: L1 usable >= 4/12, L1 blind preference >= 7/12, and L1
blind preference within child_count >= 1 trials >= 5/8.  Passing does not start
C automatically; it only permits discussion of C.
"""


def _run_readme(output_dir: Path, manifest: dict[str, object]) -> str:
    status = manifest["data_validity"]
    return f"""# BranchUnit L v1

Scope: only the local L0/L1 causal screening on `proto_sw_1_3`.

- Generated pairs: {manifest['trial_count']}/12
- Child-positive pairs: {manifest['child_positive_trial_count']}/8
- All preregistered budget checks passed: {status['all_budget_match']}
- Visual status: `{status['visual_status']}`

Start blind review from `contact_sheet_blind.png`; use individual images under
`pairs/blind/` when details are too small.  Freeze a copy of
`blind_review_template.json` as `blind_review_round1.json`, then score it with:

```powershell
python "{Path(__file__).resolve()}" score --run-dir "{output_dir.resolve()}" --review "{(output_dir / 'blind_review_round1.json').resolve()}"
```

Verify the saved profile, exact geometry payloads, source hashes, and indexed
artifact hashes with:

```powershell
python "{Path(__file__).resolve()}" verify --run-dir "{output_dir.resolve()}"
```

Do not infer visual success from `hard_valid` or budget metrics.
"""


def _failure_index(summary: dict[str, object]) -> str:
    counts = summary["counts"]
    lines = [
        "# BranchUnit L round-1 failure index",
        "",
        f"Decision: `{summary['decision']}`",
        "",
        f"- L1 usable: {counts['L1_effective_usable']}/12",
        f"- L1 preferred overall: {counts['L1_wins_overall']}/12",
        f"- L1 preferred among child-positive pairs: {counts['L1_wins_child_positive']}/8",
        "",
        "## Per-trial failures",
        "",
    ]
    for row in summary["rows"]:
        failures = []
        for variant in ("L0", "L1"):
            if not row[f"{variant}_effective_usable"]:
                hard = row["hard_failure_reasons"][variant]
                labels = [row[f"{variant}_primary_label"], *row[f"{variant}_secondary_labels"]]
                note = row[f"{variant}_notes"]
                failures.append(
                    f"{variant}: visual={','.join(str(label) for label in labels if label)}; "
                    f"hard={','.join(hard) if hard else 'none'}; note={note or 'none'}"
                )
        if failures:
            lines.append(f"- {row['trial_id']}: " + " | ".join(failures))
    lines.extend(["", "No failed trial was replaced or resampled.", ""])
    return "\n".join(lines)


def _curve_svg_path(curve: Curve) -> str:
    first = curve.cubics[0]
    commands = [f"M {first.p0[0]:.6f},{first.p0[1]:.6f}"]
    commands.extend(
        f"C {cubic.p1[0]:.6f},{cubic.p1[1]:.6f} "
        f"{cubic.p2[0]:.6f},{cubic.p2[1]:.6f} {cubic.p3[0]:.6f},{cubic.p3[1]:.6f}"
        for cubic in curve.cubics
    )
    return " ".join(commands)


def _polyline_svg(points: Sequence[tuple[float, float]], stroke: str, width: float) -> str:
    if not points:
        return ""
    d = " ".join(
        [f"M {points[0][0]:.6f},{points[0][1]:.6f}"]
        + [f"L {point[0]:.6f},{point[1]:.6f}" for point in points[1:]]
    )
    return (
        f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{width:.3f}" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )


def _fixed_view_transform(
    crop: tuple[float, float, float, float],
    image_size: tuple[int, int],
) -> tuple[float, float, float]:
    x0, y0, x1, y1 = crop
    width, height = image_size
    scale = min(width / (x1 - x0), height / (y1 - y0))
    offset_x = (width - (x1 - x0) * scale) * 0.5 - x0 * scale
    offset_y = (height - (y1 - y0) * scale) * 0.5 - y0 * scale
    return scale, offset_x, offset_y


def _tx(point: tuple[float, float], transform: tuple[float, float, float]) -> tuple[int, int]:
    scale, offset_x, offset_y = transform
    return round(point[0] * scale + offset_x), round(point[1] * scale + offset_y)


def _draw_world_polyline(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[float, float]],
    transform: tuple[float, float, float],
    fill: str,
    world_width: float,
) -> None:
    if len(points) < 2:
        return
    width = max(1, round(world_width * transform[0]))
    _draw_rounded_line(draw, [_tx(point, transform) for point in points], fill=fill, width=width)


def _draw_rounded_line(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[int, int]],
    *,
    fill: int | str,
    width: int,
) -> None:
    if len(points) < 2:
        return
    draw.line(points, fill=fill, width=width, joint="curve")
    radius = max(1, width // 2)
    for point in (points[0], points[-1]):
        draw.ellipse((point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius), fill=fill)


def _symmetric_delta(first: float, second: float) -> float:
    denominator = first + second
    return 0.0 if abs(denominator) < 1e-12 else 2.0 * abs(first - second) / denominator


def _payload_sha(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, object]:
    return {"path": str(path.resolve()), "sha256": _sha256(path), "bytes": path.stat().st_size}


def _artifact_hash_index(run_dir: Path) -> dict[str, object]:
    excluded = {"artifact_hashes.json", "verification_report.json", "blind_review_round1.json", "review_summary.json", "failure_index.md"}
    files = []
    for path in sorted(item for item in run_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(run_dir).as_posix()
        if relative in excluded:
            continue
        files.append({"path": relative, "sha256": _sha256(path), "bytes": path.stat().st_size})
    return {"schema": "branch_unit_l_artifact_hash_index_v1", "files": files}


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("cannot write empty CSV")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend([Path("C:/Windows/Fonts/arialbd.ttf"), Path("C:/Windows/Fonts/msyhbd.ttc")])
    candidates.extend([Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/msyh.ttc")])
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the BranchUnit L-only paired screening experiment.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate_parser = subparsers.add_parser("generate", help="generate the fixed 12 L0/L1 pairs")
    generate_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    verify_parser = subparsers.add_parser("verify", help="rebuild geometry from the saved profile and verify hashes")
    verify_parser.add_argument("--run-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    score_parser = subparsers.add_parser("score", help="unblind and score one frozen blind review")
    score_parser.add_argument("--run-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    score_parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        manifest = generate(args.output_dir.resolve())
        print(json.dumps(manifest["data_validity"], ensure_ascii=False, indent=2))
        return 0
    if args.command == "verify":
        report = verify(args.run_dir.resolve())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["valid"] else 1
    summary = score(args.run_dir.resolve(), args.review.resolve())
    print(json.dumps({"counts": summary["counts"], "gates": summary["gates"], "decision": summary["decision"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
