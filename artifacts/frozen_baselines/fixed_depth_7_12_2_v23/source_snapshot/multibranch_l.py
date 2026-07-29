#!/usr/bin/env python3
"""Shared kernel for the branch-free, multi-branch L development gate.

The module intentionally consumes a strict P0 whitelist.  In particular it
does not read the source profile's existing guides, growth regions, space
samples, or region graph.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence

from l_core import (
    Cubic,
    Curve,
    FlowerReserve,
    Point,
    add,
    angle_degrees,
    cross,
    dist,
    dot,
    mul,
    point_polyline_distance,
    polyline_length,
    polyline_pair_distance,
    sample_cubic,
    sample_polyline,
    sub,
)


POLICY_ID = "backbone_flower_reserves_repeat_bounds_only_v1"
GEOMETRY_KERNEL_ID = "multibranch_l_shared_geometry_v1"
ALLOWED_BRANCH_COUNTS = {4, 5}
BRANCH_WIDTH = 3.0
MIN_VISIBLE_TURN_DEGREES = 12.0
MIN_VISIBLE_TURN_LENGTH_RATIO = 0.08


def _unit(vector: Point) -> Point:
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-12:
        return (1.0, 0.0)
    return (vector[0] / length, vector[1] / length)


def _normal(vector: Point) -> Point:
    return (-vector[1], vector[0])


def _rotate(vector: Point, degrees: float) -> Point:
    radians = math.radians(degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        vector[0] * cosine - vector[1] * sine,
        vector[0] * sine + vector[1] * cosine,
    )


def _round_point(point: Point) -> list[float]:
    return [round(point[0], 8), round(point[1], 8)]


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BackboneSample:
    s: float
    point: Point
    tangent: Point

    def as_dict(self) -> dict[str, object]:
        return {
            "s": round(self.s, 8),
            "point": _round_point(self.point),
            "tangent": _round_point(self.tangent),
        }


@dataclass(frozen=True)
class StrippedP0:
    prototype_id: str
    repeat_x_range: tuple[float, float]
    canvas_width: float
    canvas_height: float
    backbone_source_path_order: tuple[int, ...]
    backbone_samples: tuple[BackboneSample, ...]
    flowers: tuple[FlowerReserve, ...]
    policy_id: str = POLICY_ID

    @property
    def backbone_points(self) -> tuple[Point, ...]:
        return tuple(sample.point for sample in self.backbone_samples)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "multibranch_stripped_p0_v1",
            "policy_id": self.policy_id,
            "prototype_id": self.prototype_id,
            "repeat_x_range": [round(value, 8) for value in self.repeat_x_range],
            "canvas": {
                "width": round(self.canvas_width, 8),
                "height": round(self.canvas_height, 8),
            },
            "backbone": {
                "source_path_order": list(self.backbone_source_path_order),
                "arc_samples": [sample.as_dict() for sample in self.backbone_samples],
            },
            "flowers": [
                {
                    "flower_id": flower.flower_id,
                    "center": _round_point(flower.center),
                    "rx": round(flower.rx, 8),
                    "ry": round(flower.ry, 8),
                }
                for flower in self.flowers
            ],
            "existing_guides": [],
            "consumed_profile_paths": [
                "prototype_id",
                "repeat_x_range",
                "canvas.width",
                "canvas.height",
                "backbone.source_path_order",
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


def strip_profile(profile: dict[str, object]) -> StrippedP0:
    """Copy only the P0 whitelist; no derived branch-aware field is touched."""

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
    repeat_x_range = tuple(float(value) for value in profile["repeat_x_range"])
    canvas = dict(profile["canvas"])
    result = StrippedP0(
        prototype_id=str(profile["prototype_id"]),
        repeat_x_range=(repeat_x_range[0], repeat_x_range[1]),
        canvas_width=float(canvas["width"]),
        canvas_height=float(canvas["height"]),
        backbone_source_path_order=tuple(int(value) for value in backbone["source_path_order"]),
        backbone_samples=samples,
        flowers=flowers,
    )
    validate_stripped_p0(result)
    return result


def validate_stripped_p0(p0: StrippedP0) -> None:
    if p0.prototype_id != "proto_sw_1_3":
        raise ValueError(f"unexpected prototype: {p0.prototype_id}")
    if p0.policy_id != POLICY_ID:
        raise ValueError("unexpected P0 context policy")
    if p0.backbone_source_path_order != (0, 1, 2, 3, 4):
        raise ValueError("backbone source paths drifted")
    if p0.repeat_x_range != (0.0, 256.0):
        raise ValueError("repeat range drifted")
    if abs(p0.canvas_width - 1024.0) > 1e-9 or abs(p0.canvas_height - 304.0) > 1e-9:
        raise ValueError("canvas drifted")
    if len(p0.flowers) != 2:
        raise ValueError("flower count drifted")
    expected = (
        ("flower_1", (89.296, 167.66), 38.815, 49.921),
        ("flower_2", (212.303, 185.832), 38.815, 49.921),
    )
    actual = tuple((f.flower_id, f.center, f.rx, f.ry) for f in p0.flowers)
    for got, want in zip(actual, expected):
        if got[0] != want[0] or dist(got[1], want[1]) > 1e-6:
            raise ValueError("flower identity or center drifted")
        if abs(got[2] - want[2]) > 1e-6 or abs(got[3] - want[3]) > 1e-6:
            raise ValueError("flower reserve size drifted")


def ignored_field_intervention(profile: dict[str, object]) -> dict[str, object]:
    """Return a deliberately corrupted copy of every branch-derived field."""

    mutated = copy.deepcopy(profile)
    mutated["existing_guides"] = [
        {
            "guide_id": "should_never_be_read",
            "points": [[-99999.0, -99999.0], [99999.0, 99999.0]],
            "source_role": "poison",
        }
    ]
    mutated["growth_regions"] = [{"region_id": "poison", "attach_s": -999.0}]
    mutated["space_samples"] = [{"blocked_by": "poison", "s": -999.0}]
    mutated["region_graph"] = {"poison": True}
    mutated["nodes"] = [{"poison": True}]
    mutated["segments"] = [{"poison": True}]
    mutated["qa"] = {"poison": True}
    return mutated


@dataclass(frozen=True)
class RawBranchToken:
    mount: float
    side: float
    length: float
    bend: float
    turn_1: float
    turn_2: float
    shape: float

    def as_dict(self) -> dict[str, float]:
        return {
            "mount": round(self.mount, 12),
            "side": round(self.side, 12),
            "length": round(self.length, 12),
            "bend": round(self.bend, 12),
            "turn_1": round(self.turn_1, 12),
            "turn_2": round(self.turn_2, 12),
            "shape": round(self.shape, 12),
        }


def materialize_tokens(seed: int, branch_count: int) -> tuple[RawBranchToken, ...]:
    if branch_count not in ALLOWED_BRANCH_COUNTS:
        raise ValueError("branch_count must be 4 or 5")
    rng = random.Random(seed)
    return tuple(
        RawBranchToken(
            mount=rng.random(),
            side=rng.random(),
            length=rng.random(),
            bend=rng.random(),
            turn_1=rng.random(),
            turn_2=rng.random(),
            shape=rng.random(),
        )
        for _ in range(branch_count)
    )


@dataclass(frozen=True)
class BranchRole:
    role_id: str
    kind: str
    flower_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"role_id": self.role_id, "kind": self.kind, "flower_id": self.flower_id}


def branch_roles(branch_count: int) -> tuple[BranchRole, ...]:
    if branch_count not in ALLOWED_BRANCH_COUNTS:
        raise ValueError("branch_count must be 4 or 5")
    return (
        BranchRole("flower_1_branch", "flower", "flower_1"),
        BranchRole("flower_2_branch", "flower", "flower_2"),
        *(BranchRole(f"free_{index}_branch", "free") for index in range(1, branch_count - 1)),
    )


@dataclass(frozen=True)
class BranchIntent:
    role: BranchRole
    source_token_index: int
    mount_s: float
    side_sign: int
    planned_bend_count: int
    turn_1_degrees: float
    turn_2_degrees: float
    shape_bias: float

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role.as_dict(),
            "source_token_index": self.source_token_index,
            "mount_s": round(self.mount_s, 10),
            "side_sign": self.side_sign,
            "planned_bend_count": self.planned_bend_count,
            "turn_1_degrees": round(self.turn_1_degrees, 10),
            "turn_2_degrees": round(self.turn_2_degrees, 10),
            "shape_bias": round(self.shape_bias, 10),
        }


@dataclass(frozen=True)
class IntentPlan:
    variant: str
    branch_count: int
    intents: tuple[BranchIntent, ...]
    trace: dict[str, object]


def _independent_windows(branch_count: int) -> dict[str, tuple[float, float]]:
    if branch_count == 4:
        return {
            "flower_1_branch": (0.31, 0.45),
            "flower_2_branch": (0.57, 0.70),
            "free_1_branch": (0.10, 0.25),
            "free_2_branch": (0.78, 0.90),
        }
    return {
        "flower_1_branch": (0.30, 0.43),
        "flower_2_branch": (0.59, 0.72),
        "free_1_branch": (0.09, 0.23),
        "free_2_branch": (0.46, 0.56),
        "free_3_branch": (0.80, 0.91),
    }


def plan_l0_independent(
    p0: StrippedP0,
    tokens: Sequence[RawBranchToken],
) -> IntentPlan:
    """Map each role row without reading any sibling row."""

    roles = branch_roles(len(tokens))
    windows = _independent_windows(len(tokens))
    intents: list[BranchIntent] = []
    for index, (role, token) in enumerate(zip(roles, tokens)):
        if role.kind == "flower":
            mount_s = _shared_flower_mounts(p0)[str(role.flower_id)]
        else:
            low, high = windows[role.role_id]
            mount_s = low + (high - low) * token.mount
        side_sign = 1 if token.side >= 0.5 else -1
        bend_count = 2 if token.bend >= 0.5 else 1
        intents.append(
            BranchIntent(
                role=role,
                source_token_index=index,
                mount_s=mount_s,
                side_sign=side_sign,
                planned_bend_count=bend_count,
                turn_1_degrees=34.0 + 28.0 * token.turn_1,
                turn_2_degrees=18.0 + 20.0 * token.turn_2 if bend_count == 2 else 0.0,
                shape_bias=2.0 * token.shape - 1.0,
            )
        )
    return IntentPlan(
        variant="L0",
        branch_count=len(tokens),
        intents=tuple(intents),
        trace={
            "mapping_id": "multibranch_l0_independent_v1",
            "sibling_state_consumed": False,
            "token_intervention_contract": "row_i_changes_only_role_i",
            "mount_windows": {key: list(value) for key, value in windows.items()},
            "generation_policy": _generation_policy(),
        },
    )


def plan_l1_joint(
    p0: StrippedP0,
    tokens: Sequence[RawBranchToken],
) -> IntentPlan:
    """Map one entire first-level set by a closed-form center+gap plan."""

    branch_count = len(tokens)
    if branch_count not in ALLOWED_BRANCH_COUNTS:
        raise ValueError("branch_count must be 4 or 5")
    free_count = branch_count - 2
    free_tokens = tokens[2:]
    center_u = sum(token.mount for token in free_tokens) / free_count
    gap_u = sum(token.side for token in free_tokens) / free_count
    if free_count == 2:
        gap = 0.66 + 0.05 * gap_u
        center_low = 0.43
        center_high = 0.55
    else:
        gap = 0.31 + 0.04 * gap_u
        center_low = 0.48
        center_high = 0.54
    center = center_low + (center_high - center_low) * center_u
    free_slots = tuple(center + (index - 0.5 * (free_count - 1)) * gap for index in range(free_count))
    flower_mounts = _shared_flower_mounts(p0)
    role_token_index = {
        role.role_id: index for index, role in enumerate(branch_roles(branch_count))
    }
    intents: list[BranchIntent] = []
    for flower_index, flower in enumerate(p0.flowers, start=1):
        role = BranchRole(f"flower_{flower_index}_branch", "flower", flower.flower_id)
        token_index = role_token_index[role.role_id]
        token = tokens[token_index]
        mount_s = flower_mounts[flower.flower_id]
        collar = flower_collar(p0, flower)[1]
        root, tangent = sample_polyline(p0.backbone_points, mount_s)
        chord = _unit(sub(collar, root))
        side_sign = 1 if cross(tangent, chord) >= 0.0 else -1
        bend_count = 1 if abs(_signed_angle(tangent, chord)) < 78.0 else 2
        intents.append(
            BranchIntent(
                role=role,
                source_token_index=token_index,
                mount_s=mount_s,
                side_sign=side_sign,
                planned_bend_count=bend_count,
                turn_1_degrees=40.0 + 18.0 * token.turn_1,
                turn_2_degrees=18.0 + 14.0 * token.turn_2 if bend_count == 2 else 0.0,
                shape_bias=2.0 * token.shape - 1.0,
            )
        )
    free_side_sequence: dict[int, int] = {}
    for free_index, mount_s in enumerate(free_slots, start=1):
        role = BranchRole(f"free_{free_index}_branch", "free")
        token_index = role_token_index[role.role_id]
        token = tokens[token_index]
        side_sign = -1 if free_index in {1, free_count} else 1
        bend_count = 2 if free_index in {1, free_count} else 1
        free_side_sequence[free_index] = side_sign
        intents.append(
            BranchIntent(
                role=role,
                source_token_index=token_index,
                mount_s=mount_s,
                side_sign=side_sign,
                planned_bend_count=bend_count,
                turn_1_degrees=44.0 + 16.0 * token.turn_1,
                turn_2_degrees=18.0 + 12.0 * token.turn_2 if bend_count == 2 else 0.0,
                shape_bias=(free_index - 0.5 * (free_count + 1)) / max(free_count - 1, 1),
            )
        )
    intents.sort(key=lambda intent: intent.role.role_id)
    return IntentPlan(
        variant="L1",
        branch_count=branch_count,
        intents=tuple(intents),
        trace={
            "mapping_id": "multibranch_l1_joint_center_gap_v1",
            "sibling_state_consumed": True,
            "center_token": round(center_u, 12),
            "gap_token": round(gap_u, 12),
            "center": round(center, 12),
            "gap": round(gap, 12),
            "free_slots": [round(value, 12) for value in free_slots],
            "shared_programmatic_flower_mounts": {
                key: round(value, 12) for key, value in flower_mounts.items()
            },
            "free_side_sequence": {str(key): value for key, value in free_side_sequence.items()},
            "generation_policy": _generation_policy(),
        },
    )


def _shared_flower_mounts(p0: StrippedP0) -> dict[str, float]:
    """Choose two P0-derived flower supports without consulting old branches."""

    preferred = {"flower_1": 74.0, "flower_2": 48.0}
    domains = {"flower_1": (0.22, 0.55), "flower_2": (0.60, 0.88)}
    result: dict[str, float] = {}
    for flower in p0.flowers:
        collar = flower_collar(p0, flower)[1]
        low, high = domains[flower.flower_id]
        candidates = [low + (high - low) * index / 320.0 for index in range(321)]
        result[flower.flower_id] = min(
            candidates,
            key=lambda value: (
                abs(dist(sample_polyline(p0.backbone_points, value)[0], collar) - preferred[flower.flower_id]),
                value,
            ),
        )
    return result


def _generation_policy() -> dict[str, object]:
    return {
        "candidate_count": 1,
        "retry_count": 0,
        "resample_count": 0,
        "repair_count": 0,
        "validation_feedback_consumed": False,
    }


def _joint_flower_slot_assignment(
    p0: StrippedP0,
    slots: Sequence[float],
    preferred_chords: dict[str, float],
) -> dict[str, int]:
    flowers = {flower.flower_id: flower for flower in p0.flowers}
    collars = {flower_id: flower_collar(p0, flower)[1] for flower_id, flower in flowers.items()}
    best: tuple[float, int, int] | None = None
    for first_index in range(len(slots)):
        for second_index in range(len(slots)):
            if first_index == second_index:
                continue
            first_root, _ = sample_polyline(p0.backbone_points, slots[first_index])
            second_root, _ = sample_polyline(p0.backbone_points, slots[second_index])
            cost = abs(dist(first_root, collars["flower_1"]) - preferred_chords["flower_1"])
            cost += abs(dist(second_root, collars["flower_2"]) - preferred_chords["flower_2"])
            candidate = (cost, first_index, second_index)
            if best is None or candidate < best:
                best = candidate
    assert best is not None
    return {"flower_1": best[1], "flower_2": best[2]}


def nearest_backbone_projection(p0: StrippedP0, point: Point) -> tuple[float, Point]:
    points = p0.backbone_points
    segment_lengths = [dist(start, end) for start, end in zip(points, points[1:])]
    total = sum(segment_lengths)
    traversed = 0.0
    best_distance = math.inf
    best_s = 0.0
    best_point = points[0]
    for start, end, length in zip(points, points[1:], segment_lengths):
        direction = sub(end, start)
        denominator = dot(direction, direction)
        local = 0.0 if denominator <= 1e-12 else max(0.0, min(1.0, dot(sub(point, start), direction) / denominator))
        projection = add(start, mul(direction, local))
        current = dist(point, projection)
        if current < best_distance:
            best_distance = current
            best_point = projection
            best_s = (traversed + local * length) / max(total, 1e-12)
        traversed += length
    return best_s, best_point


def flower_collar(p0: StrippedP0, flower: FlowerReserve) -> tuple[float, Point]:
    nearest_s, nearest = nearest_backbone_projection(p0, flower.center)
    delta = sub(nearest, flower.center)
    denominator = math.sqrt((delta[0] / flower.rx) ** 2 + (delta[1] / flower.ry) ** 2)
    if denominator <= 1e-12:
        raise ValueError(f"flower {flower.flower_id} center lies on backbone")
    return nearest_s, add(flower.center, mul(delta, 1.0 / denominator))


def shared_role_lengths(
    p0: StrippedP0,
    l0: IntentPlan,
    l1: IntentPlan,
    tokens: Sequence[RawBranchToken],
) -> dict[str, float]:
    """Create one symmetric target-length budget before either compilation."""

    roles = branch_roles(len(tokens))
    result: dict[str, float] = {}
    for role_index, role in enumerate(roles):
        if role.kind == "free":
            if len(tokens) == 5 and role.role_id == "free_2_branch":
                # The middle free branch occupies the narrow corridor between
                # the two flower reserves.  Its role budget is deliberately
                # shorter in both variants; this is a pre-compile role budget,
                # not validation-driven repair.
                result[role.role_id] = 43.0 + 4.0 * tokens[role_index].length
            else:
                result[role.role_id] = 52.0 + 18.0 * tokens[role_index].length
            continue
        flower = next(item for item in p0.flowers if item.flower_id == role.flower_id)
        collar = flower_collar(p0, flower)[1]
        chords = []
        for plan in (l0, l1):
            intent = next(item for item in plan.intents if item.role.role_id == role.role_id)
            root, _ = sample_polyline(p0.backbone_points, intent.mount_s)
            chords.append(dist(root, collar))
        result[role.role_id] = max(42.0, max(chords) * (1.14 + 0.06 * tokens[role_index].length))
    return result


@dataclass(frozen=True)
class GeneratedBranch:
    role: BranchRole
    source_token_index: int
    curve: Curve
    planned_bend_count: int
    compiler_trace: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role.as_dict(),
            "source_token_index": self.source_token_index,
            "planned_bend_count": self.planned_bend_count,
            "compiler_trace": self.compiler_trace,
            "curve": self.curve.as_dict(),
        }


@dataclass(frozen=True)
class BranchSet:
    variant: str
    branches: tuple[GeneratedBranch, ...]
    plan_trace: dict[str, object]
    target_role_lengths: dict[str, float]

    @property
    def total_length(self) -> float:
        return sum(branch.curve.length for branch in self.branches)

    @property
    def vector_ink(self) -> float:
        return sum(branch.curve.length * branch.curve.width for branch in self.branches)

    @property
    def geometry_hash(self) -> str:
        return _digest(
            {
                "geometry_kernel_id": GEOMETRY_KERNEL_ID,
                "branches": [branch.as_dict() for branch in self.branches],
            }
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "variant": self.variant,
            "geometry_kernel_id": GEOMETRY_KERNEL_ID,
            "branch_count": len(self.branches),
            "first_level_branch_count": len(self.branches),
            "child_branch_count": 0,
            "total_length": round(self.total_length, 8),
            "vector_ink": round(self.vector_ink, 8),
            "geometry_hash": self.geometry_hash,
            "target_role_lengths": {key: round(value, 8) for key, value in self.target_role_lengths.items()},
            "plan_trace": self.plan_trace,
            "branches": [branch.as_dict() for branch in self.branches],
        }


def compile_plan(
    p0: StrippedP0,
    plan: IntentPlan,
    target_role_lengths: dict[str, float],
) -> BranchSet:
    branches: list[GeneratedBranch] = []
    compiled_lengths: dict[str, float] = {}
    for intent in plan.intents:
        target_length = float(target_role_lengths[intent.role.role_id])
        root, tangent = sample_polyline(p0.backbone_points, intent.mount_s)
        if intent.role.kind == "flower":
            flower = next(item for item in p0.flowers if item.flower_id == intent.role.flower_id)
            collar = flower_collar(p0, flower)[1]
            curve, trace = _compile_flower_branch(
                curve_id=intent.role.role_id,
                root=root,
                root_tangent=tangent,
                flower=flower,
                collar=collar,
                target_length=target_length,
                mount_s=intent.mount_s,
                shape_bias=intent.shape_bias,
            )
        else:
            curve, trace = _compile_free_branch(
                curve_id=intent.role.role_id,
                root=root,
                root_tangent=tangent,
                target_length=target_length,
                mount_s=intent.mount_s,
                side_sign=intent.side_sign,
                turn_1_degrees=intent.turn_1_degrees,
                turn_2_degrees=intent.turn_2_degrees if intent.planned_bend_count == 2 else 0.0,
            )
        branches.append(
            GeneratedBranch(
                role=intent.role,
                source_token_index=intent.source_token_index,
                curve=curve,
                planned_bend_count=intent.planned_bend_count,
                compiler_trace=trace,
            )
        )
        compiled_lengths[intent.role.role_id] = curve.target_length
    branches.sort(key=lambda branch: branch.role.role_id)
    return BranchSet(
        variant=plan.variant,
        branches=tuple(branches),
        plan_trace=plan.trace,
        target_role_lengths=compiled_lengths,
    )


def _arc_cubic(start: Point, start_tangent: Point, length: float, turn_degrees: float) -> tuple[Cubic, Point]:
    theta = math.radians(turn_degrees)
    tangent = _unit(start_tangent)
    if abs(theta) <= 1e-10:
        end = add(start, mul(tangent, length))
        handle = length / 3.0
        return Cubic(start, add(start, mul(tangent, handle)), sub(end, mul(tangent, handle)), end), tangent
    curvature = theta / length
    normal = _normal(tangent)
    displacement = add(
        mul(tangent, math.sin(theta) / curvature),
        mul(normal, (1.0 - math.cos(theta)) / curvature),
    )
    end = add(start, displacement)
    end_tangent = _rotate(tangent, turn_degrees)
    radius = abs(1.0 / curvature)
    handle = (4.0 / 3.0) * radius * math.tan(abs(theta) / 4.0)
    cubic = Cubic(
        p0=start,
        p1=add(start, mul(tangent, handle)),
        p2=sub(end, mul(end_tangent, handle)),
        p3=end,
    )
    return cubic, end_tangent


def _compile_free_branch(
    *,
    curve_id: str,
    root: Point,
    root_tangent: Point,
    target_length: float,
    mount_s: float,
    side_sign: int,
    turn_1_degrees: float,
    turn_2_degrees: float,
) -> tuple[Curve, dict[str, object]]:
    sign = 1 if side_sign >= 0 else -1
    tangent = _unit(root_tangent)
    if turn_2_degrees >= MIN_VISIBLE_TURN_DEGREES:
        joint_tangent = _rotate(tangent, sign * turn_1_degrees)
        joint_direction = _rotate(tangent, sign * turn_1_degrees * 0.64)
        joint = add(root, mul(joint_direction, target_length * 0.45))
        end_tangent = _rotate(joint_tangent, -sign * turn_2_degrees)
        end_direction = _rotate(tangent, sign * (turn_1_degrees - 0.62 * turn_2_degrees))
        end = add(root, mul(end_direction, target_length * 0.76))
        start_handle = min(6.5, target_length * 0.085)
        joint_handle = target_length * 0.115
        end_handle = target_length * 0.17
        first = Cubic(
            p0=root,
            p1=add(root, mul(tangent, start_handle)),
            p2=sub(joint, mul(joint_tangent, joint_handle)),
            p3=joint,
        )
        second = Cubic(
            p0=joint,
            p1=add(joint, mul(joint_tangent, joint_handle)),
            p2=sub(end, mul(end_tangent, end_handle)),
            p3=end,
        )
        cubics = _scale_cubics_about_root((first, second), root, target_length)
        planned = 2
    else:
        travel = _rotate(tangent, sign * (turn_1_degrees * 0.82))
        end_tangent = _rotate(tangent, sign * min(76.0, turn_1_degrees + 12.0))
        end = add(root, mul(travel, target_length * 0.80))
        first = Cubic(
            p0=root,
            p1=add(root, mul(tangent, min(6.5, target_length * 0.085))),
            p2=sub(end, mul(end_tangent, target_length * 0.20)),
            p3=end,
        )
        cubics = _scale_cubics_about_root((first,), root, target_length)
        planned = 1
    curve = Curve(
        curve_id=curve_id,
        role="free_branch",
        parent_id="backbone",
        width=BRANCH_WIDTH,
        target_length=target_length,
        cubics=cubics,
        mount_fraction=mount_s,
    )
    return curve, {
        "compiler": "fast_takeoff_cubic_v2",
        "source": "program_generated",
        "planned_bend_count": planned,
        "signed_turns_degrees": [sign * turn_1_degrees]
        + ([-sign * turn_2_degrees] if planned == 2 else []),
    }


def _compile_flower_branch(
    *,
    curve_id: str,
    root: Point,
    root_tangent: Point,
    flower: FlowerReserve,
    collar: Point,
    target_length: float,
    mount_s: float,
    shape_bias: float,
) -> tuple[Curve, dict[str, object]]:
    chord_vector = sub(collar, root)
    chord_length = dist(root, collar)
    end_tangent = _unit(sub(flower.center, collar))
    bias = max(-1.0, min(1.0, shape_bias))
    handle_ratio = math.exp(0.10 * bias)
    start_handle = min(8.0, chord_length * 0.10) * handle_ratio
    end_handle = chord_length * 0.24 / handle_ratio
    cubics = (
        Cubic(
            p0=root,
            p1=add(root, mul(_unit(root_tangent), start_handle)),
            p2=sub(collar, mul(end_tangent, end_handle)),
            p3=collar,
        ),
    )
    actual_length = _cubics_length(cubics)
    curve = Curve(
        curve_id=curve_id,
        role="flower_branch",
        parent_id="backbone",
        width=BRANCH_WIDTH,
        target_length=actual_length,
        cubics=cubics,
        mount_fraction=mount_s,
    )
    return curve, {
        "compiler": "single_cubic_flower_collar_v2",
        "source": "program_generated",
        "target_flower_id": flower.flower_id,
        "flower_collar": _round_point(collar),
        "requested_shared_envelope_length": round(target_length, 10),
        "start_handle": round(start_handle, 10),
        "end_handle": round(end_handle, 10),
        "target_length_error": round(curve.length - actual_length, 10),
    }


def _cubics_length(cubics: Sequence[Cubic]) -> float:
    points: list[Point] = []
    for index, cubic in enumerate(cubics):
        sampled = sample_cubic(cubic, 192)
        points.extend(sampled if index == 0 else sampled[1:])
    return polyline_length(points)


def _scale_cubics_about_root(
    cubics: Sequence[Cubic],
    root: Point,
    target_length: float,
) -> tuple[Cubic, ...]:
    current = _cubics_length(cubics)
    scale = target_length / max(current, 1e-12)

    def scale_point(point: Point) -> Point:
        return add(root, mul(sub(point, root), scale))

    return tuple(
        Cubic(
            p0=scale_point(cubic.p0),
            p1=scale_point(cubic.p1),
            p2=scale_point(cubic.p2),
            p3=scale_point(cubic.p3),
        )
        for cubic in cubics
    )


def _signed_angle(first: Point, second: Point) -> float:
    first = _unit(first)
    second = _unit(second)
    return math.degrees(math.atan2(cross(first, second), dot(first, second)))


def bend_audit(curve: Curve) -> dict[str, object]:
    points = curve.points(128)
    segment_lengths = [dist(start, end) for start, end in zip(points, points[1:])]
    total_length = sum(segment_lengths)
    directions = [_unit(sub(end, start)) for start, end in zip(points, points[1:])]
    raw: list[dict[str, float | int]] = []
    current_sign = 0
    current_turn = 0.0
    current_length = 0.0
    for index, (first, second) in enumerate(zip(directions, directions[1:])):
        turn = _signed_angle(first, second)
        sign = 0 if abs(turn) < 0.02 else (1 if turn > 0.0 else -1)
        covered = 0.5 * (segment_lengths[index] + segment_lengths[index + 1])
        if sign == 0:
            current_length += covered
            continue
        if current_sign == 0 or sign == current_sign:
            current_sign = sign
            current_turn += turn
            current_length += covered
        else:
            raw.append({"sign": current_sign, "turn_degrees": current_turn, "length": current_length})
            current_sign = sign
            current_turn = turn
            current_length = covered
    if current_sign:
        raw.append({"sign": current_sign, "turn_degrees": current_turn, "length": current_length})

    effective = [
        lobe
        for lobe in raw
        if not (
            abs(float(lobe["turn_degrees"])) < MIN_VISIBLE_TURN_DEGREES
            and float(lobe["length"]) / max(total_length, 1e-12) < MIN_VISIBLE_TURN_LENGTH_RATIO
        )
    ]
    merged: list[dict[str, float | int]] = []
    for lobe in effective:
        if merged and int(merged[-1]["sign"]) == int(lobe["sign"]):
            merged[-1]["turn_degrees"] = float(merged[-1]["turn_degrees"]) + float(lobe["turn_degrees"])
            merged[-1]["length"] = float(merged[-1]["length"]) + float(lobe["length"])
        else:
            merged.append(dict(lobe))
    return {
        "sample_count": len(points),
        "raw_lobe_count": len(raw),
        "bend_count": len(merged),
        "curvature_sign_reversal_count": max(0, len(merged) - 1),
        "lobes": [
            {
                "sign": int(lobe["sign"]),
                "turn_degrees": round(float(lobe["turn_degrees"]), 6),
                "length_ratio": round(float(lobe["length"]) / max(total_length, 1e-12), 6),
            }
            for lobe in merged
        ],
        "thresholds": {
            "minimum_turn_degrees": MIN_VISIBLE_TURN_DEGREES,
            "minimum_length_ratio": MIN_VISIBLE_TURN_LENGTH_RATIO,
        },
    }


def _ellipse_value(point: Point, flower: FlowerReserve, padding: float = 0.0) -> float:
    rx = flower.rx + padding
    ry = flower.ry + padding
    return ((point[0] - flower.center[0]) / rx) ** 2 + ((point[1] - flower.center[1]) / ry) ** 2


def _self_intersects(points: Sequence[Point]) -> bool:
    segments = list(zip(points, points[1:]))
    for first_index, (a, b) in enumerate(segments):
        for second_index in range(first_index + 2, len(segments)):
            if second_index == first_index + 1:
                continue
            c, d = segments[second_index]
            if _segments_intersect(a, b, c, d):
                return True
    return False


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orient(p: Point, q: Point, r: Point) -> float:
        return cross(sub(q, p), sub(r, p))

    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    return (o1 > 1e-8 and o2 < -1e-8 or o1 < -1e-8 and o2 > 1e-8) and (
        o3 > 1e-8 and o4 < -1e-8 or o3 < -1e-8 and o4 > 1e-8
    )


def validate_branch_set(p0: StrippedP0, branch_set: BranchSet) -> dict[str, object]:
    issues: list[str] = []
    diagnostics: dict[str, object] = {
        "context_policy": p0.policy_id,
        "context_curve_ids": ["backbone"],
        "inherited_guide_count": 0,
        "check_only": True,
    }
    count = len(branch_set.branches)
    if count not in ALLOWED_BRANCH_COUNTS:
        issues.append("branch_count_not_4_or_5")
    flower_branches = [branch for branch in branch_set.branches if branch.role.kind == "flower"]
    free_branches = [branch for branch in branch_set.branches if branch.role.kind == "free"]
    if len(flower_branches) != 2:
        issues.append("flower_branch_count")
    if {branch.role.flower_id for branch in flower_branches} != {flower.flower_id for flower in p0.flowers}:
        issues.append("flower_coverage")
    if len(free_branches) != count - 2:
        issues.append("free_branch_count")

    per_branch: list[dict[str, object]] = []
    x0, x1 = p0.repeat_x_range
    for branch in branch_set.branches:
        curve = branch.curve
        points = curve.points(128)
        root_expected, tangent_expected = sample_polyline(p0.backbone_points, float(curve.mount_fraction))
        root_error = dist(curve.root, root_expected)
        tangent_error = angle_degrees(curve.entry_tangent, tangent_expected)
        audit = bend_audit(curve)
        branch_issues: list[str] = []
        if root_error > 0.5:
            branch_issues.append("root_off_backbone")
        if tangent_error > 5.0:
            branch_issues.append("root_tangent")
        if int(audit["bend_count"]) > 2:
            branch_issues.append("bend_count_over_2")
        if int(audit["curvature_sign_reversal_count"]) > 1:
            branch_issues.append("hidden_extra_reversal")
        if len(curve.cubics) > 2:
            branch_issues.append("cubic_segment_count_over_2")
        if len(curve.cubics) == 2:
            first, second = curve.cubics
            c0_error = dist(first.p3, second.p0)
            incoming = sub(first.p3, first.p2)
            outgoing = sub(second.p1, second.p0)
            c1_angle = angle_degrees(incoming, outgoing)
            c1_length = abs(math.hypot(*incoming) - math.hypot(*outgoing))
            if c0_error > 1e-6 or c1_angle > 1e-5 or c1_length > 1e-5:
                branch_issues.append("two_cubic_not_c1")
        else:
            c0_error = 0.0
            c1_angle = 0.0
            c1_length = 0.0
        half_width = curve.width * 0.5
        if any(
            point[0] < x0 + half_width
            or point[0] > x1 - half_width
            or point[1] < half_width
            or point[1] > p0.canvas_height - half_width
            for point in points
        ):
            branch_issues.append("out_of_bounds")
        if _self_intersects(points):
            branch_issues.append("self_intersection")
        tail = points[_prefix_after_distance(points, 18.0) :]
        backbone_clearance = min(
            (point_polyline_distance(point, p0.backbone_points) for point in tail),
            default=math.inf,
        )
        if backbone_clearance < (curve.width + 5.0) * 0.5 + 0.8:
            branch_issues.append("backbone_recontact")

        target_flower = None
        if branch.role.flower_id is not None:
            target_flower = next(flower for flower in p0.flowers if flower.flower_id == branch.role.flower_id)
        for flower in p0.flowers:
            values = [_ellipse_value(point, flower, 0.0) for point in points]
            if target_flower is flower:
                early = values[: max(1, int(len(values) * 0.92))]
                if any(value < 1.0 for value in early):
                    branch_issues.append(f"early_target_flower_intrusion:{flower.flower_id}")
                collar_error = abs(_ellipse_value(curve.tip, flower, 0.0) - 1.0)
                if collar_error > 2e-5:
                    branch_issues.append(f"flower_collar_error:{flower.flower_id}")
            elif any(value < 1.0 for value in values):
                branch_issues.append(f"flower_intrusion:{flower.flower_id}")

        length_error = abs(curve.length - curve.target_length)
        if length_error > 0.08:
            branch_issues.append("target_length_error")
        for issue in branch_issues:
            issues.append(f"{curve.curve_id}:{issue}")
        per_branch.append(
            {
                "curve_id": curve.curve_id,
                "role": branch.role.kind,
                "target_flower_id": branch.role.flower_id,
                "root_error": round(root_error, 8),
                "root_tangent_error_degrees": round(tangent_error, 8),
                "c0_error": round(c0_error, 8),
                "c1_tangent_error_degrees": round(c1_angle, 8),
                "c1_handle_delta": round(c1_length, 8),
                "backbone_clearance_after_root": round(backbone_clearance, 8),
                "target_length_error": round(length_error, 8),
                "bend_audit": audit,
                "issues": branch_issues,
            }
        )

    pair_clearances: list[dict[str, object]] = []
    for index, first in enumerate(branch_set.branches):
        for second in branch_set.branches[index + 1 :]:
            minimum = polyline_pair_distance(first.curve.points(96), second.curve.points(96))
            required = (first.curve.width + second.curve.width) * 0.5 + 1.5
            pair_clearances.append(
                {
                    "first": first.curve.curve_id,
                    "second": second.curve.curve_id,
                    "minimum": round(minimum, 8),
                    "required": round(required, 8),
                }
            )
            if minimum + 1e-6 < required:
                issues.append(f"branch_clearance:{first.curve.curve_id}:{second.curve.curve_id}")
    diagnostics["branches"] = per_branch
    diagnostics["branch_clearances"] = pair_clearances
    diagnostics["geometry_hash_after_check"] = branch_set.geometry_hash
    return {"valid": not issues, "issues": list(dict.fromkeys(issues)), "diagnostics": diagnostics}


def _prefix_after_distance(points: Sequence[Point], threshold: float) -> int:
    traversed = 0.0
    for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
        traversed += dist(start, end)
        if traversed >= threshold:
            return index
    return len(points)


def fairness_metrics(l0: BranchSet, l1: BranchSet) -> dict[str, object]:
    def symmetric(first: float, second: float) -> float:
        return abs(first - second) / max(0.5 * (abs(first) + abs(second)), 1e-12)

    l0_roles = [(b.role.role_id, b.curve.target_length, b.curve.width) for b in l0.branches]
    l1_roles = [(b.role.role_id, b.curve.target_length, b.curve.width) for b in l1.branches]
    length_delta = symmetric(l0.total_length, l1.total_length)
    ink_delta = symmetric(l0.vector_ink, l1.vector_ink)
    return {
        "branch_count_equal": len(l0.branches) == len(l1.branches),
        "role_target_lengths_and_widths_equal": l0_roles == l1_roles,
        "total_length_symmetric_delta": round(length_delta, 10),
        "vector_ink_symmetric_delta": round(ink_delta, 10),
        "thresholds": {"total_length": 0.002, "vector_ink": 0.002},
        "budget_match": l0_roles == l1_roles and length_delta <= 0.002 and ink_delta <= 0.002,
    }


def build_case(p0: StrippedP0, branch_count: int, seed: int) -> dict[str, object]:
    tokens = materialize_tokens(seed, branch_count)
    l0_plan = plan_l0_independent(p0, tokens)
    l1_plan = plan_l1_joint(p0, tokens)
    budget = shared_role_lengths(p0, l0_plan, l1_plan, tokens)
    l0 = compile_plan(p0, l0_plan, budget)
    l1 = compile_plan(p0, l1_plan, budget)
    validation_l0 = validate_branch_set(p0, l0)
    validation_l1 = validate_branch_set(p0, l1)
    return {
        "case_id": f"D{branch_count}",
        "branch_count": branch_count,
        "seed": seed,
        "tokens": [token.as_dict() for token in tokens],
        "token_digest": _digest([token.as_dict() for token in tokens]),
        "target_role_lengths": {key: round(value, 8) for key, value in budget.items()},
        "L0": {"plan": l0_plan, "branch_set": l0, "validation": validation_l0},
        "L1": {"plan": l1_plan, "branch_set": l1, "validation": validation_l1},
        "fairness": fairness_metrics(l0, l1),
    }


def serializable_case(case: dict[str, object]) -> dict[str, object]:
    return {
        "case_id": case["case_id"],
        "branch_count": case["branch_count"],
        "seed": case["seed"],
        "tokens": case["tokens"],
        "token_digest": case["token_digest"],
        "target_role_lengths": case["target_role_lengths"],
        "L0": {
            "plan": {
                "variant": case["L0"]["plan"].variant,
                "intents": [intent.as_dict() for intent in case["L0"]["plan"].intents],
                "trace": case["L0"]["plan"].trace,
            },
            "branch_set": case["L0"]["branch_set"].as_dict(),
            "validation": case["L0"]["validation"],
        },
        "L1": {
            "plan": {
                "variant": case["L1"]["plan"].variant,
                "intents": [intent.as_dict() for intent in case["L1"]["plan"].intents],
                "trace": case["L1"]["plan"].trace,
            },
            "branch_set": case["L1"]["branch_set"].as_dict(),
            "validation": case["L1"]["validation"],
        },
        "fairness": case["fairness"],
    }


def l0_token_intervention(
    p0: StrippedP0,
    tokens: Sequence[RawBranchToken],
    changed_index: int,
) -> tuple[IntentPlan, IntentPlan]:
    changed = list(tokens)
    old = changed[changed_index]
    changed[changed_index] = RawBranchToken(
        mount=(old.mount + 0.317) % 1.0,
        side=1.0 - old.side,
        length=old.length,
        bend=1.0 - old.bend,
        turn_1=(old.turn_1 + 0.271) % 1.0,
        turn_2=(old.turn_2 + 0.193) % 1.0,
        shape=1.0 - old.shape,
    )
    return plan_l0_independent(p0, tokens), plan_l0_independent(p0, changed)


def profile_intervention_proof(profile: dict[str, object]) -> dict[str, object]:
    original = strip_profile(profile)
    poisoned = strip_profile(ignored_field_intervention(profile))
    return {
        "original_digest": original.digest,
        "poisoned_ignored_fields_digest": poisoned.digest,
        "identical": original.as_dict() == poisoned.as_dict() and original.digest == poisoned.digest,
        "poisoned_fields": [
            "existing_guides",
            "growth_regions",
            "space_samples",
            "region_graph",
            "nodes",
            "segments",
            "qa",
        ],
    }


__all__ = [
    "ALLOWED_BRANCH_COUNTS",
    "BranchSet",
    "GEOMETRY_KERNEL_ID",
    "POLICY_ID",
    "StrippedP0",
    "bend_audit",
    "build_case",
    "fairness_metrics",
    "ignored_field_intervention",
    "l0_token_intervention",
    "materialize_tokens",
    "plan_l0_independent",
    "plan_l1_joint",
    "profile_intervention_proof",
    "serializable_case",
    "strip_profile",
    "validate_branch_set",
]
