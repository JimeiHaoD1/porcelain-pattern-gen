#!/usr/bin/env python3
"""Analyze Chanzhi backbone semantics before any branch generation.

The analyzer reconstructs one repeat backbone from SVG connectivity, converts it
to normalized arc length, detects peaks/troughs and rising/falling sections,
classifies flower positions, estimates free space on both normal sides, and
proposes long-branch growth regions. It intentionally does not draw branches.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

try:
    from . import chanzhi_svg_skeleton_io as eng
except ImportError:
    import chanzhi_svg_skeleton_io as eng


Point = tuple[float, float]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_ROOT = (
    REPO_ROOT
    / "newpipe"
    / "outputs"
    / "chanzhi_ready_experiment"
    / "from_chanzhidanyuan_20260513_v10"
    / "library_build"
    / "generated"
)
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
PEAK = "#dc2626"
TROUGH = "#2563eb"
FLOWER = "#db2777"
UPPER = "#15803d"
LOWER = "#b45309"
BLOCKED = "#cbd5e1"
BOUNDARY = "#475569"


@dataclass
class ArcSample:
    s: float
    point: Point
    tangent: Point
    normal: Point
    curvature: float


@dataclass
class SpaceSample:
    s: float
    root: Point
    side: float
    vertical_side: str
    direction: Point
    clearance: float
    blocked_by: str
    score: float
    nearest_flower_id: str | None
    flower_alignment: float
    node_distance: float


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scale: float) -> Point:
    return a[0] * scale, a[1] * scale


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _length(v: Point) -> float:
    return math.hypot(v[0], v[1])


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _norm(v: Point) -> Point:
    length = _length(v)
    if length < 1e-9:
        return 1.0, 0.0
    return v[0] / length, v[1] / length


def _normal(tangent: Point) -> Point:
    return -tangent[1], tangent[0]


def _polyline_length(points: list[Point]) -> float:
    return sum(_dist(a, b) for a, b in zip(points, points[1:]))


def _dedupe(points: Iterable[Point], tolerance: float = 0.15) -> list[Point]:
    result: list[Point] = []
    for point in points:
        if not result or _dist(result[-1], point) > tolerance:
            result.append(point)
    return result


def _segment_x_intersection(a: Point, b: Point, x: float) -> Point | None:
    dx = b[0] - a[0]
    if abs(dx) < 1e-9:
        return None
    t = (x - a[0]) / dx
    if 0.0 <= t <= 1.0:
        return x, a[1] + (b[1] - a[1]) * t
    return None


def _clip_polyline_x(points: list[Point], x0: float, x1: float) -> list[Point]:
    if len(points) < 2:
        return []
    clipped: list[Point] = []
    for a, b in zip(points, points[1:]):
        a_inside = x0 - 1e-6 <= a[0] <= x1 + 1e-6
        b_inside = x0 - 1e-6 <= b[0] <= x1 + 1e-6
        if a_inside and (not clipped or _dist(clipped[-1], a) > 0.1):
            clipped.append(a)
        if a_inside != b_inside:
            boundary = x0 if min(a[0], b[0]) <= x0 <= max(a[0], b[0]) else x1
            intersection = _segment_x_intersection(a, b, boundary)
            if intersection is not None and (not clipped or _dist(clipped[-1], intersection) > 0.1):
                clipped.append(intersection)
        if b_inside and (not clipped or _dist(clipped[-1], b) > 0.1):
            clipped.append(b)
    return _dedupe(clipped)


def _extract_backbone_chain(paths: list[eng.PathFeature], x0: float, x1: float) -> tuple[list[Point], list[int], list[str]]:
    segments: list[tuple[int, list[Point]]] = []
    for feature in paths:
        if feature.role != "backbone":
            continue
        clipped = _clip_polyline_x(feature.points, x0, x1)
        if len(clipped) >= 2 and _polyline_length(clipped) >= 4.0:
            segments.append((feature.source_index, clipped))
    if not segments:
        raise RuntimeError("No backbone segments intersect the requested repeat")

    start_candidates: list[tuple[float, int, bool]] = []
    for index, (_, segment) in enumerate(segments):
        start_candidates.append((abs(segment[0][0] - x0), index, False))
        start_candidates.append((abs(segment[-1][0] - x0), index, True))
    _, start_index, reverse = min(start_candidates)
    source_index, first = segments[start_index]
    chain = list(reversed(first)) if reverse else list(first)
    used = {start_index}
    source_order = [source_index]
    warnings: list[str] = []

    while len(used) < len(segments) and chain[-1][0] < x1 - 0.5:
        best: tuple[float, int, bool] | None = None
        for index, (_, segment) in enumerate(segments):
            if index in used:
                continue
            for should_reverse, endpoint in ((False, segment[0]), (True, segment[-1])):
                distance = _dist(chain[-1], endpoint)
                candidate = (distance, index, should_reverse)
                if best is None or candidate < best:
                    best = candidate
        if best is None or best[0] > 8.0:
            warnings.append(f"backbone_chain_gap_after_{len(source_order)}={best[0] if best else -1:.3f}")
            break
        distance, index, should_reverse = best
        source_index, segment = segments[index]
        oriented = list(reversed(segment)) if should_reverse else list(segment)
        if distance <= 0.75:
            chain.extend(oriented[1:])
        else:
            warnings.append(f"backbone_join_gap_{source_order[-1]}_{source_index}={distance:.3f}")
            chain.extend(oriented)
        used.add(index)
        source_order.append(source_index)

    if chain[0][0] > chain[-1][0]:
        chain.reverse()
        source_order.reverse()
    if abs(chain[0][0] - x0) > 2.0:
        warnings.append(f"left_boundary_gap={abs(chain[0][0] - x0):.3f}")
    if abs(chain[-1][0] - x1) > 2.0:
        warnings.append(f"right_boundary_gap={abs(chain[-1][0] - x1):.3f}")
    return _dedupe(chain), source_order, warnings


def _cumulative_lengths(points: list[Point]) -> list[float]:
    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + _dist(a, b))
    return cumulative


def _sample_polyline(points: list[Point], cumulative: list[float], s: float) -> tuple[Point, Point]:
    total = cumulative[-1]
    target = max(0.0, min(1.0, s)) * total
    index = 0
    while index + 1 < len(cumulative) and cumulative[index + 1] < target:
        index += 1
    if index + 1 >= len(points):
        tangent = _norm(_sub(points[-1], points[-2]))
        return points[-1], tangent
    segment_length = max(1e-9, cumulative[index + 1] - cumulative[index])
    local = (target - cumulative[index]) / segment_length
    a, b = points[index], points[index + 1]
    point = a[0] + (b[0] - a[0]) * local, a[1] + (b[1] - a[1]) * local
    return point, _norm(_sub(b, a))


def _moving_average(values: list[float], radius: int = 3) -> list[float]:
    result: list[float] = []
    for index in range(len(values)):
        lo = max(0, index - radius)
        hi = min(len(values), index + radius + 1)
        result.append(sum(values[lo:hi]) / (hi - lo))
    return result


def _curvature(samples: list[tuple[Point, Point]], index: int, step_length: float) -> float:
    if index <= 0 or index >= len(samples) - 1:
        return 0.0
    prev_tangent = samples[index - 1][1]
    next_tangent = samples[index + 1][1]
    cross = prev_tangent[0] * next_tangent[1] - prev_tangent[1] * next_tangent[0]
    dot = max(-1.0, min(1.0, _dot(prev_tangent, next_tangent)))
    return math.atan2(cross, dot) / max(step_length * 2.0, 1e-6)


def _arc_samples(points: list[Point], count: int = 161) -> list[ArcSample]:
    cumulative = _cumulative_lengths(points)
    raw = [_sample_polyline(points, cumulative, index / (count - 1)) for index in range(count)]
    step_length = cumulative[-1] / max(1, count - 1)
    return [
        ArcSample(
            s=index / (count - 1),
            point=point,
            tangent=tangent,
            normal=_normal(tangent),
            curvature=_curvature(raw, index, step_length),
        )
        for index, (point, tangent) in enumerate(raw)
    ]


def _detect_nodes(samples: list[ArcSample]) -> list[dict[str, object]]:
    ys = _moving_average([sample.point[1] for sample in samples], radius=4)
    amplitude = max(ys) - min(ys)
    prominence_threshold = max(4.0, amplitude * 0.065)
    window = max(8, round(len(samples) * 0.085))
    candidates: list[dict[str, object]] = []
    for index in range(2, len(samples) - 2):
        before = ys[index] - ys[index - 2]
        after = ys[index + 2] - ys[index]
        if before < 0.0 <= after:
            kind = "peak"
            prominence = max(ys[max(0, index - window) : min(len(ys), index + window + 1)]) - ys[index]
        elif before > 0.0 >= after:
            kind = "trough"
            prominence = ys[index] - min(ys[max(0, index - window) : min(len(ys), index + window + 1)])
        else:
            continue
        if prominence < prominence_threshold:
            continue
        candidates.append(
            {
                "kind": kind,
                "sample_index": index,
                "s": samples[index].s,
                "point": samples[index].point,
                "prominence": prominence,
                "curvature": samples[index].curvature,
            }
        )

    filtered: list[dict[str, object]] = []
    min_separation = 0.085
    for candidate in sorted(candidates, key=lambda item: float(item["prominence"]), reverse=True):
        if any(abs(float(candidate["s"]) - float(existing["s"])) < min_separation for existing in filtered):
            continue
        filtered.append(candidate)
    filtered.sort(key=lambda item: float(item["s"]))

    present = {str(item["kind"]) for item in filtered}
    if "peak" not in present:
        index = min(range(2, len(ys) - 2), key=lambda i: ys[i])
        filtered.append(
            {
                "kind": "peak",
                "sample_index": index,
                "s": samples[index].s,
                "point": samples[index].point,
                "prominence": max(ys) - ys[index],
                "curvature": samples[index].curvature,
                "fallback": True,
            }
        )
    if "trough" not in present:
        index = max(range(2, len(ys) - 2), key=lambda i: ys[i])
        filtered.append(
            {
                "kind": "trough",
                "sample_index": index,
                "s": samples[index].s,
                "point": samples[index].point,
                "prominence": ys[index] - min(ys),
                "curvature": samples[index].curvature,
                "fallback": True,
            }
        )
    filtered.sort(key=lambda item: float(item["s"]))
    kind_counts = {"peak": 0, "trough": 0}
    for node in filtered:
        kind = str(node["kind"])
        kind_counts[kind] += 1
        node["node_id"] = f"{kind}_{kind_counts[kind]}"
    return filtered


def _segment_semantics(samples: list[ArcSample], nodes: list[dict[str, object]]) -> list[dict[str, object]]:
    boundaries = [0.0] + [float(node["s"]) for node in nodes if 0.025 < float(node["s"]) < 0.975] + [1.0]
    boundaries = sorted(set(round(value, 6) for value in boundaries))
    result: list[dict[str, object]] = []
    for index, (start_s, end_s) in enumerate(zip(boundaries, boundaries[1:])):
        start_index = min(len(samples) - 1, round(start_s * (len(samples) - 1)))
        end_index = min(len(samples) - 1, round(end_s * (len(samples) - 1)))
        dy = samples[end_index].point[1] - samples[start_index].point[1]
        if dy < -3.0:
            label = "rising"
        elif dy > 3.0:
            label = "falling"
        else:
            label = "level"
        interval = samples[start_index : end_index + 1]
        result.append(
            {
                "segment_id": f"segment_{index + 1}",
                "start_s": start_s,
                "end_s": end_s,
                "flow": label,
                "start_point": samples[start_index].point,
                "end_point": samples[end_index].point,
                "mean_abs_curvature": sum(abs(sample.curvature) for sample in interval) / max(1, len(interval)),
            }
        )
    return result


def _nearest_pose(samples: list[ArcSample], point: Point) -> ArcSample:
    return min(samples, key=lambda sample: _dist(sample.point, point))


def _local_flowers(flowers: list[eng.FlowerReserve], x0: float, x1: float) -> list[eng.FlowerReserve]:
    return [flower for flower in flowers if x0 - 0.5 <= flower.cx <= x1 + 0.5]


def _flower_semantics(flowers: list[eng.FlowerReserve], samples: list[ArcSample], nodes: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index, flower in enumerate(flowers):
        center = (flower.cx, flower.cy)
        pose = _nearest_pose(samples, center)
        offset = _sub(center, pose.point)
        signed_normal_offset = _dot(offset, pose.normal)
        if flower.cy < pose.point[1] - 3.0:
            vertical_relation = "above_backbone"
        elif flower.cy > pose.point[1] + 3.0:
            vertical_relation = "below_backbone"
        else:
            vertical_relation = "on_backbone_band"
        nearest_node = min(nodes, key=lambda node: abs(float(node["s"]) - pose.s)) if nodes else None
        result.append(
            {
                "flower_id": f"flower_{index + 1}",
                "center": center,
                "radius": max(flower.rx, flower.ry),
                "rx": flower.rx,
                "ry": flower.ry,
                "nearest_backbone_s": pose.s,
                "nearest_backbone_point": pose.point,
                "vertical_relation": vertical_relation,
                "normal_side": "positive" if signed_normal_offset >= 0.0 else "negative",
                "signed_normal_offset": signed_normal_offset,
                "nearest_node_id": nearest_node["node_id"] if nearest_node else None,
                "nearest_node_kind": nearest_node["kind"] if nearest_node else None,
            }
        )
    return result


def _point_segment_distance(point: Point, a: Point, b: Point) -> float:
    ab = _sub(b, a)
    denom = _dot(ab, ab)
    if denom < 1e-9:
        return _dist(point, a)
    t = max(0.0, min(1.0, _dot(_sub(point, a), ab) / denom))
    projection = _add(a, _mul(ab, t))
    return _dist(point, projection)


def _point_polyline_distance(point: Point, points: list[Point]) -> float:
    if len(points) < 2:
        return 999.0
    return min(_point_segment_distance(point, a, b) for a, b in zip(points, points[1:]))


def _nearest_polyline_attachment(point: Point, points: list[Point]) -> tuple[float, Point, float]:
    if len(points) < 2:
        return 0.0, points[0] if points else point, 999.0
    segment_lengths = [_dist(a, b) for a, b in zip(points, points[1:])]
    total_length = sum(segment_lengths)
    best_distance = float("inf")
    best_fraction = 0.0
    best_point = points[0]
    traversed = 0.0
    for (a, b), segment_length in zip(zip(points, points[1:]), segment_lengths):
        ab = _sub(b, a)
        denom = _dot(ab, ab)
        local_t = 0.0 if denom < 1e-9 else max(0.0, min(1.0, _dot(_sub(point, a), ab) / denom))
        projection = _add(a, _mul(ab, local_t))
        distance = _dist(point, projection)
        if distance < best_distance:
            best_distance = distance
            best_point = projection
            best_fraction = 0.0 if total_length < 1e-9 else (traversed + segment_length * local_t) / total_length
        traversed += segment_length
    return best_fraction, best_point, best_distance


def _existing_guide_graph(
    paths: list[eng.PathFeature],
    backbone: list[Point],
    flowers: list[eng.FlowerReserve],
    *,
    x0: float,
    x1: float,
) -> tuple[list[dict[str, object]], list[str]]:
    candidates: list[dict[str, object]] = []
    for feature in paths:
        if feature.role not in {"primary_branch", "structural_branch", "leaf_guide"}:
            continue
        points = _clip_polyline_x(feature.points, x0, x1)
        if len(points) < 2:
            continue
        length = _polyline_length(points)
        if length < 8.0:
            continue
        candidates.append(
            {
                "source_index": feature.source_index,
                "source_role": feature.role,
                "points": points,
                "length": length,
            }
        )

    resolved: list[dict[str, object]] = []
    unresolved = list(candidates)
    warnings: list[str] = []
    while unresolved:
        best_choice: tuple[float, int, int, str, dict[str, object] | None, float, Point] | None = None
        for candidate_index, candidate in enumerate(unresolved):
            points = list(candidate["points"])
            for endpoint_index in (0, -1):
                endpoint = points[endpoint_index]
                fraction, projection, distance = _nearest_polyline_attachment(endpoint, backbone)
                if distance <= 8.0:
                    choice = (distance, candidate_index, endpoint_index, "backbone", None, fraction, projection)
                    if best_choice is None or choice[0] < best_choice[0]:
                        best_choice = choice
                for parent in resolved:
                    fraction, projection, distance = _nearest_polyline_attachment(endpoint, list(parent["points"]))
                    if distance > 6.0:
                        continue
                    choice = (distance, candidate_index, endpoint_index, "guide", parent, fraction, projection)
                    if best_choice is None or choice[0] < best_choice[0]:
                        best_choice = choice
        if best_choice is None:
            for candidate in unresolved:
                warnings.append(f"unresolved_guide_mount:source_{candidate['source_index']}")
            break

        distance, candidate_index, endpoint_index, parent_kind, parent, parent_fraction, mount_point = best_choice
        candidate = unresolved.pop(candidate_index)
        points = list(candidate["points"])
        if endpoint_index == -1:
            points.reverse()
        generation = 1 if parent_kind == "backbone" else int(parent["generation"]) + 1
        guide_id = f"guide_{len(resolved) + 1}"
        root = points[0]
        tip = points[-1]
        length = float(candidate["length"])
        source_role = str(candidate["source_role"])
        connector_flower_id: str | None = None
        for flower_index, flower in enumerate(flowers):
            if _inside_flower(tip, flower, padding=1.10):
                connector_flower_id = f"flower_{flower_index + 1}"
                break
        structural = source_role in {"primary_branch", "structural_branch"} or length >= 34.0
        semantic_role = "flower_connector" if connector_flower_id else "structural_guide" if structural else "terminal_hint"
        resolved.append(
            {
                "guide_id": guide_id,
                "source_index": candidate["source_index"],
                "source_role": source_role,
                "semantic_role": semantic_role,
                "connector_flower_id": connector_flower_id,
                "parent_kind": parent_kind,
                "parent_id": "backbone" if parent_kind == "backbone" else parent["guide_id"],
                "parent_fraction": parent_fraction,
                "mount_distance": distance,
                "generation": generation,
                "root": root,
                "tip": tip,
                "vertical_side": "upper" if tip[1] < root[1] else "lower",
                "length": length,
                "reproductive": not connector_flower_id and structural and length >= 42.0 and generation <= 2,
                "points": points,
                "mount_point": mount_point,
            }
        )
    resolved.sort(key=lambda guide: (int(guide["generation"]), float(guide["root"][0]), int(guide["source_index"])))
    id_remap = {str(guide["guide_id"]): f"guide_{index + 1}" for index, guide in enumerate(resolved)}
    for guide in resolved:
        old_id = str(guide["guide_id"])
        guide["guide_id"] = id_remap[old_id]
        if guide["parent_kind"] == "guide":
            guide["parent_id"] = id_remap[str(guide["parent_id"])]
    return resolved, warnings


def _filter_occupied_growth_regions(
    growth_regions: list[dict[str, object]],
    guides: list[dict[str, object]],
    backbone: list[Point],
) -> list[dict[str, object]]:
    occupied: list[tuple[float, str]] = []
    for guide in guides:
        if guide["parent_kind"] != "backbone" or not guide["reproductive"]:
            continue
        root_s, _, _ = _nearest_polyline_attachment(tuple(guide["root"]), backbone)
        occupied.append((root_s, str(guide["vertical_side"])))
    result = [
        region
        for region in growth_regions
        if not any(
            abs(float(region["attach_s"]) - root_s) < 0.09
            and str(region["vertical_side"]) == vertical_side
            for root_s, vertical_side in occupied
        )
    ]
    for index, region in enumerate(result):
        region["region_id"] = f"growth_region_{index + 1}"
    return result


def _inside_flower(point: Point, flower: eng.FlowerReserve, padding: float = 1.14) -> bool:
    rx = max(1.0, flower.rx * padding)
    ry = max(1.0, flower.ry * padding)
    return ((point[0] - flower.cx) / rx) ** 2 + ((point[1] - flower.cy) / ry) ** 2 <= 1.0


def _ray_clearance(
    root_sample: ArcSample,
    direction: Point,
    *,
    width: float,
    height: float,
    x0: float,
    x1: float,
    flowers: list[eng.FlowerReserve],
    obstacle_paths: list[list[Point]],
    backbone_samples: list[ArcSample],
    max_distance: float = 86.0,
) -> tuple[float, str]:
    step = 2.0
    distance = 7.0
    while distance <= max_distance:
        point = _add(root_sample.point, _mul(direction, distance))
        if point[0] < x0 + 7.0 or point[0] > x1 - 7.0 or point[1] < 7.0 or point[1] > height - 7.0:
            return max(0.0, distance - step), "repeat_or_canvas_boundary"
        if any(_inside_flower(point, flower) for flower in flowers):
            return max(0.0, distance - step), "flower_reserve"
        if any(_point_polyline_distance(point, path) < 5.2 for path in obstacle_paths):
            return max(0.0, distance - step), "existing_structure"
        if any(abs(sample.s - root_sample.s) > 0.075 and _dist(point, sample.point) < 6.0 for sample in backbone_samples):
            return max(0.0, distance - step), "backbone_return"
        distance += step
    return max_distance, "open"


def _space_samples(
    samples: list[ArcSample],
    flowers: list[eng.FlowerReserve],
    obstacle_paths: list[list[Point]],
    nodes: list[dict[str, object]],
    *,
    width: float,
    height: float,
    x0: float,
    x1: float,
) -> list[SpaceSample]:
    result: list[SpaceSample] = []
    positions = [0.08 + index * 0.04 for index in range(22)]
    for s in positions:
        sample = samples[min(len(samples) - 1, round(s * (len(samples) - 1)))]
        for side in (-1.0, 1.0):
            direction = _mul(sample.normal, side)
            clearance, blocked_by = _ray_clearance(
                sample,
                direction,
                width=width,
                height=height,
                x0=x0,
                x1=x1,
                flowers=flowers,
                obstacle_paths=obstacle_paths,
                backbone_samples=samples,
            )
            nearest_flower_id: str | None = None
            flower_alignment = -1.0
            if flowers:
                flower_index, nearest_flower = min(
                    enumerate(flowers),
                    key=lambda item: _dist(sample.point, (item[1].cx, item[1].cy)),
                )
                to_flower = _sub((nearest_flower.cx, nearest_flower.cy), sample.point)
                flower_alignment = _dot(direction, _norm(to_flower))
                flower_edge_distance = _length(to_flower) - max(nearest_flower.rx, nearest_flower.ry) * 1.14
                if flower_alignment > 0.55 and flower_edge_distance < 96.0:
                    clearance = min(clearance, max(0.0, flower_edge_distance - 8.0))
                    blocked_by = "points_toward_flower"
                nearest_flower_id = f"flower_{flower_index + 1}"
            vertical_side = "upper" if direction[1] < 0.0 else "lower"
            curvature_penalty = min(18.0, abs(sample.curvature) * 120.0)
            edge_penalty = max(0.0, 0.11 - min(s, 1.0 - s)) * 80.0
            node_distance = min((abs(sample.s - float(node["s"])) for node in nodes), default=1.0)
            node_penalty = max(0.0, 0.055 - node_distance) * 320.0
            score = clearance - curvature_penalty - edge_penalty - node_penalty
            result.append(
                SpaceSample(
                    s=sample.s,
                    root=sample.point,
                    side=side,
                    vertical_side=vertical_side,
                    direction=direction,
                    clearance=clearance,
                    blocked_by=blocked_by,
                    score=score,
                    nearest_flower_id=nearest_flower_id,
                    flower_alignment=flower_alignment,
                    node_distance=node_distance,
                )
            )
    return result


def _growth_regions(space_samples: list[SpaceSample], amplitude: float) -> list[dict[str, object]]:
    clearance_threshold = max(28.0, min(42.0, 27.0 + amplitude * 0.055))
    eligible = [
        sample
        for sample in space_samples
        if sample.clearance >= clearance_threshold
        and sample.blocked_by != "points_toward_flower"
        and sample.node_distance >= 0.03
    ]
    groups: list[list[SpaceSample]] = []
    for vertical_side in ("upper", "lower"):
        side_samples = sorted((sample for sample in eligible if sample.vertical_side == vertical_side), key=lambda item: item.s)
        current: list[SpaceSample] = []
        for sample in side_samples:
            if current and sample.s - current[-1].s > 0.061:
                groups.append(current)
                current = []
            current.append(sample)
        if current:
            groups.append(current)

    regions: list[dict[str, object]] = []
    for group in groups:
        best = max(group, key=lambda sample: sample.score)
        span = group[-1].s - group[0].s
        if span < 0.035 and best.clearance < clearance_threshold + 10.0:
            continue
        capacity = "long_plus_children" if best.clearance >= 62.0 and span >= 0.07 else "single_long" if best.clearance >= 43.0 else "short_only"
        regions.append(
            {
                "region_id": "",
                "vertical_side": best.vertical_side,
                "start_s": group[0].s,
                "end_s": group[-1].s,
                "attach_s": best.s,
                "attach_point": best.root,
                "growth_direction": best.direction,
                "max_clearance": max(sample.clearance for sample in group),
                "mean_clearance": sum(sample.clearance for sample in group) / len(group),
                "capacity": capacity,
                "sample_count": len(group),
                "score": best.score + span * 35.0,
                "nearest_flower_id": best.nearest_flower_id,
                "flower_alignment": best.flower_alignment,
                "flower_relation": "away" if best.flower_alignment < -0.20 else "tangential" if best.flower_alignment <= 0.35 else "toward",
                "node_distance": best.node_distance,
            }
        )
    regions.sort(key=lambda region: float(region["score"]), reverse=True)

    selected: list[dict[str, object]] = []
    side_counts = {"upper": 0, "lower": 0}
    for region in regions:
        side = str(region["vertical_side"])
        if side_counts[side] >= 3:
            continue
        if any(abs(float(region["attach_s"]) - float(existing["attach_s"])) < 0.11 for existing in selected):
            continue
        selected.append(region)
        side_counts[side] += 1
        if len(selected) >= 5:
            break
    selected.sort(key=lambda region: float(region["attach_s"]))
    for index, region in enumerate(selected):
        region["region_id"] = f"growth_region_{index + 1}"
    return selected


def _edge_for_s(edges: list[dict[str, object]], s: float) -> dict[str, object]:
    containing = [
        edge
        for edge in edges
        if float(edge["start_s"]) - 1e-6 <= s <= float(edge["end_s"]) + 1e-6
    ]
    if containing:
        return min(
            containing,
            key=lambda edge: abs(s - (float(edge["start_s"]) + float(edge["end_s"])) * 0.5),
        )
    return min(
        edges,
        key=lambda edge: min(abs(s - float(edge["start_s"])), abs(s - float(edge["end_s"]))),
    )


def _build_region_graph(
    samples: list[ArcSample],
    nodes: list[dict[str, object]],
    segments: list[dict[str, object]],
    flowers: list[dict[str, object]],
    growth_regions: list[dict[str, object]],
    existing_guides: list[dict[str, object]],
) -> dict[str, object]:
    graph_nodes: list[dict[str, object]] = [
        {
            "graph_node_id": "repeat_start",
            "kind": "repeat_boundary",
            "s": 0.0,
            "point": samples[0].point,
        }
    ]
    graph_nodes.extend(
        {
            "graph_node_id": str(node["node_id"]),
            "kind": str(node["kind"]),
            "s": float(node["s"]),
            "point": node["point"],
        }
        for node in nodes
        if 0.025 < float(node["s"]) < 0.975
    )
    graph_nodes.append(
        {
            "graph_node_id": "repeat_end",
            "kind": "repeat_boundary",
            "s": 1.0,
            "point": samples[-1].point,
        }
    )
    graph_nodes.sort(key=lambda node: float(node["s"]))

    backbone_edges: list[dict[str, object]] = []
    for index, segment in enumerate(segments):
        start_node = graph_nodes[index]
        end_node = graph_nodes[index + 1]
        backbone_edges.append(
            {
                "graph_edge_id": f"backbone_edge_{index + 1}",
                "segment_id": segment["segment_id"],
                "from_node": start_node["graph_node_id"],
                "to_node": end_node["graph_node_id"],
                "start_s": segment["start_s"],
                "end_s": segment["end_s"],
                "flow": segment["flow"],
                "mean_abs_curvature": segment["mean_abs_curvature"],
            }
        )

    attachments: list[dict[str, object]] = []
    for flower in flowers:
        s = float(flower["nearest_backbone_s"])
        edge = _edge_for_s(backbone_edges, s)
        vertical_relation = str(flower["vertical_relation"])
        if vertical_relation == "above_backbone":
            forbidden_vertical_side = "upper"
        elif vertical_relation == "below_backbone":
            forbidden_vertical_side = "lower"
        else:
            forbidden_vertical_side = "both"
        attachments.append(
            {
                "attachment_id": f"{flower['flower_id']}_context",
                "kind": "flower_context",
                "semantic_id": flower["flower_id"],
                "edge_id": edge["graph_edge_id"],
                "s": s,
                "vertical_relation": vertical_relation,
                "forbidden_vertical_side": forbidden_vertical_side,
                "clearance_radius": flower["radius"],
            }
        )
    for region in growth_regions:
        s = float(region["attach_s"])
        edge = _edge_for_s(backbone_edges, s)
        attachments.append(
            {
                "attachment_id": f"{region['region_id']}_anchor",
                "kind": "growth_anchor",
                "semantic_id": region["region_id"],
                "edge_id": edge["graph_edge_id"],
                "s": s,
                "vertical_side": region["vertical_side"],
                "flower_relation": region["flower_relation"],
                "capacity": region["capacity"],
                "max_clearance": region["max_clearance"],
            }
        )
    guide_edges: list[dict[str, object]] = []
    for guide in existing_guides:
        entry = {
            key: value
            for key, value in guide.items()
            if key not in {"mount_point"}
        }
        if guide["parent_kind"] == "backbone":
            root_s, _, _ = _nearest_polyline_attachment(tuple(guide["root"]), [sample.point for sample in samples])
            edge = _edge_for_s(backbone_edges, root_s)
            entry["parent_id"] = edge["graph_edge_id"]
            entry["backbone_s"] = root_s
        guide_edges.append(entry)
        attachments.append(
            {
                "attachment_id": f"{guide['guide_id']}_mount",
                "kind": "existing_guide_mount",
                "semantic_id": guide["guide_id"],
                "parent_kind": guide["parent_kind"],
                "parent_id": entry["parent_id"],
                "generation": guide["generation"],
                "reproductive": guide["reproductive"],
            }
        )

    adjacency = {str(node["graph_node_id"]): [] for node in graph_nodes}
    for edge in backbone_edges:
        edge_id = str(edge["graph_edge_id"])
        adjacency[str(edge["from_node"])].append(edge_id)
        adjacency[str(edge["to_node"])].append(edge_id)

    graph = {
        "schema": "chanzhi_region_graph_v1",
        "coordinate_system": {
            "backbone_position": "normalized_arc_length",
            "side_reference": "canvas_vertical_side",
            "absolute_svg_path_indices_required": False,
        },
        "nodes": graph_nodes,
        "backbone_edges": backbone_edges,
        "guide_edges": guide_edges,
        "attachments": attachments,
        "adjacency": adjacency,
        "grammar_inputs": {
            "long_branch_anchors": [
                attachment["attachment_id"]
                for attachment in attachments
                if attachment["kind"] == "growth_anchor"
            ],
            "flower_constraints": [
                attachment["attachment_id"]
                for attachment in attachments
                if attachment["kind"] == "flower_context"
            ],
            "reproductive_guides": [
                guide["guide_id"]
                for guide in guide_edges
                if guide["reproductive"]
            ],
            "minimum_anchor_spacing_s": 0.11,
            "prohibited_growth_relation": "toward",
        },
    }
    errors = _validate_region_graph(graph)
    graph["qa"] = {"valid": not errors, "errors": errors}
    return graph


def _validate_region_graph(graph: dict[str, object]) -> list[str]:
    nodes = list(graph["nodes"])
    edges = list(graph["backbone_edges"])
    guide_edges = list(graph["guide_edges"])
    attachments = list(graph["attachments"])
    errors: list[str] = []
    if len(edges) != max(0, len(nodes) - 1):
        errors.append("backbone_edge_count_mismatch")
    node_ids = {str(node["graph_node_id"]) for node in nodes}
    edge_ids = {str(edge["graph_edge_id"]) for edge in edges}
    previous_end = 0.0
    for index, edge in enumerate(edges):
        if edge["from_node"] not in node_ids or edge["to_node"] not in node_ids:
            errors.append(f"unknown_edge_endpoint:{edge['graph_edge_id']}")
        start_s = float(edge["start_s"])
        end_s = float(edge["end_s"])
        if end_s <= start_s:
            errors.append(f"non_positive_edge_span:{edge['graph_edge_id']}")
        if index and abs(start_s - previous_end) > 1e-5:
            errors.append(f"non_contiguous_edge:{edge['graph_edge_id']}")
        previous_end = end_s
    for attachment in attachments:
        if attachment["kind"] == "existing_guide_mount":
            continue
        edge_id = str(attachment["edge_id"])
        if edge_id not in edge_ids:
            errors.append(f"unknown_attachment_edge:{attachment['attachment_id']}")
            continue
        edge = next(edge for edge in edges if edge["graph_edge_id"] == edge_id)
        s = float(attachment["s"])
        if not float(edge["start_s"]) - 1e-6 <= s <= float(edge["end_s"]) + 1e-6:
            errors.append(f"attachment_outside_edge:{attachment['attachment_id']}")
        if attachment["kind"] == "growth_anchor" and attachment["flower_relation"] == "toward":
            errors.append(f"growth_anchor_points_toward_flower:{attachment['attachment_id']}")
    guide_ids = {str(guide["guide_id"]) for guide in guide_edges}
    for guide in guide_edges:
        parent_id = str(guide["parent_id"])
        if guide["parent_kind"] == "backbone" and parent_id not in edge_ids:
            errors.append(f"unknown_guide_backbone_parent:{guide['guide_id']}")
        if guide["parent_kind"] == "guide" and parent_id not in guide_ids:
            errors.append(f"unknown_guide_parent:{guide['guide_id']}")
        if guide["parent_kind"] == "guide":
            parent = next(item for item in guide_edges if item["guide_id"] == parent_id)
            if int(guide["generation"]) != int(parent["generation"]) + 1:
                errors.append(f"invalid_guide_generation:{guide['guide_id']}")
    adjacency = dict(graph["adjacency"])
    for index, node in enumerate(nodes):
        degree = len(adjacency.get(str(node["graph_node_id"]), []))
        expected_degree = 1 if index in (0, len(nodes) - 1) else 2
        if degree != expected_degree:
            errors.append(f"unexpected_node_degree:{node['graph_node_id']}:{degree}")
    return errors


def _round_point(point: Point) -> list[float]:
    return [round(point[0], 3), round(point[1], 3)]


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


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
    ):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _draw_polyline(draw: ImageDraw.ImageDraw, points: list[Point], transform, fill: str, width: int) -> None:
    if len(points) >= 2:
        draw.line([transform(point) for point in points], fill=fill, width=width, joint="curve")


def _render_overlay(
    *,
    prototype_id: str,
    width: int,
    height: int,
    x0: float,
    x1: float,
    context_paths: list[eng.PathFeature],
    backbone: list[Point],
    samples: list[ArcSample],
    nodes: list[dict[str, object]],
    segments: list[dict[str, object]],
    flowers: list[eng.FlowerReserve],
    flower_profiles: list[dict[str, object]],
    space_samples: list[SpaceSample],
    growth_regions: list[dict[str, object]],
) -> Image.Image:
    scale = 2.4
    margin_x = 26.0
    margin_top = 38.0
    margin_bottom = 24.0
    canvas_w = round((x1 - x0 + margin_x * 2) * scale)
    canvas_h = round((height + margin_top + margin_bottom) * scale)
    image = Image.new("RGB", (canvas_w, canvas_h), PAPER)
    draw = ImageDraw.Draw(image)
    font = _font(9 * round(scale))
    small_font = _font(7 * round(scale))

    def transform(point: Point) -> tuple[int, int]:
        return (
            round((point[0] - x0 + margin_x) * scale),
            round((point[1] + margin_top) * scale),
        )

    draw.text((12, 8), f"{prototype_id} | semantic backbone profile", fill=INK, font=font)
    for boundary_x in (x0, x1):
        px, _ = transform((boundary_x, 0.0))
        draw.line((px, transform((boundary_x, 0.0))[1], px, transform((boundary_x, height))[1]), fill=BOUNDARY, width=2)

    for feature in context_paths:
        if feature.role == "backbone":
            continue
        clipped = _clip_polyline_x(feature.points, x0, x1)
        _draw_polyline(draw, clipped, transform, CONTEXT, max(1, round(scale * 0.65)))

    segment_colors = {"rising": "#2563eb", "falling": "#7c3aed", "level": "#0f766e"}
    for segment in segments:
        selected_points = [
            sample.point
            for sample in samples
            if float(segment["start_s"]) - 1e-6 <= sample.s <= float(segment["end_s"]) + 1e-6
        ]
        _draw_polyline(draw, selected_points, transform, segment_colors[str(segment["flow"])], max(2, round(scale * 1.7)))

    for space in space_samples:
        end = _add(space.root, _mul(space.direction, min(space.clearance, 32.0)))
        color = UPPER if space.vertical_side == "upper" else LOWER
        if space.blocked_by == "points_toward_flower":
            color = "#f9a8d4"
        elif space.clearance < 28.0:
            color = BLOCKED
        root_px = transform(space.root)
        end_px = transform(end)
        draw.line((root_px, end_px), fill=color, width=max(1, round(scale * 0.42)))

    for flower, profile in zip(flowers, flower_profiles):
        center = transform((flower.cx, flower.cy))
        rx = round(flower.rx * scale)
        ry = round(flower.ry * scale)
        draw.ellipse((center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry), outline=FLOWER, width=max(2, round(scale)))
        nearest = transform(tuple(profile["nearest_backbone_point"]))
        draw.line((center, nearest), fill="#f9a8d4", width=max(1, round(scale * 0.55)))
        draw.text(
            (center[0] - rx, center[1] - ry - round(9 * scale)),
            f"{profile['flower_id']} {profile['vertical_relation']}",
            fill=FLOWER,
            font=small_font,
        )

    for node in nodes:
        point = tuple(node["point"])
        px = transform(point)
        color = PEAK if node["kind"] == "peak" else TROUGH
        radius = round(3.1 * scale)
        draw.ellipse((px[0] - radius, px[1] - radius, px[0] + radius, px[1] + radius), fill=PAPER, outline=color, width=max(2, round(scale)))
        draw.text((px[0] + radius + 2, px[1] - radius - 2), f"{node['node_id']} s={float(node['s']):.2f}", fill=color, font=small_font)

    for region in growth_regions:
        root = tuple(region["attach_point"])
        direction = tuple(region["growth_direction"])
        length = min(58.0, float(region["max_clearance"]) * 0.78)
        end = _add(root, _mul(direction, length))
        color = UPPER if region["vertical_side"] == "upper" else LOWER
        root_px = transform(root)
        end_px = transform(end)
        draw.line((root_px, end_px), fill=color, width=max(2, round(scale * 1.15)))
        radius = round(3.0 * scale)
        draw.ellipse((root_px[0] - radius, root_px[1] - radius, root_px[0] + radius, root_px[1] + radius), fill=color)
        draw.text(
            (end_px[0] + 2, end_px[1] - round(5 * scale)),
            f"{region['region_id']} {region['capacity']} {region['flower_relation']}",
            fill=color,
            font=small_font,
        )

    legend_y = canvas_h - round(17 * scale)
    draw.text(
        (12, legend_y),
        "blue/rising  purple/falling  red/peak  blue-dot/trough  green/upper space  ochre/lower space",
        fill="#475569",
        font=small_font,
    )
    return image


def _analyze_one(
    svg_path: Path,
    output_dir: Path,
    *,
    repeat_index: int,
    repeat_width: float,
    tile_width: int,
) -> tuple[dict[str, object], Path]:
    prototype_id = svg_path.parent.name
    width, height, paths, flowers = eng._load_skeleton(svg_path, tile_width)
    x0 = repeat_index * repeat_width
    x1 = x0 + repeat_width
    backbone, source_order, chain_warnings = _extract_backbone_chain(paths, x0, x1)
    samples = _arc_samples(backbone)
    nodes = _detect_nodes(samples)
    segments = _segment_semantics(samples, nodes)
    local_flowers = _local_flowers(flowers, x0, x1)
    flower_profiles = _flower_semantics(local_flowers, samples, nodes)
    obstacle_paths = [
        clipped
        for feature in paths
        if feature.role != "backbone"
        for clipped in [_clip_polyline_x(feature.points, x0, x1)]
        if len(clipped) >= 2
    ]
    space_samples = _space_samples(
        samples,
        local_flowers,
        obstacle_paths,
        nodes,
        width=width,
        height=height,
        x0=x0,
        x1=x1,
    )
    amplitude = max(sample.point[1] for sample in samples) - min(sample.point[1] for sample in samples)
    growth_regions = _growth_regions(space_samples, amplitude)
    existing_guides, guide_warnings = _existing_guide_graph(paths, backbone, local_flowers, x0=x0, x1=x1)
    growth_regions = _filter_occupied_growth_regions(growth_regions, existing_guides, backbone)
    region_graph = _build_region_graph(samples, nodes, segments, flower_profiles, growth_regions, existing_guides)
    total_length = _polyline_length(backbone)
    bbox = [
        min(point[0] for point in backbone),
        min(point[1] for point in backbone),
        max(point[0] for point in backbone),
        max(point[1] for point in backbone),
    ]
    profile: dict[str, object] = {
        "version": "0.1",
        "prototype_id": prototype_id,
        "input_svg": str(svg_path),
        "repeat_index": repeat_index,
        "repeat_x_range": [x0, x1],
        "canvas": {"width": width, "height": height},
        "backbone": {
            "source_path_order": source_order,
            "path_length": total_length,
            "bbox": bbox,
            "amplitude": amplitude,
            "left_boundary_gap": abs(backbone[0][0] - x0),
            "right_boundary_gap": abs(backbone[-1][0] - x1),
            "arc_samples": [
                {
                    "s": sample.s,
                    "point": sample.point,
                    "tangent": sample.tangent,
                    "normal": sample.normal,
                    "curvature": sample.curvature,
                }
                for sample in samples[::2]
            ],
        },
        "nodes": nodes,
        "segments": segments,
        "flowers": flower_profiles,
        "space_samples": [asdict(sample) for sample in space_samples],
        "growth_regions": growth_regions,
        "existing_guides": existing_guides,
        "region_graph": region_graph,
        "qa": {
            "chain_warnings": chain_warnings,
            "backbone_connected": not any("gap" in warning for warning in chain_warnings),
            "peak_count": sum(1 for node in nodes if node["kind"] == "peak"),
            "trough_count": sum(1 for node in nodes if node["kind"] == "trough"),
            "flower_count": len(local_flowers),
            "growth_region_count": len(growth_regions),
            "region_graph_valid": region_graph["qa"]["valid"],
            "region_graph_errors": region_graph["qa"]["errors"],
            "guide_warnings": guide_warnings,
            "existing_guide_count": len(existing_guides),
            "reproductive_guide_count": sum(1 for guide in existing_guides if guide["reproductive"]),
            "uses_fixed_source_indices": False,
            "uses_absolute_branch_slots": False,
        },
        "migration_contract": {
            "transferable": [
                "normalized arc length",
                "peak/trough node types",
                "rising/falling segment roles",
                "flower above/below relation",
                "normal-side free-space regions",
                "growth-region capacity",
            ],
            "must_be_recomputed_per_backbone": [
                "attachment coordinates",
                "tangent and normal",
                "available branch length",
                "flower avoidance side",
                "candidate region score",
            ],
        },
    }

    case_dir = output_dir / prototype_id
    case_dir.mkdir(parents=True, exist_ok=True)
    profile_path = case_dir / "skeleton_profile.json"
    profile_path.write_text(json.dumps(_jsonable(profile), ensure_ascii=False, indent=2), encoding="utf-8")
    graph_path = case_dir / "region_graph.json"
    graph_path.write_text(json.dumps(_jsonable(region_graph), ensure_ascii=False, indent=2), encoding="utf-8")
    overlay = _render_overlay(
        prototype_id=prototype_id,
        width=width,
        height=height,
        x0=x0,
        x1=x1,
        context_paths=paths,
        backbone=backbone,
        samples=samples,
        nodes=nodes,
        segments=segments,
        flowers=local_flowers,
        flower_profiles=flower_profiles,
        space_samples=space_samples,
        growth_regions=growth_regions,
    )
    overlay_path = case_dir / "skeleton_profile_overlay.png"
    overlay.save(overlay_path)
    return profile, overlay_path


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
        x = (index % columns) * cell_w
        y = (index // columns) * cell_h
        sheet.paste(image, (x, y))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def _resolve_svg(input_root: Path, prototype_id: str) -> Path:
    path = input_root / prototype_id / f"{prototype_id}_baseline.svg"
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def run(args: argparse.Namespace) -> dict[str, object]:
    input_root = args.input_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    profiles: list[dict[str, object]] = []
    overlays: list[tuple[str, Path]] = []
    errors: list[dict[str, str]] = []
    for prototype_id in args.prototype_ids:
        svg_path = _resolve_svg(input_root, prototype_id)
        try:
            profile, overlay_path = _analyze_one(
                svg_path,
                output_dir,
                repeat_index=args.repeat_index,
                repeat_width=args.repeat_width,
                tile_width=args.tile_width,
            )
            profiles.append(profile)
            overlays.append((prototype_id, overlay_path))
            print(f"Analyzed {prototype_id}: {overlay_path}")
        except Exception as exc:
            errors.append({"prototype_id": prototype_id, "error": repr(exc)})
            print(f"Failed {prototype_id}: {exc}")

    contact_sheet = output_dir / "skeleton_profile_contact_sheet.png"
    _contact_sheet(overlays, contact_sheet)
    manifest = {
        "version": "0.1",
        "input_root": str(input_root),
        "output_dir": str(output_dir),
        "prototype_ids": list(args.prototype_ids),
        "success_count": len(profiles),
        "error_count": len(errors),
        "errors": errors,
        "contact_sheet": str(contact_sheet),
        "summary": [
            {
                "prototype_id": profile["prototype_id"],
                "amplitude": profile["backbone"]["amplitude"],
                "path_length": profile["backbone"]["path_length"],
                "peak_count": profile["qa"]["peak_count"],
                "trough_count": profile["qa"]["trough_count"],
                "flower_count": profile["qa"]["flower_count"],
                "growth_region_count": profile["qa"]["growth_region_count"],
                "flower_relations": [flower["vertical_relation"] for flower in profile["flowers"]],
                "chain_warnings": profile["qa"]["chain_warnings"],
                "region_graph_valid": profile["qa"]["region_graph_valid"],
                "region_graph_errors": profile["qa"]["region_graph_errors"],
                "existing_guide_count": profile["qa"]["existing_guide_count"],
                "reproductive_guide_count": profile["qa"]["reproductive_guide_count"],
                "guide_warnings": profile["qa"]["guide_warnings"],
            }
            for profile in profiles
        ],
    }
    manifest_path = output_dir / "skeleton_analyzer_manifest.json"
    manifest_path.write_text(json.dumps(_jsonable(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {contact_sheet}")
    print(f"Saved {manifest_path}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Chanzhi main-backbone semantics across multiple SW prototypes.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "newpipe" / "outputs" / "chanzhi_skeleton_analysis" / "run1")
    parser.add_argument("--prototype-ids", nargs="+", default=list(DEFAULT_PROTOTYPE_IDS))
    parser.add_argument("--repeat-index", type=int, default=0)
    parser.add_argument("--repeat-width", type=float, default=256.0)
    parser.add_argument("--tile-width", type=int, default=512)
    manifest = run(parser.parse_args())
    return 0 if not manifest["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
