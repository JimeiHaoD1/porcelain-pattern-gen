#!/usr/bin/env python3
"""Pure terminal motif geometry shared by branch planning and rendering."""

from __future__ import annotations

import hashlib
import math
from typing import Iterable


Point = tuple[float, float]


def add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def mul(a: Point, scale: float) -> Point:
    return a[0] * scale, a[1] * scale


def norm(v: Point) -> Point:
    length = math.hypot(v[0], v[1])
    if length < 1e-9:
        return (1.0, 0.0)
    return v[0] / length, v[1] / length


def normal(v: Point) -> Point:
    return -v[1], v[0]


def turn(v: Point, angle: float) -> Point:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return norm((v[0] * cosine - v[1] * sine, v[0] * sine + v[1] * cosine))


def as_points(raw: Iterable[Iterable[float]]) -> list[Point]:
    return [(float(point[0]), float(point[1])) for point in raw]


def local_to_world(origin: Point, tangent: Point, point: Point) -> Point:
    side = normal(tangent)
    return add(origin, add(mul(tangent, point[0]), mul(side, point[1])))


def cubic(p0: Point, p1: Point, p2: Point, p3: Point, samples: int = 18) -> list[Point]:
    result: list[Point] = []
    for index in range(samples + 1):
        t = index / samples
        mt = 1.0 - t
        result.append(
            (
                mt**3 * p0[0] + 3.0 * mt**2 * t * p1[0] + 3.0 * mt * t**2 * p2[0] + t**3 * p3[0],
                mt**3 * p0[1] + 3.0 * mt**2 * t * p1[1] + 3.0 * mt * t**2 * p2[1] + t**3 * p3[1],
            )
        )
    return result


def closed_outline(
    origin: Point,
    tangent: Point,
    spine: list[Point],
    left_halves: list[float],
    right_halves: list[float],
) -> list[Point]:
    left: list[Point] = []
    right: list[Point] = []
    for index, point in enumerate(spine):
        if index == 0:
            local_tangent = norm(sub(spine[1], spine[0]))
        elif index == len(spine) - 1:
            local_tangent = norm(sub(spine[-1], spine[-2]))
        else:
            local_tangent = norm(sub(spine[index + 1], spine[index - 1]))
        local_normal = normal(local_tangent)
        left.append(local_to_world(origin, tangent, add(point, mul(local_normal, left_halves[index]))))
        right.append(local_to_world(origin, tangent, add(point, mul(local_normal, -right_halves[index]))))
    return left + list(reversed(right))


def leaf_envelope(t: float, peak: float = 0.50) -> float:
    if t <= peak:
        return math.sin((t / peak) * math.pi / 2.0) ** 0.84
    return math.cos(((t - peak) / (1.0 - peak)) * math.pi / 2.0) ** 1.12


def swollen_leaf_paths(
    origin: Point,
    tangent: Point,
    size: float,
    sign: int,
    *,
    compact: bool = False,
    width_scale: float = 1.0,
    length_scale: float = 1.0,
) -> list[tuple[list[Point], bool]]:
    length = size * (1.58 if compact else 2.05) * length_scale
    bend = size * (0.42 if compact else 0.62)
    spine = cubic(
        (0.0, 0.0),
        (length * 0.28, sign * bend * 0.04),
        (length * 0.68, sign * bend),
        (length, sign * bend * 0.34),
        samples=34,
    )
    peak = 0.48 if compact else 0.52
    max_half = size * (0.31 if compact else 0.43) * width_scale
    root_half = max(0.72, size * 0.055)
    left_halves: list[float] = []
    right_halves: list[float] = []
    for index in range(len(spine)):
        t = index / (len(spine) - 1)
        envelope = leaf_envelope(t, peak)
        entry = min(1.0, t / 0.20)
        half = root_half * (1.0 - entry) + max_half * envelope * entry
        outer = half * (1.0 + 0.12 * math.sin(math.pi * min(1.0, t / 0.82)))
        inner = half * (0.88 if t > 0.22 else 1.0)
        if sign > 0:
            left_halves.append(outer)
            right_halves.append(inner)
        else:
            left_halves.append(inner)
            right_halves.append(outer)
    return [(closed_outline(origin, tangent, spine, left_halves, right_halves), True)]


def swollen_comma_paths(
    origin: Point,
    tangent: Point,
    size: float,
    sign: int,
    *,
    compact: bool = False,
) -> list[tuple[list[Point], bool]]:
    length = size * (1.42 if compact else 1.92)
    rise = size * (0.82 if compact else 1.18)
    spine = cubic(
        (0.0, 0.0),
        (length * 0.36, sign * rise * 0.02),
        (length * 0.98, sign * rise * 0.58),
        (length * 0.54, sign * rise),
        samples=40,
    )
    peak = 0.66
    max_half = size * (0.34 if compact else 0.48)
    root_half = max(0.74, size * 0.058)
    left_halves: list[float] = []
    right_halves: list[float] = []
    for index in range(len(spine)):
        t = index / (len(spine) - 1)
        envelope = leaf_envelope(t, peak)
        entry = min(1.0, t / 0.18)
        half = root_half * (1.0 - entry) + max_half * envelope * entry
        outer = half * (1.20 - 0.10 * t)
        inner = half * (0.70 + 0.12 * t)
        if sign > 0:
            left_halves.append(inner)
            right_halves.append(outer)
        else:
            left_halves.append(outer)
            right_halves.append(inner)
    return [(closed_outline(origin, tangent, spine, left_halves, right_halves), True)]


def paired_leaf_paths(origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    first = swollen_leaf_paths(origin, tangent, size * 0.88, sign, compact=True)
    second_tangent = turn(tangent, -sign * 0.42)
    return first + swollen_leaf_paths(origin, second_tangent, size * 0.70, -sign, compact=True)


def leaf_cluster_paths(origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    """A dominant three-leaf mass for filling a region without adding more twigs."""
    result = swollen_leaf_paths(origin, turn(tangent, sign * 0.08), size * 1.02, sign)
    second_origin = add(origin, mul(tangent, size * 0.16))
    third_origin = add(origin, mul(tangent, size * 0.30))
    result += swollen_leaf_paths(
        second_origin,
        turn(tangent, -sign * 0.52),
        size * 0.76,
        -sign,
        compact=True,
    )
    result += swollen_leaf_paths(
        third_origin,
        turn(tangent, sign * 0.62),
        size * 0.62,
        sign,
        compact=True,
    )
    return result


def broad_leaf_paths(origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    return swollen_leaf_paths(
        origin,
        tangent,
        size,
        sign,
        width_scale=1.62,
        length_scale=0.92,
    )


def broad_leaf_cluster_paths(
    origin: Point,
    tangent: Point,
    size: float,
    sign: int,
) -> list[tuple[list[Point], bool]]:
    result = broad_leaf_paths(origin, turn(tangent, sign * 0.06), size * 1.02, sign)
    second_origin = add(origin, mul(tangent, size * 0.14))
    third_origin = add(origin, mul(tangent, size * 0.26))
    result += swollen_leaf_paths(
        second_origin,
        turn(tangent, -sign * 0.54),
        size * 0.74,
        -sign,
        compact=True,
        width_scale=1.36,
    )
    result += swollen_leaf_paths(
        third_origin,
        turn(tangent, sign * 0.60),
        size * 0.64,
        sign,
        compact=True,
        width_scale=1.30,
    )
    return result


def scroll_paths(origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    neck = size * 0.44
    radius = size * 0.72
    local: list[Point] = [(0.0, 0.0), (neck, 0.0)]
    center = (neck, sign * radius)
    start_angle = -sign * math.pi / 2.0
    for index in range(1, 33):
        t = index / 32
        angle = start_angle + sign * math.pi * 1.72 * t
        current_radius = radius * (1.0 - 0.58 * t)
        local.append(
            (
                center[0] + math.cos(angle) * current_radius,
                center[1] + math.sin(angle) * current_radius,
            )
        )
    return [([local_to_world(origin, tangent, point) for point in local], False)]


def droplet_paths(origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    length = size * 1.72
    width = size * 0.72
    top = cubic(
        (0.0, 0.0),
        (length * 0.26, sign * width * 0.08),
        (length * 0.61, sign * width),
        (length, 0.0),
        samples=24,
    )
    bottom = cubic(
        (length, 0.0),
        (length * 0.60, -sign * width * 0.88),
        (length * 0.24, -sign * width * 0.04),
        (0.0, 0.0),
        samples=24,
    )
    return [([local_to_world(origin, tangent, point) for point in top + bottom[1:]], True)]


def bifurcated_paths(origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    fork = size * 0.48
    shared = [local_to_world(origin, tangent, (0.0, 0.0)), local_to_world(origin, tangent, (fork, 0.0))]
    result: list[tuple[list[Point], bool]] = []
    for branch_sign, ratio in ((sign, 1.0), (-sign, 0.82)):
        length = size * 1.20 * ratio
        local = cubic(
            (fork, 0.0),
            (fork + length * 0.28, branch_sign * size * 0.10),
            (fork + length * 0.58, branch_sign * size * 0.62),
            (fork + length, branch_sign * size * 0.52),
        )
        result.append(
            (
                shared + [local_to_world(origin, tangent, point) for point in local[1:]],
                False,
            )
        )
    return result


def motif_paths(kind: str, origin: Point, tangent: Point, size: float, sign: int) -> list[tuple[list[Point], bool]]:
    if kind == "broad_leaf_cluster":
        return broad_leaf_cluster_paths(origin, tangent, size, sign)
    if kind == "broad_leaf":
        return broad_leaf_paths(origin, tangent, size, sign)
    if kind == "leaf_cluster":
        return leaf_cluster_paths(origin, tangent, size, sign)
    if kind == "swollen_leaf":
        return swollen_leaf_paths(origin, tangent, size, sign)
    if kind == "swollen_comma":
        return swollen_comma_paths(origin, tangent, size, sign)
    if kind == "paired_leaf":
        return paired_leaf_paths(origin, tangent, size, sign)
    if kind == "compact_leaf":
        return swollen_leaf_paths(origin, tangent, size, sign, compact=True)
    if kind == "droplet":
        return droplet_paths(origin, tangent, size, sign)
    if kind == "bifurcated":
        return bifurcated_paths(origin, tangent, size, sign)
    return scroll_paths(origin, tangent, size, sign)


def size_value(scale_class: str, scale: float) -> float:
    return {
        "small": 7.5,
        "medium": 11.5,
        "large": 15.5,
        "hero": 19.0,
        "none": 0.0,
    }.get(scale_class, 10.0) * scale


def scale_trials(visual_tier: str) -> tuple[float, ...]:
    if visual_tier == "dominant":
        return (1.0, 0.90, 0.80, 0.70, 0.62)
    if visual_tier == "support":
        return (1.0, 0.88, 0.76, 0.66)
    return (1.0, 0.84, 0.70)


def candidate_kinds(kind: str, visual_tier: str) -> list[str]:
    if visual_tier == "dominant":
        preferred = {
            "scroll": "leaf_cluster",
            "droplet": "swollen_leaf",
            "bifurcated": "leaf_cluster",
        }.get(kind, "leaf_cluster")
        family = ("leaf_cluster", "swollen_leaf", "swollen_comma", "paired_leaf")
    elif visual_tier == "support":
        preferred = {
            "scroll": "swollen_comma",
            "droplet": "swollen_leaf",
            "bifurcated": "paired_leaf",
        }.get(kind, "swollen_leaf")
        family = ("swollen_leaf", "paired_leaf", "swollen_comma", "compact_leaf")
    else:
        preferred = kind
        family = ("compact_leaf", "droplet", "scroll")
    return [preferred] + [candidate for candidate in family if candidate != preferred]


def terminal_sign(branch_id: str) -> int:
    digest = hashlib.sha1((branch_id + ":terminal").encode("utf-8")).digest()
    return -1 if digest[0] % 2 == 0 else 1


def terminal_priority(entry: dict[str, object]) -> tuple[int, float, str]:
    tier = str(entry.get("terminal", {}).get("visual_tier", "accent"))
    tier_rank = {"dominant": 0, "support": 1, "accent": 2}.get(tier, 3)
    return tier_rank, -float(entry.get("length_budget", 0.0)), str(entry["branch_id"])


def select_terminal_entries(
    entries: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    continued_parent_ids = {
        str(child["parent_id"])
        for child in entries
        if str(child["role"]) != "terminal_component"
        and float(child.get("mount_fraction", 0.0)) >= 0.90
    }
    candidates = [
        entry
        for entry in entries
        if str(entry["role"]) not in {"flower_connector", "terminal_component"}
        and str(entry["branch_id"]) not in continued_parent_ids
    ]
    skipped: list[dict[str, object]] = [
        {
            "branch_id": entry["branch_id"],
            "role": entry["role"],
            "visual_tier": entry.get("terminal", {}).get("visual_tier", "accent"),
            "reason": "continued_by_child",
        }
        for entry in entries
        if str(entry["branch_id"]) in continued_parent_ids
        and str(entry["role"]) not in {"flower_connector", "terminal_component"}
    ]
    candidates.sort(key=terminal_priority)
    budgets = {"dominant": 3, "support": 6, "accent": 1}
    counts = {tier: 0 for tier in budgets}
    per_parent: dict[tuple[str, str], int] = {}
    selected: list[dict[str, object]] = []
    for entry in candidates:
        terminal = dict(entry.get("terminal", {}))
        tier = str(terminal.get("visual_tier", "accent"))
        key = (tier, str(entry["parent_id"]))
        parent_limit = 2 if tier == "dominant" else 1
        if counts.get(tier, 0) >= budgets.get(tier, 0) or per_parent.get(key, 0) >= parent_limit:
            skipped.append(
                {
                    "branch_id": entry["branch_id"],
                    "role": entry["role"],
                    "visual_tier": tier,
                    "reason": "visual_hierarchy_budget",
                }
            )
            continue
        selected.append(entry)
        counts[tier] = counts.get(tier, 0) + 1
        per_parent[key] = per_parent.get(key, 0) + 1
    return selected, skipped
