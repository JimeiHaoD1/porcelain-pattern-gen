#!/usr/bin/env python3
"""Pure unit-level planner for the corrected BranchUnit L v3 experiment.

The planner has no access to L0 geometry, scene context, validation results,
trial identifiers, search, repair, or resampling.  It maps one primary, one raw
token vector, and one shared role budget to a complete dependent-curve plan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, Sequence

from l_core import ChildSpec, Curve, TerminalSpec, primary_summary, rotate, sample_polyline


PLANNER_ID = "branch_unit_l_joint_planner_v3"
MOUNT_MIN = 0.28
MOUNT_MAX = 0.78
CHILD_LENGTH_MIN_RATIO = 0.20
CHILD_LENGTH_MAX_RATIO = 0.33
CHILD_ANGLE_MIN = 42.0
CHILD_ANGLE_MAX = 66.0
CHILD_BOW_MIN = 0.12
CHILD_BOW_MAX = 0.36
TERMINAL_ANGLE_MIN = 20.0
TERMINAL_ANGLE_MAX = 32.0
TERMINAL_BOW_MIN = 0.12
TERMINAL_BOW_MAX = 0.32


class BudgetLike(Protocol):
    primary_length: float
    child_lengths: Sequence[float]
    terminal_length: float
    child_width: float
    terminal_width: float


@dataclass(frozen=True)
class JointBranchPlan:
    children: tuple[ChildSpec, ...]
    terminal: TerminalSpec
    release_side: int
    trace: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "planner_id": PLANNER_ID,
            "release_side": self.release_side,
            "trace": self.trace,
            "children": [child.as_dict() for child in self.children],
            "terminal": self.terminal.as_dict(),
        }


def map_l0_independent(
    raw: dict[str, float],
    budget: BudgetLike,
) -> tuple[tuple[ChildSpec, ...], TerminalSpec, dict[str, object]]:
    """Map L0 parameters independently, without primary or sibling access."""

    children = tuple(
        ChildSpec(
            mount_fraction=MOUNT_MIN + (MOUNT_MAX - MOUNT_MIN) * float(raw[f"child.{index}.mount"]),
            target_length=float(target_length),
            turn_sign=1 if float(raw[f"child.{index}.side"]) >= 0.5 else -1,
            angle_degrees=CHILD_ANGLE_MIN
            + (CHILD_ANGLE_MAX - CHILD_ANGLE_MIN) * float(raw[f"child.{index}.angle"]),
            bow=CHILD_BOW_MIN
            + (CHILD_BOW_MAX - CHILD_BOW_MIN) * float(raw[f"child.{index}.bow"]),
            width=float(budget.child_width),
        )
        for index, target_length in enumerate(budget.child_lengths, start=1)
    )
    terminal = TerminalSpec(
        target_length=float(budget.terminal_length),
        turn_sign=1 if float(raw["terminal.side"]) >= 0.5 else -1,
        angle_degrees=TERMINAL_ANGLE_MIN
        + (TERMINAL_ANGLE_MAX - TERMINAL_ANGLE_MIN) * float(raw["terminal.turn"]),
        bow=TERMINAL_BOW_MIN
        + (TERMINAL_BOW_MAX - TERMINAL_BOW_MIN) * float(raw["terminal.bow"]),
        width=float(budget.terminal_width),
    )
    return children, terminal, {
        "mapping_id": "branch_unit_l_independent_mapper_v3",
        "primary_summary_consumed": False,
        "sibling_state_consumed": False,
        "children": [child.as_dict() for child in children],
        "terminal": terminal.as_dict(),
        "generation_policy": {
            "candidate_count": 1,
            "retry_count": 0,
            "resample_count": 0,
            "repair_count": 0,
            "validation_feedback_consumed": False,
        },
    }


def plan_l1_joint(
    primary: Curve,
    raw: dict[str, float],
    budget: BudgetLike,
) -> JointBranchPlan:
    """Create one deterministic BranchUnit plan before curve compilation."""

    child_count = len(budget.child_lengths)
    if child_count not in {0, 1, 2}:
        raise ValueError(f"L v3 supports 0-2 children, got {child_count}")
    _require_tokens(raw, child_count)

    summary = primary_summary(primary)
    cumulative_turn = float(summary["cumulative_turn_radians"])
    if abs(cumulative_turn) <= 1e-9:
        raise ValueError("primary cumulative turn is zero; release side is undefined")
    primary_turn_sign = 1 if cumulative_turn > 0.0 else -1
    release_side = -primary_turn_sign
    primary_length = float(budget.primary_length)
    total_child_length = sum(float(value) for value in budget.child_lengths)

    mounts, mount_trace = _joint_mounts(raw, child_count, primary_length)
    lengths, length_trace = _joint_lengths(raw, child_count, primary_length, total_child_length)
    angles, fan_trace = _joint_fan(raw, child_count)
    bows, bow_trace = _joint_bows(raw, child_count)

    children = tuple(
        ChildSpec(
            mount_fraction=mounts[index],
            target_length=lengths[index],
            turn_sign=release_side,
            angle_degrees=angles[index],
            bow=bows[index],
            width=float(budget.child_width),
        )
        for index in range(child_count)
    )

    primary_points = primary.points(96)
    target_directions: list[list[float]] = []
    for child in children:
        _, tangent = sample_polyline(primary_points, child.mount_fraction)
        target = rotate(tangent, release_side * child.angle_degrees)
        target_directions.append([round(target[0], 10), round(target[1], 10)])

    theta10 = sum(
        float(sample["signed_turn_radians"])
        for sample in summary["turn_samples"]
        if float(sample["s"]) >= 0.90
    )
    q_exit = _clamp01(abs(theta10) / math.radians(20.0))
    if children:
        q_fan = _clamp01(
            abs(
                sum(
                    (child.target_length / total_child_length)
                    * math.sin(math.radians(child.angle_degrees))
                    for child in children
                )
            )
            / math.sin(math.radians(CHILD_ANGLE_MAX))
        )
    else:
        q_fan = q_exit
    terminal_mix = (q_exit + q_fan + float(raw["terminal.turn"])) / 3.0
    terminal_angle = TERMINAL_ANGLE_MIN + (TERMINAL_ANGLE_MAX - TERMINAL_ANGLE_MIN) * terminal_mix
    terminal_bow = TERMINAL_BOW_MIN + (TERMINAL_BOW_MAX - TERMINAL_BOW_MIN) * float(raw["terminal.bow"])
    terminal = TerminalSpec(
        target_length=float(budget.terminal_length),
        turn_sign=release_side,
        angle_degrees=terminal_angle,
        bow=terminal_bow,
        width=float(budget.terminal_width),
    )

    nominal_after_terminal = cumulative_turn + math.radians(release_side * terminal_angle)
    if abs(nominal_after_terminal) >= abs(cumulative_turn):
        raise ValueError("terminal plan does not release primary cumulative turn")

    _assert_domains(children, terminal, primary_length, total_child_length)
    trace: dict[str, object] = {
        "input_contract": "primary_plus_raw_tokens_plus_shared_role_budget",
        "primary_summary_consumed": True,
        "primary_cumulative_turn_radians": round(cumulative_turn, 10),
        "primary_final_10pct_turn_radians": round(theta10, 10),
        "primary_turn_sign": primary_turn_sign,
        "unit_release_side": release_side,
        "joint_mounts": mount_trace,
        "joint_lengths": length_trace,
        "shared_fan": fan_trace,
        "shared_bow": bow_trace,
        "child_target_directions": target_directions,
        "terminal_closure": {
            "q_exit": round(q_exit, 10),
            "q_fan": round(q_fan, 10),
            "raw_turn": round(float(raw["terminal.turn"]), 10),
            "mix": round(terminal_mix, 10),
            "angle_degrees": round(terminal_angle, 10),
            "signed_angle_degrees": round(release_side * terminal_angle, 10),
            "bow": round(terminal_bow, 10),
            "nominal_cumulative_turn_after_terminal_radians": round(nominal_after_terminal, 10),
            "reduces_primary_cumulative_turn": True,
        },
        "token_roles": {
            "child.1.mount": "unit_center_when_two_children",
            "child.2.mount": "unit_gap_when_two_children",
            "child.1.side": "unit_dominance_when_two_children",
            "child.1.angle": "fan_center_when_two_children",
            "child.2.angle": "fan_spread_when_two_children",
            "child.1.bow": "bow_center_when_two_children",
            "child.2.bow": "bow_spread_when_two_children",
            "terminal.turn": "terminal_closure_mix",
            "terminal.bow": "terminal_bow",
        },
        "generation_policy": {
            "candidate_count": 1,
            "retry_count": 0,
            "resample_count": 0,
            "repair_count": 0,
            "validation_feedback_consumed": False,
        },
    }
    return JointBranchPlan(children=children, terminal=terminal, release_side=release_side, trace=trace)


def _joint_mounts(
    raw: dict[str, float],
    child_count: int,
    primary_length: float,
) -> tuple[tuple[float, ...], dict[str, object]]:
    if child_count == 0:
        return (), {"mode": "no_children", "mounts": []}
    if child_count == 1:
        mount = MOUNT_MIN + (MOUNT_MAX - MOUNT_MIN) * float(raw["child.1.mount"])
        return (mount,), {
            "mode": "single_full_domain",
            "mounts": [round(mount, 10)],
        }

    center_u = float(raw["child.1.mount"])
    gap_u = float(raw["child.2.mount"])
    gap_px = 10.0 + 8.0 * gap_u
    gap_s = gap_px / primary_length
    max_gap_s = 18.0 / primary_length
    center_low = MOUNT_MIN + max_gap_s * 0.5
    center_high = MOUNT_MAX - max_gap_s * 0.5
    center = center_low + center_u * (center_high - center_low)
    proximal = center - gap_s * 0.5
    distal = center + gap_s * 0.5
    return (proximal, distal), {
        "mode": "unit_center_plus_gap",
        "center_token": round(center_u, 10),
        "gap_token": round(gap_u, 10),
        "center_fraction": round(center, 10),
        "gap_world": round(gap_px, 10),
        "gap_fraction": round(gap_s, 10),
        "mounts": [round(proximal, 10), round(distal, 10)],
    }


def _joint_lengths(
    raw: dict[str, float],
    child_count: int,
    primary_length: float,
    total_child_length: float,
) -> tuple[tuple[float, ...], dict[str, object]]:
    if child_count == 0:
        return (), {"mode": "no_children", "total": 0.0, "lengths": []}
    if child_count == 1:
        return (total_child_length,), {
            "mode": "single_shared_total",
            "total": round(total_child_length, 10),
            "lengths": [round(total_child_length, 10)],
        }

    dominance_u = float(raw["child.1.side"])
    lower = max(
        0.54,
        CHILD_LENGTH_MIN_RATIO * primary_length / total_child_length,
        1.0 - CHILD_LENGTH_MAX_RATIO * primary_length / total_child_length,
    )
    upper = min(
        0.60,
        CHILD_LENGTH_MAX_RATIO * primary_length / total_child_length,
        1.0 - CHILD_LENGTH_MIN_RATIO * primary_length / total_child_length,
    )
    if lower > upper + 1e-12:
        raise ValueError("shared child budget has no feasible dominance interval")
    dominance = lower + dominance_u * (upper - lower)
    proximal = dominance * total_child_length
    distal = total_child_length - proximal
    return (proximal, distal), {
        "mode": "shared_total_plus_dominance",
        "dominance_token": round(dominance_u, 10),
        "dominance_low": round(lower, 10),
        "dominance_high": round(upper, 10),
        "dominance": round(dominance, 10),
        "total": round(total_child_length, 10),
        "lengths": [round(proximal, 10), round(distal, 10)],
    }


def _joint_fan(
    raw: dict[str, float],
    child_count: int,
) -> tuple[tuple[float, ...], dict[str, object]]:
    if child_count == 0:
        return (), {"mode": "no_children", "angles": []}
    if child_count == 1:
        angle = CHILD_ANGLE_MIN + (CHILD_ANGLE_MAX - CHILD_ANGLE_MIN) * float(raw["child.1.angle"])
        return (angle,), {"mode": "single_release_side", "angles": [round(angle, 10)]}

    center_u = float(raw["child.1.angle"])
    spread_u = float(raw["child.2.angle"])
    center = 51.0 + 6.0 * center_u
    spread = 6.0 + 6.0 * spread_u
    proximal = center + spread * 0.5
    distal = center - spread * 0.5
    return (proximal, distal), {
        "mode": "transported_unit_fan",
        "center_token": round(center_u, 10),
        "spread_token": round(spread_u, 10),
        "center_degrees": round(center, 10),
        "spread_degrees": round(spread, 10),
        "angles": [round(proximal, 10), round(distal, 10)],
    }


def _joint_bows(
    raw: dict[str, float],
    child_count: int,
) -> tuple[tuple[float, ...], dict[str, object]]:
    if child_count == 0:
        return (), {"mode": "no_children", "bows": []}
    if child_count == 1:
        bow = CHILD_BOW_MIN + (CHILD_BOW_MAX - CHILD_BOW_MIN) * float(raw["child.1.bow"])
        return (bow,), {"mode": "single_full_domain", "bows": [round(bow, 10)]}

    center_u = float(raw["child.1.bow"])
    spread_u = float(raw["child.2.bow"])
    center = 0.21 + 0.03 * center_u
    spread = 0.06 + 0.06 * spread_u
    proximal = center - spread * 0.5
    distal = center + spread * 0.5
    return (proximal, distal), {
        "mode": "shared_bow_center_plus_spread",
        "center_token": round(center_u, 10),
        "spread_token": round(spread_u, 10),
        "center": round(center, 10),
        "spread": round(spread, 10),
        "bows": [round(proximal, 10), round(distal, 10)],
    }


def _assert_domains(
    children: Sequence[ChildSpec],
    terminal: TerminalSpec,
    primary_length: float,
    total_child_length: float,
) -> None:
    for child in children:
        if not MOUNT_MIN - 1e-12 <= child.mount_fraction <= MOUNT_MAX + 1e-12:
            raise ValueError("child mount escaped shared domain")
        if not CHILD_LENGTH_MIN_RATIO * primary_length - 1e-9 <= child.target_length <= CHILD_LENGTH_MAX_RATIO * primary_length + 1e-9:
            raise ValueError("child length escaped shared domain")
        if not CHILD_ANGLE_MIN - 1e-12 <= child.angle_degrees <= CHILD_ANGLE_MAX + 1e-12:
            raise ValueError("child angle escaped shared domain")
        if not CHILD_BOW_MIN - 1e-12 <= child.bow <= CHILD_BOW_MAX + 1e-12:
            raise ValueError("child bow escaped shared domain")
    if abs(sum(child.target_length for child in children) - total_child_length) > 1e-8:
        raise ValueError("joint child lengths do not preserve shared total")
    if not TERMINAL_ANGLE_MIN - 1e-12 <= terminal.angle_degrees <= TERMINAL_ANGLE_MAX + 1e-12:
        raise ValueError("terminal angle escaped shared domain")
    if not TERMINAL_BOW_MIN - 1e-12 <= terminal.bow <= TERMINAL_BOW_MAX + 1e-12:
        raise ValueError("terminal bow escaped shared domain")


def _require_tokens(raw: dict[str, float], child_count: int) -> None:
    required = {"terminal.turn", "terminal.bow"}
    for index in range(1, child_count + 1):
        required.update(
            {
                f"child.{index}.mount",
                f"child.{index}.length",
                f"child.{index}.angle",
                f"child.{index}.side",
                f"child.{index}.bow",
            }
        )
    missing = sorted(required - set(raw))
    if missing:
        raise KeyError(f"missing planner tokens: {missing}")
    for key in required:
        value = float(raw[key])
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"raw token outside [0,1]: {key}={value}")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
