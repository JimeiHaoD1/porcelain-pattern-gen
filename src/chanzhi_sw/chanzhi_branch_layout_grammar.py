#!/usr/bin/env python3
"""Build transferable SW branch-layout plans from semantic region graphs.

This stage assigns branch roles, hierarchy, bilateral child slots, spacing, and
terminal budgets. Preview lines are layout vectors only; final curve geometry
belongs to the next pipeline stage.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


Point = tuple[float, float]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_ROOT = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_skeleton_analysis" / "run6_flower_connectors"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_branch_layout_grammar" / "run1"
DEFAULT_PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)

PAPER = "#fbfaf5"
INK = "#0b1f46"
CONTEXT = "#cbd5e1"
FLOWER = "#db2777"
EXISTING_ACTIVE = "#1d4ed8"
NEW_LONG = "#b45309"
SECONDARY = "#0891b2"
TERTIARY = "#15803d"
MUTED = "#64748b"
ERROR = "#dc2626"


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scale: float) -> Point:
    return a[0] * scale, a[1] * scale


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _norm(v: Point) -> Point:
    length = math.hypot(v[0], v[1])
    if length < 1e-9:
        return (1.0, 0.0)
    return (v[0] / length, v[1] / length)


def _normal(v: Point) -> Point:
    return (-v[1], v[0])


def _polyline_length(points: list[Point]) -> float:
    return sum(_dist(a, b) for a, b in zip(points, points[1:]))


def _sample_polyline(points: list[Point], fraction: float) -> tuple[Point, Point]:
    if len(points) < 2:
        return (points[0] if points else (0.0, 0.0), (1.0, 0.0))
    fraction = max(0.0, min(1.0, fraction))
    lengths = [_dist(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    if total < 1e-9:
        return points[0], (1.0, 0.0)
    target = total * fraction
    traversed = 0.0
    for (a, b), length in zip(zip(points, points[1:]), lengths):
        if traversed + length >= target:
            local = 0.0 if length < 1e-9 else (target - traversed) / length
            return _add(a, _mul(_sub(b, a), local)), _norm(_sub(b, a))
        traversed += length
    return points[-1], _norm(_sub(points[-1], points[-2]))


def _as_points(raw: Iterable[Iterable[float]]) -> list[Point]:
    return [(float(point[0]), float(point[1])) for point in raw]


def _terminal_spec(role: str, generation: int, ordinal: int, length: float) -> dict[str, object]:
    """Assign a visual tier instead of giving every branch an equal small tip."""
    if role == "flower_connector":
        return {
            "kind": "flower_interface",
            "scale_class": "none",
            "visual_tier": "interface",
            "clearance_reserve": 0.0,
        }

    if role == "primary_long":
        tier = "dominant"
        scale = "hero" if length >= 76.0 else "large"
        reserve = 34.0 if scale == "hero" else 27.0
        kinds = ("bifurcated", "droplet", "scroll", "bifurcated")
    elif role in {"gap_long", "secondary_long", "primary_short"} or (
        role == "terminal_hint" and generation == 1 and length >= 25.0
    ) or (
        role == "secondary_sprig" and generation == 2 and length >= 18.0
    ):
        tier = "support"
        scale = "large" if length >= 52.0 else "medium"
        reserve = 27.0 if scale == "large" else 20.0
        kinds = ("droplet", "bifurcated", "scroll", "droplet")
    else:
        tier = "accent"
        scale = "small"
        reserve = 10.0
        kinds = ("droplet", "scroll", "droplet")

    kind = kinds[(ordinal + generation - 1) % len(kinds)]
    return {
        "kind": kind,
        "scale_class": scale,
        "visual_tier": tier,
        "clearance_reserve": reserve,
    }


def _desired_child_count(length: float) -> int:
    if length >= 84.0:
        return 2
    if length >= 60.0:
        return 2
    if length >= 42.0:
        return 1
    return 0


def _slot_fractions(count: int) -> list[float]:
    if count <= 0:
        return []
    if count == 1:
        return [0.58]
    if count == 2:
        return [0.34, 0.80]
    return [0.29, 0.56, 0.81]


def _flower_issue(root: Point, direction: Point, flowers: list[dict[str, object]]) -> bool:
    for flower in flowers:
        center = tuple(float(value) for value in flower["center"])
        radius = float(flower["radius"])
        vector = _sub(center, root)
        distance = math.hypot(vector[0], vector[1])
        if distance < 1e-9:
            return True
        alignment = _dot(_norm(direction), _norm(vector))
        if distance - radius < 94.0 and alignment > 0.48:
            return True
    return False


def _preview_child(
    parent_points: list[Point],
    fraction: float,
    side: int,
    length: float,
    flowers: list[dict[str, object]],
) -> tuple[list[Point], int] | None:
    root, tangent = _sample_polyline(parent_points, fraction)
    for candidate_side in (side, -side):
        direction = _norm(_add(_mul(tangent, 0.82), _mul(_normal(tangent), candidate_side * 0.58)))
        if _flower_issue(root, direction, flowers):
            continue
        midpoint = _add(root, _mul(tangent, min(16.0, length * 0.28)))
        tip = _add(midpoint, _mul(direction, length))
        return [root, midpoint, tip], candidate_side
    return None


def _cluster_guides(guides: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    buckets: dict[tuple[str, str], list[dict[str, object]]] = {}
    for guide in guides:
        if not guide["reproductive"]:
            continue
        parent_key = "backbone" if guide["parent_kind"] == "backbone" else str(guide["parent_id"])
        buckets.setdefault((parent_key, str(guide["vertical_side"])), []).append(guide)
    cluster_index = 0
    for bucket in buckets.values():
        bucket.sort(key=lambda guide: float(guide.get("backbone_s", guide["parent_fraction"])))
        clusters: list[list[dict[str, object]]] = []
        current: list[dict[str, object]] = []
        for guide in bucket:
            position = float(guide.get("backbone_s", guide["parent_fraction"]))
            if current:
                previous = float(current[-1].get("backbone_s", current[-1]["parent_fraction"]))
                if position - previous >= 0.18:
                    clusters.append(current)
                    current = []
            current.append(guide)
        if current:
            clusters.append(current)
        for cluster in clusters:
            cluster_index += 1
            owner = max(cluster, key=lambda guide: float(guide["length"]))
            density = "crowded" if len(cluster) >= 3 else "paired" if len(cluster) == 2 else "open"
            for guide in cluster:
                metadata[str(guide["guide_id"])] = {
                    "cluster_id": f"parent_cluster_{cluster_index}",
                    "cluster_size": len(cluster),
                    "cluster_owner": guide["guide_id"] == owner["guide_id"],
                    "density_class": density,
                }
    return metadata


def _branch_role(generation: int, length: float) -> str:
    if generation == 1:
        return "primary_long" if length >= 42.0 else "primary_short"
    if generation == 2 and length >= 42.0:
        return "secondary_long"
    if generation == 2:
        return "secondary_sprig"
    return "tertiary_sprig"


def _existing_branch_entries(
    graph: dict[str, object],
    flowers: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, list[Point]], dict[str, dict[str, object]]]:
    guides = list(graph["guide_edges"])
    cluster_meta = _cluster_guides(guides)
    entries: list[dict[str, object]] = []
    paths: dict[str, list[Point]] = {}
    by_id = {str(guide["guide_id"]): guide for guide in guides}
    for ordinal, guide in enumerate(guides):
        guide_id = str(guide["guide_id"])
        points = _as_points(guide["points"])
        paths[guide_id] = points
        generation = int(guide["generation"])
        length = float(guide["length"])
        terminal_component = (
            guide["semantic_role"] == "terminal_hint"
            and guide["parent_kind"] == "guide"
            and float(guide["parent_fraction"]) >= 0.84
        )
        flower_connector = guide["semantic_role"] == "flower_connector"
        role = (
            "flower_connector"
            if flower_connector
            else "terminal_component"
            if terminal_component
            else "terminal_hint"
            if guide["semantic_role"] == "terminal_hint"
            else _branch_role(generation, length)
        )
        entry = {
            "branch_id": guide_id,
            "source": "existing_svg_guide",
            "action": "refine_existing",
            "generation": generation,
            "role": role,
            "parent_id": guide["parent_id"],
            "mount_fraction": guide["parent_fraction"],
            "backbone_s": guide.get("backbone_s", guide["parent_fraction"]),
            "root": guide["root"],
            "tip": guide["tip"],
            "vertical_side": guide["vertical_side"],
            "length_budget": length,
            "reproductive": bool(guide["reproductive"]),
            "rhythm_child": not terminal_component and not flower_connector,
            "terminal": _terminal_spec(role, generation, ordinal, length),
            "connector_flower_id": guide.get("connector_flower_id"),
            "layout_cluster": cluster_meta.get(
                guide_id,
                {
                    "cluster_id": None,
                    "cluster_size": 1,
                    "cluster_owner": True,
                    "density_class": "non_reproductive",
                },
            ),
            "child_slot_ids": [],
        }
        entries.append(entry)

    existing_children: dict[str, list[dict[str, object]]] = {}
    for entry in entries:
        parent_id = str(entry["parent_id"])
        if parent_id in by_id:
            parent_points = paths[parent_id]
            root, tangent = _sample_polyline(parent_points, float(entry["mount_fraction"]))
            child_vector = _sub(tuple(entry["tip"]), root)
            entry["local_side"] = "left" if _dot(child_vector, _normal(tangent)) < 0.0 else "right"
            if entry["rhythm_child"]:
                existing_children.setdefault(parent_id, []).append(entry)
            else:
                parent_entry = next(item for item in entries if item["branch_id"] == parent_id)
                parent_entry["terminal"]["kind"] = "bifurcated"

    planned: list[dict[str, object]] = list(entries)
    for parent in list(entries):
        if not parent["reproductive"]:
            continue
        parent_id = str(parent["branch_id"])
        parent_points = paths[parent_id]
        density = str(parent["layout_cluster"]["density_class"])
        is_owner = bool(parent["layout_cluster"]["cluster_owner"])
        target_count = _desired_child_count(float(parent["length_budget"]))
        if density == "crowded":
            target_count = min(target_count, 2 if is_owner else 0)
        elif density == "paired":
            target_count = min(target_count, 2 if is_owner else 1)
        existing = existing_children.get(parent_id, [])
        existing_sides = {str(child["local_side"]) for child in existing}
        occupied = [float(child["mount_fraction"]) for child in existing]
        missing = max(0, target_count - len(existing))
        candidate_fractions = _slot_fractions(target_count)
        candidate_fractions = [
            fraction
            for fraction in candidate_fractions
            if all(abs(fraction - used) >= 0.18 for used in occupied)
        ]
        used_sides = {-1 if side == "left" else 1 for side in existing_sides}
        added = 0
        for slot_index, fraction in enumerate(candidate_fractions):
            if added >= missing:
                break
            if used_sides == {-1}:
                side = 1
            elif used_sides == {1}:
                side = -1
            else:
                side = -1 if (slot_index + int(parent_id.split("_")[-1])) % 2 == 0 else 1
            long_child = (
                int(parent["generation"]) == 1
                and float(parent["length_budget"]) >= 78.0
                and slot_index == max(0, missing - 1)
                and density != "crowded"
            )
            ratio = 0.56 if long_child else (0.34 if slot_index % 2 == 0 else 0.27)
            child_length = max(15.0, float(parent["length_budget"]) * ratio)
            preview = _preview_child(parent_points, fraction, side, child_length, flowers)
            if preview is None:
                continue
            child_points, actual_side = preview
            if len(used_sides) == 1 and actual_side in used_sides:
                continue
            child_id = f"{parent_id}_planned_child_{slot_index + 1}"
            generation = int(parent["generation"]) + 1
            child = {
                "branch_id": child_id,
                "source": "grammar_slot",
                "action": "generate",
                "generation": generation,
                "role": "secondary_long" if long_child else _branch_role(generation, child_length),
                "parent_id": parent_id,
                "mount_fraction": fraction,
                "local_side": "left" if actual_side < 0 else "right",
                "length_budget": child_length,
                "reproductive": long_child,
                "terminal": _terminal_spec(
                    "secondary_long" if long_child else _branch_role(generation, child_length),
                    generation,
                    slot_index,
                    child_length,
                ),
                "preview_points": child_points,
                "child_slot_ids": [],
            }
            planned.append(child)
            paths[child_id] = child_points
            parent["child_slot_ids"].append(child_id)
            used_sides.add(actual_side)
            added += 1

            if long_child:
                tertiary_used_sides: set[int] = set()
                for tertiary_index, tertiary_fraction in enumerate((0.58,)):
                    tertiary_side = -actual_side
                    tertiary_length = max(12.0, child_length * 0.30)
                    tertiary_preview = _preview_child(
                        child_points,
                        tertiary_fraction,
                        tertiary_side,
                        tertiary_length,
                        flowers,
                    )
                    if tertiary_preview is None:
                        continue
                    tertiary_points, tertiary_actual_side = tertiary_preview
                    if tertiary_used_sides and tertiary_actual_side in tertiary_used_sides:
                        continue
                    tertiary_id = f"{child_id}_tertiary_{tertiary_index + 1}"
                    tertiary = {
                        "branch_id": tertiary_id,
                        "source": "grammar_slot",
                        "action": "generate",
                        "generation": generation + 1,
                        "role": "tertiary_sprig",
                        "parent_id": child_id,
                        "mount_fraction": tertiary_fraction,
                        "local_side": "left" if tertiary_actual_side < 0 else "right",
                        "length_budget": tertiary_length,
                        "reproductive": False,
                        "terminal": _terminal_spec(
                            "tertiary_sprig",
                            generation + 1,
                            tertiary_index,
                            tertiary_length,
                        ),
                        "preview_points": tertiary_points,
                        "child_slot_ids": [],
                    }
                    planned.append(tertiary)
                    paths[tertiary_id] = tertiary_points
                    child["child_slot_ids"].append(tertiary_id)
                    tertiary_used_sides.add(tertiary_actual_side)
    return planned, paths, cluster_meta


def _add_growth_anchor_entries(
    plan: list[dict[str, object]],
    paths: dict[str, list[Point]],
    graph: dict[str, object],
    profile: dict[str, object],
) -> None:
    regions = {str(region["region_id"]): region for region in profile["growth_regions"]}
    flowers = list(profile["flowers"])
    for ordinal, attachment in enumerate(graph["attachments"]):
        if attachment["kind"] != "growth_anchor":
            continue
        region = regions[str(attachment["semantic_id"])]
        root = tuple(float(value) for value in region["attach_point"])
        direction = _norm(tuple(float(value) for value in region["growth_direction"]))
        clearance = float(region["max_clearance"])
        length = min(74.0, max(34.0, clearance * (0.76 if region["capacity"] == "long_plus_children" else 0.66)))
        branch_id = f"new_{region['region_id']}"
        backbone_s = float(attachment["s"])
        midpoint = _add(root, _mul(direction, length * 0.48))
        tip = _add(root, _mul(direction, length))
        parent_points = [root, midpoint, tip]
        parent = {
            "branch_id": branch_id,
            "source": "growth_region",
            "action": "generate",
            "generation": 1,
            "role": "gap_long",
            "parent_id": attachment["edge_id"],
            "mount_fraction": backbone_s,
            "backbone_s": backbone_s,
            "root": root,
            "tip": tip,
            "vertical_side": attachment["vertical_side"],
            "flower_relation": attachment["flower_relation"],
            "length_budget": length,
            "reproductive": region["capacity"] == "long_plus_children",
            "terminal": _terminal_spec("gap_long", 1, ordinal, length),
            "layout_cluster": {
                "cluster_id": None,
                "cluster_size": 1,
                "cluster_owner": True,
                "density_class": "open_gap",
            },
            "preview_points": parent_points,
            "child_slot_ids": [],
        }
        plan.append(parent)
        paths[branch_id] = parent_points
        child_count = 1 if parent["reproductive"] or length >= 46.0 else 0
        for slot_index, fraction in enumerate(_slot_fractions(child_count)):
            side = -1 if slot_index % 2 == 0 else 1
            child_length = length * (0.38 if slot_index == 0 else 0.29)
            preview = _preview_child(parent_points, fraction, side, child_length, flowers)
            if preview is None:
                continue
            child_points, actual_side = preview
            child_id = f"{branch_id}_child_{slot_index + 1}"
            child = {
                "branch_id": child_id,
                "source": "grammar_slot",
                "action": "generate",
                "generation": 2,
                "role": "secondary_sprig",
                "parent_id": branch_id,
                "mount_fraction": fraction,
                "local_side": "left" if actual_side < 0 else "right",
                "length_budget": child_length,
                "reproductive": False,
                "terminal": _terminal_spec("secondary_sprig", 2, slot_index, child_length),
                "preview_points": child_points,
                "child_slot_ids": [],
            }
            plan.append(child)
            paths[child_id] = child_points
            parent["child_slot_ids"].append(child_id)


def _edge_for_s(graph: dict[str, object], s: float) -> str:
    edges = list(graph["backbone_edges"])
    containing = [
        edge
        for edge in edges
        if float(edge["start_s"]) - 1e-6 <= s <= float(edge["end_s"]) + 1e-6
    ]
    if containing:
        return str(
            min(
                containing,
                key=lambda edge: abs(
                    s - (float(edge["start_s"]) + float(edge["end_s"])) * 0.5
                ),
            )["graph_edge_id"]
        )
    return str(
        min(
            edges,
            key=lambda edge: min(
                abs(s - float(edge["start_s"])),
                abs(s - float(edge["end_s"])),
            ),
        )["graph_edge_id"]
    )


def _add_balance_anchor_entries(
    plan: list[dict[str, object]],
    paths: dict[str, list[Point]],
    graph: dict[str, object],
    profile: dict[str, object],
) -> None:
    """Maintain several distributed long branches on both sides of the backbone."""
    flowers = list(profile["flowers"])
    existing_positions: dict[str, list[float]] = {"upper": [], "lower": []}
    substantial = {"upper": 0, "lower": 0}
    for branch in plan:
        if int(branch["generation"]) != 1 or branch["role"] == "flower_connector":
            continue
        side = str(branch.get("vertical_side", "upper"))
        if side not in existing_positions:
            continue
        position = float(branch.get("backbone_s", branch.get("mount_fraction", 0.0)))
        existing_positions[side].append(position)
        if float(branch.get("length_budget", 0.0)) >= 42.0:
            substantial[side] += 1

    for side in ("upper", "lower"):
        target_count = 3 if len(flowers) <= 1 else 2
        while substantial[side] < target_count:
            candidates = [
                sample
                for sample in profile["space_samples"]
                if str(sample["vertical_side"]) == side
                and float(sample["clearance"]) >= (
                    20.0 if str(sample["blocked_by"]) == "points_toward_flower" else 44.0
                )
                and str(sample["blocked_by"]) not in {
                    "flower_reserve",
                    "existing_structure",
                }
                and 0.055 <= float(sample["s"]) <= 0.945
                and all(
                    abs(float(sample["s"]) - position) >= 0.15
                    for position in existing_positions[side]
                )
            ]
            if not candidates:
                break
            sample = max(
                candidates,
                key=lambda item: (
                    float(item["score"]) + float(item["clearance"]) * 0.24
                    + min(
                        (
                            abs(float(item["s"]) - position)
                            for position in existing_positions[side]
                        ),
                        default=0.5,
                    )
                    * 16.0
                ),
            )
            root = tuple(float(value) for value in sample["root"])
            direction = _norm(tuple(float(value) for value in sample["direction"]))
            if str(sample["blocked_by"]) == "points_toward_flower" and flowers:
                nearest = min(
                    flowers,
                    key=lambda flower: _dist(
                        root,
                        tuple(float(value) for value in flower["center"]),
                    ),
                )
                center = tuple(float(value) for value in nearest["center"])
                away = _norm(_sub(root, center))
                around_a = _normal(away)
                around_b = _mul(around_a, -1.0)
                desired_y_sign = -1.0 if side == "upper" else 1.0
                around = (
                    around_a
                    if around_a[1] * desired_y_sign >= around_b[1] * desired_y_sign
                    else around_b
                )
                direction = _norm(
                    _add(
                        _mul(around, 0.78),
                        _add(_mul(away, 0.34), _mul(direction, 0.18)),
                    )
                )
                vertical = (0.0, -1.0 if side == "upper" else 1.0)
                if direction[1] * vertical[1] < 0.55:
                    direction = _norm(_add(_mul(direction, 0.64), _mul(vertical, 0.76)))
            clearance = float(sample["clearance"])
            length = min(
                126.0,
                max(
                    72.0,
                    116.0
                    if str(sample["blocked_by"]) == "points_toward_flower"
                    else clearance * 1.28,
                ),
            )
            s = float(sample["s"])
            ordinal = substantial[side] + 1
            branch_id = (
                f"coverage_{side}_primary"
                if ordinal == 1
                else f"coverage_{side}_primary_{ordinal}"
            )
            midpoint = _add(root, _mul(direction, length * 0.46))
            tip = _add(root, _mul(direction, length))
            parent_points = [root, midpoint, tip]
            parent = {
                "branch_id": branch_id,
                "source": "coverage_region",
                "action": "generate",
                "generation": 1,
                "role": "primary_long",
                "parent_id": _edge_for_s(graph, s),
                "mount_fraction": s,
                "backbone_s": s,
                "root": root,
                "tip": tip,
                "vertical_side": side,
                "flower_relation": "away"
                if float(sample.get("flower_alignment", -1.0)) < -0.20
                else "tangential",
                "length_budget": length,
                "reproductive": clearance >= 62.0,
                "terminal": _terminal_spec(
                    "primary_long",
                    1,
                    ordinal + (0 if side == "upper" else 3),
                    length,
                ),
                "layout_cluster": {
                    "cluster_id": None,
                    "cluster_size": 1,
                    "cluster_owner": True,
                    "density_class": "coverage_gap",
                },
                "coverage_target": side,
                "preview_points": parent_points,
                "child_slot_ids": [],
            }
            plan.append(parent)
            paths[branch_id] = parent_points
            existing_positions[side].append(s)
            substantial[side] += 1

            if not parent["reproductive"]:
                continue
            child_length = max(20.0, length * 0.34)
            preview = _preview_child(
                parent_points,
                0.58,
                -1 if (ordinal + (0 if side == "upper" else 1)) % 2 == 0 else 1,
                child_length,
                flowers,
            )
            if preview is None:
                continue
            child_points, actual_side = preview
            child_id = f"{branch_id}_support"
            child = {
                "branch_id": child_id,
                "source": "grammar_slot",
                "action": "generate",
                "generation": 2,
                "role": "secondary_sprig",
                "parent_id": branch_id,
                "mount_fraction": 0.58,
                "local_side": "left" if actual_side < 0 else "right",
                "length_budget": child_length,
                "reproductive": False,
                "terminal": _terminal_spec("secondary_sprig", 2, ordinal, child_length),
                "preview_points": child_points,
                "child_slot_ids": [],
            }
            plan.append(child)
            paths[child_id] = child_points
            parent["child_slot_ids"].append(child_id)


def _audit(plan: list[dict[str, object]], graph: dict[str, object]) -> dict[str, object]:
    branch_ids = {str(branch["branch_id"]) for branch in plan}
    backbone_ids = {str(edge["graph_edge_id"]) for edge in graph["backbone_edges"]}
    errors: list[str] = []
    child_groups: dict[str, list[dict[str, object]]] = {}
    for branch in plan:
        parent_id = str(branch["parent_id"])
        if parent_id not in branch_ids and parent_id not in backbone_ids:
            errors.append(f"unknown_parent:{branch['branch_id']}:{parent_id}")
        if branch.get("flower_relation") == "toward":
            errors.append(f"flower_inward_anchor:{branch['branch_id']}")
        child_groups.setdefault(parent_id, []).append(branch)
        terminal = branch.get("terminal", {})
        if (
            not terminal.get("kind")
            or (
                branch["role"] != "flower_connector"
                and float(terminal.get("clearance_reserve", 0.0)) <= 0.0
            )
        ):
            errors.append(f"missing_terminal_budget:{branch['branch_id']}")

    spacing_violations: list[str] = []
    bilateral_failures: list[str] = []
    for parent_id, children in child_groups.items():
        if parent_id not in branch_ids:
            continue
        direct_children = [
            child
            for child in children
            if child.get("local_side") in {"left", "right"} and child.get("rhythm_child", True)
        ]
        generated = [child for child in direct_children if child["source"] == "grammar_slot"]
        fractions = sorted(float(child["mount_fraction"]) for child in direct_children)
        for left, right in zip(fractions, fractions[1:]):
            if right - left < 0.18 - 1e-6:
                spacing_violations.append(parent_id)
        if len(direct_children) >= 2:
            sides = {child.get("local_side") for child in direct_children}
            if not {"left", "right"}.issubset(sides):
                bilateral_failures.append(parent_id)
    errors.extend(f"child_spacing:{parent_id}" for parent_id in sorted(set(spacing_violations)))
    errors.extend(f"missing_bilateral_rhythm:{parent_id}" for parent_id in sorted(set(bilateral_failures)))

    role_counts: dict[str, int] = {}
    generation_counts: dict[str, int] = {}
    terminal_counts: dict[str, int] = {}
    for branch in plan:
        role = str(branch["role"])
        generation = f"generation_{branch['generation']}"
        terminal = str(branch["terminal"]["kind"])
        role_counts[role] = role_counts.get(role, 0) + 1
        generation_counts[generation] = generation_counts.get(generation, 0) + 1
        terminal_counts[terminal] = terminal_counts.get(terminal, 0) + 1
    return {
        "valid": not errors,
        "errors": errors,
        "branch_count": len(plan),
        "generated_count": sum(1 for branch in plan if branch["action"] == "generate"),
        "refined_existing_count": sum(1 for branch in plan if branch["action"] == "refine_existing"),
        "role_counts": role_counts,
        "generation_counts": generation_counts,
        "terminal_counts": terminal_counts,
        "rules": {
            "minimum_child_fraction_spacing": 0.18,
            "crowded_cluster_policy": "only the longest parent owns multiple child slots",
            "bilateral_policy": "parents with two or more generated children use both local sides",
            "flower_policy": "new slots pointing toward nearby flower reserves are rejected or flipped",
        },
    }


def _font(size: int) -> ImageFont.ImageFont:
    for path in (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/msyh.ttc")):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _draw_dashed(draw: ImageDraw.ImageDraw, points: list[Point], transform, fill: str, width: int) -> None:
    for a, b in zip(points, points[1:]):
        distance = _dist(a, b)
        steps = max(1, int(distance // 5.0))
        for index in range(steps):
            if index % 2:
                continue
            t0 = index / steps
            t1 = min(1.0, (index + 1) / steps)
            p0 = _add(a, _mul(_sub(b, a), t0))
            p1 = _add(a, _mul(_sub(b, a), t1))
            draw.line([transform(p0), transform(p1)], fill=fill, width=width)


def _render_preview(
    profile: dict[str, object],
    graph: dict[str, object],
    plan: list[dict[str, object]],
    paths: dict[str, list[Point]],
    audit: dict[str, object],
) -> Image.Image:
    source_width = 256.0
    source_height = float(profile["canvas"]["height"])
    scale = 2.5
    margin_x = 24
    header = 72
    footer = 42
    image = Image.new(
        "RGB",
        (round(source_width * scale) + margin_x * 2, round(source_height * scale) + header + footer),
        PAPER,
    )
    draw = ImageDraw.Draw(image)
    transform = lambda point: (margin_x + round(point[0] * scale), header + round(point[1] * scale))
    title_font = _font(18)
    label_font = _font(12)
    draw.text((16, 14), f"{profile['prototype_id']} | transferable branch layout plan", fill=INK, font=title_font)
    status = "PASS" if audit["valid"] else "FAIL"
    draw.text(
        (16, 42),
        f"{status}  refine={audit['refined_existing_count']} generate={audit['generated_count']} "
        f"g2={audit['generation_counts'].get('generation_2', 0)} "
        f"g3={audit['generation_counts'].get('generation_3', 0)}",
        fill=EXISTING_ACTIVE if audit["valid"] else ERROR,
        font=label_font,
    )

    backbone = _as_points(sample["point"] for sample in profile["backbone"]["arc_samples"])
    draw.line([transform(point) for point in backbone], fill=INK, width=7, joint="curve")
    for flower in profile["flowers"]:
        center = tuple(float(value) for value in flower["center"])
        rx = float(flower["rx"])
        ry = float(flower["ry"])
        draw.ellipse(
            [
                transform((center[0] - rx, center[1] - ry)),
                transform((center[0] + rx, center[1] + ry)),
            ],
            outline=FLOWER,
            width=3,
        )
    for guide in graph["guide_edges"]:
        points = _as_points(guide["points"])
        draw.line([transform(point) for point in points], fill=CONTEXT, width=3, joint="curve")

    for branch in plan:
        branch_id = str(branch["branch_id"])
        points = paths.get(branch_id)
        if not points:
            continue
        generation = int(branch["generation"])
        if branch["source"] == "existing_svg_guide":
            color = EXISTING_ACTIVE if branch["reproductive"] else MUTED
            width = 5 if branch["reproductive"] else 3
            draw.line([transform(point) for point in points], fill=color, width=width, joint="curve")
        else:
            color = NEW_LONG if generation == 1 else SECONDARY if generation == 2 else TERTIARY
            _draw_dashed(draw, points, transform, color, 4 if generation == 1 else 3)
            root = transform(points[0])
            radius = 4 if generation == 1 else 3
            draw.ellipse([root[0] - radius, root[1] - radius, root[0] + radius, root[1] + radius], fill=color)

    legend_y = image.height - 30
    draw.text(
        (16, legend_y),
        "solid blue=existing reproductive guide  orange=new long slot  cyan=secondary  green=tertiary  dashed=layout only",
        fill="#475569",
        font=label_font,
    )
    return image


def _jsonable(value: object) -> object:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, float):
        return round(value, 6)
    return value


def _contact_sheet(items: list[tuple[str, Path]], output_path: Path) -> None:
    images = [(name, Image.open(path).convert("RGB")) for name, path in items]
    if not images:
        return
    columns = 2
    rows = math.ceil(len(images) / columns)
    cell_w = max(image.width for _, image in images)
    cell_h = max(image.height for _, image in images)
    sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), "#eef2f7")
    for index, (_, image) in enumerate(images):
        x = index % columns * cell_w
        y = index // columns * cell_h
        sheet.paste(image, (x, y))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def _build_one(profile_path: Path, output_dir: Path) -> tuple[dict[str, object], Path]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    graph = profile["region_graph"]
    if not graph["qa"]["valid"]:
        raise RuntimeError(f"Invalid region graph: {graph['qa']['errors']}")
    plan, paths, cluster_meta = _existing_branch_entries(graph, list(profile["flowers"]))
    _add_growth_anchor_entries(plan, paths, graph, profile)
    _add_balance_anchor_entries(plan, paths, graph, profile)
    plan.sort(key=lambda branch: (int(branch["generation"]), str(branch["branch_id"])))
    audit = _audit(plan, graph)
    result = {
        "schema": "chanzhi_branch_layout_plan_v1",
        "prototype_id": profile["prototype_id"],
        "source_profile": str(profile_path),
        "scope": "layout_and_hierarchy_only",
        "geometry_status": "preview vectors are not final curves",
        "branches": plan,
        "parent_clusters": cluster_meta,
        "qa": audit,
    }
    case_dir = output_dir / str(profile["prototype_id"])
    case_dir.mkdir(parents=True, exist_ok=True)
    plan_path = case_dir / "branch_layout_plan.json"
    plan_path.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
    preview = _render_preview(profile, graph, plan, paths, audit)
    preview_path = case_dir / "branch_layout_preview.png"
    preview.save(preview_path)
    return result, preview_path


def run(args: argparse.Namespace) -> dict[str, object]:
    input_root = args.input_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    previews: list[tuple[str, Path]] = []
    errors: list[dict[str, str]] = []
    for prototype_id in args.prototype_ids:
        profile_path = input_root / prototype_id / "skeleton_profile.json"
        try:
            result, preview_path = _build_one(profile_path, output_dir)
            results.append(result)
            previews.append((prototype_id, preview_path))
            print(f"Planned {prototype_id}: {preview_path}")
        except Exception as exc:
            errors.append({"prototype_id": prototype_id, "error": repr(exc)})
            print(f"Failed {prototype_id}: {exc}")
    contact_sheet = output_dir / "branch_layout_contact_sheet.png"
    _contact_sheet(previews, contact_sheet)
    manifest = {
        "schema": "chanzhi_branch_layout_manifest_v1",
        "input_root": str(input_root),
        "output_dir": str(output_dir),
        "success_count": len(results),
        "error_count": len(errors),
        "errors": errors,
        "contact_sheet": str(contact_sheet),
        "summary": [
            {
                "prototype_id": result["prototype_id"],
                "valid": result["qa"]["valid"],
                "branch_count": result["qa"]["branch_count"],
                "generated_count": result["qa"]["generated_count"],
                "refined_existing_count": result["qa"]["refined_existing_count"],
                "generation_counts": result["qa"]["generation_counts"],
                "role_counts": result["qa"]["role_counts"],
                "terminal_counts": result["qa"]["terminal_counts"],
                "errors": result["qa"]["errors"],
            }
            for result in results
        ],
    }
    manifest_path = output_dir / "branch_layout_manifest.json"
    manifest_path.write_text(json.dumps(_jsonable(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {contact_sheet}")
    print(f"Saved {manifest_path}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate transferable SW branch-layout plans.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prototype-ids", nargs="+", default=list(DEFAULT_PROTOTYPE_IDS))
    manifest = run(parser.parse_args())
    return 0 if not manifest["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
