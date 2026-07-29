#!/usr/bin/env python3
"""Whole-repeat hierarchical branch development for proto_sw_1_3.

The module consumes a strict P0 strip (backbone, two flower reserves, and
bounds) and produces every branch programmatically.  J0a keeps only the
7 + 12 + 2 topology fixed; its geometry parameters vary reproducibly by seed.
Validation is check-only; there is no candidate search, retry, repair, or
validation-guided mutation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence

import multibranch_l as legacy
from l_core import (
    Cubic,
    Curve,
    Point,
    add,
    angle_degrees,
    cross,
    dist,
    dot,
    mul,
    point_polyline_distance,
    polyline_pair_distance,
    rotate,
    sample_polyline,
    sub,
)


POLICY_ID = "whole_local_backbone_flowers_bounds_only_v1"
GEOMETRY_KERNEL_ID = "whole_local_true_lateral_branch_units_n12_v17"
PLAN_ID = "proto_sw_1_3_J0c_true_lateral_units_7_12_2_v21"
DEV_SEEDS = (4101, 4102, 4103)
PRIMARY_WIDTH = 3.0
SECONDARY_WIDTH = 2.1
TERTIARY_WIDTH = 1.45
STROKE_LINECAP = "round"
STROKE_LINEJOIN = "round"


def _unit(vector: Point) -> Point:
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-12:
        raise ValueError("degenerate direction")
    return vector[0] / length, vector[1] / length


def _normal(vector: Point) -> Point:
    return -vector[1], vector[0]


def _round_point(point: Point) -> list[float]:
    return [round(point[0], 8), round(point[1], 8)]


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _seed_u(seed: int, label: str) -> float:
    digest = hashlib.sha256(f"{int(seed)}|{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)


def _visible_u(seed: int, label: str) -> float:
    """Low-discrepancy seed coordinate used for deliberately visible variation."""

    golden_step = 0.6180339887498949
    return (int(seed) * golden_step + _seed_u(0, f"visible.{label}")) % 1.0


_MOUNT_STATE_PERMUTATIONS = (
    (0, 1, 2),
    (0, 2, 1),
    (1, 0, 2),
    (1, 2, 0),
    (2, 0, 1),
    (2, 1, 0),
)


def _mount_state(seed: int, label: str) -> int:
    """Assign consecutive seeds to label-specific low/mid/high mount states."""

    permutation_index = min(
        len(_MOUNT_STATE_PERMUTATIONS) - 1,
        int(_seed_u(0, f"mount.permutation.{label}") * len(_MOUNT_STATE_PERMUTATIONS)),
    )
    return _MOUNT_STATE_PERMUTATIONS[permutation_index][int(seed) % 3]


def _mount_u(seed: int, label: str) -> float:
    """Stratified attachment coordinate; labels do not move in lockstep."""

    center = (0.10, 0.50, 0.90)[_mount_state(seed, label)]
    jitter = _lerp(-0.04, 0.04, _seed_u(seed, f"mount.jitter.{label}"))
    return max(0.0, min(1.0, center + jitter))


def _lerp(low: float, high: float, value: float) -> float:
    return low + (high - low) * value


@dataclass(frozen=True)
class BackboneSample:
    s: float
    point: Point
    tangent: Point

    def as_dict(self) -> dict[str, object]:
        return {
            "s": round(self.s, 10),
            "point": _round_point(self.point),
            "tangent": _round_point(self.tangent),
        }


@dataclass(frozen=True)
class FlowerReserve:
    flower_id: str
    center: Point
    rx: float
    ry: float

    def as_dict(self) -> dict[str, object]:
        return {
            "flower_id": self.flower_id,
            "center": _round_point(self.center),
            "rx": round(self.rx, 8),
            "ry": round(self.ry, 8),
        }


@dataclass(frozen=True)
class StrictP0:
    prototype_id: str
    repeat_x_range: tuple[float, float]
    canvas_width: float
    canvas_height: float
    backbone_samples: tuple[BackboneSample, ...]
    flowers: tuple[FlowerReserve, ...]
    policy_id: str = POLICY_ID

    @property
    def backbone_points(self) -> tuple[Point, ...]:
        return tuple(sample.point for sample in self.backbone_samples)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "whole_local_strict_p0_v1",
            "policy_id": self.policy_id,
            "prototype_id": self.prototype_id,
            "repeat_x_range": [round(value, 8) for value in self.repeat_x_range],
            "canvas": {
                "width": round(self.canvas_width, 8),
                "height": round(self.canvas_height, 8),
            },
            "backbone": {
                "arc_samples": [sample.as_dict() for sample in self.backbone_samples],
            },
            "flowers": [flower.as_dict() for flower in self.flowers],
            "consumed_profile_paths": [
                "prototype_id",
                "repeat_x_range",
                "canvas.width",
                "canvas.height",
                "backbone.arc_samples[*].s",
                "backbone.arc_samples[*].point",
                "backbone.arc_samples[*].tangent",
                "flowers[*].flower_id",
                "flowers[*].center",
                "flowers[*].rx",
                "flowers[*].ry",
            ],
        }

    @property
    def digest(self) -> str:
        return _digest(self.as_dict())


def strip_profile(profile: Mapping[str, object]) -> StrictP0:
    """Copy only the strict whole-local P0 whitelist."""

    backbone = dict(profile["backbone"])
    samples = tuple(
        BackboneSample(
            s=float(sample["s"]),
            point=(float(sample["point"][0]), float(sample["point"][1])),
            tangent=_unit((float(sample["tangent"][0]), float(sample["tangent"][1]))),
        )
        for sample in backbone["arc_samples"]
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
    repeat = tuple(float(value) for value in profile["repeat_x_range"])
    canvas = dict(profile["canvas"])
    result = StrictP0(
        prototype_id=str(profile["prototype_id"]),
        repeat_x_range=(repeat[0], repeat[1]),
        canvas_width=float(canvas["width"]),
        canvas_height=float(canvas["height"]),
        backbone_samples=samples,
        flowers=flowers,
    )
    if result.prototype_id != "proto_sw_1_3":
        raise ValueError(f"unexpected prototype: {result.prototype_id}")
    if len(result.flowers) != 2 or len(result.backbone_samples) < 2:
        raise ValueError("J0a requires one backbone and two flower positions")
    finite_values = [
        *result.repeat_x_range,
        result.canvas_width,
        result.canvas_height,
        *(value for sample in result.backbone_samples for value in (sample.s, *sample.point, *sample.tangent)),
        *(value for flower in result.flowers for value in (*flower.center, flower.rx, flower.ry)),
    ]
    if not all(math.isfinite(value) for value in finite_values):
        raise ValueError("J0a strict P0 contains NaN or infinity")
    if any(flower.rx <= 0.0 or flower.ry <= 0.0 for flower in result.flowers):
        raise ValueError("J0a flower radii must be positive")
    if any(not 0.0 <= sample.s <= 1.0 for sample in result.backbone_samples):
        raise ValueError("J0a backbone sample fractions must lie in [0, 1]")
    if any(
        second.s <= first.s
        for first, second in zip(result.backbone_samples, result.backbone_samples[1:])
    ):
        raise ValueError("J0a backbone sample fractions must be strictly increasing")
    expected_repeat = (0.0, 256.0)
    if (
        any(abs(actual - expected) > 1e-8 for actual, expected in zip(result.repeat_x_range, expected_repeat))
        or abs(result.canvas_width - 1024.0) > 1e-8
        or abs(result.canvas_height - 304.0) > 1e-8
    ):
        raise ValueError(
            "J0a source canvas/repeat must be canvas 1024 x 304 with visible repeat x=[0, 256]"
        )
    return result


def ignored_field_intervention(profile: Mapping[str, object]) -> dict[str, object]:
    poisoned = copy.deepcopy(dict(profile))
    poison = [{"poison": [999999.0, -999999.0], "must_not_be_read": True}]
    for key in (
        "existing_guides",
        "growth_regions",
        "space_samples",
        "region_graph",
        "nodes",
        "segments",
        "qa",
        "attachments",
        "branch_roles",
        "clearance",
    ):
        poisoned[key] = copy.deepcopy(poison)
    backbone = dict(poisoned["backbone"])
    backbone["source_path_order"] = [999999, -999999]
    poisoned["backbone"] = backbone
    return poisoned


def _global_envelope_values(p0: StrictP0, seed: int) -> dict[str, float]:
    """Derive top/bottom edge bands and seed-varying frontier slots."""

    envelope_bottom_y = p0.canvas_height - _lerp(
        12.0,
        22.0,
        _visible_u(seed, "global.envelope.bottom_inset"),
    )
    envelope_top_y = _lerp(38.0, 52.0, _visible_u(seed, "global.envelope.top"))
    top_1_frontier_x = _lerp(25.0, 80.0, _visible_u(seed, "global.frontier.top_1_x"))
    top_6_frontier_x = _lerp(105.0, 155.0, _visible_u(seed, "global.frontier.top_6_x"))
    bottom_3_frontier_x = _lerp(70.0, 130.0, _visible_u(seed, "global.frontier.bottom_3_x"))

    primary_2_tip_x = _lerp(3.0, 22.0, _visible_u(seed, "global.unit_2.primary_tip_x"))
    primary_2_tip_y = _lerp(245.0, 268.0, _visible_u(seed, "global.unit_2.primary_tip_y"))
    primary_7_tip_x = _lerp(220.0, 248.0, _visible_u(seed, "global.unit_7.primary_tip_x"))
    primary_7_tip_y = _lerp(58.0, 85.0, _visible_u(seed, "global.unit_7.primary_tip_y"))
    secondary_2_frontier_x = _lerp(42.0, 58.0, _visible_u(seed, "global.frontier.bottom_secondary_2_x"))
    secondary_7_frontier_x = _lerp(180.0, 200.0, _visible_u(seed, "global.frontier.top_secondary_7_x"))

    return {
        "envelope_top_y": envelope_top_y,
        "envelope_bottom_y": envelope_bottom_y,
        "top_1_frontier_x": top_1_frontier_x,
        "top_6_frontier_x": top_6_frontier_x,
        "bottom_3_frontier_x": bottom_3_frontier_x,
        "primary_2_tip_x": primary_2_tip_x,
        "primary_2_tip_y": primary_2_tip_y,
        "primary_7_tip_x": primary_7_tip_x,
        "primary_7_tip_y": primary_7_tip_y,
        "secondary_2_frontier_x": secondary_2_frontier_x,
        "secondary_7_frontier_x": secondary_7_frontier_x,
    }


@dataclass(frozen=True)
class GlobalControls:
    rhythm_shift: float = 0.0
    length_scale: float = 1.0


@dataclass(frozen=True)
class SubtreeControl:
    flow: float = 0.0


@dataclass(frozen=True)
class PrimaryPlan:
    curve_id: str
    mount_s: float
    kind: str
    target_flower_id: str | None
    target_boundary: str | None
    target_point: Point | None
    terminal_tangent: Point | None
    tangent_weight: float
    normal_weight: float
    chord_length: float
    start_arm_ratio: float
    end_arm_ratio: float
    entry_opening_degrees: float
    exit_release_degrees: float
    bend_mode: str
    side_sign: int
    secondary_budget: int

    def as_dict(self) -> dict[str, object]:
        return {
            "curve_id": self.curve_id,
            "mount_s": round(self.mount_s, 10),
            "kind": self.kind,
            "target_flower_id": self.target_flower_id,
            "target_boundary": self.target_boundary,
            "target_point": None if self.target_point is None else _round_point(self.target_point),
            "terminal_tangent": None if self.terminal_tangent is None else _round_point(self.terminal_tangent),
            "tangent_weight": round(self.tangent_weight, 8),
            "normal_weight": round(self.normal_weight, 8),
            "chord_length": round(self.chord_length, 8),
            "start_arm_ratio": round(self.start_arm_ratio, 8),
            "end_arm_ratio": round(self.end_arm_ratio, 8),
            "entry_opening_degrees": round(self.entry_opening_degrees, 8),
            "exit_release_degrees": round(self.exit_release_degrees, 8),
            "bend_mode": self.bend_mode,
            "side_sign": self.side_sign,
            "secondary_budget": self.secondary_budget,
        }


@dataclass(frozen=True)
class ChildPlan:
    curve_id: str
    parent_id: str
    growth_role: str
    target_boundary: str | None
    target_point: Point | None
    terminal_tangent: Point | None
    travel_direction: Point | None
    level: int
    mount_fraction: float
    turn_sign: int
    opening_angle_degrees: float
    chord_length: float
    handle_ratio: float
    entry_opening_degrees: float
    exit_release_degrees: float
    bend_mode: str

    def as_dict(self) -> dict[str, object]:
        return {
            "curve_id": self.curve_id,
            "parent_id": self.parent_id,
            "growth_role": self.growth_role,
            "target_boundary": self.target_boundary,
            "target_point": None if self.target_point is None else _round_point(self.target_point),
            "terminal_tangent": None if self.terminal_tangent is None else _round_point(self.terminal_tangent),
            "travel_direction": None if self.travel_direction is None else _round_point(self.travel_direction),
            "level": self.level,
            "mount_fraction": round(self.mount_fraction, 8),
            "turn_sign": self.turn_sign,
            "opening_angle_degrees": round(self.opening_angle_degrees, 8),
            "chord_length": round(self.chord_length, 8),
            "handle_ratio": round(self.handle_ratio, 8),
            "entry_opening_degrees": round(self.entry_opening_degrees, 8),
            "exit_release_degrees": round(self.exit_release_degrees, 8),
            "bend_mode": self.bend_mode,
        }


@dataclass(frozen=True)
class GlobalPlan:
    plan_id: str
    seed: int
    controls: GlobalControls
    primaries: tuple[PrimaryPlan, ...]
    descendants: tuple[ChildPlan, ...]
    latent_summary: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "seed": self.seed,
            "controls": {
                "rhythm_shift": round(self.controls.rhythm_shift, 8),
                "length_scale": round(self.controls.length_scale, 8),
            },
            "primaries": [row.as_dict() for row in self.primaries],
            "descendants": [row.as_dict() for row in self.descendants],
            "latent_summary": {key: round(value, 10) for key, value in sorted(self.latent_summary.items())},
            "generation_policy": {
                "candidate_count": 1,
                "retry_count": 0,
                "resample_count": 0,
                "repair_count": 0,
                "validation_feedback_consumed": False,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.as_dict())


def plan_j0a(
    p0: StrictP0,
    seed: int,
    controls: GlobalControls = GlobalControls(),
    subtree_controls: Mapping[str, SubtreeControl] | None = None,
) -> GlobalPlan:
    """Create seven true local BranchUnits in one replayable 7 + 12 + 2 plan."""

    if not -0.04 <= controls.rhythm_shift <= 0.04:
        raise ValueError("rhythm_shift must remain in [-0.04, 0.04]")
    if not 0.85 <= controls.length_scale <= 1.15:
        raise ValueError("length_scale must remain in [0.85, 1.15]")
    subtree_controls = dict(subtree_controls or {})
    rhythm = 2.0 * _seed_u(seed, "global.rhythm") - 1.0
    length_latent = _seed_u(seed, "global.length")
    bend_latent = _seed_u(seed, "global.bend")
    envelope_plan = _global_envelope_values(p0, seed)
    envelope_top_y = envelope_plan["envelope_top_y"]
    envelope_bottom_y = envelope_plan["envelope_bottom_y"]

    primary_geometry: dict[str, tuple[Point, str | None, Point]] = {
        "primary_1_free": (
            (envelope_plan["top_1_frontier_x"], envelope_top_y + 0.5 * PRIMARY_WIDTH),
            "top_frontier",
            (1.0, 0.0),
        ),
        "primary_2_free": (
            (envelope_plan["primary_2_tip_x"], envelope_plan["primary_2_tip_y"]),
            None,
            (0.0, 1.0),
        ),
        "primary_3_free": (
            (envelope_plan["bottom_3_frontier_x"], envelope_bottom_y - 0.5 * PRIMARY_WIDTH),
            "bottom_frontier",
            (-1.0, 0.0),
        ),
        "primary_6_balance": (
            (envelope_plan["top_6_frontier_x"], envelope_top_y + 0.5 * PRIMARY_WIDTH),
            "top_frontier",
            (-1.0, 0.0),
        ),
        "primary_7_free": (
            (envelope_plan["primary_7_tip_x"], envelope_plan["primary_7_tip_y"]),
            None,
            (1.0, 0.0),
        ),
    }
    fixed_side_sign = {
        "primary_1_free": -1,
        "primary_2_free": 1,
        "primary_3_free": 1,
        "primary_6_balance": -1,
        "primary_7_free": -1,
    }
    primary_templates = (
        ("primary_1_free", (0.035, 0.090), "free", None, 2, (44.0, 60.0)),
        ("primary_2_free", (0.145, 0.215), "free", None, 2, (42.0, 58.0)),
        ("primary_3_free", (0.285, 0.355), "free", None, 2, (48.0, 62.0)),
        ("primary_4_flower_1", (0.392, 0.408), "flower", "flower_1", 1, (40.0, 52.0)),
        ("primary_5_flower_2", (0.485, 0.560), "flower", "flower_2", 1, (40.0, 52.0)),
        ("primary_6_balance", (0.570, 0.675), "balance", None, 2, (38.0, 56.0)),
        ("primary_7_free", (0.735, 0.850), "free", None, 2, (54.0, 68.0)),
    )
    rhythm_weights = (-0.85, 0.65, -0.55, 0.0, 0.50, -0.45, 0.75)
    primary_mount_states = {
        "primary_1_free": (0.040, 0.065, 0.090),
        "primary_2_free": (0.210, 0.180, 0.150),
        "primary_3_free": (0.335, 0.307, 0.285),
        "primary_5_flower_2": (0.5225, 0.490, 0.555),
        "primary_6_balance": (0.580, 0.625, 0.670),
        "primary_7_free": (0.740, 0.820, 0.780),
    }
    primaries: list[PrimaryPlan] = []
    for index, (
        curve_id,
        mount_range,
        kind,
        flower_id,
        child_budget,
        opening_range,
    ) in enumerate(primary_templates):
        control = subtree_controls.get(curve_id, SubtreeControl())
        flow = max(-1.0, min(1.0, control.flow))
        subtree_latent = 2.0 * _seed_u(seed, f"{curve_id}.subtree") - 1.0
        if curve_id in primary_mount_states:
            mount_s = primary_mount_states[curve_id][
                _mount_state(seed, f"{curve_id}.mount")
            ] + _lerp(
                -0.0015,
                0.0015,
                _seed_u(seed, f"{curve_id}.primary_mount_jitter"),
            )
        else:
            mount_s = _lerp(
                mount_range[0],
                mount_range[1],
                _visible_u(seed, f"{curve_id}.mount"),
            )
        if curve_id != "primary_4_flower_1":
            mount_s += controls.rhythm_shift * rhythm_weights[index]
            mount_s = max(mount_range[0], min(mount_range[1], mount_s))
        root, tangent = sample_polyline(p0.backbone_points, mount_s)
        if kind == "flower":
            flower = next(item for item in p0.flowers if item.flower_id == flower_id)
            endpoint = radial_flower_collar(root, flower)
            target_boundary = None
            target_point = None
            terminal_tangent = None
        else:
            endpoint, target_boundary, terminal_tangent = primary_geometry[curve_id]
            target_point = endpoint
        direction = _unit(sub(endpoint, root))
        signed_delta = _signed_angle(tangent, direction)
        opening_u = 0.55 * _visible_u(seed, f"{curve_id}.opening") + 0.45 * min(
            1.0,
            abs(signed_delta) / 120.0,
        )
        entry_opening = _lerp(opening_range[0], opening_range[1], opening_u)
        bend_u = max(
            0.0,
            min(
                1.0,
                0.30 * bend_latent
                + 0.50 * _visible_u(seed, f"{curve_id}.bend")
                + 0.20 * (0.5 + 0.5 * subtree_latent),
            ),
        )
        start_arm = _lerp(
            0.28,
            0.39 if kind == "flower" else 0.43,
            _visible_u(seed, f"{curve_id}.start_arm"),
        ) * (1.0 + 0.12 * flow)
        end_arm = _lerp(
            0.28 if kind == "flower" else 0.30,
            0.40 if kind == "flower" else 0.45,
            _visible_u(seed, f"{curve_id}.end_arm"),
        ) * (1.0 - 0.10 * flow)
        if curve_id == "primary_6_balance":
            start_arm = _lerp(
                0.20,
                0.52,
                _visible_u(seed, f"{curve_id}.start_arm"),
            ) * (1.0 + 0.12 * flow)
            end_arm = _lerp(
                0.24,
                0.56,
                _visible_u(seed, f"{curve_id}.visible_length"),
            ) * (1.0 - 0.10 * flow)
        if curve_id == "primary_7_free":
            start_arm *= 0.78
            end_arm *= 0.80
        if curve_id == "primary_1_free":
            arm_scale = (1.16, 0.94, 1.00)[
                _mount_state(seed, f"{curve_id}.mount")
            ]
            start_arm *= arm_scale
            end_arm *= arm_scale
        primaries.append(
            PrimaryPlan(
                curve_id=curve_id,
                mount_s=mount_s,
                kind=kind,
                target_flower_id=flower_id,
                target_boundary=target_boundary,
                target_point=target_point,
                terminal_tangent=terminal_tangent,
                tangent_weight=dot(direction, tangent),
                normal_weight=dot(direction, _normal(tangent)),
                chord_length=dist(root, endpoint),
                start_arm_ratio=start_arm,
                end_arm_ratio=end_arm,
                entry_opening_degrees=entry_opening,
                exit_release_degrees=(0.0 if terminal_tangent is not None or kind == "flower" else _lerp(18.0, 34.0, bend_u)),
                bend_mode="C" if kind == "flower" or _visible_u(seed, f"{curve_id}.mode") < 0.55 else "S",
                side_sign=fixed_side_sign.get(
                    curve_id,
                    1 if cross(tangent, direction) >= 0.0 else -1,
                ),
                secondary_budget=child_budget,
            )
        )

    child_templates = (
        ("secondary_1a_lat", "primary_1_free", 2, "lateral", (0.28, 0.56), (50.0, 68.0), (24.0, 52.0), (-25.0, 35.0), None),
        ("secondary_1b_lat", "primary_1_free", 2, "lateral", (0.48, 0.76), (50.0, 68.0), (18.0, 28.0), (-140.0, -105.0), None),
        ("secondary_2a_lat", "primary_2_free", 2, "lateral", (0.48, 0.76), (45.0, 65.0), (0.0, 0.0), (0.0, 0.0), "bottom_frontier"),
        ("secondary_2b_lat", "primary_2_free", 2, "lateral", (0.28, 0.56), (50.0, 68.0), (14.0, 26.0), (-160.0, -110.0), None),
        ("secondary_3a_lat", "primary_3_free", 2, "lateral", (0.28, 0.56), (50.0, 68.0), (14.0, 24.0), (100.0, 150.0), None),
        ("secondary_3b_lat", "primary_3_free", 2, "lateral", (0.48, 0.76), (42.0, 68.0), (14.0, 38.0), (-42.0, 2.0), None),
        ("secondary_4a_wrap", "primary_4_flower_1", 2, "flower_wrap", (0.565, 0.775), (42.0, 65.0), (18.0, 38.0), (-180.0, -160.0), None),
        ("secondary_5a_wrap", "primary_5_flower_2", 2, "flower_wrap", (0.565, 0.775), (50.0, 68.0), (22.0, 44.0), (45.0, 105.0), None),
        ("secondary_6a_lat", "primary_6_balance", 2, "lateral", (0.28, 0.56), (42.0, 68.0), (28.0, 58.0), (-180.0, -120.0), None),
        ("secondary_6b_lat", "primary_6_balance", 2, "lateral", (0.48, 0.76), (50.0, 68.0), (20.0, 36.0), (-50.0, 10.0), None),
        ("secondary_7a_lat", "primary_7_free", 2, "lateral", (0.48, 0.76), (45.0, 65.0), (0.0, 0.0), (0.0, 0.0), "top_frontier"),
        ("secondary_7b_lat", "primary_7_free", 2, "lateral", (0.28, 0.56), (42.0, 68.0), (18.0, 26.0), (-180.0, -150.0), None),
        ("tertiary_3a_1", "secondary_3a_lat", 3, "lateral", (0.24, 0.76), (38.0, 65.0), (6.0, 12.0), (20.0, 70.0), None),
        ("tertiary_6a_1", "secondary_6a_lat", 3, "lateral", (0.24, 0.76), (38.0, 65.0), (10.0, 24.0), (85.0, 145.0), None),
    )
    primary_preview = {
        row.curve_id: _compile_primary(p0, row)
        for row in primaries
    }
    paired_mount_roles = {
        "primary_1_free": ("secondary_1a_lat", "secondary_1b_lat"),
        "primary_2_free": ("secondary_2b_lat", "secondary_2a_lat"),
        "primary_3_free": ("secondary_3a_lat", "secondary_3b_lat"),
        "primary_6_balance": ("secondary_6a_lat", "secondary_6b_lat"),
        "primary_7_free": ("secondary_7b_lat", "secondary_7a_lat"),
    }
    pair_center_states = {
        "primary_1_free": (0.40, 0.50, 0.60),
        "primary_2_free": (0.45, 0.52, 0.59),
        "primary_3_free": (0.45, 0.56, 0.61),
        "primary_6_balance": (0.48, 0.52, 0.61),
        "primary_7_free": (0.55, 0.60, 0.65),
    }
    coordinated_mounts: dict[str, float] = {}
    for primary_id, (near_id, far_id) in paired_mount_roles.items():
        state = _mount_state(seed, f"{primary_id}.child_pair")
        center = pair_center_states[primary_id][state] + _lerp(
            -0.008,
            0.008,
            _seed_u(seed, f"{primary_id}.child_pair.jitter"),
        )
        coordinated_mounts[near_id] = center - 0.10
        coordinated_mounts[far_id] = center + 0.10
    for primary_id, child_id in (
        ("primary_4_flower_1", "secondary_4a_wrap"),
        ("primary_5_flower_2", "secondary_5a_wrap"),
    ):
        state = _mount_state(seed, f"{primary_id}.single_child")
        coordinated_mounts[child_id] = (0.57, 0.67, 0.77)[state] + _lerp(
            -0.005,
            0.005,
            _seed_u(seed, f"{primary_id}.single_child.jitter"),
        )
    for child_id in ("tertiary_3a_1", "tertiary_6a_1"):
        state = _mount_state(seed, f"{child_id}.mount")
        coordinated_mounts[child_id] = (0.45, 0.56, 0.67)[state] + _lerp(
            -0.005,
            0.005,
            _seed_u(seed, f"{child_id}.mount.jitter"),
        )
    descendants: list[ChildPlan] = []
    for (
        curve_id,
        parent_id,
        level,
        growth_role,
        mount_range,
        opening_range,
        length_range,
        travel_angle_range,
        target_boundary,
    ) in child_templates:
        subtree_id = _subtree_id(curve_id)
        control = subtree_controls.get(subtree_id, SubtreeControl())
        flow = max(-1.0, min(1.0, control.flow))
        subtree_u = _seed_u(seed, f"{subtree_id}.subtree")
        mount_fraction = coordinated_mounts.get(
            curve_id,
            _lerp(*mount_range, _mount_u(seed, f"{curve_id}.mount")),
        )
        opening = _lerp(*opening_range, _visible_u(seed, f"{curve_id}.opening")) * (1.0 + 0.06 * flow)
        if target_boundary == "bottom_frontier":
            target_point = (
                envelope_plan["secondary_2_frontier_x"],
                envelope_bottom_y - 0.5 * SECONDARY_WIDTH,
            )
            terminal_tangent = (1.0, 0.0)
            travel_direction = None
            parent = primary_preview[parent_id]
            estimated_root, _ = sample_polyline(parent.curve.points(192), mount_fraction)
            chord = dist(estimated_root, target_point)
        elif target_boundary == "top_frontier":
            target_point = (
                envelope_plan["secondary_7_frontier_x"],
                envelope_top_y + 0.5 * SECONDARY_WIDTH,
            )
            terminal_tangent = (1.0, 0.0)
            travel_direction = None
            parent = primary_preview[parent_id]
            estimated_root, _ = sample_polyline(parent.curve.points(192), mount_fraction)
            chord = dist(estimated_root, target_point)
        else:
            target_point = None
            terminal_tangent = None
            travel_angle = _lerp(*travel_angle_range, _visible_u(seed, f"{curve_id}.travel_angle"))
            travel_direction = (
                math.cos(math.radians(travel_angle)),
                math.sin(math.radians(travel_angle)),
            )
            length_u = _visible_u(seed, f"{curve_id}.length")
            chord = _lerp(*length_range, length_u) * controls.length_scale * (1.0 + 0.10 * flow)
        bend_u = 0.35 * bend_latent + 0.65 * _visible_u(seed, f"{curve_id}.bend")
        arm_u = _visible_u(seed, f"{curve_id}.arm")
        handle_ratio = _lerp(0.24, 0.38, arm_u) * (1.0 + 0.10 * flow)
        if curve_id == "secondary_6a_lat":
            shape_u = _visible_u(seed, f"{curve_id}.shape_bulge")
            handle_ratio = _lerp(0.18, 0.40, shape_u) * (1.0 + 0.10 * flow)
        if curve_id == "secondary_7a_lat":
            shape_u = _visible_u(seed, f"{curve_id}.shape_bulge")
            handle_ratio = _lerp(0.16, 0.42, shape_u) * (1.0 + 0.10 * flow)
        if curve_id == "secondary_2b_lat":
            handle_ratio *= 0.82
        if curve_id == "secondary_7b_lat":
            handle_ratio *= (0.72, 0.84, 0.96)[
                _mount_state(seed, f"{curve_id}.shape_gain")
            ]
        descendants.append(
            ChildPlan(
                curve_id=curve_id,
                parent_id=parent_id,
                growth_role=growth_role,
                target_boundary=target_boundary,
                target_point=target_point,
                terminal_tangent=terminal_tangent,
                travel_direction=travel_direction,
                level=level,
                mount_fraction=mount_fraction,
                turn_sign=1,
                opening_angle_degrees=opening,
                chord_length=chord,
                handle_ratio=handle_ratio,
                entry_opening_degrees=opening,
                exit_release_degrees=(0.0 if terminal_tangent is not None else _lerp(18.0, 34.0, bend_u)),
                bend_mode="C" if terminal_tangent is not None or _visible_u(seed, f"{curve_id}.mode") < 0.55 else "S",
            )
        )
    return GlobalPlan(
        PLAN_ID,
        int(seed),
        controls,
        tuple(primaries),
        tuple(descendants),
        {
            "rhythm": rhythm,
            "length": length_latent,
            "bend": bend_latent,
            **envelope_plan,
        },
    )


def _subtree_id(curve_id: str) -> str:
    if curve_id.startswith("primary_"):
        return curve_id
    if curve_id.startswith("secondary_1") or curve_id.startswith("tertiary_1"):
        return "primary_1_free"
    if curve_id.startswith("secondary_2"):
        return "primary_2_free"
    if curve_id.startswith("secondary_3") or curve_id.startswith("tertiary_3"):
        return "primary_3_free"
    if curve_id.startswith("secondary_4") or curve_id.startswith("tertiary_4"):
        return "primary_4_flower_1"
    if curve_id.startswith("secondary_5") or curve_id.startswith("tertiary_5"):
        return "primary_5_flower_2"
    if curve_id.startswith("secondary_6") or curve_id.startswith("tertiary_6"):
        return "primary_6_balance"
    if curve_id.startswith("secondary_7") or curve_id.startswith("tertiary_7"):
        return "primary_7_free"
    raise ValueError(f"unregistered subtree for {curve_id}")


@dataclass(frozen=True)
class HierarchyCurve:
    curve: Curve
    level: int
    kind: str
    target_flower_id: str | None = None
    source: str = "program_generated"

    def as_dict(self) -> dict[str, object]:
        return {
            "curve_id": self.curve.curve_id,
            "level": self.level,
            "kind": self.kind,
            "parent_id": self.curve.parent_id,
            "target_flower_id": self.target_flower_id,
            "source": self.source,
            "curve": self.curve.as_dict(),
        }


@dataclass(frozen=True)
class HierarchyResult:
    plan: GlobalPlan
    curves: tuple[HierarchyCurve, ...]

    @property
    def by_id(self) -> dict[str, HierarchyCurve]:
        return {node.curve.curve_id: node for node in self.curves}

    @property
    def geometry_hash(self) -> str:
        payload = {
            "geometry_kernel_id": GEOMETRY_KERNEL_ID,
            "stroke_model": {"linecap": STROKE_LINECAP, "linejoin": STROKE_LINEJOIN},
            "curves": [node.as_dict() for node in sorted(self.curves, key=lambda item: item.curve.curve_id)],
        }
        return _digest(payload)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "whole_local_hierarchy_result_v1",
            "geometry_kernel_id": GEOMETRY_KERNEL_ID,
            "stroke_model": {
                "linecap": STROKE_LINECAP,
                "linejoin": STROKE_LINEJOIN,
                "width_alignment": "centered_on_curve",
            },
            "plan": self.plan.as_dict(),
            "topology": {
                "level_1": sum(node.level == 1 for node in self.curves),
                "level_2": sum(node.level == 2 for node in self.curves),
                "level_3": sum(node.level == 3 for node in self.curves),
                "maximum_depth": max(node.level for node in self.curves),
            },
            "curves": [node.as_dict() for node in sorted(self.curves, key=lambda item: item.curve.curve_id)],
            "geometry_hash": self.geometry_hash,
        }


def flower_collar(p0: StrictP0, flower: FlowerReserve) -> tuple[float, Point]:
    nearest_s, nearest = _nearest_backbone_projection(p0.backbone_points, flower.center)
    delta = sub(nearest, flower.center)
    denominator = math.sqrt((delta[0] / flower.rx) ** 2 + (delta[1] / flower.ry) ** 2)
    if denominator <= 1e-12:
        raise ValueError(f"flower {flower.flower_id} center lies on backbone")
    return nearest_s, add(flower.center, mul(delta, 1.0 / denominator))


def radial_flower_collar(root: Point, flower: FlowerReserve) -> Point:
    """Intersect the root-to-flower-centre ray with the flower ellipse."""

    delta = sub(root, flower.center)
    denominator = math.sqrt((delta[0] / flower.rx) ** 2 + (delta[1] / flower.ry) ** 2)
    if denominator <= 1e-12:
        raise ValueError(f"flower {flower.flower_id} center equals branch root")
    return add(flower.center, mul(delta, 1.0 / denominator))


def _nearest_backbone_projection(points: Sequence[Point], point: Point) -> tuple[float, Point]:
    lengths = [dist(start, end) for start, end in zip(points, points[1:])]
    total = sum(lengths)
    traversed = 0.0
    best_distance = math.inf
    best_s = 0.0
    best_point = points[0]
    for start, end, length in zip(points, points[1:], lengths):
        vector = sub(end, start)
        denominator = dot(vector, vector)
        local = 0.0 if denominator <= 1e-12 else max(0.0, min(1.0, dot(sub(point, start), vector) / denominator))
        projection = add(start, mul(vector, local))
        current = dist(point, projection)
        if current < best_distance:
            best_distance = current
            best_s = (traversed + local * length) / max(total, 1e-12)
            best_point = projection
        traversed += length
    return best_s, best_point


def _elevated_quadratic(start: Point, control: Point, end: Point) -> Cubic:
    return Cubic(
        p0=start,
        p1=add(start, mul(sub(control, start), 2.0 / 3.0)),
        p2=add(end, mul(sub(control, end), 2.0 / 3.0)),
        p3=end,
    )


def _signed_angle(first: Point, second: Point) -> float:
    first = _unit(first)
    second = _unit(second)
    return math.degrees(math.atan2(cross(first, second), dot(first, second)))


def _rotate_toward(first: Point, second: Point, maximum_degrees: float) -> Point:
    turn = _signed_angle(first, second)
    applied = max(-maximum_degrees, min(maximum_degrees, turn))
    return _unit(rotate(first, applied))


def _branch_entry_tangent(parent_tangent: Point, travel_direction: Point, opening_degrees: float) -> Point:
    """Apply the planned visible fork angle toward the branch travel side."""

    turn = _signed_angle(parent_tangent, travel_direction)
    sign = 1.0 if turn >= 0.0 else -1.0
    return _unit(rotate(parent_tangent, sign * opening_degrees))


def _curve(
    curve_id: str,
    role: str,
    parent_id: str,
    width: float,
    mount_fraction: float,
    cubics: tuple[Cubic, ...],
) -> Curve:
    provisional = Curve(curve_id, role, parent_id, width, 0.0, cubics, mount_fraction)
    return replace(provisional, target_length=provisional.length)


def _compile_primary(p0: StrictP0, row: PrimaryPlan) -> HierarchyCurve:
    root, tangent = sample_polyline(p0.backbone_points, row.mount_s)
    if row.kind == "flower":
        flower = next(item for item in p0.flowers if item.flower_id == row.target_flower_id)
        endpoint = radial_flower_collar(root, flower)
        direction = _unit(sub(flower.center, endpoint))
        exit_tangent = direction
    else:
        direction = _unit(add(mul(tangent, row.tangent_weight), mul(_normal(tangent), row.normal_weight)))
        endpoint = row.target_point if row.target_point is not None else add(root, mul(direction, row.chord_length))
        if row.terminal_tangent is not None:
            exit_tangent = _unit(row.terminal_tangent)
        else:
            turn_sign = 1.0 if _signed_angle(tangent, direction) >= 0.0 else -1.0
            release_sign = turn_sign if row.bend_mode == "C" else -turn_sign
            exit_tangent = _unit(rotate(direction, release_sign * row.exit_release_degrees))
    entry_tangent = _unit(rotate(tangent, row.side_sign * row.entry_opening_degrees))
    chord = dist(root, endpoint)
    first_control = add(root, mul(entry_tangent, chord * row.start_arm_ratio))
    second_control = sub(endpoint, mul(exit_tangent, chord * row.end_arm_ratio))
    if row.target_point is not None and row.terminal_tangent is not None:
        cubics = (Cubic(root, first_control, second_control, endpoint),)
    else:
        midpoint = mul(add(first_control, second_control), 0.5)
        cubics = (
            _elevated_quadratic(root, first_control, midpoint),
            _elevated_quadratic(midpoint, second_control, endpoint),
        )
    role = "flower_primary" if row.kind == "flower" else "free_primary"
    curve = _curve(row.curve_id, role, "backbone", PRIMARY_WIDTH, row.mount_s, cubics)
    return HierarchyCurve(curve, 1, row.kind, row.target_flower_id)


def _compile_child(parent: HierarchyCurve, row: ChildPlan) -> HierarchyCurve:
    """Compile a real lateral child rooted on the interior of its parent."""

    if row.growth_role not in {"lateral", "flower_wrap"}:
        raise ValueError(f"unsupported child growth role: {row.growth_role}")
    if row.level != parent.level + 1 or row.level not in {2, 3}:
        raise ValueError(f"invalid hierarchy level for {row.curve_id}")
    if not 0.0 < row.mount_fraction < 0.8:
        raise ValueError(f"lateral child {row.curve_id} must mount inside its parent")
    if row.target_boundary not in {None, "top_frontier", "bottom_frontier"}:
        raise ValueError(f"invalid frontier side for {row.curve_id}")
    if (row.target_boundary is None) != (row.target_point is None):
        raise ValueError(f"incomplete frontier target for {row.curve_id}")
    root, tangent = sample_polyline(parent.curve.points(192), row.mount_fraction)
    if row.target_point is not None:
        endpoint = row.target_point
        direction = _unit(sub(endpoint, root))
        entry_tangent = _branch_entry_tangent(tangent, direction, row.entry_opening_degrees)
        if row.terminal_tangent is None:
            raise ValueError(f"frontier lateral {row.curve_id} lacks a terminal tangent")
        exit_tangent = _unit(row.terminal_tangent)
    else:
        direction = (
            _unit(row.travel_direction)
            if row.travel_direction is not None
            else _unit(rotate(tangent, row.turn_sign * row.opening_angle_degrees))
        )
        endpoint = add(root, mul(direction, row.chord_length))
        entry_tangent = _branch_entry_tangent(tangent, direction, row.entry_opening_degrees)
        release_sign = row.turn_sign if row.bend_mode == "C" else -row.turn_sign
        exit_tangent = _unit(rotate(direction, release_sign * row.exit_release_degrees))
    chord_length = dist(root, endpoint)
    start_ratio = max(0.18, min(0.40, row.handle_ratio))
    end_ratio = max(0.18, min(0.40, row.handle_ratio + row.exit_release_degrees * 0.0015))
    first_control = add(root, mul(entry_tangent, chord_length * start_ratio))
    second_control = sub(endpoint, mul(exit_tangent, chord_length * end_ratio))
    midpoint = mul(add(first_control, second_control), 0.5)
    cubics = (
        _elevated_quadratic(root, first_control, midpoint),
        _elevated_quadratic(midpoint, second_control, endpoint),
    )
    width = SECONDARY_WIDTH if row.level == 2 else TERTIARY_WIDTH
    role = "secondary_lateral" if row.level == 2 else "tertiary_lateral"
    return HierarchyCurve(
        _curve(row.curve_id, role, row.parent_id, width, row.mount_fraction, cubics),
        row.level,
        "free",
    )


def compile_plan(plan: GlobalPlan, p0: StrictP0, traversal_order: Sequence[str] | None = None) -> HierarchyResult:
    primary_by_id = {row.curve_id: row for row in plan.primaries}
    order = tuple(traversal_order or primary_by_id.keys())
    if set(order) != set(primary_by_id) or len(order) != len(primary_by_id):
        raise ValueError("traversal_order must contain every primary exactly once")
    generated: dict[str, HierarchyCurve] = {}
    descendants_by_subtree: dict[str, list[ChildPlan]] = {key: [] for key in primary_by_id}
    for row in plan.descendants:
        descendants_by_subtree[_subtree_id(row.curve_id)].append(row)
    for primary_id in order:
        rows = descendants_by_subtree[primary_id]
        generated[primary_id] = _compile_primary(p0, primary_by_id[primary_id])
        for level in (2, 3):
            for row in sorted((item for item in rows if item.level == level), key=lambda item: item.curve_id):
                parent = generated[row.parent_id]
                generated[row.curve_id] = _compile_child(parent, row)
    return HierarchyResult(plan, tuple(sorted(generated.values(), key=lambda item: item.curve.curve_id)))


def build_j0a(
    p0: StrictP0,
    seed: int,
    controls: GlobalControls = GlobalControls(),
    subtree_controls: Mapping[str, SubtreeControl] | None = None,
    traversal_order: Sequence[str] | None = None,
) -> HierarchyResult:
    return compile_plan(plan_j0a(p0, seed, controls, subtree_controls), p0, traversal_order)


def _ellipse_value(point: Point, flower: FlowerReserve, padding: float = 0.0) -> float:
    return ((point[0] - flower.center[0]) / (flower.rx + padding)) ** 2 + (
        (point[1] - flower.center[1]) / (flower.ry + padding)
    ) ** 2


def _self_intersects(points: Sequence[Point]) -> bool:
    for first_index, (a, b) in enumerate(zip(points, points[1:])):
        for second_index, (c, d) in enumerate(zip(points, points[1:])):
            if second_index <= first_index + 1:
                continue
            if _segments_intersect(a, b, c, d):
                return True
    return False


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orient(p: Point, q: Point, r: Point) -> float:
        return cross(sub(q, p), sub(r, p))

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return (o1 > 1e-8 and o2 < -1e-8 or o1 < -1e-8 and o2 > 1e-8) and (
        o3 > 1e-8 and o4 < -1e-8 or o3 < -1e-8 and o4 > 1e-8
    )


def _cubic_coordinate(cubic: Cubic, axis: int, parameter: float) -> float:
    inverse = 1.0 - parameter
    values = (cubic.p0[axis], cubic.p1[axis], cubic.p2[axis], cubic.p3[axis])
    return (
        inverse**3 * values[0]
        + 3.0 * inverse**2 * parameter * values[1]
        + 3.0 * inverse * parameter**2 * values[2]
        + parameter**3 * values[3]
    )


def _cubic_axis_candidates(cubic: Cubic, axis: int) -> tuple[tuple[float, float], ...]:
    p0, p1, p2, p3 = cubic.p0[axis], cubic.p1[axis], cubic.p2[axis], cubic.p3[axis]
    quadratic = 3.0 * (-p0 + 3.0 * p1 - 3.0 * p2 + p3)
    linear = 2.0 * (3.0 * p0 - 6.0 * p1 + 3.0 * p2)
    constant = -3.0 * p0 + 3.0 * p1
    parameters = [0.0, 1.0]
    if abs(quadratic) <= 1e-12:
        if abs(linear) > 1e-12:
            root = -constant / linear
            if 0.0 < root < 1.0:
                parameters.append(root)
    else:
        discriminant = linear * linear - 4.0 * quadratic * constant
        if discriminant >= -1e-12:
            root_term = math.sqrt(max(0.0, discriminant))
            for root in (
                (-linear - root_term) / (2.0 * quadratic),
                (-linear + root_term) / (2.0 * quadratic),
            ):
                if 0.0 < root < 1.0:
                    parameters.append(root)
    return tuple((parameter, _cubic_coordinate(cubic, axis, parameter)) for parameter in parameters)


def _cubic_axis_extrema(cubic: Cubic, axis: int) -> tuple[float, float]:
    """Return the exact coordinate extrema, including derivative roots."""

    values = [value for _, value in _cubic_axis_candidates(cubic, axis)]
    return min(values), max(values)


def _curve_exact_extrema(curve: Curve) -> dict[str, float]:
    x_extrema = [_cubic_axis_extrema(cubic, 0) for cubic in curve.cubics]
    y_extrema = [_cubic_axis_extrema(cubic, 1) for cubic in curve.cubics]
    return {
        "left": min(value[0] for value in x_extrema),
        "right": max(value[1] for value in x_extrema),
        "top": min(value[0] for value in y_extrema),
        "bottom": max(value[1] for value in y_extrema),
    }


def _curve_extremum_locations(
    curve: Curve,
) -> dict[str, tuple[float, tuple[tuple[int, float], ...]]]:
    """Return each exact side extremum and every cubic location attaining it."""

    candidates: dict[int, list[tuple[float, int, float]]] = {0: [], 1: []}
    for cubic_index, cubic in enumerate(curve.cubics):
        for axis in (0, 1):
            candidates[axis].extend(
                (value, cubic_index, parameter)
                for parameter, value in _cubic_axis_candidates(cubic, axis)
            )

    def select(axis: int, choose_minimum: bool) -> tuple[float, tuple[tuple[int, float], ...]]:
        values = [row[0] for row in candidates[axis]]
        extreme = min(values) if choose_minimum else max(values)
        locations = tuple(
            (cubic_index, parameter)
            for value, cubic_index, parameter in candidates[axis]
            if abs(value - extreme) <= 1e-8
        )
        return extreme, locations

    return {
        "left": select(0, True),
        "right": select(0, False),
        "top": select(1, True),
        "bottom": select(1, False),
    }


def _cubic_threshold_roots(cubic: Cubic, axis: int, threshold: float) -> tuple[float, ...]:
    """Find every coordinate/threshold crossing on monotonic cubic intervals."""

    critical = sorted({parameter for parameter, _ in _cubic_axis_candidates(cubic, axis)})
    roots: list[float] = []
    tolerance = 1e-10
    for parameter in critical:
        if abs(_cubic_coordinate(cubic, axis, parameter) - threshold) <= tolerance:
            roots.append(parameter)
    for start, end in zip(critical, critical[1:]):
        start_value = _cubic_coordinate(cubic, axis, start) - threshold
        end_value = _cubic_coordinate(cubic, axis, end) - threshold
        if start_value * end_value >= 0.0:
            continue
        low, high = start, end
        low_value = start_value
        for _ in range(64):
            middle = 0.5 * (low + high)
            middle_value = _cubic_coordinate(cubic, axis, middle) - threshold
            if low_value * middle_value <= 0.0:
                high = middle
            else:
                low = middle
                low_value = middle_value
        roots.append(0.5 * (low + high))
    return tuple(
        value
        for index, value in enumerate(sorted(roots))
        if index == 0 or abs(value - sorted(roots)[index - 1]) > 1e-9
    )


def _curve_side_band_intervals(
    curve: Curve,
    side: str,
    threshold: float,
) -> tuple[tuple[tuple[float, float], ...], tuple[float, ...]]:
    """Return exact-parametric intervals and contacts inside one edge band."""

    axis = 0 if side in {"left", "right"} else 1
    lower_side = side in {"left", "top"}
    intervals: list[tuple[float, float]] = []
    contacts: list[float] = []
    for cubic_index, cubic in enumerate(curve.cubics):
        roots = _cubic_threshold_roots(cubic, axis, threshold)
        contacts.extend(cubic_index + parameter for parameter in roots)
        breaks = sorted({0.0, 1.0, *roots})
        for start, end in zip(breaks, breaks[1:]):
            if end - start <= 1e-12:
                continue
            value = _cubic_coordinate(cubic, axis, 0.5 * (start + end))
            inside = value <= threshold + 1e-10 if lower_side else value >= threshold - 1e-10
            if inside:
                intervals.append((cubic_index + start, cubic_index + end))
    merged: list[tuple[float, float]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 1e-9:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    unique_contacts = tuple(
        value
        for index, value in enumerate(sorted(contacts))
        if index == 0 or abs(value - sorted(contacts)[index - 1]) > 1e-9
    )
    return tuple(merged), unique_contacts


def _prefix_after_distance(points: Sequence[Point], threshold: float) -> int:
    traversed = 0.0
    for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
        traversed += dist(start, end)
        if traversed >= threshold:
            return index
    return len(points)


def _normalized_sagitta(curve: Curve) -> float:
    """Return maximum centerline departure from the root-tip chord, normalized by chord."""

    chord = dist(curve.root, curve.tip)
    if chord <= 1e-9:
        return math.inf
    chord_line = (curve.root, curve.tip)
    return max(point_polyline_distance(point, chord_line) for point in curve.points(192)) / chord


def validate_result(p0: StrictP0, result: HierarchyResult) -> dict[str, object]:
    """Read-only whole-scene validation; never mutates or repairs geometry."""

    before = result.geometry_hash
    issues: list[str] = []
    nodes = result.by_id
    levels = {level: [node for node in result.curves if node.level == level] for level in (1, 2, 3)}
    if [len(levels[level]) for level in (1, 2, 3)] != [7, 12, 2]:
        issues.append("topology_count_not_7_12_2")
    if any(node.source != "program_generated" for node in result.curves):
        issues.append("non_program_source")
    if sum(node.target_flower_id is not None for node in levels[1]) != 2:
        issues.append("flower_primary_count")

    plan_child_by_id = {row.curve_id: row for row in result.plan.descendants}
    plan_primary_by_id = {row.curve_id: row for row in result.plan.primaries}
    expected_child_mount_ranges = {
        "secondary_1a_lat": (0.28, 0.56),
        "secondary_1b_lat": (0.48, 0.76),
        "secondary_2a_lat": (0.48, 0.76),
        "secondary_2b_lat": (0.28, 0.56),
        "secondary_3a_lat": (0.28, 0.56),
        "secondary_3b_lat": (0.48, 0.76),
        "secondary_4a_wrap": (0.565, 0.775),
        "secondary_5a_wrap": (0.565, 0.775),
        "secondary_6a_lat": (0.28, 0.56),
        "secondary_6b_lat": (0.48, 0.76),
        "secondary_7a_lat": (0.48, 0.76),
        "secondary_7b_lat": (0.28, 0.56),
        "tertiary_3a_1": (0.24, 0.76),
        "tertiary_6a_1": (0.24, 0.76),
    }
    expected_primary_opening_ranges = {
        "primary_1_free": (44.0, 60.0),
        "primary_2_free": (42.0, 58.0),
        "primary_3_free": (48.0, 62.0),
        "primary_4_flower_1": (40.0, 52.0),
        "primary_5_flower_2": (40.0, 52.0),
        "primary_6_balance": (38.0, 56.0),
        "primary_7_free": (54.0, 68.0),
    }
    per_curve: list[dict[str, object]] = []
    x0, x1 = p0.repeat_x_range
    expected_envelope_plan = _global_envelope_values(p0, result.plan.seed)
    envelope_declaration_mismatches = [
        key
        for key, expected in expected_envelope_plan.items()
        if key not in result.plan.latent_summary
        or abs(result.plan.latent_summary[key] - expected) > 1e-9
    ]
    if envelope_declaration_mismatches:
        issues.append("global_envelope_declaration_mismatch")
    envelope = {
        "left": x0,
        "right": x1,
        "top": expected_envelope_plan["envelope_top_y"],
        "bottom": expected_envelope_plan["envelope_bottom_y"],
    }
    visible_extrema_rows: list[dict[str, float | str]] = []
    for node in result.curves:
        curve = node.curve
        points = curve.points(192)
        branch_issues: list[str] = []
        child_row = None if node.level == 1 else plan_child_by_id[curve.curve_id]
        if node.level == 1:
            expected_root, expected_tangent = sample_polyline(p0.backbone_points, float(curve.mount_fraction))
        else:
            parent = nodes[curve.parent_id].curve
            expected_root, expected_tangent = sample_polyline(parent.points(192), float(curve.mount_fraction))
        root_error = dist(curve.root, expected_root)
        tangent_error = angle_degrees(curve.entry_tangent, expected_tangent)
        child_chord_opening = None
        if root_error > 0.5:
            branch_issues.append("root_off_parent")
        if child_row is not None:
            if abs(tangent_error - child_row.entry_opening_degrees) > 0.5:
                branch_issues.append("lateral_opening_differs_from_plan")
            if not 34.0 - 1e-6 <= tangent_error <= 70.0 + 1e-6:
                branch_issues.append("lateral_root_opening_angle")
            child_chord_opening = angle_degrees(sub(curve.tip, curve.root), expected_tangent)
            if not 30.0 - 1e-6 <= child_chord_opening <= 150.0 + 1e-6:
                branch_issues.append("lateral_chord_direction_not_sideways")
        else:
            primary_row = plan_primary_by_id[curve.curve_id]
            low, high = expected_primary_opening_ranges[curve.curve_id]
            if abs(tangent_error - primary_row.entry_opening_degrees) > 0.5:
                branch_issues.append("root_opening_differs_from_plan")
            if not low - 1e-6 <= tangent_error <= high + 1e-6:
                branch_issues.append("root_opening_angle")
        audit = legacy.bend_audit(curve)
        normalized_sagitta = _normalized_sagitta(curve)
        if int(audit["bend_count"]) > 2 or int(audit["curvature_sign_reversal_count"]) > 1:
            branch_issues.append("bend_count_over_2")
        if normalized_sagitta > 0.25:
            branch_issues.append("curvature_too_large")
        if len(curve.cubics) > 2:
            branch_issues.append("cubic_segment_count_over_2")
        degenerate_handles = any(
            dist(cubic.p0, cubic.p1) <= 1e-8 or dist(cubic.p2, cubic.p3) <= 1e-8
            for cubic in curve.cubics
        )
        if degenerate_handles:
            branch_issues.append("degenerate_derivative")
        c0_error = 0.0
        c1_angle = 0.0
        c1_handle_delta = 0.0
        if len(curve.cubics) == 2:
            first_cubic, second_cubic = curve.cubics
            c0_error = dist(first_cubic.p3, second_cubic.p0)
            incoming = sub(first_cubic.p3, first_cubic.p2)
            outgoing = sub(second_cubic.p1, second_cubic.p0)
            c1_angle = angle_degrees(incoming, outgoing)
            c1_handle_delta = abs(math.hypot(*incoming) - math.hypot(*outgoing))
            if c0_error > 1e-6 or c1_angle > 1e-5 or c1_handle_delta > 1e-5:
                branch_issues.append("two_cubic_not_c1")
        if _self_intersects(points):
            branch_issues.append("self_intersection")
        half_width = curve.width * 0.5
        extremum_locations = _curve_extremum_locations(curve)
        centerline_extrema = {side: row[0] for side, row in extremum_locations.items()}
        if (
            centerline_extrema["left"] < x0 + half_width
            or centerline_extrema["right"] > x1 - half_width
            or centerline_extrema["top"] < half_width
            or centerline_extrema["bottom"] > p0.canvas_height - half_width
        ):
            branch_issues.append("out_of_bounds")
        visible_extrema = {
            "curve_id": curve.curve_id,
            "left": centerline_extrema["left"] - half_width,
            "right": centerline_extrema["right"] + half_width,
            "top": centerline_extrema["top"] - half_width,
            "bottom": centerline_extrema["bottom"] + half_width,
        }
        visible_extrema_rows.append(visible_extrema)
        if (
            visible_extrema["top"] < envelope["top"] - 1e-6
            or visible_extrema["bottom"] > envelope["bottom"] + 1e-6
        ):
            branch_issues.append("outside_vertical_visible_envelope")
        registered_boundary = (
            plan_primary_by_id[curve.curve_id].target_boundary
            if node.level == 1
            else plan_child_by_id[curve.curve_id].target_boundary
        )
        tip_envelope_clearances = {
            "left": curve.tip[0] - half_width - envelope["left"],
            "right": envelope["right"] - curve.tip[0] - half_width,
            "top": curve.tip[1] - half_width - envelope["top"],
            "bottom": envelope["bottom"] - curve.tip[1] - half_width,
        }
        visible_envelope_clearances = {
            "left": visible_extrema["left"] - envelope["left"],
            "right": envelope["right"] - visible_extrema["right"],
            "top": visible_extrema["top"] - envelope["top"],
            "bottom": envelope["bottom"] - visible_extrema["bottom"],
        }
        outward_normals = {
            "left": (-1.0, 0.0),
            "right": (1.0, 0.0),
            "top": (0.0, -1.0),
            "bottom": (0.0, 1.0),
        }
        approach_bands = {
            "top": 0.04 * p0.canvas_height,
            "bottom": 0.04 * p0.canvas_height,
        }
        band_thresholds = {
            "top": envelope["top"] + half_width + approach_bands["top"],
            "bottom": envelope["bottom"] - half_width - approach_bands["bottom"],
        }
        root_leaves_edge_inward = {
            side: dot(curve.entry_tangent, outward_normals[side]) < -0.15
            for side in outward_normals
        }
        band_intervals: dict[str, tuple[tuple[float, float], ...]] = {}
        band_contacts: dict[str, tuple[float, ...]] = {}
        initial_root_departure_sides: list[str] = []
        edge_approach_sides: list[str] = []
        curve_parameter_end = float(len(curve.cubics))
        for side in ("top", "bottom"):
            intervals, contacts = _curve_side_band_intervals(curve, side, band_thresholds[side])
            band_intervals[side] = intervals
            band_contacts[side] = contacts
            root_interval = intervals[0] if intervals and intervals[0][0] <= 1e-9 else None
            root_contact = bool(contacts and contacts[0] <= 1e-9)
            root_departure = root_leaves_edge_inward[side] and (root_interval is not None or root_contact)
            if root_departure:
                initial_root_departure_sides.append(side)
                departure_end = 0.0 if root_interval is None else root_interval[1]
                later_intervals = intervals if root_interval is None else intervals[1:]
                later_contacts = [value for value in contacts if value > departure_end + 1e-9]
                stayed_inside_band = root_interval is not None and departure_end >= curve_parameter_end - 1e-9
                if stayed_inside_band or later_intervals or later_contacts:
                    edge_approach_sides.append(side)
            elif intervals or contacts:
                edge_approach_sides.append(side)
        envelope_contact_sides = [
            side for side in ("top", "bottom") if visible_envelope_clearances[side] <= 0.5
        ]
        allowed_boundary_sides = {
            None: frozenset(),
            "top_frontier": frozenset({"top"}),
            "bottom_frontier": frozenset({"bottom"}),
        }.get(registered_boundary, frozenset())
        unexpected_approach_sides = [
            side for side in edge_approach_sides if side not in allowed_boundary_sides
        ]
        unexpected_contact_sides = [
            side for side in envelope_contact_sides if side not in allowed_boundary_sides
        ]
        if unexpected_contact_sides:
            branch_issues.append("unregistered_visible_envelope_contact")
        boundary_distance = None
        boundary_side_clearances: dict[str, float] = {}
        boundary_tangent_error = None
        terminal_handle_ratio = None
        ratio = None
        if node.level > 1:
            row = plan_child_by_id[curve.curve_id]
            parent_length = nodes[curve.parent_id].curve.length
            ratio = curve.length / max(parent_length, 1e-12)
            mount_range = expected_child_mount_ranges.get(curve.curve_id)
            if mount_range is None:
                branch_issues.append("unregistered_lateral_mount_range")
            else:
                if not mount_range[0] - 1e-9 <= row.mount_fraction <= mount_range[1] + 1e-9:
                    branch_issues.append("lateral_mount_outside_registered_range")
            if row.mount_fraction >= 0.80 - 1e-9:
                branch_issues.append("lateral_mount_at_parent_tip")
            if not 34.0 <= row.opening_angle_degrees <= 70.0:
                branch_issues.append("lateral_opening_angle")
            if row.target_boundary not in {None, "top_frontier", "bottom_frontier"}:
                branch_issues.append("invalid_lateral_frontier_side")
            if (row.target_boundary is None) != (row.target_point is None):
                branch_issues.append("incomplete_lateral_frontier_target")
            if node.level == 3:
                ratio_range = (0.20, 0.80)
            elif row.target_boundary is not None:
                ratio_range = (0.25, 1.60)
            elif row.growth_role == "flower_wrap":
                ratio_range = (0.15, 1.25)
            else:
                ratio_range = (0.12, 0.75)
            if not ratio_range[0] <= ratio <= ratio_range[1]:
                branch_issues.append("lateral_parent_length_ratio")

        planned_row = plan_primary_by_id[curve.curve_id] if node.level == 1 else plan_child_by_id[curve.curve_id]
        boundary_sides = {
            "top_frontier": ("top", 1, ((-1.0, 0.0), (1.0, 0.0))),
            "bottom_frontier": ("bottom", 1, ((-1.0, 0.0), (1.0, 0.0))),
        }
        if registered_boundary in boundary_sides:
            side, axis, parallel_directions = boundary_sides[registered_boundary]
            boundary_distance = abs(tip_envelope_clearances[side])
            boundary_side_clearances = {side: tip_envelope_clearances[side]}
            boundary_tangent_error = min(
                angle_degrees(curve.exit_tangent, candidate) for candidate in parallel_directions
            )
            terminal_handle_ratio = dist(curve.cubics[-1].p2, curve.cubics[-1].p3) / max(curve.length, 1e-12)
            if planned_row.target_point is None or dist(curve.tip, planned_row.target_point) > 1e-5:
                branch_issues.append("frontier_target_point_error")
            if boundary_distance > 0.5 + 1e-6:
                branch_issues.append("frontier_visible_clearance")
            if boundary_tangent_error > 5.0:
                branch_issues.append("frontier_exit_not_parallel")
            if terminal_handle_ratio < 0.06:
                branch_issues.append("frontier_turn_begins_too_late")
            if abs(centerline_extrema[side] - curve.tip[axis]) > 0.25:
                branch_issues.append("frontier_extremum_not_at_apex")

        target = next((flower for flower in p0.flowers if flower.flower_id == node.target_flower_id), None)
        for flower in p0.flowers:
            values = [_ellipse_value(point, flower) for point in points]
            if target is flower:
                if any(value < 1.0 for value in values[: max(1, int(0.90 * len(values)))]):
                    branch_issues.append(f"early_target_flower_intrusion:{flower.flower_id}")
                if abs(values[-1] - 1.0) > 2e-5:
                    branch_issues.append(f"flower_collar_error:{flower.flower_id}")
                approach_error = angle_degrees(curve.exit_tangent, _unit(sub(flower.center, curve.tip)))
                if approach_error > 25.0:
                    branch_issues.append(f"flower_approach:{flower.flower_id}")
            elif any(value < 1.0 for value in values):
                branch_issues.append(f"flower_intrusion:{flower.flower_id}")

        parent_points = p0.backbone_points if node.level == 1 else nodes[curve.parent_id].curve.points(192)
        contact_zone = min(10.0 if node.level == 1 else 8.0, 0.75 * curve.length)
        tail_start = _prefix_after_distance(points, contact_zone)
        parent_clearance = min(
            (point_polyline_distance(point, parent_points) for point in points[tail_start:]),
            default=math.inf,
        )
        parent_width = 5.0 if node.level == 1 else nodes[curve.parent_id].curve.width
        required_parent_clearance = 0.5 * (curve.width + parent_width) + 0.8
        if parent_clearance < required_parent_clearance:
            branch_issues.append("parent_recontact")
        if node.level > 1:
            backbone_clearance = min(point_polyline_distance(point, p0.backbone_points) for point in points)
            required_backbone_clearance = 0.5 * (curve.width + 5.0) + 0.8
            if backbone_clearance < required_backbone_clearance:
                branch_issues.append("backbone_contact")
        else:
            backbone_clearance = parent_clearance
            required_backbone_clearance = required_parent_clearance

        for issue in branch_issues:
            issues.append(f"{curve.curve_id}:{issue}")
        per_curve.append(
            {
                "curve_id": curve.curve_id,
                "level": node.level,
                "parent_id": curve.parent_id,
                "growth_role": None if child_row is None else child_row.growth_role,
                "root_error": round(root_error, 8),
                "root_opening_angle_degrees": round(tangent_error, 8),
                "child_chord_opening_degrees": (
                    None if child_chord_opening is None else round(child_chord_opening, 8)
                ),
                "bend_audit": audit,
                "normalized_sagitta": round(normalized_sagitta, 8),
                "c0_error": round(c0_error, 10),
                "c1_tangent_error_degrees": round(c1_angle, 10),
                "c1_handle_delta": round(c1_handle_delta, 10),
                "degenerate_derivatives": degenerate_handles,
                "parent_contact_zone_length": round(contact_zone, 8),
                "parent_clearance_after_root": round(parent_clearance, 8),
                "parent_clearance_required": round(required_parent_clearance, 8),
                "backbone_clearance": round(backbone_clearance, 8),
                "backbone_clearance_required": round(required_backbone_clearance, 8),
                "child_parent_length_ratio": None if ratio is None else round(ratio, 8),
                "visible_extrema": {
                    key: round(value, 8) for key, value in visible_extrema.items() if key != "curve_id"
                },
                "tip_envelope_clearances": {
                    key: round(value, 8) for key, value in tip_envelope_clearances.items()
                },
                "visible_envelope_clearances": {
                    key: round(value, 8) for key, value in visible_envelope_clearances.items()
                },
                "approach_bands": {key: round(value, 8) for key, value in approach_bands.items()},
                "root_leaves_edge_inward": root_leaves_edge_inward,
                "initial_root_departure_sides": initial_root_departure_sides,
                "band_intervals": {
                    side: [[round(start, 8), round(end, 8)] for start, end in intervals]
                    for side, intervals in band_intervals.items()
                },
                "band_contacts": {
                    side: [round(value, 8) for value in contacts]
                    for side, contacts in band_contacts.items()
                },
                "edge_approach_sides": edge_approach_sides,
                "envelope_contact_sides": envelope_contact_sides,
                "unexpected_approach_sides": unexpected_approach_sides,
                "unexpected_contact_sides": unexpected_contact_sides,
                "target_boundary": registered_boundary,
                "boundary_distance": None if boundary_distance is None else round(boundary_distance, 8),
                "boundary_side_clearances": {
                    key: round(value, 8) for key, value in boundary_side_clearances.items()
                },
                "boundary_tangent_error_degrees": (
                    None if boundary_tangent_error is None else round(boundary_tangent_error, 8)
                ),
                "terminal_handle_length_ratio": (
                    None if terminal_handle_ratio is None else round(terminal_handle_ratio, 8)
                ),
                "issues": branch_issues,
            }
        )

    pair_rows: list[dict[str, object]] = []
    curves = list(result.curves)
    for first_index, first in enumerate(curves):
        for second in curves[first_index + 1 :]:
            parent_child = first.curve.parent_id == second.curve.curve_id or second.curve.parent_id == first.curve.curve_id
            allowed_contact = None
            contact_radius = 0.0
            if parent_child:
                child = first if first.level > second.level else second
                allowed_contact = child.curve.root
                contact_radius = min(8.0, 0.75 * child.curve.length)
            required = 0.5 * (first.curve.width + second.curve.width) + 1.0
            first_box = _curve_exact_extrema(first.curve)
            second_box = _curve_exact_extrema(second.curve)
            bbox_dx = max(
                0.0,
                first_box["left"] - second_box["right"],
                second_box["left"] - first_box["right"],
            )
            bbox_dy = max(
                0.0,
                first_box["top"] - second_box["bottom"],
                second_box["top"] - first_box["bottom"],
            )
            bbox_distance = math.hypot(bbox_dx, bbox_dy)
            if not parent_child and bbox_distance >= required:
                minimum = bbox_distance
                clearance_method = "exact_bbox_certificate"
            else:
                minimum = polyline_pair_distance(
                    first.curve.points(128),
                    second.curve.points(128),
                    allowed_contact=allowed_contact,
                    contact_radius=contact_radius,
                )
                clearance_method = "sampled_polyline_128"
            pair_rows.append(
                {
                    "first": first.curve.curve_id,
                    "second": second.curve.curve_id,
                    "minimum": round(minimum, 8),
                    "required": round(required, 8),
                    "registered_parent_child": parent_child,
                    "method": clearance_method,
                }
            )
            if minimum + 1e-6 < required:
                issues.append(f"curve_clearance:{first.curve.curve_id}:{second.curve.curve_id}")

    primary_rows = sorted(result.plan.primaries, key=lambda row: row.mount_s)
    trough_flower_mount = plan_primary_by_id["primary_4_flower_1"].mount_s
    if abs(trough_flower_mount - 0.40) > 0.01 + 1e-9:
        issues.append("flower_1_root_outside_trough_band")
    gaps = [second.mount_s - first.mount_s for first, second in zip(primary_rows, primary_rows[1:])]
    if any(gap < 0.025 or gap > 0.30 for gap in gaps):
        issues.append("global_mount_gap")
    side_sequence = [row.side_sign for row in primary_rows]
    if abs(side_sequence.count(1) - side_sequence.count(-1)) > 2:
        issues.append("global_side_balance")
    if any(
        side_sequence[index]
        == side_sequence[index + 1]
        == side_sequence[index + 2]
        == side_sequence[index + 3]
        == side_sequence[index + 4]
        for index in range(len(side_sequence) - 4)
    ):
        issues.append("global_five_same_side")
    primary_lengths = [nodes[row.curve_id].curve.length for row in primary_rows]
    length_ratio = max(primary_lengths) / max(min(primary_lengths), 1e-12)
    balance_rows = [row for row in primary_rows if row.kind == "balance"]
    if len(balance_rows) != 1:
        issues.append("global_balance_primary_count")
    secondary_parent_count = len({node.curve.parent_id for node in levels[2]})
    if secondary_parent_count != 7:
        issues.append("secondary_distribution")
    expected_primary_ids = {
        "primary_1_free",
        "primary_2_free",
        "primary_3_free",
        "primary_4_flower_1",
        "primary_5_flower_2",
        "primary_6_balance",
        "primary_7_free",
    }
    expected_secondary_parents = {
        "secondary_1a_lat": "primary_1_free",
        "secondary_1b_lat": "primary_1_free",
        "secondary_2a_lat": "primary_2_free",
        "secondary_2b_lat": "primary_2_free",
        "secondary_3a_lat": "primary_3_free",
        "secondary_3b_lat": "primary_3_free",
        "secondary_4a_wrap": "primary_4_flower_1",
        "secondary_5a_wrap": "primary_5_flower_2",
        "secondary_6a_lat": "primary_6_balance",
        "secondary_6b_lat": "primary_6_balance",
        "secondary_7a_lat": "primary_7_free",
        "secondary_7b_lat": "primary_7_free",
    }
    expected_tertiary_parents = {
        "tertiary_3a_1": "secondary_3a_lat",
        "tertiary_6a_1": "secondary_6a_lat",
    }
    expected_child_parents = {**expected_secondary_parents, **expected_tertiary_parents}
    if {node.curve.curve_id for node in levels[1]} != expected_primary_ids:
        issues.append("global_primary_id_set")
    if {node.curve.curve_id for node in levels[2]} != set(expected_secondary_parents):
        issues.append("global_secondary_id_set")
    if {node.curve.curve_id for node in levels[3]} != set(expected_tertiary_parents):
        issues.append("global_tertiary_id_set")
    actual_child_parents = {row.curve_id: row.parent_id for row in result.plan.descendants}
    if actual_child_parents != expected_child_parents:
        issues.append("global_child_parent_assignment")
    if any(
        nodes[child_id].level != (2 if child_id.startswith("secondary_") else 3)
        or nodes[parent_id].level != (1 if child_id.startswith("secondary_") else 2)
        for child_id, parent_id in expected_child_parents.items()
        if child_id in nodes and parent_id in nodes
    ):
        issues.append("global_child_parent_level")
    expected_child_roles = {
        child_id: ("flower_wrap" if child_id in {"secondary_4a_wrap", "secondary_5a_wrap"} else "lateral")
        for child_id in expected_child_parents
    }
    actual_child_roles = {row.curve_id: row.growth_role for row in result.plan.descendants}
    if actual_child_roles != expected_child_roles:
        issues.append("global_child_growth_roles")
    if any("continuation" in row.growth_role for row in result.plan.descendants) or any(
        "continuation" in node.curve.role for node in result.curves
    ):
        issues.append("continuation_semantics_present")
    expected_secondary_budgets = {
        "primary_1_free": 2,
        "primary_2_free": 2,
        "primary_3_free": 2,
        "primary_4_flower_1": 1,
        "primary_5_flower_2": 1,
        "primary_6_balance": 2,
        "primary_7_free": 2,
    }
    actual_secondary_budgets = {
        primary_id: sum(
            row.level == 2 and row.parent_id == primary_id for row in result.plan.descendants
        )
        for primary_id in expected_primary_ids
    }
    declared_secondary_budgets = {
        row.curve_id: row.secondary_budget for row in result.plan.primaries
    }
    if actual_secondary_budgets != expected_secondary_budgets:
        issues.append("global_secondary_budget_topology")
    if declared_secondary_budgets != expected_secondary_budgets:
        issues.append("global_secondary_budget_declaration")
    unit_mount_separations: dict[str, float] = {}
    unit_direction_separations: dict[str, float] = {}
    for primary_id, budget in expected_secondary_budgets.items():
        child_ids = sorted(
            row.curve_id
            for row in result.plan.descendants
            if row.level == 2 and row.parent_id == primary_id and row.curve_id in nodes
        )
        if len(child_ids) != budget:
            issues.append(f"{primary_id}:secondary_budget_realization")
        if len(child_ids) == 2:
            mount_separation = abs(
                plan_child_by_id[child_ids[1]].mount_fraction
                - plan_child_by_id[child_ids[0]].mount_fraction
            )
            direction_separation = angle_degrees(
                sub(nodes[child_ids[0]].curve.tip, nodes[child_ids[0]].curve.root),
                sub(nodes[child_ids[1]].curve.tip, nodes[child_ids[1]].curve.root),
            )
            unit_mount_separations[primary_id] = mount_separation
            unit_direction_separations[primary_id] = direction_separation
            if mount_separation < 0.06:
                issues.append(f"{primary_id}:secondary_mounts_not_separated")
            if direction_separation < 30.0:
                issues.append(f"{primary_id}:secondary_directions_not_separated")

    expected_boundary_assignments = {
        "primary_1_free": "top_frontier",
        "primary_3_free": "bottom_frontier",
        "primary_6_balance": "top_frontier",
    }
    actual_boundary_assignments = {
        row.curve_id: row.target_boundary for row in result.plan.primaries if row.target_boundary is not None
    }
    if actual_boundary_assignments != expected_boundary_assignments:
        issues.append("global_boundary_assignment")
    expected_child_boundary_assignments = {
        "secondary_2a_lat": "bottom_frontier",
        "secondary_7a_lat": "top_frontier",
    }
    actual_child_boundary_assignments = {
        row.curve_id: row.target_boundary for row in result.plan.descendants if row.target_boundary is not None
    }
    if actual_child_boundary_assignments != expected_child_boundary_assignments:
        issues.append("global_child_boundary_assignment")

    expected_frontier_specs = {
        "primary_1_free": (
            "primary_1_free",
            "top_frontier",
            (expected_envelope_plan["top_1_frontier_x"], envelope["top"] + 0.5 * PRIMARY_WIDTH),
        ),
        "secondary_2a_lat": (
            "primary_2_free",
            "bottom_frontier",
            (expected_envelope_plan["secondary_2_frontier_x"], envelope["bottom"] - 0.5 * SECONDARY_WIDTH),
        ),
        "primary_3_free": (
            "primary_3_free",
            "bottom_frontier",
            (expected_envelope_plan["bottom_3_frontier_x"], envelope["bottom"] - 0.5 * PRIMARY_WIDTH),
        ),
        "primary_6_balance": (
            "primary_6_balance",
            "top_frontier",
            (expected_envelope_plan["top_6_frontier_x"], envelope["top"] + 0.5 * PRIMARY_WIDTH),
        ),
        "secondary_7a_lat": (
            "primary_7_free",
            "top_frontier",
            (expected_envelope_plan["secondary_7_frontier_x"], envelope["top"] + 0.5 * SECONDARY_WIDTH),
        ),
    }
    frontier_rows: dict[str, PrimaryPlan | ChildPlan] = {
        **{row.curve_id: row for row in result.plan.primaries if row.target_boundary is not None},
        **{row.curve_id: row for row in result.plan.descendants if row.target_boundary is not None},
    }
    frontier_subtrees: set[str] = set()
    frontier_side_counts = {"top": 0, "bottom": 0}
    frontier_target_errors: list[str] = []
    for curve_id, (subtree_id, boundary, expected_point) in expected_frontier_specs.items():
        row = frontier_rows.get(curve_id)
        if row is None or row.target_boundary != boundary or row.target_point is None:
            frontier_target_errors.append(curve_id)
            continue
        if dist(row.target_point, expected_point) > 1e-8:
            frontier_target_errors.append(curve_id)
            continue
        frontier_subtrees.add(subtree_id)
        frontier_side_counts[boundary.removesuffix("_frontier")] += 1
    if set(frontier_rows) != set(expected_frontier_specs) or frontier_target_errors:
        issues.append("global_frontier_target_assignment")
    expected_free_subtrees = {
        "primary_1_free",
        "primary_2_free",
        "primary_3_free",
        "primary_6_balance",
        "primary_7_free",
    }
    if frontier_subtrees != expected_free_subtrees:
        issues.append("free_subtree_frontier_coverage")
    expected_side_counts = {"top": 3, "bottom": 2}
    if frontier_side_counts != expected_side_counts:
        issues.append("frontier_side_coverage")
    descendant_frontier_count = sum(curve_id.startswith("secondary_") for curve_id in frontier_rows)
    if descendant_frontier_count != 2:
        issues.append("descendant_frontier_count")
    top_frontier_xs = sorted(
        nodes[curve_id].curve.tip[0]
        for curve_id in ("primary_1_free", "primary_6_balance", "secondary_7a_lat")
    )
    top_frontier_spacings = [second - first for first, second in zip(top_frontier_xs, top_frontier_xs[1:])]
    bottom_frontier_spacing = abs(
        nodes["primary_3_free"].curve.tip[0] - nodes["secondary_2a_lat"].curve.tip[0]
    )
    if min(top_frontier_spacings) < 24.0:
        issues.append("top_frontier_slots_too_close")
    if bottom_frontier_spacing < 12.0:
        issues.append("bottom_frontier_slots_too_close")
    unit_frontier_path_lengths = {
        "primary_1_free": nodes["primary_1_free"].curve.length,
        "primary_2_free": (
            nodes["primary_2_free"].curve.length
            * plan_child_by_id["secondary_2a_lat"].mount_fraction
            + nodes["secondary_2a_lat"].curve.length
        ),
        "primary_3_free": nodes["primary_3_free"].curve.length,
        "primary_6_balance": nodes["primary_6_balance"].curve.length,
        "primary_7_free": (
            nodes["primary_7_free"].curve.length
            * plan_child_by_id["secondary_7a_lat"].mount_fraction
            + nodes["secondary_7a_lat"].curve.length
        ),
    }
    unit_frontier_path_length_ratio = max(unit_frontier_path_lengths.values()) / max(
        min(unit_frontier_path_lengths.values()), 1e-12
    )
    if unit_frontier_path_length_ratio > 3.2:
        issues.append("unit_frontier_path_length_imbalance")

    curvature_by_id = {
        curve_id: _normalized_sagitta(node.curve) for curve_id, node in nodes.items()
    }
    free_primary_curvatures = [curvature_by_id[curve_id] for curve_id in sorted(expected_primary_ids) if "flower" not in curve_id]
    secondary_curvatures = [curvature_by_id[curve_id] for curve_id in sorted(expected_secondary_parents)]
    tertiary_curvatures = [curvature_by_id[curve_id] for curve_id in sorted(expected_tertiary_parents)]
    curved_free_primary_count = sum(0.055 <= value <= 0.20 for value in free_primary_curvatures)
    curved_secondary_count = sum(0.05 <= value <= 0.20 for value in secondary_curvatures)
    curved_tertiary_count = sum(0.05 <= value <= 0.20 for value in tertiary_curvatures)
    if curved_free_primary_count < 4:
        issues.append("free_primary_curvature_coverage")
    if curved_secondary_count < 9:
        issues.append("secondary_curvature_coverage")
    if curved_tertiary_count < 1:
        issues.append("tertiary_curvature_coverage")

    scene_visible_extrema = {
        "left": min(float(row["left"]) for row in visible_extrema_rows),
        "right": max(float(row["right"]) for row in visible_extrema_rows),
        "top": min(float(row["top"]) for row in visible_extrema_rows),
        "bottom": max(float(row["bottom"]) for row in visible_extrema_rows),
    }
    envelope_overflow = {
        "left": max(0.0, envelope["left"] - scene_visible_extrema["left"]),
        "right": max(0.0, scene_visible_extrema["right"] - envelope["right"]),
        "top": max(0.0, envelope["top"] - scene_visible_extrema["top"]),
        "bottom": max(0.0, scene_visible_extrema["bottom"] - envelope["bottom"]),
    }
    if max(envelope_overflow[side] for side in ("top", "bottom")) > 1e-6:
        issues.append("global_visible_envelope_overflow")

    after = result.geometry_hash
    diagnostics = {
        "check_only": True,
        "geometry_hash_before_check": before,
        "geometry_hash_after_check": after,
        "geometry_unchanged": before == after,
        "per_curve": per_curve,
        "pair_clearances": pair_rows,
        "global": {
            "mount_gaps": [round(gap, 8) for gap in gaps],
            "side_sequence": side_sequence,
            "primary_length_ratio": round(length_ratio, 8),
            "balance_primary_count": len(balance_rows),
            "secondary_parent_count": secondary_parent_count,
            "flower_1_trough_mount_s": round(trough_flower_mount, 8),
            "envelope_recomputed_from_seed_and_p0": True,
            "envelope_declaration_mismatches": envelope_declaration_mismatches,
            "shared_visible_envelope": {key: round(value, 8) for key, value in envelope.items()},
            "scene_visible_extrema": {key: round(value, 8) for key, value in scene_visible_extrema.items()},
            "envelope_overflow": {key: round(value, 8) for key, value in envelope_overflow.items()},
            "boundary_assignments": actual_boundary_assignments,
            "child_boundary_assignments": actual_child_boundary_assignments,
            "child_growth_roles": actual_child_roles,
            "child_parent_assignments": actual_child_parents,
            "secondary_budgets": declared_secondary_budgets,
            "unit_mount_separations": {
                key: round(value, 8) for key, value in unit_mount_separations.items()
            },
            "unit_direction_separations_degrees": {
                key: round(value, 8) for key, value in unit_direction_separations.items()
            },
            "free_subtree_frontier_coverage": len(frontier_subtrees),
            "expected_free_subtree_frontier_coverage": len(expected_free_subtrees),
            "descendant_frontier_count": descendant_frontier_count,
            "frontier_side_counts": frontier_side_counts,
            "top_frontier_spacings": [round(value, 8) for value in top_frontier_spacings],
            "bottom_frontier_spacing": round(bottom_frontier_spacing, 8),
            "frontier_target_errors": frontier_target_errors,
            "unit_frontier_path_lengths": {
                key: round(value, 8) for key, value in unit_frontier_path_lengths.items()
            },
            "unit_frontier_path_length_ratio": round(unit_frontier_path_length_ratio, 8),
            "curvature_by_id": {
                key: round(value, 8) for key, value in sorted(curvature_by_id.items())
            },
            "curvature_coverage": {
                "free_primary": [curved_free_primary_count, len(free_primary_curvatures)],
                "secondary": [curved_secondary_count, len(secondary_curvatures)],
                "tertiary": [curved_tertiary_count, len(tertiary_curvatures)],
            },
        },
    }
    return {"valid": not issues, "issues": list(dict.fromkeys(issues)), "diagnostics": diagnostics}


def intervention_proof(profile: Mapping[str, object], seed: int = DEV_SEEDS[0]) -> dict[str, object]:
    original_p0 = strip_profile(profile)
    poisoned_p0 = strip_profile(ignored_field_intervention(profile))
    original = build_j0a(original_p0, seed)
    poisoned = build_j0a(poisoned_p0, seed)
    return {
        "original_input_digest": original_p0.digest,
        "poisoned_input_digest": poisoned_p0.digest,
        "original_geometry_hash": original.geometry_hash,
        "poisoned_geometry_hash": poisoned.geometry_hash,
        "identical": original_p0.digest == poisoned_p0.digest and original.geometry_hash == poisoned.geometry_hash,
        "poisoned_fields": [
            "backbone.source_path_order",
            "existing_guides",
            "growth_regions",
            "space_samples",
            "region_graph",
            "nodes",
            "segments",
            "qa",
            "attachments",
            "branch_roles",
            "clearance",
        ],
    }


def global_dependency_proof(p0: StrictP0, seed: int = DEV_SEEDS[0]) -> dict[str, object]:
    original = build_j0a(p0, seed)
    changed = build_j0a(p0, seed, controls=GlobalControls(rhythm_shift=0.02, length_scale=1.0))
    first = original.by_id
    second = changed.by_id
    changed_primaries = [
        curve_id
        for curve_id in sorted(row.curve_id for row in original.plan.primaries)
        if first[curve_id].curve.as_dict() != second[curve_id].curve.as_dict()
    ]
    return {
        "control": "rhythm_shift",
        "changed_primary_ids": changed_primaries,
        "changed_primary_count": len(changed_primaries),
        "passes": len(changed_primaries) >= 3,
    }


def subtree_dependency_proof(
    p0: StrictP0,
    seed: int = DEV_SEEDS[0],
    subtree_id: str = "primary_6_balance",
) -> dict[str, object]:
    original = build_j0a(p0, seed)
    changed = build_j0a(p0, seed, subtree_controls={subtree_id: SubtreeControl(flow=0.5)})
    first = original.by_id
    second = changed.by_id
    changed_ids = [curve_id for curve_id in sorted(first) if first[curve_id].curve.as_dict() != second[curve_id].curve.as_dict()]
    expected = sorted(curve_id for curve_id in first if _subtree_id(curve_id) == subtree_id)
    return {
        "subtree_id": subtree_id,
        "changed_curve_ids": changed_ids,
        "expected_subtree_curve_ids": expected,
        "other_subtrees_byte_identical": changed_ids == expected,
        "primary_and_descendant_changed": subtree_id in changed_ids and len(changed_ids) >= 2,
        "passes": changed_ids == expected and subtree_id in changed_ids and len(changed_ids) >= 2,
    }


def traversal_order_proof(p0: StrictP0, seed: int = DEV_SEEDS[0]) -> dict[str, object]:
    plan = plan_j0a(p0, seed)
    forward = compile_plan(plan, p0)
    reverse = compile_plan(plan, p0, tuple(reversed([row.curve_id for row in plan.primaries])))
    return {
        "forward_hash": forward.geometry_hash,
        "reverse_hash": reverse.geometry_hash,
        "identical": forward.geometry_hash == reverse.geometry_hash,
    }


def _curve_direction_degrees(curve: Curve) -> float:
    chord = sub(curve.tip, curve.root)
    return math.degrees(math.atan2(chord[1], chord[0]))


def _circular_angle_delta_degrees(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _symmetric_relative_difference(first: float, second: float) -> float:
    return abs(first - second) / max(0.5 * (abs(first) + abs(second)), 1e-12)


def _normalized_shape_signature(curve: Curve, sample_count: int = 33) -> tuple[Point, ...]:
    """Sample equal-arclength points in a root/chord-aligned normalized frame."""

    if sample_count < 3:
        raise ValueError("shape signature needs at least three samples")
    chord = sub(curve.tip, curve.root)
    chord_length = math.hypot(*chord)
    if chord_length <= 1e-9:
        raise ValueError(f"degenerate root-tip chord for {curve.curve_id}")
    cosine = chord[0] / chord_length
    sine = chord[1] / chord_length
    points = curve.points(512)
    signature: list[Point] = []
    for index in range(sample_count):
        point, _ = sample_polyline(points, index / float(sample_count - 1))
        local_x = point[0] - curve.root[0]
        local_y = point[1] - curve.root[1]
        signature.append(
            (
                (local_x * cosine + local_y * sine) / chord_length,
                (-local_x * sine + local_y * cosine) / chord_length,
            )
        )
    return tuple(signature)


def _shape_rms(first: Curve, second: Curve) -> float:
    first_signature = _normalized_shape_signature(first)
    second_signature = _normalized_shape_signature(second)
    return math.sqrt(
        sum(
            (first_point[0] - second_point[0]) ** 2
            + (first_point[1] - second_point[1]) ** 2
            for first_point, second_point in zip(first_signature, second_signature)
        )
        / len(first_signature)
    )


def seed_visible_variation_proof(
    p0: StrictP0,
    seeds: Sequence[int] = DEV_SEEDS,
) -> dict[str, object]:
    """Prove pairwise seed changes are visually material, not merely hash-distinct."""

    seed_tuple = tuple(int(seed) for seed in seeds)
    if len(seed_tuple) < 2:
        raise ValueError("visible seed variation requires at least two seeds")
    results = {seed: build_j0a(p0, seed) for seed in seed_tuple}
    free_primary_ids = (
        "primary_1_free",
        "primary_2_free",
        "primary_3_free",
        "primary_6_balance",
        "primary_7_free",
    )
    movable_primary_mount_ids = (
        "primary_1_free",
        "primary_2_free",
        "primary_3_free",
        "primary_5_flower_2",
        "primary_6_balance",
        "primary_7_free",
    )
    secondary_ids = tuple(
        sorted(
            node.curve.curve_id
            for node in results[seed_tuple[0]].curves
            if node.level == 2
        )
    )
    tertiary_ids = tuple(
        sorted(
            node.curve.curve_id
            for node in results[seed_tuple[0]].curves
            if node.level == 3
        )
    )
    thresholds = {
        "free_primary_root_displacement": {
            "minimum_count_at_6px": 3,
            "minimum_median_px": 5.0,
        },
        "secondary_root_displacement": {
            "minimum_count_at_5px": 7,
            "minimum_count_at_9px": 3,
            "minimum_affected_subtrees": 4,
        },
        "direction_change_degrees": {
            "free_primary_minimum_count_at_8": 3,
            "secondary_minimum_count_at_10": 7,
            "secondary_minimum_count_at_18": 3,
        },
        "symmetric_relative_length_change": {
            "free_primary_minimum_median": 0.12,
            "secondary_minimum_count_at_0_15": 6,
            "secondary_minimum_count_at_0_25": 2,
        },
        "normalized_shape_rms": {
            "secondary_minimum_count_at_0_045": 6,
            "secondary_minimum_count_at_0_08": 2,
        },
        "attachment_coordinates": {
            "movable_primary_minimum_each_delta_mount_s": 0.020,
            "secondary_minimum_each_delta_mount_fraction": 0.035,
            "secondary_minimum_count_at_0_07": 8,
            "secondary_slide_minimum_count_at_5px": 7,
            "secondary_slide_minimum_count_at_9px": 3,
            "secondary_slide_minimum_affected_units": 4,
            "tertiary_minimum_each_delta_mount_fraction": 0.10,
            "fixed_primary_anchor": "primary_4_flower_1",
        },
    }
    pair_rows: list[dict[str, object]] = []
    for first_index, first_seed in enumerate(seed_tuple):
        for second_seed in seed_tuple[first_index + 1 :]:
            first = results[first_seed].by_id
            second = results[second_seed].by_id
            first_primary_plan = {
                row.curve_id: row for row in results[first_seed].plan.primaries
            }
            second_primary_plan = {
                row.curve_id: row for row in results[second_seed].plan.primaries
            }
            first_child_plan = {
                row.curve_id: row for row in results[first_seed].plan.descendants
            }
            second_child_plan = {
                row.curve_id: row for row in results[second_seed].plan.descendants
            }
            primary_mount_delta = {
                curve_id: abs(
                    first_primary_plan[curve_id].mount_s
                    - second_primary_plan[curve_id].mount_s
                )
                for curve_id in movable_primary_mount_ids
            }
            secondary_mount_delta = {
                curve_id: abs(
                    first_child_plan[curve_id].mount_fraction
                    - second_child_plan[curve_id].mount_fraction
                )
                for curve_id in secondary_ids
            }
            secondary_parent_relative_slide = {
                curve_id: min(
                    first[first_child_plan[curve_id].parent_id].curve.length,
                    second[second_child_plan[curve_id].parent_id].curve.length,
                )
                * secondary_mount_delta[curve_id]
                for curve_id in secondary_ids
            }
            tertiary_mount_delta = {
                curve_id: abs(
                    first_child_plan[curve_id].mount_fraction
                    - second_child_plan[curve_id].mount_fraction
                )
                for curve_id in tertiary_ids
            }
            free_root = {
                curve_id: dist(first[curve_id].curve.root, second[curve_id].curve.root)
                for curve_id in free_primary_ids
            }
            secondary_root = {
                curve_id: dist(first[curve_id].curve.root, second[curve_id].curve.root)
                for curve_id in secondary_ids
            }
            free_direction = {
                curve_id: _circular_angle_delta_degrees(
                    _curve_direction_degrees(first[curve_id].curve),
                    _curve_direction_degrees(second[curve_id].curve),
                )
                for curve_id in free_primary_ids
            }
            secondary_direction = {
                curve_id: _circular_angle_delta_degrees(
                    _curve_direction_degrees(first[curve_id].curve),
                    _curve_direction_degrees(second[curve_id].curve),
                )
                for curve_id in secondary_ids
            }
            free_length = {
                curve_id: _symmetric_relative_difference(
                    first[curve_id].curve.length,
                    second[curve_id].curve.length,
                )
                for curve_id in free_primary_ids
            }
            secondary_length = {
                curve_id: _symmetric_relative_difference(
                    first[curve_id].curve.length,
                    second[curve_id].curve.length,
                )
                for curve_id in secondary_ids
            }
            secondary_shape = {
                curve_id: _shape_rms(first[curve_id].curve, second[curve_id].curve)
                for curve_id in secondary_ids
            }
            sorted_free_roots = sorted(free_root.values())
            free_root_median = sorted_free_roots[len(sorted_free_roots) // 2]
            sorted_free_lengths = sorted(free_length.values())
            free_length_median = sorted_free_lengths[len(sorted_free_lengths) // 2]
            affected_subtrees = {
                _subtree_id(curve_id)
                for curve_id, displacement in secondary_root.items()
                if displacement >= 5.0
            }
            slide_affected_units = {
                first_child_plan[curve_id].parent_id
                for curve_id, displacement in secondary_parent_relative_slide.items()
                if displacement >= 5.0
            }
            gate_results = {
                "primary_mount_parameters": all(
                    value >= 0.020 for value in primary_mount_delta.values()
                ),
                "secondary_mount_parameters": (
                    all(value >= 0.035 for value in secondary_mount_delta.values())
                    and sum(value >= 0.07 for value in secondary_mount_delta.values()) >= 8
                ),
                "secondary_parent_relative_slide": (
                    sum(value >= 5.0 for value in secondary_parent_relative_slide.values()) >= 7
                    and sum(value >= 9.0 for value in secondary_parent_relative_slide.values()) >= 3
                    and len(slide_affected_units) >= 4
                ),
                "tertiary_mount_parameters": all(
                    value >= 0.10 for value in tertiary_mount_delta.values()
                ),
                "free_primary_roots": (
                    sum(value >= 6.0 for value in free_root.values()) >= 3
                    and free_root_median >= 5.0
                ),
                "secondary_roots": (
                    sum(value >= 5.0 for value in secondary_root.values()) >= 7
                    and sum(value >= 9.0 for value in secondary_root.values()) >= 3
                    and len(affected_subtrees) >= 4
                ),
                "free_primary_directions": (
                    sum(value >= 8.0 for value in free_direction.values()) >= 3
                ),
                "secondary_directions": (
                    sum(value >= 10.0 for value in secondary_direction.values()) >= 7
                    and sum(value >= 18.0 for value in secondary_direction.values()) >= 3
                ),
                "free_primary_lengths": free_length_median >= 0.12,
                "secondary_lengths": (
                    sum(value >= 0.15 for value in secondary_length.values()) >= 6
                    and sum(value >= 0.25 for value in secondary_length.values()) >= 2
                ),
                "secondary_shapes": (
                    sum(value >= 0.045 for value in secondary_shape.values()) >= 6
                    and sum(value >= 0.08 for value in secondary_shape.values()) >= 2
                ),
            }
            pair_rows.append(
                {
                    "first_seed": first_seed,
                    "second_seed": second_seed,
                    "movable_primary_delta_mount_s": {
                        key: round(value, 8) for key, value in primary_mount_delta.items()
                    },
                    "secondary_delta_mount_fraction": {
                        key: round(value, 8) for key, value in secondary_mount_delta.items()
                    },
                    "secondary_parent_relative_slide_px": {
                        key: round(value, 8)
                        for key, value in secondary_parent_relative_slide.items()
                    },
                    "secondary_slide_affected_units": sorted(slide_affected_units),
                    "tertiary_delta_mount_fraction": {
                        key: round(value, 8) for key, value in tertiary_mount_delta.items()
                    },
                    "free_primary_root_displacement_px": {
                        key: round(value, 8) for key, value in free_root.items()
                    },
                    "secondary_root_displacement_px": {
                        key: round(value, 8) for key, value in secondary_root.items()
                    },
                    "affected_secondary_root_subtrees": sorted(affected_subtrees),
                    "free_primary_direction_change_degrees": {
                        key: round(value, 8) for key, value in free_direction.items()
                    },
                    "secondary_direction_change_degrees": {
                        key: round(value, 8) for key, value in secondary_direction.items()
                    },
                    "free_primary_symmetric_relative_length_change": {
                        key: round(value, 8) for key, value in free_length.items()
                    },
                    "secondary_symmetric_relative_length_change": {
                        key: round(value, 8) for key, value in secondary_length.items()
                    },
                    "secondary_normalized_shape_rms": {
                        key: round(value, 8) for key, value in secondary_shape.items()
                    },
                    "summary": {
                        "movable_primary_minimum_delta_mount_s": round(
                            min(primary_mount_delta.values()), 8
                        ),
                        "secondary_minimum_delta_mount_fraction": round(
                            min(secondary_mount_delta.values()), 8
                        ),
                        "secondary_mount_count_at_0_07": sum(
                            value >= 0.07 for value in secondary_mount_delta.values()
                        ),
                        "secondary_slide_count_at_5px": sum(
                            value >= 5.0
                            for value in secondary_parent_relative_slide.values()
                        ),
                        "secondary_slide_count_at_9px": sum(
                            value >= 9.0
                            for value in secondary_parent_relative_slide.values()
                        ),
                        "secondary_slide_affected_unit_count": len(slide_affected_units),
                        "tertiary_minimum_delta_mount_fraction": round(
                            min(tertiary_mount_delta.values()), 8
                        ),
                        "free_root_count_at_6px": sum(value >= 6.0 for value in free_root.values()),
                        "free_root_median_px": round(free_root_median, 8),
                        "secondary_root_count_at_5px": sum(value >= 5.0 for value in secondary_root.values()),
                        "secondary_root_count_at_9px": sum(value >= 9.0 for value in secondary_root.values()),
                        "secondary_root_affected_subtree_count": len(affected_subtrees),
                        "free_direction_count_at_8_degrees": sum(value >= 8.0 for value in free_direction.values()),
                        "secondary_direction_count_at_10_degrees": sum(value >= 10.0 for value in secondary_direction.values()),
                        "secondary_direction_count_at_18_degrees": sum(value >= 18.0 for value in secondary_direction.values()),
                        "free_length_median": round(free_length_median, 8),
                        "secondary_length_count_at_0_15": sum(value >= 0.15 for value in secondary_length.values()),
                        "secondary_length_count_at_0_25": sum(value >= 0.25 for value in secondary_length.values()),
                        "secondary_shape_count_at_0_045": sum(value >= 0.045 for value in secondary_shape.values()),
                        "secondary_shape_count_at_0_08": sum(value >= 0.08 for value in secondary_shape.values()),
                    },
                    "gates": gate_results,
                    "passes": all(gate_results.values()),
                }
            )
    fixed_seed_sequence = seed_tuple == DEV_SEEDS
    return {
        "seeds": list(seed_tuple),
        "fixed_seed_sequence": fixed_seed_sequence,
        "thresholds": thresholds,
        "pairwise": pair_rows,
        "passes": fixed_seed_sequence and bool(pair_rows) and all(row["passes"] for row in pair_rows),
    }


def seed_variation_proof(p0: StrictP0, seeds: Sequence[int] = DEV_SEEDS) -> dict[str, object]:
    results = [build_j0a(p0, seed) for seed in seeds]
    replays = [build_j0a(p0, seed) for seed in seeds]
    hashes = [result.geometry_hash for result in results]
    plans = [result.plan.digest for result in results]
    serialized = [
        json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for result in results
    ]
    replay_serialized = [
        json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for result in replays
    ]
    replay_by_seed = {
        str(seed): first == second
        for seed, first, second in zip(seeds, serialized, replay_serialized)
    }
    raw_object_replay_by_seed = {
        str(seed): first == second
        for seed, first, second in zip(seeds, results, replays)
    }
    geometry_hash_replay_by_seed = {
        str(seed): first.geometry_hash == second.geometry_hash
        for seed, first, second in zip(seeds, results, replays)
    }
    all_replays_identical = (
        all(replay_by_seed.values())
        and all(raw_object_replay_by_seed.values())
        and all(geometry_hash_replay_by_seed.values())
    )
    visible_variation = seed_visible_variation_proof(p0, seeds)
    return {
        "seeds": list(seeds),
        "geometry_hashes": hashes,
        "plan_digests": plans,
        "canonical_json_byte_identical_by_seed": replay_by_seed,
        "raw_plan_and_geometry_equal_by_seed": raw_object_replay_by_seed,
        "geometry_hash_replay_by_seed": geometry_hash_replay_by_seed,
        "all_replays_byte_identical": all_replays_identical,
        "all_geometry_distinct": len(set(hashes)) == len(hashes),
        "all_parameter_plans_distinct": len(set(plans)) == len(plans),
        "visible_variation": visible_variation,
        "passes": (
            all_replays_identical
            and len(set(hashes)) == len(hashes)
            and len(set(plans)) == len(plans)
            and bool(visible_variation["passes"])
        ),
    }


__all__ = [
    "DEV_SEEDS",
    "GEOMETRY_KERNEL_ID",
    "GlobalControls",
    "GlobalPlan",
    "HierarchyCurve",
    "HierarchyResult",
    "PLAN_ID",
    "POLICY_ID",
    "StrictP0",
    "SubtreeControl",
    "build_j0a",
    "compile_plan",
    "global_dependency_proof",
    "ignored_field_intervention",
    "intervention_proof",
    "plan_j0a",
    "seed_visible_variation_proof",
    "seed_variation_proof",
    "strip_profile",
    "subtree_dependency_proof",
    "traversal_order_proof",
    "validate_result",
]
