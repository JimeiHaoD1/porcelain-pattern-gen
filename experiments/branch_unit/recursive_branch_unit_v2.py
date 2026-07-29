#!/usr/bin/env python3
"""Second bounded recursive BranchUnit experiment for ``proto_sw_1_3``.

V2 preserves the failed V1 planner and changes only the diagnosed causal chain:

* an edge goal is assigned before descendants are grown;
* the far secondary in every free Unit becomes an interior edge carrier;
* its tertiary child performs only the final edge approach and glide;
* extra tertiary branches are limited to free Units and remain subordinate;
* each Unit consumes the visible envelopes of both cyclic neighbours.

Planning is still one-pass and path-addressed.  Validation is check-only.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Sequence

import recursive_branch_unit as v1
import whole_local_branch as base
from l_core import Point, angle_degrees, dist, rotate, sample_polyline, sub


PLAN_ID = "proto_sw_1_3_recursive_branch_units_v2_joint_edge_chain"
GEOMETRY_KERNEL_ID = v1.GEOMETRY_KERNEL_ID
SAMPLER_ID = v1.SAMPLER_ID
POLICY_ID = v1.POLICY_ID
DEV_SEEDS = v1.DEV_SEEDS

PRIMARY_WIDTH = v1.PRIMARY_WIDTH
SECONDARY_WIDTH = v1.SECONDARY_WIDTH
TERTIARY_WIDTH = v1.TERTIARY_WIDTH
STROKE_LINECAP = v1.STROKE_LINECAP
STROKE_LINEJOIN = v1.STROKE_LINEJOIN

StrictP0 = v1.StrictP0
PrimaryPlan = v1.PrimaryPlan
ChildPlan = v1.ChildPlan
HierarchyCurve = v1.HierarchyCurve
RecursiveControls = v1.RecursiveControls
RecursiveNodeMeta = v1.RecursiveNodeMeta
RecursivePlan = v1.RecursivePlan
RecursiveResult = v1.RecursiveResult
EdgeSlot = v1.EdgeSlot
SampleRecord = v1.SampleRecord
strip_profile = v1.strip_profile

FREE_UNITS = v1.FREE_UNITS
UNIT_ORDER = v1.UNIT_ORDER
UNIT_NUMBER = v1.UNIT_NUMBER
SECONDARY_BUDGETS = v1.SECONDARY_BUDGETS
SECONDARY_TEMPLATES = v1.SECONDARY_TEMPLATES
EDGE_SLOT_RANGES = v1.EDGE_SLOT_RANGES

# V1 repeatedly sent P1/S1 through the upper rim of flower_1.  V2 keeps the
# same angular capacity but moves that sampled lobe into the free upper-left
# corridor.  This is a legal-domain correction, not a fixed angle.
SECONDARY_TEMPLATES_V2 = dict(SECONDARY_TEMPLATES)
SECONDARY_TEMPLATES_V2["primary_1_free"] = (
    ("s1", (-64.0, -30.0), (36.0, 54.0)),
    SECONDARY_TEMPLATES["primary_1_free"][1],
)

# Start at the two flower anchors and then expand outwards.  This does not
# change IDs or topology; it only determines which neighbour envelope is exact
# and which one is still represented by its already-known primary envelope.
CONTEXT_ORDER = (
    "primary_4_flower_1",
    "primary_5_flower_2",
    "primary_3_free",
    "primary_6_balance",
    "primary_2_free",
    "primary_7_free",
    "primary_1_free",
)
EDGE_CARRIER_SLOT = {
    "primary_1_free": "s2",
    "primary_2_free": "s1",
    "primary_3_free": "s1",
    "primary_6_balance": "s2",
    "primary_7_free": "s2",
}


class PlanningFailure(RuntimeError):
    """A sampled legal domain is empty; callers must retain the failed seed."""


def _round_point(point: Point) -> list[float]:
    return [round(point[0], 8), round(point[1], 8)]


def _unit(vector: Point) -> Point:
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-12:
        raise ValueError("degenerate direction")
    return vector[0] / length, vector[1] / length


def _signed_angle(first: Point, second: Point) -> float:
    first = _unit(first)
    second = _unit(second)
    return math.degrees(
        math.atan2(
            first[0] * second[1] - first[1] * second[0],
            first[0] * second[0] + first[1] * second[1],
        )
    )


def _wrap_degrees(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def _envelope_center(envelope: tuple[float, float, float, float]) -> Point:
    return 0.5 * (envelope[0] + envelope[2]), 0.5 * (envelope[1] + envelope[3])


def _cyclic_neighbours(unit_id: str) -> tuple[str, str]:
    index = UNIT_ORDER.index(unit_id)
    return UNIT_ORDER[(index - 1) % len(UNIT_ORDER)], UNIT_ORDER[(index + 1) % len(UNIT_ORDER)]


@dataclass(frozen=True)
class NeighborContextRecord:
    """V2 trace: the old fields plus the two cyclic neighbour reservations."""

    unit_id: str
    previous_unit_id: str | None
    previous_visible_envelope: tuple[float, float, float, float] | None
    current_primary_center_y: float
    direction_bias_degrees: float
    secondary_angle_ranges: tuple[tuple[str, float, float], ...]
    resulting_visible_envelope: tuple[float, float, float, float]
    edge_slots_before: tuple[str, ...]
    edge_slots_after: tuple[str, ...]
    left_unit_id: str
    right_unit_id: str
    left_visible_envelope: tuple[float, float, float, float]
    right_visible_envelope: tuple[float, float, float, float]
    committed_neighbours: tuple[str, ...]
    edge_stage_legal_components: tuple[tuple[float, float], ...]
    context_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "generation_previous_unit_id": self.previous_unit_id,
            "generation_previous_visible_envelope": (
                None
                if self.previous_visible_envelope is None
                else [round(value, 8) for value in self.previous_visible_envelope]
            ),
            "current_primary_center_y": round(self.current_primary_center_y, 8),
            "direction_bias_degrees": round(self.direction_bias_degrees, 8),
            "secondary_angle_ranges": [
                {"slot": slot, "low": round(low, 8), "high": round(high, 8)}
                for slot, low, high in self.secondary_angle_ranges
            ],
            "resulting_visible_envelope": [round(value, 8) for value in self.resulting_visible_envelope],
            "edge_slots_before": list(self.edge_slots_before),
            "edge_slots_after": list(self.edge_slots_after),
            "cyclic_neighbours": {
                "left": self.left_unit_id,
                "right": self.right_unit_id,
                "left_visible_envelope": [round(value, 8) for value in self.left_visible_envelope],
                "right_visible_envelope": [round(value, 8) for value in self.right_visible_envelope],
                "committed": list(self.committed_neighbours),
            },
            "edge_stage_legal_components": [
                [round(low, 8), round(high, 8)]
                for low, high in self.edge_stage_legal_components
            ],
            "context_digest": self.context_digest,
        }


def _primary_rows(
    p0: StrictP0,
    seed: int,
    sampler: v1._Sampler,
) -> tuple[PrimaryPlan, ...]:
    """Keep flower supports, but stop blindly shrinking every free primary."""

    legacy_plan = base.plan_j0a(p0, seed)
    rows: list[PrimaryPlan] = []
    for row in legacy_plan.primaries:
        if row.kind == "flower":
            rows.append(row)
            continue
        path = f"unit.{UNIT_NUMBER[row.curve_id]}.primary"
        if row.curve_id == "primary_1_free":
            low = max(70.0, 0.72 * row.chord_length)
            high = max(low + 8.0, min(105.0, 0.88 * row.chord_length))
        elif row.curve_id in {"primary_2_free", "primary_3_free"}:
            low = max(62.0, 0.88 * row.chord_length)
            high = max(low + 8.0, min(86.0, 1.02 * row.chord_length))
        elif row.curve_id == "primary_6_balance":
            low = max(80.0, 0.68 * row.chord_length)
            high = max(low + 8.0, min(110.0, 0.82 * row.chord_length))
        else:
            low = max(60.0, 0.86 * row.chord_length)
            high = max(low + 8.0, min(98.0, 1.02 * row.chord_length))
        chord_length = sampler.sample(path, "chord_length", low, high)
        entry_opening = sampler.sample(path, "entry_opening_degrees", 38.0, 48.0)
        exit_release = sampler.sample(path, "exit_release_degrees", 16.0, 28.0)
        start_arm = sampler.sample(path, "start_arm_ratio", 0.24, 0.33)
        end_arm = sampler.sample(path, "end_arm_ratio", 0.24, 0.34)
        rows.append(
            replace(
                row,
                target_boundary=None,
                target_point=None,
                terminal_tangent=None,
                chord_length=chord_length,
                start_arm_ratio=start_arm,
                end_arm_ratio=end_arm,
                entry_opening_degrees=entry_opening,
                exit_release_degrees=exit_release,
            )
        )
    return tuple(rows)


def _context_bias(
    sampler: v1._Sampler,
    unit_id: str,
    primary_envelope: tuple[float, float, float, float],
    left_envelope: tuple[float, float, float, float],
    right_envelope: tuple[float, float, float, float],
    strength: float,
) -> tuple[float, Point]:
    """Return a bounded repulsion angle derived from both neighbour envelopes."""

    own = _envelope_center(primary_envelope)
    left = _envelope_center(left_envelope)
    right = _envelope_center(right_envelope)
    path = f"unit.{UNIT_NUMBER[unit_id]}.context"
    left_weight = sampler.sample(path, "left_neighbor_weight", 0.40, 0.60)

    def repel(other: Point) -> Point:
        delta = own[0] - other[0], own[1] - other[1]
        scale = max(18.0, math.hypot(delta[0], delta[1]))
        return delta[0] / scale, delta[1] / scale

    left_vector = repel(left)
    right_vector = repel(right)
    vector = (
        left_weight * left_vector[0] + (1.0 - left_weight) * right_vector[0],
        left_weight * left_vector[1] + (1.0 - left_weight) * right_vector[1],
    )
    if math.hypot(vector[0], vector[1]) <= 1e-6:
        polarity = sampler.sample(path, "tie_break_polarity", -1.0, 1.0)
        vector = (0.0, -1.0 if polarity < 0.0 else 1.0)
    repel_angle = math.degrees(math.atan2(vector[1], vector[0]))
    signed_strength = sampler.sample(path, "response_strength_degrees", 0.60 * strength, strength)
    return signed_strength, (math.cos(math.radians(repel_angle)), math.sin(math.radians(repel_angle)))


def _shift_angle_range(
    base_range: tuple[float, float],
    repulsion_direction: Point,
    strength: float,
) -> tuple[float, float, float]:
    center = 0.5 * (base_range[0] + base_range[1])
    repel_angle = math.degrees(math.atan2(repulsion_direction[1], repulsion_direction[0]))
    delta = _wrap_degrees(repel_angle - center)
    shift = max(-strength, min(strength, 0.16 * delta))
    return base_range[0] + shift, base_range[1] + shift, shift


def _sample_interval_union(
    components: Sequence[tuple[float, float]],
    u: float,
    *,
    failure_label: str,
) -> float:
    legal = [(low, high) for low, high in components if high > low]
    total = sum(high - low for low, high in legal)
    if total <= 0.0:
        raise PlanningFailure(f"{failure_label}: empty interval union")
    cursor = min(max(u, 0.0), 1.0) * total
    for index, (low, high) in enumerate(legal):
        width = high - low
        if cursor < width or index == len(legal) - 1:
            return low + min(cursor, width)
        cursor -= width
    raise AssertionError("interval-union mapping fell through")


def _stage_x_legal_components(
    slot_range: tuple[float, float],
    root: Point,
    parent_tangent: Point,
    stage_y: float,
    parent_length: float,
) -> tuple[tuple[float, float], ...]:
    """Numerically materialize the one-dimensional legal staging domain."""

    low = slot_range[0] + 8.0
    high = slot_range[1] - 8.0
    step = 0.25
    count = max(1, math.ceil((high - low) / step))
    xs = [low + (high - low) * index / count for index in range(count + 1)]
    minimum_length = max(20.0, 0.22 * parent_length)
    maximum_length = min(90.0, 0.92 * parent_length)

    def legal(x_value: float) -> bool:
        vector = (x_value - root[0], stage_y - root[1])
        length = math.hypot(vector[0], vector[1])
        if not minimum_length <= length <= maximum_length:
            return False
        turn = angle_degrees(parent_tangent, vector)
        return 15.0 <= turn <= 112.0

    flags = [legal(x_value) for x_value in xs]
    components: list[tuple[float, float]] = []
    start: float | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = xs[index]
        is_last = index == len(flags) - 1
        if start is not None and (not flag or is_last):
            end = xs[index] if flag and is_last else xs[index - 1]
            if end - start >= 0.5:
                components.append((start, end))
            start = None
    return tuple(components)


def plan_recursive(
    p0: StrictP0,
    seed: int,
    controls: RecursiveControls = RecursiveControls(),
) -> RecursivePlan:
    """Plan the V2 hierarchy once; no validation result is consumed."""

    v1._validate_controls(controls)
    sampler = v1._Sampler(int(seed))
    global_length_scale = sampler.sample("scene", "descendant_length_scale", 0.94, 1.08)
    context_strength = sampler.sample("scene", "context_strength_degrees", 4.0, 8.0)
    tertiary_selector = sampler.sample_stratified(
        "scene", "tertiary_count_selector", 0.0, 1.0, 4
    )
    tertiary_count = controls.tertiary_min + min(
        controls.tertiary_max - controls.tertiary_min,
        int(tertiary_selector * (controls.tertiary_max - controls.tertiary_min + 1)),
    )

    primaries = _primary_rows(p0, int(seed), sampler)
    primary_previews = {
        row.curve_id: base._compile_primary(p0, row)  # noqa: SLF001
        for row in primaries
    }
    primary_envelopes = {
        unit_id: v1._curve_visible_envelope([primary_previews[unit_id]])
        for unit_id in UNIT_ORDER
    }
    envelope_plan = base._global_envelope_values(p0, int(seed))  # noqa: SLF001

    edge_intents: dict[str, dict[str, object]] = {}
    for unit_id in FREE_UNITS:
        unit_number = UNIT_NUMBER[unit_id]
        path = f"unit.{unit_number}.edge"
        side, x_low, x_high = EDGE_SLOT_RANGES[unit_id]
        edge_y = (
            envelope_plan["envelope_top_y"] + 0.5 * TERTIARY_WIDTH
            if side == "top_frontier"
            else envelope_plan["envelope_bottom_y"] - 0.5 * TERTIARY_WIDTH
        )
        stage_inset = sampler.sample(path, "stage_inset", 10.0, 18.0)
        stage_y = edge_y + stage_inset if side == "top_frontier" else edge_y - stage_inset
        edge_intents[unit_id] = {
            "side": side,
            "slot_range": (x_low, x_high),
            "edge_y": edge_y,
            "stage_y": stage_y,
            "stage_selector": sampler.sample(path, "stage_selector", 0.0, 1.0),
        }

    descendants: list[ChildPlan] = []
    metadata: list[RecursiveNodeMeta] = []
    secondary_previews: dict[str, HierarchyCurve] = {}
    secondary_slot_by_id: dict[str, str] = {}
    unit_secondary_ids: dict[str, list[str]] = {unit_id: [] for unit_id in UNIT_ORDER}
    context_records: list[NeighborContextRecord] = []
    committed_nodes: dict[str, list[HierarchyCurve]] = {}
    previous_unit_id: str | None = None
    previous_envelope: tuple[float, float, float, float] | None = None
    occupied_slot_labels: list[str] = []

    for unit_id in CONTEXT_ORDER:
        primary = primary_previews[unit_id]
        primary_points = primary.curve.points(96)
        primary_center_y = sum(point[1] for point in primary_points) / len(primary_points)
        left_unit, right_unit = _cyclic_neighbours(unit_id)
        left_envelope = (
            v1._curve_visible_envelope(committed_nodes[left_unit])
            if left_unit in committed_nodes
            else primary_envelopes[left_unit]
        )
        right_envelope = (
            v1._curve_visible_envelope(committed_nodes[right_unit])
            if right_unit in committed_nodes
            else primary_envelopes[right_unit]
        )
        response_strength, repel_direction = _context_bias(
            sampler,
            unit_id,
            primary_envelopes[unit_id],
            left_envelope,
            right_envelope,
            context_strength,
        )

        unit_nodes: list[HierarchyCurve] = [primary]
        angle_ranges: list[tuple[str, float, float]] = []
        shifts: list[float] = []
        templates = SECONDARY_TEMPLATES_V2[unit_id]
        for slot_index, (slot, base_angle_range, base_length_range) in enumerate(templates):
            curve_id = v1._secondary_curve_id(unit_id, slot)
            path = f"unit.{UNIT_NUMBER[unit_id]}.{slot}"
            is_carrier = unit_id in FREE_UNITS and slot == EDGE_CARRIER_SLOT[unit_id]
            if unit_id == "primary_6_balance" and slot == "s1":
                mount_range = (0.38, 0.46)
            elif len(templates) == 2:
                if is_carrier:
                    if slot_index == 0:
                        mount_range = (0.58, 0.70)
                    elif unit_id in {"primary_1_free", "primary_7_free"}:
                        mount_range = (0.32, 0.46)
                    else:
                        mount_range = (0.40, 0.54)
                else:
                    mount_range = (0.25, 0.41) if slot_index == 0 else (0.52, 0.69)
            else:
                mount_range = (0.40, 0.64)
            mount_fraction = sampler.sample(path, "mount_fraction", *mount_range)
            parent_root, parent_tangent = sample_polyline(primary.curve.points(192), mount_fraction)

            if is_carrier:
                intent = edge_intents[unit_id]
                slot_range = intent["slot_range"]
                assert isinstance(slot_range, tuple)
                stage_components = _stage_x_legal_components(
                    (float(slot_range[0]), float(slot_range[1])),
                    parent_root,
                    parent_tangent,
                    float(intent["stage_y"]),
                    primary.curve.length,
                )
                stage_x = _sample_interval_union(
                    stage_components,
                    float(intent["stage_selector"]),
                    failure_label=f"seed={seed} unit={unit_id} edge.stage_x",
                )
                stage_point = (stage_x, float(intent["stage_y"]))
                intent["stage_point"] = stage_point
                intent["stage_legal_components"] = stage_components
                travel_direction = _unit(sub(stage_point, parent_root))
                chord_length = dist(parent_root, stage_point)
                travel_angle = math.degrees(math.atan2(travel_direction[1], travel_direction[0]))
                angle_low = travel_angle
                angle_high = travel_angle
                shift = 0.0
                entry_opening = sampler.sample(path, "entry_opening_degrees", 11.0, 15.0)
                handle_ratio = sampler.sample(path, "handle_ratio", 0.23, 0.31)
                exit_release = sampler.sample(path, "exit_release_degrees", 12.0, 24.0)
                bend_mode = "C"
                terminal_role = "edge_parent"
                edge_goal = str(intent["side"])
            else:
                angle_low, angle_high, shift = _shift_angle_range(
                    base_angle_range, repel_direction, response_strength
                )
                travel_angle = sampler.sample(path, "travel_angle_degrees", angle_low, angle_high)
                travel_direction = (
                    math.cos(math.radians(travel_angle)),
                    math.sin(math.radians(travel_angle)),
                )
                parent_length = primary.curve.length
                if "flower" in unit_id:
                    length_low = max(16.0, 0.34 * parent_length)
                    length_high = min(32.0, base_length_range[1] * global_length_scale, 0.65 * parent_length)
                else:
                    length_low = max(26.0, 0.32 * parent_length)
                    length_high = min(58.0, base_length_range[1] * global_length_scale, 0.60 * parent_length)
                if length_high <= length_low:
                    length_high = length_low + 3.0
                chord_length = sampler.sample(path, "chord_length", length_low, length_high)
                entry_opening = sampler.sample(path, "entry_opening_degrees", 10.0, 15.0)
                handle_ratio = sampler.sample(path, "handle_ratio", 0.24, 0.34)
                exit_release = sampler.sample(path, "exit_release_degrees", 18.0, 30.0)
                mode_u = sampler.sample(path, "bend_mode_selector", 0.0, 1.0)
                bend_mode = "C" if mode_u < 0.72 else "S"
                terminal_role = "recursive_parent_candidate"
                edge_goal = None

            turn = _signed_angle(parent_tangent, travel_direction)
            row = ChildPlan(
                curve_id=curve_id,
                parent_id=unit_id,
                growth_role=("flower_wrap" if "flower" in unit_id else "lateral"),
                target_boundary=None,
                target_point=None,
                terminal_tangent=None,
                travel_direction=travel_direction,
                level=2,
                mount_fraction=mount_fraction,
                turn_sign=1 if turn >= 0.0 else -1,
                opening_angle_degrees=abs(turn),
                chord_length=chord_length,
                handle_ratio=handle_ratio,
                entry_opening_degrees=entry_opening,
                exit_release_degrees=exit_release,
                bend_mode=bend_mode,
            )
            preview = base._compile_child(primary, row)  # noqa: SLF001
            descendants.append(row)
            secondary_previews[curve_id] = preview
            secondary_slot_by_id[curve_id] = slot
            unit_secondary_ids[unit_id].append(curve_id)
            unit_nodes.append(preview)
            angle_ranges.append((slot, angle_low, angle_high))
            shifts.append(shift)
            metadata.append(
                RecursiveNodeMeta(
                    curve_id=curve_id,
                    unit_id=unit_id,
                    path=f"P{UNIT_NUMBER[unit_id]}/{slot.upper()}",
                    level=2,
                    parent_id=unit_id,
                    edge_goal=edge_goal,
                    terminal_role=terminal_role,
                    is_edge_heir=False,
                    sample_keys=sampler.keys_with_prefix(path + "."),
                )
            )

        resulting_envelope = v1._curve_visible_envelope(unit_nodes)
        committed_nodes[unit_id] = unit_nodes
        before = tuple(occupied_slot_labels)
        if unit_id in edge_intents:
            intent = edge_intents[unit_id]
            stage = intent["stage_point"]
            assert isinstance(stage, tuple)
            occupied_slot_labels.append(f"{intent['side']}:stage@{stage[0]:.4f}")
        payload = {
            "unit_id": unit_id,
            "left": left_unit,
            "right": right_unit,
            "left_envelope": left_envelope,
            "right_envelope": right_envelope,
            "angle_ranges": angle_ranges,
            "resulting_envelope": resulting_envelope,
            "edge_stage_legal_components": (
                edge_intents[unit_id].get("stage_legal_components", ())
                if unit_id in edge_intents
                else ()
            ),
        }
        context_records.append(
            NeighborContextRecord(
                unit_id=unit_id,
                previous_unit_id=previous_unit_id,
                previous_visible_envelope=previous_envelope,
                current_primary_center_y=primary_center_y,
                direction_bias_degrees=(sum(shifts) / len(shifts) if shifts else 0.0),
                secondary_angle_ranges=tuple(angle_ranges),
                resulting_visible_envelope=resulting_envelope,
                edge_slots_before=before,
                edge_slots_after=tuple(occupied_slot_labels),
                left_unit_id=left_unit,
                right_unit_id=right_unit,
                left_visible_envelope=left_envelope,
                right_visible_envelope=right_envelope,
                committed_neighbours=tuple(
                    neighbour for neighbour in (left_unit, right_unit) if neighbour in committed_nodes
                ),
                edge_stage_legal_components=tuple(
                    edge_intents[unit_id].get("stage_legal_components", ())
                    if unit_id in edge_intents
                    else ()
                ),
                context_digest=hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            )
        )
        previous_unit_id = unit_id
        previous_envelope = resulting_envelope

    if len(descendants) != controls.secondary_count:
        raise AssertionError("secondary planning did not realize its declared budget")

    edge_slots: list[EdgeSlot] = []
    occupied_secondary_ids: set[str] = set()
    for unit_id in FREE_UNITS:
        unit_number = UNIT_NUMBER[unit_id]
        path = f"unit.{unit_number}.edge"
        parent_slot = EDGE_CARRIER_SLOT[unit_id]
        parent_id = v1._secondary_curve_id(unit_id, parent_slot)
        parent = secondary_previews[parent_id]
        intent = edge_intents[unit_id]
        side = str(intent["side"])
        stage_point = intent["stage_point"]
        slot_range = intent["slot_range"]
        assert isinstance(stage_point, tuple)
        assert isinstance(slot_range, tuple)
        mount_fraction = sampler.sample(path, "mount_fraction", 0.62, 0.72)
        entry_opening = sampler.sample(path, "entry_opening_degrees", 10.0, 14.0)
        handle_ratio = sampler.sample(path, "handle_ratio", 0.22, 0.30)
        root, tangent = sample_polyline(parent.curve.points(192), mount_fraction)
        target_x_low = max(float(slot_range[0]), stage_point[0] - 10.0, root[0] - 16.0)
        target_x_high = min(float(slot_range[1]), stage_point[0] + 10.0, root[0] + 16.0)
        if target_x_low >= target_x_high:
            raise PlanningFailure(
                f"seed={seed} unit={unit_id} edge.target_x empty legal range "
                f"[{target_x_low:.6f}, {target_x_high:.6f}]"
            )
        target_x = sampler.sample(path, "target_x", target_x_low, target_x_high)
        target_point = (target_x, float(intent["edge_y"]))
        direction = _unit(sub(target_point, root))
        turn = _signed_angle(tangent, direction)
        terminal_tangent = (1.0, 0.0) if target_point[0] >= root[0] else (-1.0, 0.0)
        curve_id = v1._tertiary_curve_id(unit_id, parent_slot)
        row = ChildPlan(
            curve_id=curve_id,
            parent_id=parent_id,
            growth_role="lateral",
            target_boundary=side,
            target_point=target_point,
            terminal_tangent=terminal_tangent,
            travel_direction=None,
            level=3,
            mount_fraction=mount_fraction,
            turn_sign=1 if turn >= 0.0 else -1,
            opening_angle_degrees=abs(turn),
            chord_length=dist(root, target_point),
            handle_ratio=handle_ratio,
            entry_opening_degrees=entry_opening,
            exit_release_degrees=0.0,
            bend_mode="C",
        )
        descendants.append(row)
        occupied_secondary_ids.add(parent_id)
        edge_slots.append(EdgeSlot(unit_id, side, target_point, curve_id))
        metadata.append(
            RecursiveNodeMeta(
                curve_id=curve_id,
                unit_id=unit_id,
                path=f"P{unit_number}/{parent_slot.upper()}/T1",
                level=3,
                parent_id=parent_id,
                edge_goal=side,
                terminal_role="edge_glide",
                is_edge_heir=True,
                sample_keys=sampler.keys_with_prefix(path + "."),
            )
        )

    # Only the five free Units may receive the remaining 1..4 tertiary leaves.
    # Each free Unit has exactly one unused secondary after edge assignment.
    extra_needed = tertiary_count - len(FREE_UNITS)
    ranked_extra_parents: list[tuple[float, str, str]] = []
    for unit_id in FREE_UNITS:
        parent_slot = "s1" if EDGE_CARRIER_SLOT[unit_id] == "s2" else "s2"
        parent_id = v1._secondary_curve_id(unit_id, parent_slot)
        priority = sampler.sample(
            f"unit.{UNIT_NUMBER[unit_id]}.{parent_slot}.extra", "selection_priority", 0.0, 1.0
        )
        ranked_extra_parents.append((priority, unit_id, parent_id))
    ranked_extra_parents.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected_extra = [(unit_id, parent_id) for _, unit_id, parent_id in ranked_extra_parents[:extra_needed]]

    for unit_id, parent_id in selected_extra:
        unit_number = UNIT_NUMBER[unit_id]
        parent_slot = secondary_slot_by_id[parent_id]
        path = f"unit.{unit_number}.{parent_slot}.extra"
        curve_id = v1._tertiary_curve_id(unit_id, parent_slot)
        parent = secondary_previews[parent_id]
        mount_fraction = sampler.sample(path, "mount_fraction", 0.42, 0.64)
        root, tangent = sample_polyline(parent.curve.points(192), mount_fraction)
        side_u = sampler.sample(path, "turn_side_selector", 0.0, 1.0)
        turn_degrees = sampler.sample(path, "turn_degrees", 42.0, 72.0)
        length_low = max(14.0, 0.30 * parent.curve.length)
        length_high = max(length_low + 3.0, min(30.0, 0.52 * parent.curve.length))
        chord_length = sampler.sample(path, "chord_length", length_low, length_high)
        side_rows: list[tuple[float, int, Point]] = []
        for turn_sign in (-1, 1):
            direction = _unit(rotate(tangent, turn_sign * turn_degrees))
            midpoint = (
                root[0] + 0.50 * chord_length * direction[0],
                root[1] + 0.50 * chord_length * direction[1],
            )
            endpoint = (
                root[0] + chord_length * direction[0],
                root[1] + chord_length * direction[1],
            )
            flower_clearance_score = min(
                min(base._ellipse_value(midpoint, flower), base._ellipse_value(endpoint, flower))  # noqa: SLF001
                for flower in p0.flowers
            )
            side_rows.append((flower_clearance_score, turn_sign, direction))
        side_rows.sort(key=lambda item: (item[0], item[1]))
        if abs(side_rows[1][0] - side_rows[0][0]) > 0.05:
            _, turn_sign, travel_direction = side_rows[1]
        else:
            _, turn_sign, travel_direction = side_rows[0 if side_u < 0.5 else 1]
        entry_opening = sampler.sample(path, "entry_opening_degrees", 10.0, 14.0)
        handle_ratio = sampler.sample(path, "handle_ratio", 0.23, 0.32)
        exit_release = sampler.sample(path, "exit_release_degrees", 18.0, 28.0)
        mode_u = sampler.sample(path, "bend_mode_selector", 0.0, 1.0)
        row = ChildPlan(
            curve_id=curve_id,
            parent_id=parent_id,
            growth_role="lateral",
            target_boundary=None,
            target_point=None,
            terminal_tangent=None,
            travel_direction=travel_direction,
            level=3,
            mount_fraction=mount_fraction,
            turn_sign=turn_sign,
            opening_angle_degrees=turn_degrees,
            chord_length=chord_length,
            handle_ratio=handle_ratio,
            entry_opening_degrees=entry_opening,
            exit_release_degrees=exit_release,
            bend_mode="C" if mode_u < 0.80 else "S",
        )
        descendants.append(row)
        metadata.append(
            RecursiveNodeMeta(
                curve_id=curve_id,
                unit_id=unit_id,
                path=f"P{unit_number}/{parent_slot.upper()}/T1",
                level=3,
                parent_id=parent_id,
                edge_goal=None,
                terminal_role="free_curl",
                is_edge_heir=False,
                sample_keys=sampler.keys_with_prefix(path + "."),
            )
        )

    return RecursivePlan(
        plan_id=PLAN_ID,
        seed=int(seed),
        controls=controls,
        primaries=tuple(primaries),
        descendants=tuple(sorted(descendants, key=lambda row: (row.level, row.curve_id))),
        node_metadata=tuple(sorted(metadata, key=lambda row: row.curve_id)),
        samples=tuple(sampler.records),
        contexts=tuple(context_records),
        edge_slots=tuple(edge_slots),
        style_latents={
            "descendant_length_scale": global_length_scale,
            "context_strength_degrees": context_strength,
            "tertiary_count_selector": tertiary_selector,
            "tertiary_count": float(tertiary_count),
            "envelope_top_y": envelope_plan["envelope_top_y"],
            "envelope_bottom_y": envelope_plan["envelope_bottom_y"],
        },
    )


def compile_plan(
    plan: RecursivePlan,
    p0: StrictP0,
    traversal_order: Sequence[str] | None = None,
) -> RecursiveResult:
    return v1.compile_plan(plan, p0, traversal_order)


def build_recursive(
    p0: StrictP0,
    seed: int,
    controls: RecursiveControls = RecursiveControls(),
    traversal_order: Sequence[str] | None = None,
) -> RecursiveResult:
    return compile_plan(plan_recursive(p0, seed, controls), p0, traversal_order)


def validate_result(p0: StrictP0, result: RecursiveResult) -> dict[str, object]:
    """Run every V1 geometry check, replacing only its obsolete context-order rule."""

    report = v1.validate_result(p0, result)
    issues = [
        issue
        for issue in report["issues"]
        if not (
            issue.endswith(":neighbor_context_order")
            or issue.endswith(":missing_previous_envelope")
            or issue.endswith(":context_not_applied")
        )
    ]
    contexts = result.plan.contexts
    if tuple(row.unit_id for row in contexts) != CONTEXT_ORDER:
        issues.append("v2_context_order_mismatch")
    context_details: list[dict[str, object]] = []
    for row in contexts:
        expected = set(_cyclic_neighbours(row.unit_id))
        observed = {row.left_unit_id, row.right_unit_id}
        if observed != expected:
            issues.append(f"{row.unit_id}:cyclic_neighbour_context_mismatch")
        if not row.context_digest:
            issues.append(f"{row.unit_id}:missing_context_digest")
        context_details.append(
            {
                "unit_id": row.unit_id,
                "left": row.left_unit_id,
                "right": row.right_unit_id,
                "committed_neighbours": list(row.committed_neighbours),
                "context_digest": row.context_digest,
            }
        )

    nodes = result.by_id
    metadata = result.plan.metadata_by_id
    hierarchy_ratios: list[dict[str, object]] = []
    for row in result.plan.descendants:
        child_length = nodes[row.curve_id].curve.length
        parent_length = nodes[row.parent_id].curve.length
        ratio = child_length / max(parent_length, 1e-12)
        meta = metadata[row.curve_id]
        if row.level == 2:
            limit = 0.82 if meta.edge_goal is not None else 0.72
        else:
            limit = 0.78 if meta.is_edge_heir else 0.72
        if ratio > limit:
            issues.append(f"{row.curve_id}:hierarchy_length_ratio_over_{limit:.2f}")
        hierarchy_ratios.append(
            {
                "curve_id": row.curve_id,
                "parent_id": row.parent_id,
                "ratio": round(ratio, 8),
                "limit": limit,
            }
        )

    flower_units = set(UNIT_ORDER) - set(FREE_UNITS)
    if any(meta.level == 3 and meta.unit_id in flower_units for meta in result.plan.node_metadata):
        issues.append("flower_unit_has_tertiary")

    edge_turns: list[dict[str, object]] = []
    carrier_turns: list[dict[str, object]] = []
    for meta in result.plan.node_metadata:
        if meta.level != 2 or meta.edge_goal is None:
            continue
        row = next(item for item in result.plan.descendants if item.curve_id == meta.curve_id)
        parent = nodes[row.parent_id]
        root, tangent = sample_polyline(parent.curve.points(192), row.mount_fraction)
        direction = _unit(sub(nodes[row.curve_id].curve.tip, root))
        turn = angle_degrees(tangent, direction)
        if not 15.0 <= turn <= 112.0:
            issues.append(f"{row.curve_id}:edge_carrier_lateral_turn_outside_15_112")
        carrier_turns.append({"curve_id": row.curve_id, "turn_degrees": round(turn, 8)})

    for meta in result.plan.node_metadata:
        if not meta.is_edge_heir:
            continue
        row = next(item for item in result.plan.descendants if item.curve_id == meta.curve_id)
        parent = nodes[row.parent_id]
        root, tangent = sample_polyline(parent.curve.points(192), row.mount_fraction)
        edge_curve = nodes[row.curve_id].curve
        direction = _unit(sub(edge_curve.tip, root))
        turn = angle_degrees(tangent, direction)
        chord = dist(root, edge_curve.tip)
        stretch = edge_curve.length / max(chord, 1e-12)
        points = edge_curve.points(192)
        if turn > 95.0:
            issues.append(f"{row.curve_id}:edge_heir_turn_over_95")
        if stretch > 1.18:
            issues.append(f"{row.curve_id}:edge_heir_path_stretch_over_1_18")
        if row.target_boundary == "top_frontier":
            reverse_progress = max(
                (second[1] - first[1] for first, second in zip(points, points[1:])),
                default=0.0,
            )
        else:
            reverse_progress = max(
                (first[1] - second[1] for first, second in zip(points, points[1:])),
                default=0.0,
            )
        if reverse_progress > 2.0:
            issues.append(f"{row.curve_id}:edge_progress_reverses")
        edge_turns.append(
            {
                "curve_id": row.curve_id,
                "turn_degrees": round(turn, 8),
                "actual_to_chord": round(stretch, 8),
                "maximum_reverse_progress": round(reverse_progress, 8),
            }
        )

    unique_issues = list(dict.fromkeys(issues))
    diagnostics = dict(report["diagnostics"])
    diagnostics["v2_context"] = context_details
    diagnostics["hierarchy_length_ratios"] = hierarchy_ratios
    diagnostics["edge_carrier_turns"] = carrier_turns
    diagnostics["edge_heir_turns"] = edge_turns
    return {"valid": not unique_issues, "issues": unique_issues, "diagnostics": diagnostics}


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
            results[seed].plan.digest == replays[seed].plan.digest
            and results[seed].geometry_hash == replays[seed].geometry_hash
        )
        for seed in seed_tuple
    }
    topology_signatures = {
        seed: tuple(
            sorted(row.curve_id for row in results[seed].plan.descendants if row.level == 3)
        )
        for seed in seed_tuple
    }
    pairwise: list[dict[str, object]] = []
    for first_index, first_seed in enumerate(seed_tuple):
        for second_seed in seed_tuple[first_index + 1 :]:
            first_rows = {
                row.curve_id: row
                for row in results[first_seed].plan.descendants
                if row.level == 2
            }
            second_rows = {
                row.curve_id: row
                for row in results[second_seed].plan.descendants
                if row.level == 2
            }
            common = sorted(set(first_rows) & set(second_rows))
            mount_changes = [
                abs(first_rows[curve_id].mount_fraction - second_rows[curve_id].mount_fraction)
                for curve_id in common
            ]
            direction_changes = [
                angle_degrees(
                    first_rows[curve_id].travel_direction,
                    second_rows[curve_id].travel_direction,
                )
                for curve_id in common
            ]
            length_changes = [
                abs(first_rows[curve_id].chord_length - second_rows[curve_id].chord_length)
                / max(
                    0.5
                    * (
                        first_rows[curve_id].chord_length
                        + second_rows[curve_id].chord_length
                    ),
                    1e-12,
                )
                for curve_id in common
            ]
            pairwise.append(
                {
                    "first_seed": first_seed,
                    "second_seed": second_seed,
                    "secondary_mount_count_delta_ge_0_04": sum(value >= 0.04 for value in mount_changes),
                    "secondary_direction_count_delta_ge_12deg": sum(value >= 12.0 for value in direction_changes),
                    "secondary_length_count_delta_ge_0_15": sum(value >= 0.15 for value in length_changes),
                    "tertiary_slot_symmetric_difference": sorted(
                        set(topology_signatures[first_seed]) ^ set(topology_signatures[second_seed])
                    ),
                }
            )
    return {
        "seeds": list(seed_tuple),
        "replay_by_seed": replay_by_seed,
        "geometry_hashes": {str(seed): results[seed].geometry_hash for seed in seed_tuple},
        "plan_digests": {str(seed): results[seed].plan.digest for seed in seed_tuple},
        "tertiary_counts": {str(seed): len(topology_signatures[seed]) for seed in seed_tuple},
        "tertiary_slot_sets": {str(seed): list(topology_signatures[seed]) for seed in seed_tuple},
        "validation_passes": {str(seed): validations[seed]["valid"] for seed in seed_tuple},
        "pairwise": pairwise,
        "passes": (
            all(replay_by_seed.values())
            and len({result.geometry_hash for result in results.values()}) == len(seed_tuple)
            and len({result.plan.digest for result in results.values()}) == len(seed_tuple)
            and all(6 <= len(topology_signatures[seed]) <= 9 for seed in seed_tuple)
            and all(validation["valid"] for validation in validations.values())
        ),
    }


def _default_profile_path() -> Path:
    return v1._default_profile_path()


__all__ = [
    "CONTEXT_ORDER",
    "DEV_SEEDS",
    "EDGE_CARRIER_SLOT",
    "FREE_UNITS",
    "GEOMETRY_KERNEL_ID",
    "NeighborContextRecord",
    "PLAN_ID",
    "PlanningFailure",
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
