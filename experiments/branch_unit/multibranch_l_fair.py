#!/usr/bin/env python3
"""Pure-L multi-branch comparison with one shared cross-branch layout.

All four/five branches use identical roots, roles, endpoints, widths, topology,
and raw token rows in L0/L1.  The only changed factor is how the two cubic
segments *inside each branch* are parameterized: independent component mapping
versus one joint branch mapping.  Neither variant reads sibling geometry.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Sequence

import multibranch_l as base
from l_core import Cubic, Curve, Point, add, cross, dist, dot, mul, sample_polyline, sub


GEOMETRY_KERNEL_ID = "multibranch_l_pure_local_shared_layout_v1"
LAYOUT_ID = "proto_sw_1_3_shared_four_five_branch_layout_v1"


def _unit(vector: Point) -> Point:
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-12:
        return (1.0, 0.0)
    return (vector[0] / length, vector[1] / length)


def _normal(vector: Point) -> Point:
    return (-vector[1], vector[0])


def _angle(vector: Point) -> float:
    return math.degrees(math.atan2(vector[1], vector[0]))


def _vector(angle_degrees: float) -> Point:
    radians = math.radians(angle_degrees)
    return (math.cos(radians), math.sin(radians))


def _wrap(angle_degrees: float) -> float:
    return (angle_degrees + 180.0) % 360.0 - 180.0


def _digest(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SharedBranchLayout:
    role: base.BranchRole
    mount_s: float
    root: Point
    endpoint: Point
    entry_tangent: Point
    exit_tangent: Point
    side_sign: int

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role.as_dict(),
            "mount_s": round(self.mount_s, 10),
            "root": [round(value, 8) for value in self.root],
            "endpoint": [round(value, 8) for value in self.endpoint],
            "entry_tangent": [round(value, 8) for value in self.entry_tangent],
            "exit_tangent": [round(value, 8) for value in self.exit_tangent],
            "side_sign": self.side_sign,
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _free_layout(
    p0: base.StrippedP0,
    role_id: str,
    mount_s: float,
    tangent_weight: float,
    normal_weight: float,
    chord_length: float,
) -> SharedBranchLayout:
    root, tangent = sample_polyline(p0.backbone_points, mount_s)
    normal = _normal(tangent)
    direction = _unit(add(mul(tangent, tangent_weight), mul(normal, normal_weight)))
    endpoint = add(root, mul(direction, chord_length))
    side_sign = 1 if cross(tangent, direction) >= 0.0 else -1
    return SharedBranchLayout(
        role=base.BranchRole(role_id, "free", None),
        mount_s=mount_s,
        root=root,
        endpoint=endpoint,
        entry_tangent=tangent,
        exit_tangent=direction,
        side_sign=side_sign,
    )


def shared_layout(p0: base.StrippedP0, branch_count: int) -> tuple[SharedBranchLayout, ...]:
    """One closed-form layout shared byte-for-byte by both variants.

    The constants are preregistered development offsets for proto_sw_1_3, not
    results of candidate enumeration or validation feedback.
    """

    if branch_count not in base.ALLOWED_BRANCH_COUNTS:
        raise ValueError("branch_count must be 4 or 5")
    flower_by_id = {flower.flower_id: flower for flower in p0.flowers}
    projection = {
        flower_id: base.flower_collar(p0, flower)[0]
        for flower_id, flower in flower_by_id.items()
    }
    flower_mounts = {
        "flower_1": _clamp(projection["flower_1"] - 0.194, 0.10, 0.90),
        "flower_2": _clamp(projection["flower_2"] + 0.103, 0.10, 0.90),
    }

    layouts: list[SharedBranchLayout] = []
    layouts.append(
        _free_layout(
            p0,
            "free_1_branch",
            mount_s=0.23,
            tangent_weight=0.60,
            normal_weight=0.40,
            chord_length=58.0,
        )
    )
    for flower_index in (1, 2):
        flower_id = f"flower_{flower_index}"
        flower = flower_by_id[flower_id]
        mount_s = flower_mounts[flower_id]
        _, collar = base.flower_collar(p0, flower)
        _, tangent = sample_polyline(p0.backbone_points, mount_s)
        chord = _unit(sub(collar, sample_polyline(p0.backbone_points, mount_s)[0]))
        layouts.append(
            SharedBranchLayout(
                role=base.BranchRole(f"flower_{flower_index}_branch", "flower", flower_id),
                mount_s=mount_s,
                root=sample_polyline(p0.backbone_points, mount_s)[0],
                endpoint=collar,
                entry_tangent=tangent,
                exit_tangent=_unit(sub(flower.center, collar)),
                side_sign=1 if cross(tangent, chord) >= 0.0 else -1,
            )
        )
    if branch_count == 5:
        middle_mount = _clamp(0.5 * (projection["flower_1"] + projection["flower_2"]) - 0.096, 0.44, 0.58)
        layouts.append(
            _free_layout(
                p0,
                "free_2_branch",
                mount_s=middle_mount,
                tangent_weight=0.25,
                normal_weight=0.75,
                chord_length=43.0,
            )
        )
        right_role = "free_3_branch"
    else:
        right_role = "free_2_branch"
    layouts.append(
        _free_layout(
            p0,
            right_role,
            mount_s=0.88,
            tangent_weight=0.28,
            normal_weight=-0.72,
            chord_length=61.0,
        )
    )
    layouts.sort(key=lambda item: item.role.role_id)
    if len(layouts) != branch_count:
        raise AssertionError("shared layout branch count drifted")
    return tuple(layouts)


@dataclass(frozen=True)
class InternalMapping:
    variant: str
    start_arm_ratio: float
    end_arm_ratio: float
    trace: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "variant": self.variant,
            "start_arm_ratio": round(self.start_arm_ratio, 10),
            "end_arm_ratio": round(self.end_arm_ratio, 10),
            "trace": self.trace,
        }


def map_l0_independent(
    layout: SharedBranchLayout,
    token: base.RawBranchToken,
) -> InternalMapping:
    return InternalMapping(
        variant="L0",
        start_arm_ratio=0.12 + 0.12 * token.turn_1,
        end_arm_ratio=0.12 + 0.12 * token.turn_2,
        trace={
            "mapping_id": "independent_entry_exit_arms_v2",
            "consumed_token_fields": ["turn_1", "turn_2"],
            "sibling_state_consumed": False,
            "validation_feedback_consumed": False,
        },
    )


def map_l1_joint(
    layout: SharedBranchLayout,
    token: base.RawBranchToken,
) -> InternalMapping:
    root = layout.root
    chord = sub(layout.endpoint, root)
    chord_angle = _angle(chord)
    entry_angle = _angle(layout.entry_tangent)
    exit_delta = _wrap(_angle(layout.exit_tangent) - entry_angle)
    exit_angle = entry_angle + exit_delta
    chord_unwrapped = entry_angle + _wrap(chord_angle - entry_angle)
    entry_demand = abs(chord_unwrapped - entry_angle)
    exit_demand = abs(exit_angle - chord_unwrapped)
    demand_balance = (exit_demand - entry_demand) / max(entry_demand + exit_demand, 1e-9)
    total_arm_ratio = 0.24 + 0.24 * (0.5 * token.turn_1 + 0.5 * token.turn_2)
    balance = _clamp(
        0.5 + 0.10 * (token.turn_1 - token.turn_2) + 0.10 * demand_balance,
        0.32,
        0.68,
    )
    return InternalMapping(
        variant="L1",
        start_arm_ratio=total_arm_ratio * balance,
        end_arm_ratio=total_arm_ratio * (1.0 - balance),
        trace={
            "mapping_id": "joint_total_arm_plus_balance_v2",
            "input_summary": {
                "entry_angle_degrees": round(entry_angle, 8),
                "chord_angle_unwrapped_degrees": round(chord_unwrapped, 8),
                "exit_angle_unwrapped_degrees": round(exit_angle, 8),
                "entry_turn_demand_degrees": round(entry_demand, 8),
                "exit_turn_demand_degrees": round(exit_demand, 8),
                "total_arm_ratio": round(total_arm_ratio, 8),
                "balance": round(balance, 8),
            },
            "consumed_token_fields": ["turn_1", "turn_2"],
            "sibling_state_consumed": False,
            "validation_feedback_consumed": False,
        },
    )


def compile_curve(
    layout: SharedBranchLayout,
    mapping: InternalMapping,
) -> tuple[Curve, dict[str, object]]:
    root = layout.root
    chord_length = dist(root, layout.endpoint)
    start_arm = chord_length * mapping.start_arm_ratio
    end_arm = chord_length * mapping.end_arm_ratio
    first_control = add(root, mul(layout.entry_tangent, start_arm))
    second_control = sub(layout.endpoint, mul(layout.exit_tangent, end_arm))
    midpoint = mul(add(first_control, second_control), 0.5)
    first = _elevated_quadratic(root, first_control, midpoint)
    second = _elevated_quadratic(midpoint, second_control, layout.endpoint)
    role = "flower_branch" if layout.role.kind == "flower" else "free_branch"
    provisional = Curve(
        curve_id=layout.role.role_id,
        role=role,
        parent_id="backbone",
        width=base.BRANCH_WIDTH,
        target_length=chord_length,
        cubics=(first, second),
        mount_fraction=layout.mount_s,
    )
    curve = Curve(
        curve_id=provisional.curve_id,
        role=provisional.role,
        parent_id=provisional.parent_id,
        width=provisional.width,
        target_length=provisional.length,
        cubics=provisional.cubics,
        mount_fraction=provisional.mount_fraction,
    )
    return curve, {
        "compiler": "two_c1_degree_elevated_quadratics_v2",
        "source": "program_generated",
        "layout_id": LAYOUT_ID,
        "mapping": mapping.as_dict(),
        "endpoint": [round(value, 8) for value in layout.endpoint],
        "start_arm": round(start_arm, 8),
        "end_arm": round(end_arm, 8),
        "quadratic_controls": [
            [round(value, 8) for value in first_control],
            [round(value, 8) for value in second_control],
        ],
    }


def _elevated_quadratic(start: Point, control: Point, end: Point) -> Cubic:
    return Cubic(
        p0=start,
        p1=add(start, mul(sub(control, start), 2.0 / 3.0)),
        p2=add(end, mul(sub(control, end), 2.0 / 3.0)),
        p3=end,
    )


def _build_variant(
    p0: base.StrippedP0,
    layouts: Sequence[SharedBranchLayout],
    tokens: Sequence[base.RawBranchToken],
    variant: str,
) -> base.BranchSet:
    branches: list[base.GeneratedBranch] = []
    mappings: dict[str, object] = {}
    for index, (layout, token) in enumerate(zip(layouts, tokens)):
        mapping = map_l0_independent(layout, token) if variant == "L0" else map_l1_joint(layout, token)
        curve, trace = compile_curve(layout, mapping)
        branches.append(
            base.GeneratedBranch(
                role=layout.role,
                source_token_index=index,
                curve=curve,
                planned_bend_count=2,
                compiler_trace=trace,
            )
        )
        mappings[layout.role.role_id] = mapping.as_dict()
    branches.sort(key=lambda branch: branch.role.role_id)
    return base.BranchSet(
        variant=variant,
        branches=tuple(branches),
        plan_trace={
            "mapping_scope": "inside_each_branch_only",
            "sibling_state_consumed": False,
            "shared_layout_id": LAYOUT_ID,
            "mappings": mappings,
            "generation_policy": {
                "candidate_count": 1,
                "retry_count": 0,
                "resample_count": 0,
                "repair_count": 0,
                "validation_feedback_consumed": False,
            },
        },
        target_role_lengths={branch.role.role_id: branch.curve.target_length for branch in branches},
    )


def fairness_metrics(
    layouts: Sequence[SharedBranchLayout],
    l0: base.BranchSet,
    l1: base.BranchSet,
) -> dict[str, object]:
    def symmetric(first: float, second: float) -> float:
        return abs(first - second) / max(0.5 * (abs(first) + abs(second)), 1e-12)

    by_role_l0 = {branch.role.role_id: branch for branch in l0.branches}
    by_role_l1 = {branch.role.role_id: branch for branch in l1.branches}
    role_rows: list[dict[str, object]] = []
    all_layout_equal = True
    all_geometry_changed = True
    max_role_delta = 0.0
    for layout in layouts:
        role_id = layout.role.role_id
        first = by_role_l0[role_id]
        second = by_role_l1[role_id]
        layout_equal = (
            first.curve.root == second.curve.root
            and first.curve.tip == second.curve.tip
            and first.curve.mount_fraction == second.curve.mount_fraction
            and first.curve.width == second.curve.width
            and first.curve.parent_id == second.curve.parent_id == "backbone"
        )
        changed = first.curve.as_dict() != second.curve.as_dict()
        length_delta = symmetric(first.curve.length, second.curve.length)
        max_role_delta = max(max_role_delta, length_delta)
        all_layout_equal = all_layout_equal and layout_equal
        all_geometry_changed = all_geometry_changed and changed
        role_rows.append(
            {
                "role_id": role_id,
                "shared_root_endpoint_mount_width": layout_equal,
                "geometry_changed": changed,
                "length_symmetric_delta": round(length_delta, 10),
            }
        )
    total_delta = symmetric(l0.total_length, l1.total_length)
    ink_delta = symmetric(l0.vector_ink, l1.vector_ink)
    return {
        "shared_layout_id": LAYOUT_ID,
        "all_roots_endpoints_mounts_widths_equal": all_layout_equal,
        "all_branches_participate_in_comparison": all_geometry_changed,
        "role_rows": role_rows,
        "maximum_role_length_symmetric_delta": round(max_role_delta, 10),
        "total_length_symmetric_delta": round(total_delta, 10),
        "vector_ink_symmetric_delta": round(ink_delta, 10),
        "thresholds": {"per_role_length": 0.03, "total_length": 0.015, "vector_ink": 0.015},
        "budget_match": (
            all_layout_equal
            and all_geometry_changed
            and max_role_delta <= 0.03
            and total_delta <= 0.015
            and ink_delta <= 0.015
        ),
    }


def build_case(p0: base.StrippedP0, branch_count: int, seed: int) -> dict[str, object]:
    layouts = shared_layout(p0, branch_count)
    tokens = base.materialize_tokens(seed, branch_count)
    l0 = _build_variant(p0, layouts, tokens, "L0")
    l1 = _build_variant(p0, layouts, tokens, "L1")
    validation_l0 = base.validate_branch_set(p0, l0)
    validation_l1 = base.validate_branch_set(p0, l1)
    fairness = fairness_metrics(layouts, l0, l1)
    return {
        "case_id": f"P{branch_count}",
        "branch_count": branch_count,
        "seed": seed,
        "tokens": [token.as_dict() for token in tokens],
        "token_digest": _digest([token.as_dict() for token in tokens]),
        "shared_layout": [layout.as_dict() for layout in layouts],
        "shared_layout_digest": _digest([layout.as_dict() for layout in layouts]),
        "L0": {"branch_set": l0, "validation": validation_l0},
        "L1": {"branch_set": l1, "validation": validation_l1},
        "fairness": fairness,
    }


def serializable_case(case: dict[str, object]) -> dict[str, object]:
    return {
        "case_id": case["case_id"],
        "branch_count": case["branch_count"],
        "seed": case["seed"],
        "tokens": case["tokens"],
        "token_digest": case["token_digest"],
        "shared_layout": case["shared_layout"],
        "shared_layout_digest": case["shared_layout_digest"],
        "L0": {
            "branch_set": case["L0"]["branch_set"].as_dict(),
            "validation": case["L0"]["validation"],
        },
        "L1": {
            "branch_set": case["L1"]["branch_set"].as_dict(),
            "validation": case["L1"]["validation"],
        },
        "fairness": case["fairness"],
    }


__all__ = [
    "GEOMETRY_KERNEL_ID",
    "LAYOUT_ID",
    "SharedBranchLayout",
    "build_case",
    "compile_curve",
    "fairness_metrics",
    "map_l0_independent",
    "map_l1_joint",
    "serializable_case",
    "shared_layout",
]
