#!/usr/bin/env python3
"""Rule-inheriting recursive BranchUnit V3A for ``proto_sw_1_3``.

V3A freezes the accepted J0c/v23 level-1 and level-2 plan and geometry, removes
its two historical tertiary fixtures, and adds 6..9 level-3 children.  New
children are expressed only in their actual parent's arclength/tangent frame.
The planner is deterministic and one-pass; validation is read-only.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import recursive_branch_unit as v1
import whole_local_branch as base
from l_core import (
    Point,
    angle_degrees,
    dist,
    point_polyline_distance,
    polyline_pair_distance,
    rotate,
    sample_polyline,
    sub,
)


PLAN_ID = "proto_sw_1_3_recursive_branch_units_v3a_rule_inheritance"
RULE_ID = "parent_relative_recursive_child_rule_v3a"
BASELINE_PLAN_ID = base.PLAN_ID
GEOMETRY_KERNEL_ID = "whole_local_bezier_plus_rule_inheriting_tertiary_v3a"
SAMPLER_ID = "recursive_branch_unit_path_hash_visible_state_v3a"
POLICY_ID = base.POLICY_ID
DEV_SEEDS = base.DEV_SEEDS

PRIMARY_WIDTH = base.PRIMARY_WIDTH
SECONDARY_WIDTH = base.SECONDARY_WIDTH
TERTIARY_WIDTH = base.TERTIARY_WIDTH
STROKE_LINECAP = base.STROKE_LINECAP
STROKE_LINEJOIN = base.STROKE_LINEJOIN

StrictP0 = base.StrictP0
PrimaryPlan = base.PrimaryPlan
ChildPlan = base.ChildPlan
HierarchyCurve = base.HierarchyCurve
RecursiveControls = v1.RecursiveControls
RecursiveNodeMeta = v1.RecursiveNodeMeta
EdgeSlot = v1.EdgeSlot
SampleRecord = v1.SampleRecord
strip_profile = base.strip_profile

FREE_UNITS = v1.FREE_UNITS
UNIT_ORDER = v1.UNIT_ORDER
UNIT_NUMBER = v1.UNIT_NUMBER
SECONDARY_BUDGETS = v1.SECONDARY_BUDGETS
CONTEXT_ORDER = (
    "primary_3_free",
    "primary_6_balance",
    "primary_2_free",
    "primary_7_free",
    "primary_1_free",
    "primary_4_flower_1",
    "primary_5_flower_2",
)

MOUNT_LOW = 0.28
MOUNT_HIGH = 0.72
TAIL_MIN_ABSOLUTE = 8.0
TAIL_MIN_RATIO = 0.20
ENTRY_RANGE = (34.0, 60.0)
CHORD_ANGLE_RANGE = (42.0, 78.0)
CHORD_RATIO_RANGE = (0.48, 0.72)
CHORD_ABSOLUTE_RANGE = (12.0, 34.0)
ACTUAL_LENGTH_RATIO_MAX = 0.82
SAGITTA_RANGE = (0.055, 0.20)


class PlanningFailure(RuntimeError):
    """The declared rule intersection is empty; it must not be widened."""


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _round_point(point: Point) -> list[float]:
    return [round(point[0], 8), round(point[1], 8)]


def _unit(vector: Point) -> Point:
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-12:
        raise ValueError("degenerate direction")
    return vector[0] / length, vector[1] / length


def _symmetric_relative_difference(first: float, second: float) -> float:
    return abs(first - second) / max(0.5 * (abs(first) + abs(second)), 1e-12)


@dataclass(frozen=True)
class UnitContextRecord:
    unit_id: str
    left_unit_id: str
    right_unit_id: str
    left_repeat_shift: float
    right_repeat_shift: float
    current_visible_envelope: tuple[float, float, float, float]
    left_visible_envelope: tuple[float, float, float, float]
    right_visible_envelope: tuple[float, float, float, float]
    eligible_parent_scores: tuple[tuple[str, float], ...]
    selected_parent_ids: tuple[str, ...]
    tertiary_ids: tuple[str, ...]
    side_scores: tuple[tuple[str, float, float], ...]
    context_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "left_unit_id": self.left_unit_id,
            "right_unit_id": self.right_unit_id,
            "left_repeat_shift": self.left_repeat_shift,
            "right_repeat_shift": self.right_repeat_shift,
            "current_visible_envelope": [round(value, 8) for value in self.current_visible_envelope],
            "left_visible_envelope": [round(value, 8) for value in self.left_visible_envelope],
            "right_visible_envelope": [round(value, 8) for value in self.right_visible_envelope],
            "eligible_parent_scores": [
                {"parent_id": parent_id, "score": round(score, 8)}
                for parent_id, score in self.eligible_parent_scores
            ],
            "selected_parent_ids": list(self.selected_parent_ids),
            "tertiary_ids": list(self.tertiary_ids),
            "side_scores": [
                {"curve_id": curve_id, "negative": round(negative, 8), "positive": round(positive, 8)}
                for curve_id, negative, positive in self.side_scores
            ],
            "context_digest": self.context_digest,
        }


@dataclass(frozen=True)
class RecursivePlan:
    plan_id: str
    seed: int
    controls: RecursiveControls
    primaries: tuple[PrimaryPlan, ...]
    descendants: tuple[ChildPlan, ...]
    node_metadata: tuple[RecursiveNodeMeta, ...]
    samples: tuple[SampleRecord, ...]
    contexts: tuple[UnitContextRecord, ...]
    edge_slots: tuple[EdgeSlot, ...]
    style_latents: dict[str, float]

    @property
    def metadata_by_id(self) -> dict[str, RecursiveNodeMeta]:
        return {row.curve_id: row for row in self.node_metadata}

    @property
    def digest(self) -> str:
        return _digest(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "recursive_branch_unit_plan_v3a",
            "plan_id": self.plan_id,
            "rule_id": RULE_ID,
            "baseline_plan_id": BASELINE_PLAN_ID,
            "sampler_id": SAMPLER_ID,
            "seed": self.seed,
            "controls": self.controls.as_dict(),
            "primaries": [row.as_dict() for row in self.primaries],
            "descendants": [row.as_dict() for row in self.descendants],
            "node_metadata": [row.as_dict() for row in self.node_metadata],
            "samples": [row.as_dict() for row in self.samples],
            "neighbor_context": [row.as_dict() for row in self.contexts],
            "edge_slots": [row.as_dict() for row in self.edge_slots],
            "style_latents": {
                key: round(value, 10) for key, value in sorted(self.style_latents.items())
            },
            "generation_policy": {
                "candidate_count": 1,
                "retry_count": 0,
                "resample_count": 0,
                "repair_count": 0,
                "validation_feedback_consumed": False,
            },
        }


@dataclass(frozen=True)
class RecursiveResult:
    plan: RecursivePlan
    curves: tuple[HierarchyCurve, ...]

    @property
    def by_id(self) -> dict[str, HierarchyCurve]:
        return {node.curve.curve_id: node for node in self.curves}

    @property
    def geometry_hash(self) -> str:
        return _digest(
            {
                "geometry_kernel_id": GEOMETRY_KERNEL_ID,
                "stroke_model": {"linecap": STROKE_LINECAP, "linejoin": STROKE_LINEJOIN},
                "curves": [
                    node.as_dict()
                    for node in sorted(self.curves, key=lambda item: item.curve.curve_id)
                ],
            }
        )

    def as_dict(self) -> dict[str, object]:
        levels = {
            level: sum(node.level == level for node in self.curves)
            for level in range(1, self.plan.controls.max_depth + 1)
        }
        return {
            "schema": "recursive_branch_unit_result_v3a",
            "geometry_kernel_id": GEOMETRY_KERNEL_ID,
            "rule_id": RULE_ID,
            "stroke_model": {
                "linecap": STROKE_LINECAP,
                "linejoin": STROKE_LINEJOIN,
                "width_alignment": "centered_on_curve",
            },
            "plan": self.plan.as_dict(),
            "topology": {
                "levels": {str(key): value for key, value in levels.items()},
                "maximum_depth": max((node.level for node in self.curves), default=0),
            },
            "curves": [
                node.as_dict()
                for node in sorted(self.curves, key=lambda item: item.curve.curve_id)
            ],
            "geometry_hash": self.geometry_hash,
        }


class _Sampler:
    def __init__(self, seed: int) -> None:
        self.seed = int(seed)
        self.records: list[SampleRecord] = []
        self._keys: set[str] = set()

    @staticmethod
    def _hash_u(text: str) -> float:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(2**64 - 1)

    def _record(self, key: str, low: float, high: float, u: float) -> float:
        if key in self._keys:
            raise ValueError(f"duplicate sample key: {key}")
        if not math.isfinite(low) or not math.isfinite(high) or not low < high:
            raise PlanningFailure(f"empty legal range for {key}: [{low}, {high}]")
        value = low + (high - low) * u
        self._keys.add(key)
        self.records.append(SampleRecord(key, low, high, u, value))
        return value

    def sample(self, path: str, parameter: str, low: float, high: float) -> float:
        key = f"{path}.{parameter}"
        u = self._hash_u(f"{SAMPLER_ID}|{self.seed}|{key}")
        return self._record(key, low, high, u)

    def sample_visible_state(
        self,
        path: str,
        parameter: str,
        low: float,
        high: float,
        *,
        states: int = 3,
    ) -> float:
        """Cycle seeds through separated strata so seed changes are visible."""

        if states < 2:
            raise ValueError("visible state sampling needs at least two states")
        key = f"{path}.{parameter}"
        offset_digest = hashlib.sha256(f"{SAMPLER_ID}|state|{key}".encode("utf-8")).digest()
        offset = int.from_bytes(offset_digest[:8], "big") % states
        state = (self.seed + offset) % states
        # Separated strata make adjacent development seeds visibly different;
        # path-addressed jitter keeps parameters continuous inside each legal
        # stratum instead of reducing the generator to three fixed templates.
        centers = tuple(0.05 + index * 0.90 / (states - 1) for index in range(states))
        jitter_u = self._hash_u(f"{SAMPLER_ID}|{self.seed}|jitter|{key}")
        u = max(0.04, min(0.96, centers[state] + 0.02 * (jitter_u - 0.5)))
        return self._record(key, low, high, u)

    def sample_count(self, path: str, low_count: int, high_count: int) -> int:
        states = high_count - low_count + 1
        key = f"{path}.tertiary_count_selector"
        offset_digest = hashlib.sha256(f"{SAMPLER_ID}|count|{key}".encode("utf-8")).digest()
        offset = int.from_bytes(offset_digest[:8], "big") % states
        state = (self.seed + offset) % states
        u = (state + 0.5) / states
        self._record(key, 0.0, 1.0, u)
        return low_count + state

    def record_mapping(
        self,
        path: str,
        parameter: str,
        low: float,
        high: float,
        u: float,
    ) -> float:
        """Record a deterministic mapping after choosing a legal parent component."""

        return self._record(f"{path}.{parameter}", low, high, u)

    def keys_with_prefix(self, prefix: str) -> tuple[str, ...]:
        return tuple(row.key for row in self.records if row.key.startswith(prefix))


def _validate_controls(controls: RecursiveControls) -> None:
    v1._validate_controls(controls)  # noqa: SLF001 - same bounded topology contract


def _curve_visible_envelope(nodes: Sequence[HierarchyCurve]) -> tuple[float, float, float, float]:
    return v1._curve_visible_envelope(nodes)  # noqa: SLF001 - shared evidence definition


def _cyclic_neighbours(unit_id: str) -> tuple[str, str]:
    index = UNIT_ORDER.index(unit_id)
    return UNIT_ORDER[(index - 1) % len(UNIT_ORDER)], UNIT_ORDER[(index + 1) % len(UNIT_ORDER)]


def _periodic_shift(unit_id: str, neighbour_id: str, repeat_width: float) -> float:
    current = UNIT_ORDER.index(unit_id)
    neighbour = UNIT_ORDER.index(neighbour_id)
    if current == 0 and neighbour == len(UNIT_ORDER) - 1:
        return -repeat_width
    if current == len(UNIT_ORDER) - 1 and neighbour == 0:
        return repeat_width
    return 0.0


def _shift_envelope(
    envelope: tuple[float, float, float, float], shift_x: float
) -> tuple[float, float, float, float]:
    return envelope[0] + shift_x, envelope[1], envelope[2] + shift_x, envelope[3]


def _baseline_parts(
    p0: StrictP0, seed: int
) -> tuple[base.GlobalPlan, tuple[PrimaryPlan, ...], tuple[ChildPlan, ...], base.HierarchyResult]:
    baseline_plan = base.plan_j0a(p0, int(seed))
    secondaries = tuple(row for row in baseline_plan.descendants if row.level == 2)
    partial_plan = base.GlobalPlan(
        baseline_plan.plan_id,
        baseline_plan.seed,
        baseline_plan.controls,
        baseline_plan.primaries,
        secondaries,
        baseline_plan.latent_summary,
    )
    partial_result = base.compile_plan(partial_plan, p0)
    return baseline_plan, baseline_plan.primaries, secondaries, partial_result


def _unit_nodes(result: base.HierarchyResult, unit_id: str) -> tuple[HierarchyCurve, ...]:
    return tuple(
        node
        for node in result.curves
        if node.curve.curve_id == unit_id or node.curve.parent_id == unit_id
    )


def _length_domain(parent_length: float) -> tuple[float, float] | None:
    low = max(CHORD_ABSOLUTE_RANGE[0], CHORD_RATIO_RANGE[0] * parent_length)
    # The implementation uses the conservative 0.68 subrange so the compiled
    # curve can still satisfy the 0.82 actual-arclength hierarchy gate.
    high = min(CHORD_ABSOLUTE_RANGE[1], 0.68 * parent_length)
    if not low < high:
        return None
    return low, high


def _mount_domain(parent_length: float) -> tuple[float, float] | None:
    tail = max(TAIL_MIN_ABSOLUTE, TAIL_MIN_RATIO * parent_length)
    high = min(MOUNT_HIGH, 1.0 - tail / max(parent_length, 1e-12))
    if not MOUNT_LOW < high:
        return None
    return MOUNT_LOW, high


def _point_at(root: Point, direction: Point, length: float) -> Point:
    return root[0] + direction[0] * length, root[1] + direction[1] * length


def _side_score(
    p0: StrictP0,
    root: Point,
    parent: HierarchyCurve,
    tangent: Point,
    sign: int,
    chord_angle: float,
    chord_length: float,
    obstacles: Sequence[HierarchyCurve],
    envelope_top: float,
    envelope_bottom: float,
) -> tuple[bool, float]:
    direction = _unit(rotate(tangent, sign * chord_angle))
    samples = [_point_at(root, direction, chord_length * fraction) for fraction in (0.35, 0.60, 0.82, 1.0)]
    half_width = 0.5 * TERTIARY_WIDTH
    x0, x1 = p0.repeat_x_range
    legal = all(
        x0 + half_width <= point[0] <= x1 - half_width
        and envelope_top + half_width <= point[1] <= envelope_bottom - half_width
        for point in samples
    )
    flower_values = [
        base._ellipse_value(point, flower)  # noqa: SLF001 - exact shared reserve model
        for point in samples
        for flower in p0.flowers
    ]
    if min(flower_values, default=math.inf) < 1.03:
        legal = False

    parent_points = parent.curve.points(192)
    parent_clearance = min(
        point_polyline_distance(point, parent_points) for point in samples[1:]
    )
    obstacle_clearance = math.inf
    repeat_width = p0.repeat_x_range[1] - p0.repeat_x_range[0]
    for obstacle in obstacles:
        if obstacle.curve.curve_id == parent.curve.curve_id:
            continue
        points = obstacle.curve.points(96)
        for shift in (-repeat_width, 0.0, repeat_width):
            shifted = tuple((point[0] + shift, point[1]) for point in points)
            obstacle_clearance = min(
                obstacle_clearance,
                *(point_polyline_distance(point, shifted) for point in samples[1:]),
            )
    boundary_clearance = min(
        min(point[0] - x0, x1 - point[0], point[1] - envelope_top, envelope_bottom - point[1])
        for point in samples
    )
    score = min(parent_clearance, obstacle_clearance, boundary_clearance)
    score += 0.08 * chord_length
    return legal, score


def _compiled_child_domain(
    p0: StrictP0,
    parent: HierarchyCurve,
    row: ChildPlan,
    obstacles: Sequence[HierarchyCurve],
    envelope_top: float,
    envelope_bottom: float,
) -> tuple[bool, float, tuple[str, ...], HierarchyCurve]:
    """Intersect one discrete turn component with the actual curve tube."""

    node = base._compile_child(parent, row)  # noqa: SLF001 - shared compiler
    curve = node.curve
    reasons: list[str] = []
    extrema = base._curve_exact_extrema(curve)  # noqa: SLF001
    half_width = 0.5 * curve.width
    if (
        extrema["left"] < p0.repeat_x_range[0] + half_width
        or extrema["right"] > p0.repeat_x_range[1] - half_width
        or extrema["top"] < envelope_top + half_width
        or extrema["bottom"] > envelope_bottom - half_width
    ):
        reasons.append("visible_envelope")
    for flower in p0.flowers:
        if any(
            base._ellipse_value(point, flower) < 1.0  # noqa: SLF001
            for point in curve.points(192)
        ):
            reasons.append(f"flower:{flower.flower_id}")
    sagitta = base._normalized_sagitta(curve)  # noqa: SLF001
    if not SAGITTA_RANGE[0] <= sagitta <= SAGITTA_RANGE[1]:
        reasons.append("curvature")
    bend = base.legacy.bend_audit(curve)
    if int(bend["bend_count"]) > 2 or int(bend["curvature_sign_reversal_count"]) > 1:
        reasons.append("bend")
    if base._self_intersects(curve.points(192)):  # noqa: SLF001
        reasons.append("self_intersection")

    minimum_clearance = math.inf
    repeat_width = p0.repeat_x_range[1] - p0.repeat_x_range[0]
    curve_points_48 = curve.points(48)
    curve_box = base._curve_exact_extrema(curve)  # noqa: SLF001
    for obstacle in obstacles:
        parent_child = obstacle.curve.curve_id == parent.curve.curve_id
        required = 0.5 * (curve.width + obstacle.curve.width) + 0.8
        obstacle_points = obstacle.curve.points(48)
        obstacle_box = base._curve_exact_extrema(obstacle.curve)  # noqa: SLF001
        shifts = (0.0,) if parent_child else (-repeat_width, 0.0, repeat_width)
        obstacle_minimum = math.inf
        for shift in shifts:
            shifted_box = {
                "left": obstacle_box["left"] + shift,
                "right": obstacle_box["right"] + shift,
                "top": obstacle_box["top"],
                "bottom": obstacle_box["bottom"],
            }
            bbox_dx = max(
                0.0,
                curve_box["left"] - shifted_box["right"],
                shifted_box["left"] - curve_box["right"],
            )
            bbox_dy = max(
                0.0,
                curve_box["top"] - shifted_box["bottom"],
                shifted_box["top"] - curve_box["bottom"],
            )
            bbox_distance = math.hypot(bbox_dx, bbox_dy)
            if not parent_child and bbox_distance >= required:
                minimum = bbox_distance
            else:
                shifted = tuple((point[0] + shift, point[1]) for point in obstacle_points)
                minimum = polyline_pair_distance(
                    curve_points_48,
                    shifted,
                    allowed_contact=curve.root if parent_child and shift == 0.0 else None,
                    contact_radius=min(8.0, 0.35 * curve.length) if parent_child else 0.0,
                )
            obstacle_minimum = min(obstacle_minimum, minimum)
        minimum_clearance = min(minimum_clearance, obstacle_minimum - required)
        if obstacle_minimum + 1e-6 < required:
            reasons.append(f"clearance:{obstacle.curve.curve_id}")
    return not reasons, minimum_clearance, tuple(reasons), node


def _candidate_parent_score(
    p0: StrictP0,
    parent: HierarchyCurve,
    obstacles: Sequence[HierarchyCurve],
    envelope_top: float,
    envelope_bottom: float,
) -> float | None:
    mount_domain = _mount_domain(parent.curve.length)
    length_domain = _length_domain(parent.curve.length)
    if mount_domain is None or length_domain is None:
        return None
    mount = 0.5 * (mount_domain[0] + mount_domain[1])
    root, tangent = sample_polyline(parent.curve.points(192), mount)
    chord = 0.5 * (length_domain[0] + length_domain[1])
    side_scores = [
        _side_score(
            p0,
            root,
            parent,
            tangent,
            sign,
            58.0,
            chord,
            obstacles,
            envelope_top,
            envelope_bottom,
        )
        for sign in (-1, 1)
    ]
    legal_scores = [score for legal, score in side_scores if legal]
    if not legal_scores:
        return None
    return max(legal_scores) + 0.05 * parent.curve.length


def _secondary_slot(curve_id: str) -> str:
    stem = curve_id.removeprefix("secondary_")
    return stem.split("_", 1)[0]


def _frontier_slots(
    primaries: Sequence[PrimaryPlan], secondaries: Sequence[ChildPlan]
) -> tuple[EdgeSlot, ...]:
    slots: list[EdgeSlot] = []
    for row in primaries:
        if row.target_boundary is not None and row.target_point is not None:
            slots.append(EdgeSlot(row.curve_id, row.target_boundary, row.target_point, row.curve_id))
    for row in secondaries:
        if row.target_boundary is not None and row.target_point is not None:
            slots.append(EdgeSlot(row.parent_id, row.target_boundary, row.target_point, row.curve_id))
    return tuple(sorted(slots, key=lambda item: item.unit_id))


def plan_recursive(
    p0: StrictP0,
    seed: int,
    controls: RecursiveControls = RecursiveControls(),
) -> RecursivePlan:
    """Plan V3A exactly once from the frozen baseline and the full child rule."""

    _validate_controls(controls)
    sampler = _Sampler(int(seed))
    tertiary_count = sampler.sample_count(
        "scene", controls.tertiary_min, controls.tertiary_max
    )
    baseline_plan, primaries, secondaries, baseline_result = _baseline_parts(p0, int(seed))
    baseline_nodes = baseline_result.by_id
    envelope_top = float(baseline_plan.latent_summary["envelope_top_y"])
    envelope_bottom = float(baseline_plan.latent_summary["envelope_bottom_y"])

    secondary_by_unit: dict[str, list[HierarchyCurve]] = {unit_id: [] for unit_id in UNIT_ORDER}
    secondary_rows_by_id = {row.curve_id: row for row in secondaries}
    for row in secondaries:
        secondary_by_unit[row.parent_id].append(baseline_nodes[row.curve_id])
    for rows in secondary_by_unit.values():
        rows.sort(key=lambda node: node.curve.curve_id)

    unit_envelopes = {
        unit_id: _curve_visible_envelope(_unit_nodes(baseline_result, unit_id))
        for unit_id in UNIT_ORDER
    }
    obstacles: list[HierarchyCurve] = list(baseline_result.curves)
    parent_scores: dict[str, dict[str, float]] = {unit_id: {} for unit_id in UNIT_ORDER}
    for unit_id in FREE_UNITS:
        scores: list[tuple[float, str]] = []
        for parent in secondary_by_unit[unit_id]:
            score = _candidate_parent_score(
                p0, parent, obstacles, envelope_top, envelope_bottom
            )
            if score is not None:
                # Seed affects a declared planning decision without overriding
                # the legal-space or hierarchy terms of the score.
                priority = sampler.sample(
                    f"unit.{UNIT_NUMBER[unit_id]}.parent.{parent.curve.curve_id}",
                    "context_priority",
                    0.0,
                    1.0,
                )
                combined = score + 1.5 * priority
                parent_scores[unit_id][parent.curve.curve_id] = combined
                scores.append((combined, parent.curve.curve_id))
        if not scores:
            raise PlanningFailure(f"{unit_id}: no legal level-2 parent for mandatory tertiary")

    extra_needed = tertiary_count - len(FREE_UNITS)
    extra_ranking: list[tuple[float, str]] = []
    for unit_id in FREE_UNITS:
        ranked_parents = sorted(
            parent_scores[unit_id].items(), key=lambda item: (-item[1], item[0])
        )
        if len(ranked_parents) < 2:
            continue
        priority = sampler.sample(
            f"unit.{UNIT_NUMBER[unit_id]}.extra", "allocation_priority", 0.0, 1.0
        )
        score = ranked_parents[1][1] + 2.0 * priority
        extra_ranking.append((score, unit_id))
    extra_ranking.sort(key=lambda item: (-item[0], item[1]))
    if extra_needed > len(extra_ranking):
        raise PlanningFailure(
            f"only {len(extra_ranking)} legal extra parents for {extra_needed} extra tertiaries"
        )
    extra_units = {unit_id for _, unit_id in extra_ranking[:extra_needed]}

    descendants: list[ChildPlan] = list(secondaries)
    metadata: list[RecursiveNodeMeta] = []
    for row in secondaries:
        unit_id = row.parent_id
        metadata.append(
            RecursiveNodeMeta(
                curve_id=row.curve_id,
                unit_id=unit_id,
                path=f"P{UNIT_NUMBER[unit_id]}/{_secondary_slot(row.curve_id).upper()}",
                level=2,
                parent_id=row.parent_id,
                edge_goal=row.target_boundary,
                terminal_role=(
                    "baseline_frontier" if row.target_boundary is not None else row.growth_role
                ),
                is_edge_heir=row.target_boundary is not None,
                sample_keys=(),
            )
        )

    context_records: list[UnitContextRecord] = []
    planned_tertiaries: dict[str, list[HierarchyCurve]] = {unit_id: [] for unit_id in UNIT_ORDER}
    repeat_width = p0.repeat_x_range[1] - p0.repeat_x_range[0]
    for unit_id in CONTEXT_ORDER:
        left_id, right_id = _cyclic_neighbours(unit_id)
        left_shift = _periodic_shift(unit_id, left_id, repeat_width)
        right_shift = _periodic_shift(unit_id, right_id, repeat_width)
        selected: list[str] = []
        branch_budget = 0 if unit_id not in FREE_UNITS else 1 + int(unit_id in extra_units)
        available_parent_ids = sorted(parent_scores[unit_id])
        tertiary_ids: list[str] = []
        side_rows: list[tuple[str, float, float]] = []
        for rank in range(1, branch_budget + 1):
            path = f"unit.{UNIT_NUMBER[unit_id]}.tertiary.{rank}"
            # Sample parent-independent tokens first.  Each token is mapped
            # into every surviving parent component, and the joint
            # parent/side domain is selected once; this is not fallback retry.
            mount_u = sampler.sample_visible_state(path, "mount_fraction_u", 0.0, 1.0)
            length_u = sampler.sample_visible_state(path, "chord_length_u", 0.0, 1.0)
            chord_angle = sampler.sample_visible_state(
                path, "chord_opening_degrees", *CHORD_ANGLE_RANGE
            )
            entry_opening = sampler.sample_visible_state(
                path, "entry_opening_degrees", *ENTRY_RANGE
            )
            # This joint box was enumerated across every visible-state corner,
            # both bend modes, and both turn signs.  The shared compiler then
            # stays inside the declared 0.055..0.20 sagitta band by construction.
            handle_ratio = sampler.sample_visible_state(path, "handle_ratio", 0.31, 0.34)
            exit_release = sampler.sample_visible_state(
                path, "exit_release_degrees", 19.0, 26.0
            )
            bend_selector = sampler.sample(path, "bend_mode_selector", 0.0, 1.0)
            bend_mode = "C" if bend_selector < 0.72 else "S"
            component_selector = sampler.sample(path, "turn_side_selector", 0.0, 1.0)

            component_domain: list[
                tuple[
                    float,
                    str,
                    int,
                    ChildPlan,
                    HierarchyCurve,
                    tuple[float, float],
                    tuple[float, float],
                ]
            ] = []
            component_reasons: list[str] = []
            evidence_by_parent: dict[
                str, dict[int, tuple[bool, float, tuple[str, ...]]]
            ] = {}
            for parent_id in available_parent_ids:
                parent = baseline_nodes[parent_id]
                mount_domain = _mount_domain(parent.curve.length)
                length_domain = _length_domain(parent.curve.length)
                if mount_domain is None or length_domain is None:
                    component_reasons.append(f"{parent_id}:empty_mount_or_length")
                    continue
                mount = mount_domain[0] + (mount_domain[1] - mount_domain[0]) * mount_u
                chord_length = length_domain[0] + (length_domain[1] - length_domain[0]) * length_u
                root, tangent = sample_polyline(parent.curve.points(192), mount)
                curve_id = (
                    f"tertiary_{UNIT_NUMBER[unit_id]}_"
                    f"{_secondary_slot(parent_id)}_r{rank}"
                )
                evidence_by_parent[parent_id] = {}
                for turn_sign in (-1, 1):
                    chord_legal, chord_score = _side_score(
                        p0,
                        root,
                        parent,
                        tangent,
                        turn_sign,
                        chord_angle,
                        chord_length,
                        obstacles,
                        envelope_top,
                        envelope_bottom,
                    )
                    candidate_row = ChildPlan(
                        curve_id=curve_id,
                        parent_id=parent_id,
                        growth_role="lateral",
                        target_boundary=None,
                        target_point=None,
                        terminal_tangent=None,
                        travel_direction=_unit(rotate(tangent, turn_sign * chord_angle)),
                        level=3,
                        mount_fraction=mount,
                        turn_sign=turn_sign,
                        opening_angle_degrees=chord_angle,
                        chord_length=chord_length,
                        handle_ratio=handle_ratio,
                        entry_opening_degrees=entry_opening,
                        exit_release_degrees=exit_release,
                        bend_mode=bend_mode,
                    )
                    curve_legal, curve_score, curve_reasons, candidate_node = (
                        _compiled_child_domain(
                            p0,
                            parent,
                            candidate_row,
                            obstacles,
                            envelope_top,
                            envelope_bottom,
                        )
                    )
                    reasons = (
                        (() if chord_legal else ("chord_envelope_or_flower",))
                        + curve_reasons
                    )
                    legal = chord_legal and curve_legal
                    score = (
                        min(chord_score, curve_score)
                        + 0.10 * parent_scores[unit_id][parent_id]
                    )
                    evidence_by_parent[parent_id][turn_sign] = (legal, score, reasons)
                    if legal:
                        component_domain.append(
                            (
                                score,
                                parent_id,
                                turn_sign,
                                candidate_row,
                                candidate_node,
                                mount_domain,
                                length_domain,
                            )
                        )
                    else:
                        component_reasons.append(
                            f"{parent_id}:{turn_sign}:" + ",".join(reasons)
                        )
            if not component_domain:
                raise PlanningFailure(
                    f"{path}: empty joint parent/side domain; "
                    + "; ".join(component_reasons)
                )
            component_domain.sort(key=lambda item: (-item[0], item[1], item[2]))
            best_score = component_domain[0][0]
            near_best = [item for item in component_domain if best_score - item[0] < 2.0]
            if len(near_best) == 1:
                chosen = near_best[0]
            else:
                chosen_index = min(
                    int(component_selector * len(near_best)), len(near_best) - 1
                )
                chosen = near_best[chosen_index]
            _, parent_id, turn_sign, row, node, mount_domain, length_domain = chosen
            sampler.record_mapping(
                path, "mount_fraction", mount_domain[0], mount_domain[1], mount_u
            )
            sampler.record_mapping(
                path, "chord_length", length_domain[0], length_domain[1], length_u
            )
            selected.append(parent_id)
            available_parent_ids.remove(parent_id)
            descendants.append(row)
            obstacles.append(node)
            planned_tertiaries[unit_id].append(node)
            tertiary_ids.append(row.curve_id)
            chosen_evidence = evidence_by_parent[parent_id]
            side_rows.append(
                (row.curve_id, chosen_evidence[-1][1], chosen_evidence[1][1])
            )
            metadata.append(
                RecursiveNodeMeta(
                    curve_id=row.curve_id,
                    unit_id=unit_id,
                    path=f"P{UNIT_NUMBER[unit_id]}/T{rank}",
                    level=3,
                    parent_id=parent_id,
                    edge_goal=None,
                    terminal_role=("recursive_mandatory" if rank == 1 else "recursive_extra"),
                    is_edge_heir=False,
                    sample_keys=sampler.keys_with_prefix(path + "."),
                )
            )

        context_payload = {
            "unit_id": unit_id,
            "left_unit_id": left_id,
            "right_unit_id": right_id,
            "left_repeat_shift": left_shift,
            "right_repeat_shift": right_shift,
            "selected_parent_ids": selected,
            "tertiary_ids": tertiary_ids,
            "side_scores": side_rows,
        }
        context_records.append(
            UnitContextRecord(
                unit_id=unit_id,
                left_unit_id=left_id,
                right_unit_id=right_id,
                left_repeat_shift=left_shift,
                right_repeat_shift=right_shift,
                current_visible_envelope=unit_envelopes[unit_id],
                left_visible_envelope=_shift_envelope(unit_envelopes[left_id], left_shift),
                right_visible_envelope=_shift_envelope(unit_envelopes[right_id], right_shift),
                eligible_parent_scores=tuple(
                    sorted(parent_scores[unit_id].items())
                ),
                selected_parent_ids=tuple(selected),
                tertiary_ids=tuple(tertiary_ids),
                side_scores=tuple(side_rows),
                context_digest=_digest(context_payload),
            )
        )

    if sum(len(rows) for rows in planned_tertiaries.values()) != tertiary_count:
        raise AssertionError("tertiary allocation did not realize the sampled count")
    return RecursivePlan(
        plan_id=PLAN_ID,
        seed=int(seed),
        controls=controls,
        primaries=tuple(primaries),
        descendants=tuple(sorted(descendants, key=lambda row: (row.level, row.curve_id))),
        node_metadata=tuple(sorted(metadata, key=lambda row: row.curve_id)),
        samples=tuple(sampler.records),
        contexts=tuple(context_records),
        edge_slots=_frontier_slots(primaries, secondaries),
        style_latents={
            "tertiary_count": float(tertiary_count),
            "envelope_top_y": envelope_top,
            "envelope_bottom_y": envelope_bottom,
            "baseline_plan_digest_prefix": float(int(baseline_plan.digest[:12], 16)),
        },
    )


def compile_plan(
    plan: RecursivePlan,
    p0: StrictP0,
    traversal_order: Sequence[str] | None = None,
) -> RecursiveResult:
    primary_by_id = {row.curve_id: row for row in plan.primaries}
    order = tuple(traversal_order or [row.curve_id for row in plan.primaries])
    if set(order) != set(primary_by_id) or len(order) != len(primary_by_id):
        raise ValueError("traversal_order must contain every primary exactly once")
    generated: dict[str, HierarchyCurve] = {
        curve_id: base._compile_primary(p0, primary_by_id[curve_id])  # noqa: SLF001
        for curve_id in order
    }
    for level in (2, 3):
        pending = sorted(
            (row for row in plan.descendants if row.level == level),
            key=lambda row: row.curve_id,
        )
        for row in pending:
            parent = generated.get(row.parent_id)
            if parent is None:
                raise ValueError(f"missing parent {row.parent_id} for {row.curve_id}")
            generated[row.curve_id] = base._compile_child(parent, row)  # noqa: SLF001
    expected_ids = {row.curve_id for row in plan.primaries} | {
        row.curve_id for row in plan.descendants
    }
    if set(generated) != expected_ids:
        raise ValueError("compiled curve set differs from plan")
    return RecursiveResult(
        plan,
        tuple(sorted(generated.values(), key=lambda node: node.curve.curve_id)),
    )


def build_recursive(
    p0: StrictP0,
    seed: int,
    controls: RecursiveControls = RecursiveControls(),
    traversal_order: Sequence[str] | None = None,
) -> RecursiveResult:
    return compile_plan(plan_recursive(p0, seed, controls), p0, traversal_order)


def _level_geometry_hash(result: object, levels: set[int]) -> str:
    curves = getattr(result, "curves")
    return _digest(
        [
            node.as_dict()
            for node in sorted(curves, key=lambda item: item.curve.curve_id)
            if node.level in levels
        ]
    )


def _root_unit(curve_id: str, child_rows: Mapping[str, ChildPlan]) -> str:
    current = curve_id
    seen: set[str] = set()
    while current not in UNIT_ORDER:
        if current in seen or current not in child_rows:
            raise ValueError(f"cannot resolve root unit for {curve_id}")
        seen.add(current)
        current = child_rows[current].parent_id
    return current


def validate_result(p0: StrictP0, result: RecursiveResult) -> dict[str, object]:
    """Check the V3A contract without mutation, retry, or repair."""

    before = result.geometry_hash
    issues: list[str] = []
    plan = result.plan
    nodes = result.by_id
    primary_rows = {row.curve_id: row for row in plan.primaries}
    child_rows = {row.curve_id: row for row in plan.descendants}
    secondary_rows = [row for row in plan.descendants if row.level == 2]
    tertiary_rows = [row for row in plan.descendants if row.level == 3]
    level_counts = {
        level: sum(node.level == level for node in result.curves) for level in (1, 2, 3)
    }
    if level_counts != {1: 7, 2: 12, 3: len(tertiary_rows)}:
        issues.append("topology_level_count_mismatch")
    if not plan.controls.tertiary_min <= len(tertiary_rows) <= plan.controls.tertiary_max:
        issues.append("tertiary_count_outside_6_9")
    if set(nodes) != set(primary_rows) | set(child_rows):
        issues.append("plan_geometry_id_mismatch")

    baseline_result = base.build_j0a(p0, plan.seed)
    baseline_validation = base.validate_result(p0, baseline_result)
    baseline_secondaries = tuple(
        row for row in baseline_result.plan.descendants if row.level == 2
    )
    baseline_plan_equal = (
        tuple(plan.primaries) == tuple(baseline_result.plan.primaries)
        and tuple(secondary_rows) == baseline_secondaries
    )
    baseline_geometry_equal = _level_geometry_hash(result, {1, 2}) == _level_geometry_hash(
        baseline_result, {1, 2}
    )
    if not baseline_validation["valid"]:
        issues.append("frozen_baseline_is_not_structurally_valid")
    if not baseline_plan_equal:
        issues.append("frozen_level_1_or_2_plan_changed")
    if not baseline_geometry_equal:
        issues.append("frozen_level_1_or_2_geometry_changed")

    metadata = plan.metadata_by_id
    if set(metadata) != set(child_rows):
        issues.append("descendant_metadata_mismatch")
    units_by_tertiary: dict[str, str] = {}
    tertiary_per_unit = {unit_id: 0 for unit_id in UNIT_ORDER}
    tertiary_per_secondary = {row.curve_id: 0 for row in secondary_rows}
    for row in tertiary_rows:
        try:
            unit_id = _root_unit(row.curve_id, child_rows)
        except ValueError as error:
            issues.append(str(error))
            continue
        units_by_tertiary[row.curve_id] = unit_id
        tertiary_per_unit[unit_id] += 1
        if row.parent_id in tertiary_per_secondary:
            tertiary_per_secondary[row.parent_id] += 1
        else:
            issues.append(f"{row.curve_id}:parent_is_not_level_2")
        if unit_id not in FREE_UNITS:
            issues.append(f"{row.curve_id}:tertiary_in_flower_unit")
        meta = metadata.get(row.curve_id)
        if meta is None or meta.unit_id != unit_id or meta.parent_id != row.parent_id:
            issues.append(f"{row.curve_id}:metadata_parent_or_unit_mismatch")
    if any(tertiary_per_unit[unit_id] < 1 for unit_id in FREE_UNITS):
        issues.append("free_unit_missing_tertiary")
    if any(count > 2 for count in tertiary_per_unit.values()):
        issues.append("tertiary_per_unit_over_2")
    if any(count > 1 for count in tertiary_per_secondary.values()):
        issues.append("tertiary_per_secondary_over_1")

    sample_by_key = {row.key: row for row in plan.samples}
    if len(sample_by_key) != len(plan.samples):
        issues.append("duplicate_sample_keys")
    for sample in plan.samples:
        expected = sample.low + (sample.high - sample.low) * sample.u
        if not sample.low < sample.high or not 0.0 <= sample.u <= 1.0:
            issues.append(f"{sample.key}:invalid_sample_domain")
        if abs(sample.value - expected) > 1e-10:
            issues.append(f"{sample.key}:sample_mapping_error")
    if any(
        key not in sample_by_key
        for meta in plan.node_metadata
        for key in meta.sample_keys
    ):
        issues.append("metadata_references_missing_sample")

    if tuple(context.unit_id for context in plan.contexts) != CONTEXT_ORDER:
        issues.append("context_order_mismatch")
    repeat_width = p0.repeat_x_range[1] - p0.repeat_x_range[0]
    for context in plan.contexts:
        left, right = _cyclic_neighbours(context.unit_id)
        if (context.left_unit_id, context.right_unit_id) != (left, right):
            issues.append(f"{context.unit_id}:cyclic_neighbour_mismatch")
        if context.left_repeat_shift != _periodic_shift(context.unit_id, left, repeat_width):
            issues.append(f"{context.unit_id}:left_repeat_shift_mismatch")
        if context.right_repeat_shift != _periodic_shift(context.unit_id, right, repeat_width):
            issues.append(f"{context.unit_id}:right_repeat_shift_mismatch")
        if not context.context_digest:
            issues.append(f"{context.unit_id}:missing_context_digest")

    expected_frontier_units = set(FREE_UNITS)
    actual_frontier_units = {slot.unit_id for slot in plan.edge_slots}
    if len(plan.edge_slots) != 5 or actual_frontier_units != expected_frontier_units:
        issues.append("baseline_frontier_unit_coverage_changed")
    if {slot.side for slot in plan.edge_slots} - {"top_frontier", "bottom_frontier"}:
        issues.append("non_vertical_frontier_present")

    per_tertiary: list[dict[str, object]] = []
    for row in tertiary_rows:
        node = nodes[row.curve_id]
        parent = nodes[row.parent_id]
        root, parent_tangent = sample_polyline(parent.curve.points(192), row.mount_fraction)
        root_error = dist(root, node.curve.root)
        entry = angle_degrees(node.curve.entry_tangent, parent_tangent)
        chord_direction = angle_degrees(sub(node.curve.tip, node.curve.root), parent_tangent)
        chord = dist(node.curve.root, node.curve.tip)
        chord_ratio = chord / max(parent.curve.length, 1e-12)
        actual_ratio = node.curve.length / max(parent.curve.length, 1e-12)
        tail = (1.0 - row.mount_fraction) * parent.curve.length
        sagitta = base._normalized_sagitta(node.curve)  # noqa: SLF001
        bend = base.legacy.bend_audit(node.curve)
        branch_issues: list[str] = []
        if root_error > 0.5:
            branch_issues.append("root_off_parent")
        if not MOUNT_LOW - 1e-8 <= row.mount_fraction <= MOUNT_HIGH + 1e-8:
            branch_issues.append("mount_outside_0_28_0_72")
        if tail + 1e-8 < max(TAIL_MIN_ABSOLUTE, TAIL_MIN_RATIO * parent.curve.length):
            branch_issues.append("parent_tail_reserve_too_short")
        if not ENTRY_RANGE[0] - 0.5 <= entry <= ENTRY_RANGE[1] + 0.5:
            branch_issues.append("entry_opening_outside_34_60")
        if abs(entry - row.entry_opening_degrees) > 0.5:
            branch_issues.append("entry_opening_differs_from_plan")
        if not CHORD_ANGLE_RANGE[0] - 0.5 <= chord_direction <= CHORD_ANGLE_RANGE[1] + 0.5:
            branch_issues.append("chord_opening_outside_42_78")
        if abs(chord_direction - row.opening_angle_degrees) > 0.5:
            branch_issues.append("chord_opening_differs_from_plan")
        if not CHORD_RATIO_RANGE[0] - 1e-8 <= chord_ratio <= CHORD_RATIO_RANGE[1] + 1e-8:
            branch_issues.append("chord_parent_ratio_outside_0_48_0_72")
        if not CHORD_ABSOLUTE_RANGE[0] - 1e-8 <= chord <= CHORD_ABSOLUTE_RANGE[1] + 1e-8:
            branch_issues.append("chord_absolute_length_outside_12_34")
        if actual_ratio >= ACTUAL_LENGTH_RATIO_MAX:
            branch_issues.append("actual_child_not_subordinate")
        if not SAGITTA_RANGE[0] <= sagitta <= SAGITTA_RANGE[1]:
            branch_issues.append("normalized_sagitta_outside_0_055_0_20")
        if len(node.curve.cubics) > 2:
            branch_issues.append("cubic_piece_count_over_2")
        if int(bend["bend_count"]) > 2:
            branch_issues.append("bend_count_over_2")
        if int(bend["curvature_sign_reversal_count"]) > 1:
            branch_issues.append("curvature_reversal_count_over_1")
        if base._self_intersects(node.curve.points(192)):  # noqa: SLF001
            branch_issues.append("self_intersection")

        extrema = base._curve_exact_extrema(node.curve)  # noqa: SLF001
        half_width = 0.5 * node.curve.width
        if (
            extrema["left"] < p0.repeat_x_range[0] + half_width
            or extrema["right"] > p0.repeat_x_range[1] - half_width
            or extrema["top"] < plan.style_latents["envelope_top_y"] + half_width
            or extrema["bottom"] > plan.style_latents["envelope_bottom_y"] - half_width
        ):
            branch_issues.append("outside_shared_visible_envelope")
        for flower in p0.flowers:
            if any(
                base._ellipse_value(point, flower) < 1.0  # noqa: SLF001
                for point in node.curve.points(192)
            ):
                branch_issues.append(f"flower_intrusion:{flower.flower_id}")

        points = node.curve.points(192)
        contact_zone = min(8.0, 0.35 * node.curve.length)
        cumulative = 0.0
        tail_index = 1
        for index, (first, second) in enumerate(zip(points, points[1:]), start=1):
            cumulative += dist(first, second)
            if cumulative >= contact_zone:
                tail_index = index
                break
        parent_clearance = min(
            (
                point_polyline_distance(point, parent.curve.points(192))
                for point in points[tail_index:]
            ),
            default=math.inf,
        )
        required_parent_clearance = 0.5 * (node.curve.width + parent.curve.width) + 0.8
        if parent_clearance < required_parent_clearance:
            branch_issues.append("parent_recontact")
        for issue in branch_issues:
            issues.append(f"{row.curve_id}:{issue}")
        per_tertiary.append(
            {
                "curve_id": row.curve_id,
                "unit_id": units_by_tertiary.get(row.curve_id),
                "parent_id": row.parent_id,
                "mount_fraction": round(row.mount_fraction, 8),
                "tail_reserve": round(tail, 8),
                "entry_opening_degrees": round(entry, 8),
                "chord_opening_degrees": round(chord_direction, 8),
                "chord_length": round(chord, 8),
                "chord_parent_ratio": round(chord_ratio, 8),
                "actual_parent_ratio": round(actual_ratio, 8),
                "normalized_sagitta": round(sagitta, 8),
                "bend_count": int(bend["bend_count"]),
                "curvature_sign_reversal_count": int(
                    bend["curvature_sign_reversal_count"]
                ),
                "parent_clearance": round(parent_clearance, 8),
                "required_parent_clearance": round(required_parent_clearance, 8),
                "issues": branch_issues,
            }
        )

    tertiary_ids = {row.curve_id for row in tertiary_rows}
    pair_clearances: list[dict[str, object]] = []
    all_nodes = list(result.curves)
    for first_index, first in enumerate(all_nodes):
        for second in all_nodes[first_index + 1 :]:
            if first.curve.curve_id not in tertiary_ids and second.curve.curve_id not in tertiary_ids:
                continue
            parent_child = (
                first.curve.parent_id == second.curve.curve_id
                or second.curve.parent_id == first.curve.curve_id
            )
            child = first if first.level > second.level else second
            allowed_contact = child.curve.root if parent_child else None
            contact_radius = min(8.0, 0.35 * child.curve.length) if parent_child else 0.0
            minimum = polyline_pair_distance(
                first.curve.points(96),
                second.curve.points(96),
                allowed_contact=allowed_contact,
                contact_radius=contact_radius,
            )
            required = 0.5 * (first.curve.width + second.curve.width) + 0.8
            if minimum + 1e-6 < required:
                issues.append(
                    f"curve_clearance:{first.curve.curve_id}:{second.curve.curve_id}"
                )
            pair_clearances.append(
                {
                    "first": first.curve.curve_id,
                    "second": second.curve.curve_id,
                    "minimum": round(minimum, 8),
                    "required": round(required, 8),
                    "registered_parent_child": parent_child,
                }
            )

    after = result.geometry_hash
    if before != after:
        issues.append("validation_mutated_geometry")
    unique_issues = list(dict.fromkeys(issues))
    return {
        "valid": not unique_issues,
        "issues": unique_issues,
        "diagnostics": {
            "check_only": True,
            "geometry_hash_before_check": before,
            "geometry_hash_after_check": after,
            "geometry_unchanged": before == after,
            "baseline_plan_id": BASELINE_PLAN_ID,
            "baseline_validation_valid": baseline_validation["valid"],
            "baseline_plan_equal_levels_1_2": baseline_plan_equal,
            "baseline_geometry_equal_levels_1_2": baseline_geometry_equal,
            "topology_counts": {str(key): value for key, value in level_counts.items()},
            "tertiary_per_unit": tertiary_per_unit,
            "tertiary_per_secondary": tertiary_per_secondary,
            "per_tertiary": per_tertiary,
            "pair_clearances": pair_clearances,
            "generation_policy": plan.as_dict()["generation_policy"],
        },
    }


def _mandatory_rows(result: RecursiveResult) -> dict[str, ChildPlan]:
    rows = {row.curve_id: row for row in result.plan.descendants}
    return {
        meta.unit_id: rows[meta.curve_id]
        for meta in result.plan.node_metadata
        if meta.level == 3 and meta.terminal_role == "recursive_mandatory"
    }


def seed_variation_proof(
    p0: StrictP0,
    seeds: Sequence[int] = DEV_SEEDS,
) -> dict[str, object]:
    seed_tuple = tuple(int(seed) for seed in seeds)
    if len(seed_tuple) < 2:
        raise ValueError("seed variation proof requires at least two seeds")
    results = {seed: build_recursive(p0, seed) for seed in seed_tuple}
    replays = {seed: build_recursive(p0, seed) for seed in seed_tuple}
    validations = {seed: validate_result(p0, result) for seed, result in results.items()}
    replay_by_seed = {
        str(seed): (
            results[seed].plan == replays[seed].plan
            and results[seed].plan.digest == replays[seed].plan.digest
            and results[seed].geometry_hash == replays[seed].geometry_hash
        )
        for seed in seed_tuple
    }
    mandatory = {seed: _mandatory_rows(result) for seed, result in results.items()}
    pairwise: list[dict[str, object]] = []
    pairwise_passes: list[bool] = []
    for first_index, first_seed in enumerate(seed_tuple):
        for second_seed in seed_tuple[first_index + 1 :]:
            units = sorted(set(mandatory[first_seed]) & set(mandatory[second_seed]))
            mount_delta = {
                unit_id: abs(
                    mandatory[first_seed][unit_id].mount_fraction
                    - mandatory[second_seed][unit_id].mount_fraction
                )
                for unit_id in units
            }
            direction_delta = {
                unit_id: abs(
                    mandatory[first_seed][unit_id].opening_angle_degrees
                    - mandatory[second_seed][unit_id].opening_angle_degrees
                )
                for unit_id in units
            }
            length_delta = {
                unit_id: _symmetric_relative_difference(
                    mandatory[first_seed][unit_id].chord_length,
                    mandatory[second_seed][unit_id].chord_length,
                )
                for unit_id in units
            }
            mount_count = sum(value >= 0.10 for value in mount_delta.values())
            direction_count = sum(value >= 10.0 for value in direction_delta.values())
            length_count = sum(value >= 0.12 for value in length_delta.values())
            passes = len(units) == 5 and mount_count >= 4 and direction_count >= 3 and length_count >= 3
            pairwise_passes.append(passes)
            pairwise.append(
                {
                    "first_seed": first_seed,
                    "second_seed": second_seed,
                    "mandatory_units": units,
                    "mount_delta": {key: round(value, 8) for key, value in mount_delta.items()},
                    "direction_delta_degrees": {
                        key: round(value, 8) for key, value in direction_delta.items()
                    },
                    "length_symmetric_relative_delta": {
                        key: round(value, 8) for key, value in length_delta.items()
                    },
                    "mount_count_ge_0_10": mount_count,
                    "direction_count_ge_10deg": direction_count,
                    "length_count_ge_0_12": length_count,
                    "passes": passes,
                }
            )
    return {
        "seeds": list(seed_tuple),
        "replay_by_seed": replay_by_seed,
        "geometry_hashes": {
            str(seed): results[seed].geometry_hash for seed in seed_tuple
        },
        "plan_digests": {str(seed): results[seed].plan.digest for seed in seed_tuple},
        "tertiary_counts": {
            str(seed): sum(node.level == 3 for node in results[seed].curves)
            for seed in seed_tuple
        },
        "validation_passes": {
            str(seed): validations[seed]["valid"] for seed in seed_tuple
        },
        "pairwise": pairwise,
        "passes": (
            all(replay_by_seed.values())
            and len({result.plan.digest for result in results.values()}) == len(seed_tuple)
            and len({result.geometry_hash for result in results.values()}) == len(seed_tuple)
            and all(pairwise_passes)
            and all(validation["valid"] for validation in validations.values())
        ),
    }


def _default_profile_path() -> Path:
    return v1._default_profile_path()  # noqa: SLF001


__all__ = [
    "BASELINE_PLAN_ID",
    "CONTEXT_ORDER",
    "DEV_SEEDS",
    "FREE_UNITS",
    "GEOMETRY_KERNEL_ID",
    "PLAN_ID",
    "POLICY_ID",
    "PlanningFailure",
    "RECURSIVE_RULE_ID",
    "RULE_ID",
    "RecursiveControls",
    "RecursivePlan",
    "RecursiveResult",
    "StrictP0",
    "UNIT_ORDER",
    "build_recursive",
    "compile_plan",
    "plan_recursive",
    "seed_variation_proof",
    "strip_profile",
    "validate_result",
]

# Alias retained for test/readability symmetry.
RECURSIVE_RULE_ID = RULE_ID
