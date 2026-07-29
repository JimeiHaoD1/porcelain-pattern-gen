"""Shared deterministic geometry metrics for dynamic BranchUnit optimization line R."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


Point = tuple[float, float]


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def scope(
    prototype_id: str = "",
    seed: int = 0,
    lane_id: str = "",
    branch_unit_id: str = "",
    curve_id: str = "",
) -> dict[str, object]:
    return {
        "prototype_id": prototype_id,
        "seed": seed,
        "lane_id": lane_id,
        "branch_unit_id": branch_unit_id,
        "curve_id": curve_id,
    }


def metric_row(
    metric_name: str,
    measured_value: object,
    metric_scope: Mapping[str, object],
    *,
    source: str,
    applicable: bool = True,
) -> dict[str, object]:
    return {
        "metric_name": metric_name,
        "scope": dict(metric_scope),
        "measured_value": measured_value,
        "applicable": applicable,
        "source": source,
    }


def _point(value: Sequence[object]) -> Point:
    return (float(value[0]), float(value[1]))


def _sub(first: Point, second: Point) -> Point:
    return (first[0] - second[0], first[1] - second[1])


def _dot(first: Point, second: Point) -> float:
    return first[0] * second[0] + first[1] * second[1]


def _cross(first: Point, second: Point) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _norm(vector: Point) -> float:
    return math.hypot(vector[0], vector[1])


def _unit(vector: Point) -> Point:
    length = _norm(vector)
    if length <= 1e-12:
        return (0.0, 0.0)
    return (vector[0] / length, vector[1] / length)


def angle_degrees(first: Point, second: Point, *, unsigned_axis: bool = False) -> float:
    first_unit = _unit(first)
    second_unit = _unit(second)
    cosine = max(-1.0, min(1.0, _dot(first_unit, second_unit)))
    if unsigned_axis:
        cosine = abs(cosine)
    return math.degrees(math.acos(cosine))


def sample_cubic(segment: Mapping[str, object], sample_count: int) -> list[Point]:
    p0 = _point(segment["p0"])  # type: ignore[arg-type]
    p1 = _point(segment["p1"])  # type: ignore[arg-type]
    p2 = _point(segment["p2"])  # type: ignore[arg-type]
    p3 = _point(segment["p3"])  # type: ignore[arg-type]
    points: list[Point] = []
    for index in range(sample_count + 1):
        t = index / sample_count
        u = 1.0 - t
        points.append(
            (
                u**3 * p0[0]
                + 3.0 * u * u * t * p1[0]
                + 3.0 * u * t * t * p2[0]
                + t**3 * p3[0],
                u**3 * p0[1]
                + 3.0 * u * u * t * p1[1]
                + 3.0 * u * t * t * p2[1]
                + t**3 * p3[1],
            )
        )
    return points


def sample_segments(
    segments: Sequence[Mapping[str, object]],
    sample_count: int,
) -> list[Point]:
    points: list[Point] = []
    for segment in segments:
        sampled = sample_cubic(segment, sample_count)
        if points:
            sampled = sampled[1:]
        points.extend(sampled)
    return points


def polyline_length(points: Sequence[Point]) -> float:
    return sum(
        math.dist(first, second)
        for first, second in zip(points, points[1:])
    )


def cumulative_lengths(points: Sequence[Point]) -> list[float]:
    result = [0.0]
    for first, second in zip(points, points[1:]):
        result.append(result[-1] + math.dist(first, second))
    return result


def root_tangent_error(
    segments: Sequence[Mapping[str, object]],
    parent_tangent: Point,
) -> float:
    first = segments[0]
    direction = _sub(
        _point(first["p1"]),  # type: ignore[arg-type]
        _point(first["p0"]),  # type: ignore[arg-type]
    )
    return angle_degrees(direction, parent_tangent, unsigned_axis=True)


def horizontal_progress_ratio(points: Sequence[Point]) -> float:
    length = polyline_length(points)
    if length <= 1e-12:
        return 0.0
    return abs(points[-1][0] - points[0][0]) / length


def out_of_bounds_stats(
    points: Sequence[Point],
    y_min: float,
    y_max: float,
) -> tuple[float, float]:
    total = 0.0
    outside = 0.0
    for first, second in zip(points, points[1:]):
        length = math.dist(first, second)
        total += length
        midpoint_y = (first[1] + second[1]) * 0.5
        if midpoint_y < y_min or midpoint_y > y_max:
            outside += length
    return outside, outside / total if total > 1e-12 else 0.0


def nearest_backbone_sample(
    strict: Mapping[str, object],
    root_s: float,
) -> Mapping[str, object]:
    samples = strict["backbone"]["arc_samples"]  # type: ignore[index]
    return min(
        samples,
        key=lambda row: min(
            abs(float(row["s"]) - root_s),
            1.0 - abs(float(row["s"]) - root_s),
        ),
    )


def periodic_backbone_points(strict: Mapping[str, object]) -> list[Point]:
    samples = strict["backbone"]["arc_samples"]  # type: ignore[index]
    base = [_point(row["point"]) for row in samples]
    return [
        (point[0] + shift, point[1])
        for shift in (-2.0, -1.0, 0.0, 1.0, 2.0)
        for point in base
    ]


def point_segment_distance(point: Point, first: Point, second: Point) -> float:
    delta = _sub(second, first)
    denominator = _dot(delta, delta)
    if denominator <= 1e-16:
        return math.dist(point, first)
    t = max(0.0, min(1.0, _dot(_sub(point, first), delta) / denominator))
    projection = (first[0] + t * delta[0], first[1] + t * delta[1])
    return math.dist(point, projection)


def point_polyline_distance(point: Point, polyline: Sequence[Point]) -> float:
    return min(
        point_segment_distance(point, first, second)
        for first, second in zip(polyline, polyline[1:])
    )


def non_root_backbone_min_distance(
    points: Sequence[Point],
    strict: Mapping[str, object],
    root_exclusion_fraction: float,
) -> float:
    lengths = cumulative_lengths(points)
    total = lengths[-1]
    eligible = [
        point
        for point, distance in zip(points, lengths)
        if total <= 1e-12 or distance / total >= root_exclusion_fraction
    ]
    if not eligible:
        return 0.0
    backbone = periodic_backbone_points(strict)
    return min(point_polyline_distance(point, backbone) for point in eligible)


def root_local_density(root_s_values: Sequence[float], window: float) -> int:
    if not root_s_values:
        return 0
    roots = sorted(value % 1.0 for value in root_s_values)
    extended = roots + [value + 1.0 for value in roots]
    maximum = 0
    for start_index, start in enumerate(roots):
        count = sum(
            1
            for value in extended[start_index : start_index + len(roots)]
            if value - start <= window + 1e-12
        )
        maximum = max(maximum, count)
    return maximum


def _proper_segment_intersection(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
    epsilon: float,
) -> bool:
    first_delta = _sub(first_end, first_start)
    second_delta = _sub(second_end, second_start)
    denominator = _cross(first_delta, second_delta)
    if abs(denominator) <= epsilon:
        return False
    offset = _sub(second_start, first_start)
    first_t = _cross(offset, second_delta) / denominator
    second_t = _cross(offset, first_delta) / denominator
    return (
        epsilon < first_t < 1.0 - epsilon
        and epsilon < second_t < 1.0 - epsilon
    )


def polyline_crossing_count(
    first: Sequence[Point],
    second: Sequence[Point],
    epsilon: float,
) -> int:
    count = 0
    for first_start, first_end in zip(first, first[1:]):
        for second_start, second_end in zip(second, second[1:]):
            if _proper_segment_intersection(
                first_start,
                first_end,
                second_start,
                second_end,
                epsilon,
            ):
                count += 1
    return count


def pairwise_curve_crossing_count(
    curves: Sequence[Sequence[Point]],
    epsilon: float,
) -> int:
    count = 0
    for first_index, first in enumerate(curves):
        for second in curves[first_index + 1 :]:
            count += polyline_crossing_count(first, second, epsilon)
    return count


def periodic_curve_crossing_count(
    curves: Sequence[Sequence[Point]],
    shifts: Sequence[float],
    epsilon: float,
) -> int:
    count = 0
    for shift in shifts:
        shifted = [
            [(point[0] + shift, point[1]) for point in curve]
            for curve in curves
        ]
        for first in curves:
            for second in shifted:
                count += polyline_crossing_count(first, second, epsilon)
    return count


def ellipse_wrap_stats(
    points: Sequence[Point],
    flower: Mapping[str, object],
) -> dict[str, float]:
    center = _point(flower["center"])  # type: ignore[arg-type]
    rx = float(flower["rx"])
    ry = float(flower["ry"])
    angles: list[float] = []
    rho_values: list[float] = []
    for point in points:
        nx = (point[0] - center[0]) / rx
        ny = (point[1] - center[1]) / ry
        rho_values.append(math.hypot(nx, ny))
        angles.append(math.atan2(ny, nx))
    unwrapped = [angles[0]]
    for angle in angles[1:]:
        previous = unwrapped[-1]
        while angle - previous > math.pi:
            angle -= 2.0 * math.pi
        while angle - previous < -math.pi:
            angle += 2.0 * math.pi
        unwrapped.append(angle)
    mean = sum(rho_values) / len(rho_values)
    variance = sum((value - mean) ** 2 for value in rho_values) / len(rho_values)
    return {
        "wrap_span_deg": math.degrees(max(unwrapped) - min(unwrapped)),
        "minimum_rho": min(rho_values),
        "mean_rho": mean,
        "rho_cv": math.sqrt(variance) / mean if mean > 1e-12 else 0.0,
    }


def geometry_digest_from_stage3b(root: Path, cases: Iterable[tuple[str, int]]) -> str:
    rows: list[dict[str, object]] = []
    for prototype_id, seed in cases:
        plan = read_json(
            root
            / prototype_id
            / f"seed_{seed}"
            / "global_l1_flow_plan.json"
        )
        rows.append(
            {
                "prototype_id": prototype_id,
                "seed": seed,
                "lanes": [
                    {
                        "slot_id": lane["slot_id"],
                        "role": lane["role"],
                        "root_s": lane["root_s"],
                        "segments": lane["segments"],
                    }
                    for lane in plan["lanes"]
                ],
            }
        )
    return canonical_digest(rows)


def selection_digest_from_stage5(root: Path, cases: Iterable[tuple[str, int]]) -> str:
    rows: list[dict[str, object]] = []
    for prototype_id, seed in cases:
        selection = read_json(
            root
            / prototype_id
            / f"seed_{seed}"
            / "global_unit_selection.json"
        )
        rows.append(
            {
                "prototype_id": prototype_id,
                "seed": seed,
                "feasible": selection["feasible"],
                "selection_digest": selection["selection_digest"],
                "selected_candidate_ids": selection["selected_candidate_ids"],
            }
        )
    return canonical_digest(rows)

