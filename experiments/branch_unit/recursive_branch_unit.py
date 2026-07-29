#!/usr/bin/env python3
"""Bounded recursive BranchUnit experiment for ``proto_sw_1_3``.

This module deliberately keeps planning separate from geometry compilation:

* the old module supplies the strict P0 input and the tested Bezier compilers;
* this module plans a dynamic 7 + 12 + (6..9) hierarchy;
* every random scalar is addressed by a stable seed/path/parameter key;
* five free units pass an edge goal to a tertiary leaf;
* validation is check-only and never retries, resamples, repairs, or mutates.

No SVG branch from the source prototype is consumed.  The retained P0 is only
the repeat bounds, backbone, and two flower reserves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Sequence

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


PLAN_ID = "proto_sw_1_3_recursive_branch_units_v1"
GEOMETRY_KERNEL_ID = "recursive_branch_unit_base_bezier_v1"
SAMPLER_ID = "recursive_branch_unit_path_hash_v1"
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
strip_profile = base.strip_profile


FREE_UNITS = (
    "primary_1_free",
    "primary_2_free",
    "primary_3_free",
    "primary_6_balance",
    "primary_7_free",
)
UNIT_ORDER = (
    "primary_1_free",
    "primary_2_free",
    "primary_3_free",
    "primary_4_flower_1",
    "primary_5_flower_2",
    "primary_6_balance",
    "primary_7_free",
)
UNIT_NUMBER = {unit_id: index + 1 for index, unit_id in enumerate(UNIT_ORDER)}
SECONDARY_BUDGETS = {
    "primary_1_free": 2,
    "primary_2_free": 2,
    "primary_3_free": 2,
    "primary_4_flower_1": 1,
    "primary_5_flower_2": 1,
    "primary_6_balance": 2,
    "primary_7_free": 2,
}
EDGE_SLOT_RANGES = {
    "primary_1_free": ("top_frontier", 24.0, 68.0),
    "primary_2_free": ("bottom_frontier", 34.0, 72.0),
    "primary_3_free": ("bottom_frontier", 88.0, 132.0),
    "primary_6_balance": ("top_frontier", 112.0, 154.0),
    "primary_7_free": ("top_frontier", 184.0, 226.0),
}


# World-angle and chord-length ranges.  Context shifts the angle interval before
# sampling; the interval itself is therefore part of the replay record.
SECONDARY_TEMPLATES: Mapping[str, tuple[tuple[str, tuple[float, float], tuple[float, float]], ...]] = {
    "primary_1_free": (
        ("s1", (-25.0, 35.0), (36.0, 54.0)),
        ("s2", (-142.0, -104.0), (30.0, 48.0)),
    ),
    "primary_2_free": (
        ("s1", (24.0, 70.0), (36.0, 54.0)),
        ("s2", (-162.0, -112.0), (30.0, 48.0)),
    ),
    "primary_3_free": (
        ("s1", (100.0, 150.0), (32.0, 50.0)),
        ("s2", (-42.0, 5.0), (34.0, 52.0)),
    ),
    "primary_4_flower_1": (
        ("s1", (-180.0, -150.0), (30.0, 46.0)),
    ),
    "primary_5_flower_2": (
        ("s1", (45.0, 105.0), (32.0, 50.0)),
    ),
    "primary_6_balance": (
        ("s1", (-180.0, -120.0), (38.0, 56.0)),
        ("s2", (-52.0, 10.0), (34.0, 52.0)),
    ),
    "primary_7_free": (
        ("s1", (132.0, 174.0), (32.0, 50.0)),
        ("s2", (-158.0, -116.0), (34.0, 52.0)),
    ),
}


def _round_point(point: Point) -> list[float]:
    return [round(point[0], 8), round(point[1], 8)]


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


@dataclass(frozen=True)
class RecursiveControls:
    max_depth: int = 3
    secondary_count: int = 12
    tertiary_min: int = 6
    tertiary_max: int = 9
    max_tertiary_per_secondary: int = 1
    max_tertiary_per_unit: int = 2
    max_short_per_unit: int = 1
    context_enabled: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "max_depth": self.max_depth,
            "secondary_count": self.secondary_count,
            "tertiary_range": [self.tertiary_min, self.tertiary_max],
            "max_tertiary_per_secondary": self.max_tertiary_per_secondary,
            "max_tertiary_per_unit": self.max_tertiary_per_unit,
            "max_short_per_unit": self.max_short_per_unit,
            "context_enabled": self.context_enabled,
        }


@dataclass(frozen=True)
class SampleRecord:
    key: str
    low: float
    high: float
    u: float
    value: float

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "legal_range": [round(self.low, 10), round(self.high, 10)],
            "u": round(self.u, 12),
            "value": round(self.value, 10),
        }


@dataclass(frozen=True)
class RecursiveNodeMeta:
    curve_id: str
    unit_id: str
    path: str
    level: int
    parent_id: str
    edge_goal: str | None
    terminal_role: str
    is_edge_heir: bool
    sample_keys: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "curve_id": self.curve_id,
            "unit_id": self.unit_id,
            "path": self.path,
            "level": self.level,
            "parent_id": self.parent_id,
            "edge_goal": self.edge_goal,
            "terminal_role": self.terminal_role,
            "is_edge_heir": self.is_edge_heir,
            "sample_keys": list(self.sample_keys),
        }


@dataclass(frozen=True)
class EdgeSlot:
    unit_id: str
    side: str
    target_point: Point
    inherited_by: str

    def as_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "side": self.side,
            "target_point": _round_point(self.target_point),
            "inherited_by": self.inherited_by,
        }


@dataclass(frozen=True)
class NeighborContextRecord:
    unit_id: str
    previous_unit_id: str | None
    previous_visible_envelope: tuple[float, float, float, float] | None
    current_primary_center_y: float
    direction_bias_degrees: float
    secondary_angle_ranges: tuple[tuple[str, float, float], ...]
    resulting_visible_envelope: tuple[float, float, float, float]
    edge_slots_before: tuple[str, ...]
    edge_slots_after: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "previous_unit_id": self.previous_unit_id,
            "previous_visible_envelope": (
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
            "resulting_visible_envelope": [
                round(value, 8) for value in self.resulting_visible_envelope
            ],
            "edge_slots_before": list(self.edge_slots_before),
            "edge_slots_after": list(self.edge_slots_after),
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
    contexts: tuple[NeighborContextRecord, ...]
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
            "schema": "recursive_branch_unit_plan_v1",
            "plan_id": self.plan_id,
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
                "stroke_model": {
                    "linecap": STROKE_LINECAP,
                    "linejoin": STROKE_LINEJOIN,
                },
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
            "schema": "recursive_branch_unit_result_v1",
            "geometry_kernel_id": GEOMETRY_KERNEL_ID,
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

    def sample(self, path: str, parameter: str, low: float, high: float) -> float:
        if not math.isfinite(low) or not math.isfinite(high) or not low < high:
            raise ValueError(f"invalid legal range for {path}.{parameter}: [{low}, {high}]")
        key = f"{path}.{parameter}"
        if key in self._keys:
            raise ValueError(f"duplicate sample key: {key}")
        digest = hashlib.sha256(
            f"{SAMPLER_ID}|{self.seed}|{key}".encode("utf-8")
        ).digest()
        u = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
        value = low + (high - low) * u
        self._keys.add(key)
        self.records.append(SampleRecord(key, low, high, u, value))
        return value

    def sample_stratified(
        self,
        path: str,
        parameter: str,
        low: float,
        high: float,
        strata: int,
    ) -> float:
        """Use a seed-permuted stratum while retaining path-hash jitter."""

        if strata < 2:
            raise ValueError("stratified sampling requires at least two strata")
        if not math.isfinite(low) or not math.isfinite(high) or not low < high:
            raise ValueError(f"invalid legal range for {path}.{parameter}: [{low}, {high}]")
        key = f"{path}.{parameter}"
        if key in self._keys:
            raise ValueError(f"duplicate sample key: {key}")
        offset_digest = hashlib.sha256(
            f"{SAMPLER_ID}|stratum-offset|{key}".encode("utf-8")
        ).digest()
        offset = int.from_bytes(offset_digest[:8], "big") % strata
        jitter_digest = hashlib.sha256(
            f"{SAMPLER_ID}|{self.seed}|stratum-jitter|{key}".encode("utf-8")
        ).digest()
        jitter = int.from_bytes(jitter_digest[:8], "big") / float(2**64 - 1)
        stratum = (self.seed + offset) % strata
        u = (stratum + 0.10 + 0.80 * jitter) / strata
        value = low + (high - low) * u
        self._keys.add(key)
        self.records.append(SampleRecord(key, low, high, u, value))
        return value

    def keys_with_prefix(self, prefix: str) -> tuple[str, ...]:
        return tuple(row.key for row in self.records if row.key.startswith(prefix))


def _curve_visible_envelope(nodes: Sequence[HierarchyCurve]) -> tuple[float, float, float, float]:
    points_with_width = [
        (point, node.curve.width * 0.5)
        for node in nodes
        for point in node.curve.points(96)
    ]
    return (
        min(point[0] - half_width for point, half_width in points_with_width),
        min(point[1] - half_width for point, half_width in points_with_width),
        max(point[0] + half_width for point, half_width in points_with_width),
        max(point[1] + half_width for point, half_width in points_with_width),
    )


def _secondary_curve_id(unit_id: str, slot: str) -> str:
    return f"secondary_{UNIT_NUMBER[unit_id]}_{slot}"


def _tertiary_curve_id(unit_id: str, parent_slot: str) -> str:
    return f"tertiary_{UNIT_NUMBER[unit_id]}_{parent_slot}_t1"


def _validate_controls(controls: RecursiveControls) -> None:
    if controls.max_depth != 3:
        raise ValueError("the first recursive experiment fixes maximum depth at 3")
    if controls.secondary_count != 12:
        raise ValueError("the first recursive experiment fixes 12 secondary branches")
    if (controls.tertiary_min, controls.tertiary_max) != (6, 9):
        raise ValueError("the first recursive experiment fixes the tertiary range at [6, 9]")
    if controls.max_tertiary_per_secondary != 1:
        raise ValueError("each secondary may carry at most one tertiary")
    if controls.max_tertiary_per_unit != 2:
        raise ValueError("each unit may carry at most two tertiary branches")
    if controls.max_short_per_unit != 1:
        raise ValueError("each unit may carry at most one short descendant")


def _primary_rows(
    p0: StrictP0,
    seed: int,
    sampler: _Sampler,
) -> tuple[PrimaryPlan, ...]:
    """Reuse the established seven primary roles but terminate free primaries inside."""

    legacy_plan = base.plan_j0a(p0, seed)
    rows: list[PrimaryPlan] = []
    for row in legacy_plan.primaries:
        if row.kind == "flower":
            rows.append(row)
            continue
        path = f"unit.{UNIT_NUMBER[row.curve_id]}.primary"
        scale = sampler.sample(path, "interior_length_scale", 0.68, 0.86)
        release = sampler.sample(path, "exit_release_degrees", 18.0, 34.0)
        rows.append(
            replace(
                row,
                target_boundary=None,
                target_point=None,
                terminal_tangent=None,
                chord_length=row.chord_length * scale,
                exit_release_degrees=release,
            )
        )
    return tuple(rows)


def plan_recursive(
    p0: StrictP0,
    seed: int,
    controls: RecursiveControls = RecursiveControls(),
) -> RecursivePlan:
    """Plan one bounded recursive hierarchy without search or validation feedback."""

    _validate_controls(controls)
    sampler = _Sampler(int(seed))
    global_length_scale = sampler.sample("scene", "descendant_length_scale", 0.90, 1.10)
    context_strength = sampler.sample("scene", "context_strength_degrees", 4.0, 10.0)
    tertiary_selector = sampler.sample_stratified(
        "scene", "tertiary_count_selector", 0.0, 1.0, 4
    )
    tertiary_count = controls.tertiary_min + min(
        controls.tertiary_max - controls.tertiary_min,
        int(tertiary_selector * (controls.tertiary_max - controls.tertiary_min + 1)),
    )

    primaries = _primary_rows(p0, int(seed), sampler)
    primary_previews = {
        row.curve_id: base._compile_primary(p0, row)  # noqa: SLF001 - intentional geometry reuse
        for row in primaries
    }

    descendants: list[ChildPlan] = []
    metadata: list[RecursiveNodeMeta] = []
    secondary_previews: dict[str, HierarchyCurve] = {}
    secondary_slot_by_id: dict[str, str] = {}
    unit_secondary_ids: dict[str, list[str]] = {unit_id: [] for unit_id in UNIT_ORDER}
    context_drafts: list[dict[str, object]] = []
    previous_unit_id: str | None = None
    previous_envelope: tuple[float, float, float, float] | None = None

    for unit_id in UNIT_ORDER:
        primary = primary_previews[unit_id]
        primary_points = primary.curve.points(96)
        primary_center_y = sum(point[1] for point in primary_points) / len(primary_points)
        if controls.context_enabled and previous_envelope is not None:
            previous_center_y = 0.5 * (previous_envelope[1] + previous_envelope[3])
            direction_bias = context_strength if previous_center_y <= primary_center_y else -context_strength
        else:
            direction_bias = 0.0

        unit_nodes: list[HierarchyCurve] = [primary]
        angle_ranges: list[tuple[str, float, float]] = []
        templates = SECONDARY_TEMPLATES[unit_id]
        for slot_index, (slot, base_angle_range, base_length_range) in enumerate(templates):
            curve_id = _secondary_curve_id(unit_id, slot)
            path = f"unit.{UNIT_NUMBER[unit_id]}.{slot}"
            if len(templates) == 2:
                mount_range = (0.24, 0.42) if slot_index == 0 else (0.54, 0.72)
            else:
                mount_range = (0.42, 0.70)
            mount_fraction = sampler.sample(path, "mount_fraction", *mount_range)
            angle_low = base_angle_range[0] + direction_bias
            angle_high = base_angle_range[1] + direction_bias
            travel_angle = sampler.sample(path, "travel_angle_degrees", angle_low, angle_high)
            length_low = base_length_range[0] * global_length_scale
            length_high = base_length_range[1] * global_length_scale
            chord_length = sampler.sample(path, "chord_length", length_low, length_high)
            entry_opening = sampler.sample(path, "entry_opening_degrees", 8.0, 15.0)
            handle_ratio = sampler.sample(path, "handle_ratio", 0.25, 0.38)
            exit_release = sampler.sample(path, "exit_release_degrees", 18.0, 34.0)
            mode_u = sampler.sample(path, "bend_mode_selector", 0.0, 1.0)
            travel_direction = (
                math.cos(math.radians(travel_angle)),
                math.sin(math.radians(travel_angle)),
            )
            parent_root, parent_tangent = sample_polyline(
                primary.curve.points(192), mount_fraction
            )
            del parent_root
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
                bend_mode="C" if mode_u < 0.60 else "S",
            )
            preview = base._compile_child(primary, row)  # noqa: SLF001
            descendants.append(row)
            secondary_previews[curve_id] = preview
            secondary_slot_by_id[curve_id] = slot
            unit_secondary_ids[unit_id].append(curve_id)
            unit_nodes.append(preview)
            angle_ranges.append((slot, angle_low, angle_high))
            metadata.append(
                RecursiveNodeMeta(
                    curve_id=curve_id,
                    unit_id=unit_id,
                    path=f"P{UNIT_NUMBER[unit_id]}/{slot.upper()}",
                    level=2,
                    parent_id=unit_id,
                    edge_goal=None,
                    terminal_role="recursive_parent_candidate",
                    is_edge_heir=False,
                    sample_keys=sampler.keys_with_prefix(path + "."),
                )
            )

        resulting_envelope = _curve_visible_envelope(unit_nodes)
        context_drafts.append(
            {
                "unit_id": unit_id,
                "previous_unit_id": previous_unit_id,
                "previous_visible_envelope": previous_envelope,
                "current_primary_center_y": primary_center_y,
                "direction_bias_degrees": direction_bias,
                "secondary_angle_ranges": tuple(angle_ranges),
                "resulting_visible_envelope": resulting_envelope,
            }
        )
        previous_unit_id = unit_id
        previous_envelope = resulting_envelope

    if len(descendants) != controls.secondary_count:
        raise AssertionError("secondary planning did not realize its declared budget")

    envelope_plan = base._global_envelope_values(p0, int(seed))  # noqa: SLF001
    edge_slots: list[EdgeSlot] = []
    occupied_secondary_ids: set[str] = set()

    # Every free Unit passes its edge goal to one tertiary leaf.
    for unit_id in FREE_UNITS:
        unit_number = UNIT_NUMBER[unit_id]
        path = f"unit.{unit_number}.edge"
        parent_selector = sampler.sample(path, "parent_slot_selector", 0.0, 1.0)
        parent_ids = unit_secondary_ids[unit_id]
        parent_id = parent_ids[min(len(parent_ids) - 1, int(parent_selector * len(parent_ids)))]
        parent_slot = secondary_slot_by_id[parent_id]
        curve_id = _tertiary_curve_id(unit_id, parent_slot)
        side, x_low, x_high = EDGE_SLOT_RANGES[unit_id]
        target_x = sampler.sample(path, "target_x", x_low, x_high)
        target_y = (
            envelope_plan["envelope_top_y"] + 0.5 * TERTIARY_WIDTH
            if side == "top_frontier"
            else envelope_plan["envelope_bottom_y"] - 0.5 * TERTIARY_WIDTH
        )
        target_point = (target_x, target_y)
        mount_fraction = sampler.sample(path, "mount_fraction", 0.38, 0.68)
        entry_opening = sampler.sample(path, "entry_opening_degrees", 8.0, 15.0)
        handle_ratio = sampler.sample(path, "handle_ratio", 0.24, 0.36)
        parent = secondary_previews[parent_id]
        root, tangent = sample_polyline(parent.curve.points(192), mount_fraction)
        direction = _unit(sub(target_point, root))
        turn = _signed_angle(tangent, direction)
        terminal_tangent = (1.0, 0.0) if target_x >= root[0] else (-1.0, 0.0)
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
        metadata = [
            replace(
                meta,
                edge_goal=side,
                terminal_role="edge_parent",
            )
            if meta.curve_id == parent_id
            else meta
            for meta in metadata
        ]
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

    # Rank all unused secondary slots once.  The selected prefix supplies the
    # remaining 1..4 tertiary branches without retry or resampling.
    extra_needed = tertiary_count - len(FREE_UNITS)
    ranked_extra_parents: list[tuple[float, str, str]] = []
    for unit_id in UNIT_ORDER:
        for parent_id in unit_secondary_ids[unit_id]:
            if parent_id in occupied_secondary_ids:
                continue
            parent_slot = secondary_slot_by_id[parent_id]
            priority = sampler.sample(
                f"unit.{UNIT_NUMBER[unit_id]}.{parent_slot}.extra",
                "selection_priority",
                0.0,
                1.0,
            )
            ranked_extra_parents.append((priority, unit_id, parent_id))
    ranked_extra_parents.sort(key=lambda item: (-item[0], item[1], item[2]))

    tertiary_per_unit = {unit_id: int(unit_id in FREE_UNITS) for unit_id in UNIT_ORDER}
    selected_extra: list[tuple[str, str]] = []
    for _, unit_id, parent_id in ranked_extra_parents:
        if len(selected_extra) >= extra_needed:
            break
        if tertiary_per_unit[unit_id] >= controls.max_tertiary_per_unit:
            continue
        selected_extra.append((unit_id, parent_id))
        tertiary_per_unit[unit_id] += 1
        occupied_secondary_ids.add(parent_id)
    if len(selected_extra) != extra_needed:
        raise AssertionError("tertiary allocation exhausted its legal slots")

    for unit_id, parent_id in selected_extra:
        unit_number = UNIT_NUMBER[unit_id]
        parent_slot = secondary_slot_by_id[parent_id]
        path = f"unit.{unit_number}.{parent_slot}.extra"
        curve_id = _tertiary_curve_id(unit_id, parent_slot)
        parent = secondary_previews[parent_id]
        mount_fraction = sampler.sample(path, "mount_fraction", 0.36, 0.66)
        root, tangent = sample_polyline(parent.curve.points(192), mount_fraction)
        side_u = sampler.sample(path, "turn_side_selector", 0.0, 1.0)
        turn_sign = -1 if side_u < 0.5 else 1
        turn_degrees = sampler.sample(path, "turn_degrees", 40.0, 85.0)
        travel_direction = _unit(rotate(tangent, turn_sign * turn_degrees))
        length_low = max(20.0, 0.38 * parent.curve.length)
        length_high = max(length_low + 4.0, min(38.0, 0.64 * parent.curve.length))
        chord_length = sampler.sample(path, "chord_length", length_low, length_high)
        entry_opening = sampler.sample(path, "entry_opening_degrees", 8.0, 15.0)
        handle_ratio = sampler.sample(path, "handle_ratio", 0.24, 0.37)
        exit_release = sampler.sample(path, "exit_release_degrees", 20.0, 34.0)
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
            bend_mode="C" if mode_u < 0.60 else "S",
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

    slots_by_unit = {row.unit_id: row for row in edge_slots}
    contexts: list[NeighborContextRecord] = []
    occupied_slot_labels: list[str] = []
    for draft in context_drafts:
        unit_id = str(draft["unit_id"])
        before = tuple(occupied_slot_labels)
        if unit_id in slots_by_unit:
            occupied_slot_labels.append(
                f"{slots_by_unit[unit_id].side}@{slots_by_unit[unit_id].target_point[0]:.4f}"
            )
        contexts.append(
            NeighborContextRecord(
                unit_id=unit_id,
                previous_unit_id=(
                    None
                    if draft["previous_unit_id"] is None
                    else str(draft["previous_unit_id"])
                ),
                previous_visible_envelope=draft["previous_visible_envelope"],  # type: ignore[arg-type]
                current_primary_center_y=float(draft["current_primary_center_y"]),
                direction_bias_degrees=float(draft["direction_bias_degrees"]),
                secondary_angle_ranges=draft["secondary_angle_ranges"],  # type: ignore[arg-type]
                resulting_visible_envelope=draft["resulting_visible_envelope"],  # type: ignore[arg-type]
                edge_slots_before=before,
                edge_slots_after=tuple(occupied_slot_labels),
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
        contexts=tuple(contexts),
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
    """Compile by explicit parent links; descendant IDs carry no routing semantics."""

    primary_by_id = {row.curve_id: row for row in plan.primaries}
    descendant_by_id = {row.curve_id: row for row in plan.descendants}
    all_ids = [row.curve_id for row in plan.primaries] + [
        row.curve_id for row in plan.descendants
    ]
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("curve IDs must be globally unique")
    if len(primary_by_id) != len(plan.primaries) or len(descendant_by_id) != len(plan.descendants):
        raise ValueError("duplicate plan rows")

    order = tuple(traversal_order or [row.curve_id for row in plan.primaries])
    if set(order) != set(primary_by_id) or len(order) != len(primary_by_id):
        raise ValueError("traversal_order must contain every primary exactly once")

    generated: dict[str, HierarchyCurve] = {}
    for primary_id in order:
        generated[primary_id] = base._compile_primary(  # noqa: SLF001
            p0, primary_by_id[primary_id]
        )

    children_by_parent: dict[str, list[ChildPlan]] = {}
    for row in plan.descendants:
        children_by_parent.setdefault(row.parent_id, []).append(row)

    def compile_children(parent_id: str) -> None:
        parent = generated[parent_id]
        children = sorted(
            children_by_parent.get(parent_id, []), key=lambda item: item.curve_id
        )
        if children and parent.level >= plan.controls.max_depth:
            raise ValueError(f"children exceed maximum depth below {parent_id}")
        for row in children:
            parent = generated.get(row.parent_id)
            if parent is None:
                raise ValueError(
                    f"missing or later-level parent {row.parent_id} for {row.curve_id}"
                )
            if row.level != parent.level + 1:
                raise ValueError(
                    f"non-adjacent hierarchy level for {row.curve_id}: "
                    f"parent={parent.level}, child={row.level}"
                )
            generated[row.curve_id] = base._compile_child(parent, row)  # noqa: SLF001
            compile_children(row.curve_id)

    for primary_id in order:
        compile_children(primary_id)

    if len(generated) != len(all_ids):
        uncompiled = sorted(set(all_ids) - set(generated))
        raise ValueError(f"uncompiled plan rows: {uncompiled}")
    return RecursiveResult(
        plan,
        tuple(sorted(generated.values(), key=lambda item: item.curve.curve_id)),
    )


def build_recursive(
    p0: StrictP0,
    seed: int,
    controls: RecursiveControls = RecursiveControls(),
    traversal_order: Sequence[str] | None = None,
) -> RecursiveResult:
    return compile_plan(plan_recursive(p0, seed, controls), p0, traversal_order)


def _root_unit(
    curve_id: str,
    primary_ids: set[str],
    child_by_id: Mapping[str, ChildPlan],
) -> str:
    seen: set[str] = set()
    current = curve_id
    while current not in primary_ids:
        if current in seen:
            raise ValueError(f"cycle while resolving unit for {curve_id}")
        seen.add(current)
        row = child_by_id.get(current)
        if row is None:
            raise ValueError(f"orphan curve while resolving unit for {curve_id}")
        current = row.parent_id
    return current


def validate_result(p0: StrictP0, result: RecursiveResult) -> dict[str, object]:
    """Check the actual recursive graph and geometry without mutation or repair."""

    before = result.geometry_hash
    issues: list[str] = []
    plan = result.plan
    nodes = result.by_id
    primary_by_id = {row.curve_id: row for row in plan.primaries}
    child_by_id = {row.curve_id: row for row in plan.descendants}
    metadata_by_id = plan.metadata_by_id
    primary_ids = set(primary_by_id)
    level_rows = {
        level: [node for node in result.curves if node.level == level]
        for level in range(1, plan.controls.max_depth + 1)
    }
    level_counts = {level: len(rows) for level, rows in level_rows.items()}

    if level_counts.get(1) != 7:
        issues.append("primary_count_not_7")
    if level_counts.get(2) != plan.controls.secondary_count:
        issues.append("secondary_count_not_12")
    if not plan.controls.tertiary_min <= level_counts.get(3, 0) <= plan.controls.tertiary_max:
        issues.append("tertiary_count_outside_6_9")
    if max((node.level for node in result.curves), default=0) > plan.controls.max_depth:
        issues.append("maximum_depth_exceeded")
    if primary_ids != set(UNIT_ORDER):
        issues.append("unexpected_primary_id_set")
    if len(nodes) != len(result.curves):
        issues.append("duplicate_curve_ids")
    if set(child_by_id) != set(metadata_by_id):
        issues.append("descendant_metadata_mismatch")
    if any(node.source != "program_generated" for node in result.curves):
        issues.append("non_program_generated_curve")

    units_by_curve: dict[str, str] = {}
    for row in plan.descendants:
        if row.parent_id not in nodes:
            issues.append(f"{row.curve_id}:missing_parent")
            continue
        if row.level != nodes[row.parent_id].level + 1:
            issues.append(f"{row.curve_id}:non_adjacent_level")
        try:
            unit_id = _root_unit(row.curve_id, primary_ids, child_by_id)
        except ValueError as error:
            issues.append(str(error))
            continue
        units_by_curve[row.curve_id] = unit_id
        meta = metadata_by_id.get(row.curve_id)
        if meta is not None and (meta.unit_id != unit_id or meta.parent_id != row.parent_id):
            issues.append(f"{row.curve_id}:metadata_parent_or_unit_mismatch")

    secondary_rows = [row for row in plan.descendants if row.level == 2]
    tertiary_rows = [row for row in plan.descendants if row.level == 3]
    secondary_child_counts = {
        row.curve_id: sum(child.parent_id == row.curve_id for child in tertiary_rows)
        for row in secondary_rows
    }
    if any(
        count > plan.controls.max_tertiary_per_secondary
        for count in secondary_child_counts.values()
    ):
        issues.append("tertiary_per_secondary_budget_exceeded")
    tertiary_per_unit = {
        unit_id: sum(units_by_curve.get(row.curve_id) == unit_id for row in tertiary_rows)
        for unit_id in UNIT_ORDER
    }
    if any(
        count > plan.controls.max_tertiary_per_unit
        for count in tertiary_per_unit.values()
    ):
        issues.append("tertiary_per_unit_budget_exceeded")
    if any(tertiary_per_unit[unit_id] < 1 for unit_id in FREE_UNITS):
        issues.append("free_unit_missing_tertiary")

    edge_heirs = [meta for meta in plan.node_metadata if meta.is_edge_heir]
    edge_parents = [
        meta
        for meta in plan.node_metadata
        if meta.level == 2 and meta.edge_goal is not None
    ]
    if len(edge_heirs) != len(FREE_UNITS):
        issues.append("edge_heir_count_not_5")
    if {meta.unit_id for meta in edge_heirs} != set(FREE_UNITS):
        issues.append("edge_heir_free_unit_coverage")
    if len(edge_parents) != len(FREE_UNITS) or {
        meta.unit_id for meta in edge_parents
    } != set(FREE_UNITS):
        issues.append("edge_parent_free_unit_coverage")
    for meta in edge_heirs:
        row = child_by_id.get(meta.curve_id)
        if row is None or row.level != 3:
            issues.append(f"{meta.curve_id}:edge_heir_not_tertiary")
            continue
        if any(child.parent_id == row.curve_id for child in plan.descendants):
            issues.append(f"{meta.curve_id}:edge_heir_not_leaf")
        if row.target_boundary != meta.edge_goal or row.target_point is None:
            issues.append(f"{meta.curve_id}:edge_goal_not_realized")
        parent_meta = metadata_by_id.get(row.parent_id)
        if parent_meta is None or parent_meta.edge_goal != meta.edge_goal:
            issues.append(f"{meta.curve_id}:edge_goal_not_inherited_from_parent")
    if len(plan.edge_slots) != 5:
        issues.append("edge_slot_count_not_5")
    if {slot.inherited_by for slot in plan.edge_slots} != {
        meta.curve_id for meta in edge_heirs
    }:
        issues.append("edge_slot_heir_mismatch")

    sample_by_key = {row.key: row for row in plan.samples}
    if len(sample_by_key) != len(plan.samples):
        issues.append("duplicate_sample_keys")
    for row in plan.samples:
        expected = row.low + (row.high - row.low) * row.u
        if not row.low < row.high:
            issues.append(f"{row.key}:invalid_sample_range")
        if not 0.0 <= row.u <= 1.0:
            issues.append(f"{row.key}:sample_u_out_of_range")
        if abs(row.value - expected) > 1e-10:
            issues.append(f"{row.key}:sample_mapping_error")
    if any(
        key not in sample_by_key
        for meta in plan.node_metadata
        for key in meta.sample_keys
    ):
        issues.append("node_references_missing_sample")
    count_record = sample_by_key.get("scene.tertiary_count_selector")
    if count_record is None:
        issues.append("missing_tertiary_count_sample")
    else:
        expected_count = plan.controls.tertiary_min + min(
            plan.controls.tertiary_max - plan.controls.tertiary_min,
            int(
                count_record.value
                * (plan.controls.tertiary_max - plan.controls.tertiary_min + 1)
            ),
        )
        if expected_count != len(tertiary_rows):
            issues.append("tertiary_count_not_replayed_from_sample")

    if len(plan.contexts) != len(UNIT_ORDER):
        issues.append("neighbor_context_count_not_7")
    for index, context in enumerate(plan.contexts):
        expected_previous = None if index == 0 else UNIT_ORDER[index - 1]
        if context.unit_id != UNIT_ORDER[index] or context.previous_unit_id != expected_previous:
            issues.append(f"{context.unit_id}:neighbor_context_order")
        if plan.controls.context_enabled and index > 0:
            if context.previous_visible_envelope is None:
                issues.append(f"{context.unit_id}:missing_previous_envelope")
            elif abs(context.direction_bias_degrees) < 1e-9:
                issues.append(f"{context.unit_id}:context_not_applied")

    envelope_top = plan.style_latents["envelope_top_y"]
    envelope_bottom = plan.style_latents["envelope_bottom_y"]
    per_curve: list[dict[str, object]] = []
    short_by_unit = {unit_id: 0 for unit_id in UNIT_ORDER}
    descendant_roots: list[tuple[str, Point]] = []

    for node in result.curves:
        curve = node.curve
        points = curve.points(192)
        branch_issues: list[str] = []
        if node.level == 1:
            expected_root, parent_tangent = sample_polyline(
                p0.backbone_points, float(curve.mount_fraction)
            )
            planned_row: PrimaryPlan | ChildPlan = primary_by_id[curve.curve_id]
        else:
            parent = nodes.get(curve.parent_id)
            if parent is None:
                continue
            expected_root, parent_tangent = sample_polyline(
                parent.curve.points(192), float(curve.mount_fraction)
            )
            planned_row = child_by_id[curve.curve_id]
            descendant_roots.append((curve.curve_id, curve.root))
        root_error = dist(curve.root, expected_root)
        if root_error > 0.5:
            branch_issues.append("root_off_parent")
        entry_error = angle_degrees(curve.entry_tangent, parent_tangent)
        if node.level > 1:
            child_row = child_by_id[curve.curve_id]
            if abs(entry_error - child_row.entry_opening_degrees) > 0.5:
                branch_issues.append("entry_opening_differs_from_plan")
            if not 8.0 - 1e-6 <= entry_error <= 15.0 + 1e-6:
                branch_issues.append("entry_opening_outside_8_15")

        audit = base.legacy.bend_audit(curve)
        sagitta = base._normalized_sagitta(curve)  # noqa: SLF001
        if int(audit["bend_count"]) > 2 or int(audit["curvature_sign_reversal_count"]) > 1:
            branch_issues.append("bend_count_over_2")
        if len(curve.cubics) > 2:
            branch_issues.append("cubic_segment_count_over_2")
        if sagitta > 0.25:
            branch_issues.append("curvature_too_large")
        if base._self_intersects(points):  # noqa: SLF001
            branch_issues.append("self_intersection")
        if any(
            dist(cubic.p0, cubic.p1) <= 1e-8 or dist(cubic.p2, cubic.p3) <= 1e-8
            for cubic in curve.cubics
        ):
            branch_issues.append("degenerate_derivative")

        extrema = base._curve_exact_extrema(curve)  # noqa: SLF001
        half_width = 0.5 * curve.width
        if (
            extrema["left"] < p0.repeat_x_range[0] + half_width
            or extrema["right"] > p0.repeat_x_range[1] - half_width
            or extrema["top"] < half_width
            or extrema["bottom"] > p0.canvas_height - half_width
        ):
            branch_issues.append("out_of_bounds")

        registered_boundary = planned_row.target_boundary
        if registered_boundary is not None:
            if planned_row.target_point is None or dist(curve.tip, planned_row.target_point) > 1e-5:
                branch_issues.append("edge_target_point_error")
            expected_y = (
                envelope_top + half_width
                if registered_boundary == "top_frontier"
                else envelope_bottom - half_width
            )
            if abs(curve.tip[1] - expected_y) > 0.5:
                branch_issues.append("edge_band_error")
            if min(
                angle_degrees(curve.exit_tangent, (-1.0, 0.0)),
                angle_degrees(curve.exit_tangent, (1.0, 0.0)),
            ) > 5.0:
                branch_issues.append("edge_exit_not_parallel")

        for flower in p0.flowers:
            values = [base._ellipse_value(point, flower) for point in points]  # noqa: SLF001
            if node.target_flower_id == flower.flower_id:
                if any(value < 1.0 for value in values[: max(1, int(0.90 * len(values)))]):
                    branch_issues.append(f"early_flower_intrusion:{flower.flower_id}")
                if abs(values[-1] - 1.0) > 2e-5:
                    branch_issues.append(f"flower_collar_error:{flower.flower_id}")
            elif any(value < 1.0 for value in values):
                branch_issues.append(f"flower_intrusion:{flower.flower_id}")

        parent_points = (
            p0.backbone_points
            if node.level == 1
            else nodes[curve.parent_id].curve.points(192)
        )
        contact_zone = min(10.0 if node.level == 1 else 8.0, 0.75 * curve.length)
        cumulative = 0.0
        tail_index = 1
        for index, (first, second) in enumerate(zip(points, points[1:]), start=1):
            cumulative += dist(first, second)
            if cumulative >= contact_zone:
                tail_index = index
                break
        parent_clearance = min(
            (point_polyline_distance(point, parent_points) for point in points[tail_index:]),
            default=math.inf,
        )
        parent_width = 5.0 if node.level == 1 else nodes[curve.parent_id].curve.width
        required_parent_clearance = 0.5 * (curve.width + parent_width) + 0.8
        if parent_clearance < required_parent_clearance:
            branch_issues.append("parent_recontact")

        if node.level > 1:
            parent_length = nodes[curve.parent_id].curve.length
            is_short = curve.length < max(18.0, 0.30 * parent_length)
            if is_short:
                short_by_unit[units_by_curve[curve.curve_id]] += 1

        for issue in branch_issues:
            issues.append(f"{curve.curve_id}:{issue}")
        per_curve.append(
            {
                "curve_id": curve.curve_id,
                "level": node.level,
                "parent_id": curve.parent_id,
                "root_error": round(root_error, 8),
                "entry_opening_degrees": round(entry_error, 8),
                "normalized_sagitta": round(sagitta, 8),
                "parent_clearance": round(parent_clearance, 8),
                "required_parent_clearance": round(required_parent_clearance, 8),
                "issues": branch_issues,
            }
        )

    if any(
        count > plan.controls.max_short_per_unit for count in short_by_unit.values()
    ):
        issues.append("short_branch_unit_budget_exceeded")
    dense_root_clusters: list[list[str]] = []
    for curve_id, root in descendant_roots:
        nearby = sorted(
            other_id
            for other_id, other_root in descendant_roots
            if dist(root, other_root) < 24.0
        )
        if len(nearby) >= 3 and nearby not in dense_root_clusters:
            dense_root_clusters.append(nearby)
    if dense_root_clusters:
        issues.append("dense_descendant_root_cluster")

    pair_clearances: list[dict[str, object]] = []
    curves = list(result.curves)
    for first_index, first in enumerate(curves):
        for second in curves[first_index + 1 :]:
            parent_child = (
                first.curve.parent_id == second.curve.curve_id
                or second.curve.parent_id == first.curve.curve_id
            )
            child = first if first.level > second.level else second
            allowed_contact = child.curve.root if parent_child else None
            contact_radius = min(8.0, 0.75 * child.curve.length) if parent_child else 0.0
            required = 0.5 * (first.curve.width + second.curve.width) + 1.0
            first_box = base._curve_exact_extrema(first.curve)  # noqa: SLF001
            second_box = base._curve_exact_extrema(second.curve)  # noqa: SLF001
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
                method = "exact_bbox_certificate"
            else:
                minimum = polyline_pair_distance(
                    first.curve.points(96),
                    second.curve.points(96),
                    allowed_contact=allowed_contact,
                    contact_radius=contact_radius,
                )
                method = "sampled_polyline_96"
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
                    "method": method,
                }
            )

    after = result.geometry_hash
    if before != after:
        issues.append("validation_mutated_geometry")
    return {
        "valid": not issues,
        "issues": list(dict.fromkeys(issues)),
        "diagnostics": {
            "check_only": True,
            "geometry_hash_before_check": before,
            "geometry_hash_after_check": after,
            "geometry_unchanged": before == after,
            "topology_counts": {str(key): value for key, value in level_counts.items()},
            "tertiary_per_unit": tertiary_per_unit,
            "tertiary_per_secondary": secondary_child_counts,
            "short_branches_per_unit": short_by_unit,
            "dense_root_clusters": dense_root_clusters,
            "per_curve": per_curve,
            "pair_clearances": pair_clearances,
            "generation_policy": plan.as_dict()["generation_policy"],
        },
    }


def seed_variation_proof(
    p0: StrictP0,
    seeds: Sequence[int] = DEV_SEEDS,
) -> dict[str, object]:
    """Replay and compare dynamic topology without assuming identical tertiary IDs."""

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
            sorted(
                row.curve_id
                for row in results[seed].plan.descendants
                if row.level == 3
            )
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
                    "secondary_mount_count_delta_ge_0_04": sum(
                        value >= 0.04 for value in mount_changes
                    ),
                    "secondary_direction_count_delta_ge_12deg": sum(
                        value >= 12.0 for value in direction_changes
                    ),
                    "secondary_length_count_delta_ge_0_15": sum(
                        value >= 0.15 for value in length_changes
                    ),
                    "tertiary_slot_symmetric_difference": sorted(
                        set(topology_signatures[first_seed])
                        ^ set(topology_signatures[second_seed])
                    ),
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
            str(seed): len(topology_signatures[seed]) for seed in seed_tuple
        },
        "tertiary_slot_sets": {
            str(seed): list(topology_signatures[seed]) for seed in seed_tuple
        },
        "validation_passes": {
            str(seed): validations[seed]["valid"] for seed in seed_tuple
        },
        "pairwise": pairwise,
        "passes": (
            all(replay_by_seed.values())
            and len({result.geometry_hash for result in results.values()}) == len(seed_tuple)
            and len({result.plan.digest for result in results.values()}) == len(seed_tuple)
            and all(
                6 <= len(topology_signatures[seed]) <= 9 for seed in seed_tuple
            )
            and all(validation["valid"] for validation in validations.values())
        ),
    }


def _default_profile_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "artifacts"
        / "runs"
        / "run57_reproduction"
        / "01_skeleton_analysis"
        / "proto_sw_1_3"
        / "skeleton_profile.json"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=_default_profile_path())
    parser.add_argument("--seed", type=int, default=DEV_SEEDS[0])
    parser.add_argument("--full-json", action="store_true")
    args = parser.parse_args(argv)
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    p0 = strip_profile(profile)
    result = build_recursive(p0, args.seed)
    validation = validate_result(p0, result)
    payload: object
    if args.full_json:
        payload = {"result": result.as_dict(), "validation": validation}
    else:
        payload = {
            "seed": args.seed,
            "plan_id": result.plan.plan_id,
            "plan_digest": result.plan.digest,
            "geometry_hash": result.geometry_hash,
            "topology": result.as_dict()["topology"],
            "valid": validation["valid"],
            "issues": validation["issues"],
            "generation_policy": result.plan.as_dict()["generation_policy"],
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEV_SEEDS",
    "GEOMETRY_KERNEL_ID",
    "PLAN_ID",
    "POLICY_ID",
    "EdgeSlot",
    "NeighborContextRecord",
    "RecursiveControls",
    "RecursiveNodeMeta",
    "RecursivePlan",
    "RecursiveResult",
    "SampleRecord",
    "StrictP0",
    "build_recursive",
    "compile_plan",
    "plan_recursive",
    "seed_variation_proof",
    "strip_profile",
    "validate_result",
]
