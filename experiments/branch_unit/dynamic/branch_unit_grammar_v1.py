#!/usr/bin/env python3
"""Stage-4 complete BranchUnit grammar and deterministic candidate generator.

The approved stage-3B L1 geometry is immutable.  This module enumerates the
declared grammar/role/parameter strata exactly once, materializes L2/L3 cubic
Bezier descendants, and preserves every valid or invalid candidate.  It never
repairs, retries, resamples, deletes, or globally selects candidates.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any, Mapping, Sequence


SCHEMA = "dynamic_branch_stage4_unit_candidate_inventory_v1"
CANDIDATE_SCHEMA = "dynamic_branch_unit_candidate_v1"
CONTRACT_SCHEMA = "dynamic_branch_stage4_unit_grammar_contract_v1"
Point = tuple[float, float]


class UnitGrammarError(RuntimeError):
    """The stage-4 grammar input or complete candidate pool is invalid."""


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _finite(value: object, path: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise UnitGrammarError(f"{path} must be finite")
    return number


def _point(value: object, path: str = "point") -> Point:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
    ):
        raise UnitGrammarError(f"{path} must be a two-number point")
    return _finite(value[0], f"{path}[0]"), _finite(value[1], f"{path}[1]")


def _round(value: float) -> float:
    return round(float(value), 9)


def _round_point(point: Point) -> list[float]:
    return [_round(point[0]), _round(point[1])]


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scalar: float) -> Point:
    return a[0] * scalar, a[1] * scalar


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _length(vector: Point) -> float:
    return math.hypot(vector[0], vector[1])


def _distance(a: Point, b: Point) -> float:
    return _length(_sub(a, b))


def _unit(vector: Point, path: str = "vector") -> Point:
    length = _length(vector)
    if length <= 1e-12:
        raise UnitGrammarError(f"{path} must be non-degenerate")
    return vector[0] / length, vector[1] / length


def _rotate(vector: Point, degrees: float) -> Point:
    angle = math.radians(degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return (
        vector[0] * cosine - vector[1] * sine,
        vector[0] * sine + vector[1] * cosine,
    )


def _lerp(a: Point, b: Point, fraction: float) -> Point:
    return (
        a[0] + (b[0] - a[0]) * fraction,
        a[1] + (b[1] - a[1]) * fraction,
    )


def _cubic(
    p0: Point,
    p1: Point,
    p2: Point,
    p3: Point,
) -> dict[str, list[float]]:
    return {
        "p0": _round_point(p0),
        "p1": _round_point(p1),
        "p2": _round_point(p2),
        "p3": _round_point(p3),
    }


def _circular_arc_cubics(
    root: Point,
    entry: Point,
    signed_turn_degrees: float,
    arc_length: float,
    segment_count: int = 2,
) -> list[dict[str, list[float]]]:
    """Approximate a constant-curvature arc with tangent-matched cubics."""

    total_radians = math.radians(signed_turn_degrees)
    radius = arc_length / abs(total_radians)
    turn_sign = 1.0 if total_radians > 0.0 else -1.0
    normal = (-entry[1], entry[0])
    center = _add(root, _mul(normal, turn_sign * radius))
    root_radius = _sub(root, center)
    segment_degrees = signed_turn_degrees / segment_count
    segment_radians = total_radians / segment_count
    handle_length = (
        4.0
        / 3.0
        * radius
        * math.tan(abs(segment_radians) / 4.0)
    )
    segments: list[dict[str, list[float]]] = []
    for index in range(segment_count):
        start_degrees = segment_degrees * index
        end_degrees = segment_degrees * (index + 1)
        p0 = _add(center, _rotate(root_radius, start_degrees))
        p3 = _add(center, _rotate(root_radius, end_degrees))
        start_tangent = _rotate(entry, start_degrees)
        end_tangent = _rotate(entry, end_degrees)
        segments.append(
            _cubic(
                p0,
                _add(p0, _mul(start_tangent, handle_length)),
                _sub(p3, _mul(end_tangent, handle_length)),
                p3,
            )
        )
    return segments


def _cubic_point(segment: Mapping[str, Sequence[float]], t: float) -> Point:
    p0 = _point(segment["p0"], "segment.p0")
    p1 = _point(segment["p1"], "segment.p1")
    p2 = _point(segment["p2"], "segment.p2")
    p3 = _point(segment["p3"], "segment.p3")
    u = 1.0 - t
    return (
        u**3 * p0[0]
        + 3.0 * u * u * t * p1[0]
        + 3.0 * u * t * t * p2[0]
        + t**3 * p3[0],
        u**3 * p0[1]
        + 3.0 * u * u * t * p1[1]
        + 3.0 * u * t * t * p2[1]
        + t**3 * p3[1],
    )


def _sample_segments(
    segments: Sequence[Mapping[str, Sequence[float]]],
    count: int = 36,
) -> list[Point]:
    points: list[Point] = []
    for segment_index, segment in enumerate(segments):
        start = 0 if segment_index == 0 else 1
        points.extend(
            _cubic_point(segment, index / count)
            for index in range(start, count + 1)
        )
    return points


def _polyline_length(points: Sequence[Point]) -> float:
    return sum(
        _distance(points[index - 1], points[index])
        for index in range(1, len(points))
    )


def _sample_polyline(
    points: Sequence[Point],
    fraction: float,
) -> tuple[Point, Point]:
    if len(points) < 2:
        raise UnitGrammarError("polyline needs at least two points")
    lengths = [
        _distance(points[index - 1], points[index])
        for index in range(1, len(points))
    ]
    total = sum(lengths)
    if total <= 1e-12:
        raise UnitGrammarError("polyline must be non-degenerate")
    target = max(0.0, min(1.0, fraction)) * total
    traversed = 0.0
    for index, segment_length in enumerate(lengths, start=1):
        if traversed + segment_length >= target or index == len(lengths):
            local = (target - traversed) / segment_length
            return (
                _lerp(points[index - 1], points[index], local),
                _unit(_sub(points[index], points[index - 1]), "polyline tangent"),
            )
        traversed += segment_length
    raise AssertionError("unreachable polyline sample")


def _angle_degrees(a: Point, b: Point) -> float:
    cosine = max(-1.0, min(1.0, _dot(_unit(a), _unit(b))))
    return math.degrees(math.acos(cosine))


def _halton(index: int, base: int, scramble: int) -> float:
    if index <= 0:
        raise UnitGrammarError("Halton index must be positive")
    result = 0.0
    factor = 1.0 / base
    value = index
    while value:
        digit = value % base
        digit = (digit + scramble) % base
        result += digit * factor
        value //= base
        factor /= base
    return result


def _seed_scramble(seed: int, lane_id: str, dimension: int, base: int) -> int:
    digest = hashlib.sha256(
        f"{seed}|{lane_id}|{dimension}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:4], "big") % base


def _quantile(statistic: Mapping[str, Any], quantile: float) -> float:
    samples = [float(value) for value in statistic["samples"]]
    if not samples:
        raise UnitGrammarError("empirical statistic has no samples")
    position = max(0.0, min(1.0, quantile)) * (len(samples) - 1)
    lower = int(math.floor(position))
    upper = min(len(samples) - 1, lower + 1)
    return samples[lower] + (samples[upper] - samples[lower]) * (
        position - lower
    )


def _stat(
    prior: Mapping[str, Any],
    role_condition: str,
    name: str,
) -> Mapping[str, Any]:
    role_stats = prior["statistics"]["role_conditioned"].get(role_condition)
    if not isinstance(role_stats, Mapping) or name not in role_stats:
        raise UnitGrammarError(
            f"fixed visual prior lacks {role_condition}.{name}"
        )
    statistic = role_stats[name]
    if not isinstance(statistic, Mapping):
        raise UnitGrammarError(
            f"fixed visual prior statistic is invalid: {role_condition}.{name}"
        )
    return statistic


def _candidate_strata(
    lane: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> list[tuple[str, str, bool]]:
    role = str(lane["role"])
    coverage = contract["candidate_coverage"]
    if role in {"primary_sweep", "balance"}:
        rows: list[tuple[str, str, bool]] = []
        for grammar_id in ("Y-C", "Y-2C"):
            for stratum in coverage["ordinary_grammar_strata"][grammar_id]:
                rows.append(
                    (
                        grammar_id,
                        str(stratum),
                        stratum in {"open_c", "open_asymmetric"},
                    )
                )
        return rows
    if role == "frontier":
        return [
            (
                "Frontier-Y-C",
                str(stratum),
                stratum == "outer_hook",
            )
            for stratum in coverage["frontier_strata"]
        ]
    if role == "flower_support":
        return [
            ("FlowerSupport-C", str(stratum), False)
            for stratum in coverage["flower_support_strata"]
        ]
    if role == "terminal_flower_support":
        return [
            ("TerminalSupport-C", str(stratum), False)
            for stratum in coverage["terminal_support_strata"]
        ]
    raise UnitGrammarError(f"unsupported stage-3B lane role: {role}")


def _role_condition(role: str, level: int) -> str:
    if level == 3:
        return "tertiary_lateral"
    if role == "frontier":
        return "secondary_frontier"
    if role == "flower_support":
        return "secondary_flower_wrap"
    return "secondary_lateral"


def _child_semantic_role(
    role: str,
    guide_channel: Mapping[str, Any] | None,
) -> str:
    if role == "flower_support":
        return "flower_support_echo"
    if guide_channel is not None:
        return "flower_wrap"
    if role == "terminal_flower_support":
        return "terminal_subordinate"
    if role == "frontier":
        return "frontier_extension"
    return "lateral_subordinate"


def _local_density_scale(
    lane: Mapping[str, Any],
    all_lanes: Sequence[Mapping[str, Any]],
) -> float:
    root_s = float(lane["root_s"])
    gaps = sorted(
        min(abs(root_s - float(other["root_s"])), 1.0 - abs(root_s - float(other["root_s"])))
        for other in all_lanes
        if other["slot_id"] != lane["slot_id"]
    )
    if not gaps:
        return 1.0
    nearest = gaps[0]
    return max(0.72, min(1.05, 0.72 + nearest / 0.22 * 0.33))


def _nearest_backbone_vector(
    analysis: Mapping[str, Any],
    point: Point,
) -> Point:
    backbone_points = [
        _point(row["point"], "backbone.point")
        for row in analysis["backbone"]["samples"]
    ]
    nearest = min(backbone_points, key=lambda value: _distance(point, value))
    vector = _sub(point, nearest)
    if _length(vector) <= 1e-8:
        tangent = _unit(
            _sub(backbone_points[-1], backbone_points[0]),
            "backbone endpoint tangent",
        )
        return -tangent[1], tangent[0]
    return _unit(vector, "outward vector")


def _child_signs(
    parent_points: Sequence[Point],
    mounts: Sequence[float],
    analysis: Mapping[str, Any],
    lane: Mapping[str, Any],
    asymmetry: float,
) -> list[int]:
    signs: list[int] = []
    for index, mount in enumerate(mounts):
        root, tangent = _sample_polyline(parent_points, mount)
        outward = _nearest_backbone_vector(analysis, root)
        flower_avoidance = (0.0, 0.0)
        for flower in analysis["flowers"]:
            center = _point(flower["center"], "flower.center")
            near_center = min(
                (
                    (center[0] - 1.0, center[1]),
                    center,
                    (center[0] + 1.0, center[1]),
                ),
                key=lambda value: _distance(root, value),
            )
            away = _sub(root, near_center)
            distance = max(0.04, _length(away))
            weight = (
                2.2
                if lane["role"] == "flower_support"
                and flower["flower_id"] == lane["flower_id"]
                else 0.8
            )
            flower_avoidance = _add(
                flower_avoidance,
                _mul(_unit(away, "flower avoidance"), weight / distance),
            )
        positive_direction = _rotate(tangent, 55.0)
        negative_direction = _rotate(tangent, -55.0)
        positive = _dot(positive_direction, outward) + 0.55 * _dot(
            positive_direction,
            flower_avoidance,
        ) + 0.08 * asymmetry
        negative = _dot(negative_direction, outward) + 0.55 * _dot(
            negative_direction,
            flower_avoidance,
        ) - 0.08 * asymmetry
        preferred = 1 if positive >= negative else -1
        if len(mounts) == 2 and index == 1:
            preferred *= -1
        signs.append(preferred)
    return signs


def _mounts(
    prior: Mapping[str, Any],
    role_condition: str,
    count: int,
    quantiles: Sequence[float],
    contract: Mapping[str, Any],
) -> list[float]:
    low, high = [
        float(value) for value in contract["geometry"]["mount_fraction_range"]
    ]
    statistic = _stat(prior, role_condition, "mount_fraction")
    if count == 1:
        return [max(low, min(high, _quantile(statistic, quantiles[0])))]
    center = _quantile(statistic, quantiles[0])
    minimum_gap = float(
        contract["geometry"]["minimum_sibling_mount_separation"]
    )
    expansion = minimum_gap + 0.04 * quantiles[1]
    lower = max(low, min(high - expansion, center - expansion * 0.5))
    upper = lower + expansion
    return [lower, upper]


def _contextual_mounts(
    parent_points: Sequence[Point],
    preferred_mounts: Sequence[float],
    lane: Mapping[str, Any],
    analysis: Mapping[str, Any],
    contract: Mapping[str, Any],
    phase: float,
) -> list[float]:
    """Solve prior fidelity and flower-clearance before geometry materialization."""

    low, high = [
        float(value) for value in contract["geometry"]["mount_fraction_range"]
    ]
    minimum_gap = float(
        contract["geometry"]["minimum_sibling_mount_separation"]
    )
    samples = [
        low + (high - low) * index / 48.0
        for index in range(49)
    ]

    def clearance(fraction: float) -> float:
        point, _ = _sample_polyline(parent_points, fraction)
        values: list[float] = []
        for flower in analysis["flowers"]:
            is_sw1_target = (
                lane["role"] == "flower_support"
                and flower["flower_id"] == lane["flower_id"]
            )
            values.append(
                _ellipse_value(
                    point,
                    flower,
                    protection=not is_sw1_target,
                )
            )
        return min(values, default=4.0)

    selected: list[float] = []
    for index, preferred in enumerate(preferred_mounts):
        eligible = [
            fraction
            for fraction in samples
            if all(abs(fraction - other) >= minimum_gap for other in selected)
        ]
        if not eligible:
            raise UnitGrammarError(
                f"{lane['slot_id']} has no legal sibling mount interval"
            )
        chosen = max(
            eligible,
            key=lambda fraction: (
                min(4.0, clearance(fraction))
                - 1.45 * abs(fraction - preferred)
                + 0.035
                * math.cos(
                    2.0
                    * math.pi
                    * (fraction + phase + index * 0.31)
                ),
                -abs(fraction - preferred),
                -fraction,
            ),
        )
        selected.append(chosen)
    return sorted(selected)


def _child_length_ratio(
    prior: Mapping[str, Any],
    role: str,
    level: int,
    quantile: float,
    parent_length: float,
    density_scale: float,
    contract: Mapping[str, Any],
) -> float:
    role_condition = _role_condition(role, level)
    empirical = _quantile(
        _stat(prior, role_condition, "child_to_parent_actual_ratio"),
        quantile,
    )
    if level == 3:
        bounds = contract["geometry"]["tertiary_parent_length_ratio_range"]
    elif role == "frontier":
        bounds = contract["geometry"]["frontier_child_parent_length_ratio_range"]
    elif role == "flower_support":
        bounds = contract["geometry"][
            "flower_support_child_parent_length_ratio_range"
        ]
    elif role == "terminal_flower_support":
        bounds = contract["geometry"][
            "terminal_support_child_parent_length_ratio_range"
        ]
    else:
        bounds = contract["geometry"]["ordinary_child_parent_length_ratio_range"]
    long_parent_scale = max(0.68, min(1.08, 1.08 - 0.42 * max(0.0, parent_length - 0.24)))
    value = empirical * density_scale * long_parent_scale
    return max(float(bounds[0]), min(float(bounds[1]), value))


def _compile_guide_following_child_curve(
    *,
    curve_id: str,
    branch_unit_id: str,
    parent_curve: Mapping[str, Any],
    mount_fraction: float,
    semantic_role: str,
    guide_channel: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    parent_points = [
        _point(value, f"{parent_curve['curve_id']}.centerline")
        for value in parent_curve["centerline"]
    ]
    root, parent_tangent = _sample_polyline(
        parent_points,
        mount_fraction,
    )
    guide_points = [
        _point(value, f"{curve_id}.guide_centerline")
        for value in guide_channel["guide_centerline"]
    ]
    guide_tangents = [
        _unit(
            _point(value, f"{curve_id}.guide_tangent"),
            "guided wrap tangent",
        )
        for value in guide_channel["guide_tangents"]
    ]
    if len(guide_points) < 3 or len(guide_points) != len(
        guide_tangents
    ):
        raise UnitGrammarError(
            f"{curve_id} guide centerline/tangent mismatch"
        )
    guide_root_translation = _sub(root, guide_points[0])
    if _length(guide_root_translation) > float(
        contract["guided_support_wrap"][
            "maximum_guide_root_translation"
        ]
    ):
        raise UnitGrammarError(
            f"{curve_id} guide root does not match parent mount"
        )
    guide_points = [
        _add(point, guide_root_translation)
        for point in guide_points
    ]
    guide_points[0] = root
    guide_tangents[0] = parent_tangent
    handle_fraction = float(
        contract["guided_support_wrap"]["guide_handle_fraction"]
    )
    segments: list[dict[str, list[float]]] = []
    for start, end, start_tangent, end_tangent in zip(
        guide_points,
        guide_points[1:],
        guide_tangents,
        guide_tangents[1:],
    ):
        chord = _distance(start, end)
        segments.append(
            _cubic(
                start,
                _add(
                    start,
                    _mul(start_tangent, chord * handle_fraction),
                ),
                _sub(
                    end,
                    _mul(end_tangent, chord * handle_fraction),
                ),
                end,
            )
        )
    centerline = _sample_segments(
        segments,
        int(
            contract["guided_support_wrap"][
                "samples_per_guide_segment"
            ]
        ),
    )
    actual_length = _polyline_length(centerline)
    parent_length = _polyline_length(parent_points)
    entry_error = _angle_degrees(
        parent_tangent,
        _unit(
            _sub(
                _point(segments[0]["p1"]),
                _point(segments[0]["p0"]),
            )
        ),
    )
    return {
        "curve_id": curve_id,
        "branch_unit_id": branch_unit_id,
        "level": "L2",
        "hierarchy_level": 2,
        "parent_curve_id": parent_curve["curve_id"],
        "mount_fraction": _round(mount_fraction),
        "semantic_role": semantic_role,
        "shape_signature": "guided_flower_wrap",
        "turn_sign": int(guide_channel["wrap_direction"]),
        "entry_opening_degrees": _round(entry_error),
        "intended_parent_length_ratio": _round(
            actual_length / parent_length
        ),
        "actual_length": _round(actual_length),
        "cubic_segments": segments,
        "centerline": [
            _round_point(point) for point in centerline
        ],
        "guide_channel": dict(guide_channel),
        "sampling_trace": {
            "source": "global_l1_role_guide_channel",
            "guide_digest": canonical_digest(guide_channel),
            "guide_root_translation": _round_point(
                guide_root_translation
            ),
            "generated_once": True,
            "validation_guided_retry_count": 0,
            "validation_guided_resample_count": 0,
        },
    }


def _compile_child_curve(
    *,
    curve_id: str,
    branch_unit_id: str,
    parent_curve: Mapping[str, Any],
    mount_fraction: float,
    sign: int,
    role: str,
    semantic_role: str,
    level: int,
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    quantiles: Sequence[float],
    density_scale: float,
    shape_signature: str,
    target_flower: Mapping[str, Any] | None,
    guide_channel: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    parent_points = [
        _point(value, f"{parent_curve['curve_id']}.centerline")
        for value in parent_curve["centerline"]
    ]
    root, parent_tangent = _sample_polyline(parent_points, mount_fraction)
    if guide_channel is not None:
        return _compile_guide_following_child_curve(
            curve_id=curve_id,
            branch_unit_id=branch_unit_id,
            parent_curve=parent_curve,
            mount_fraction=mount_fraction,
            semantic_role=semantic_role,
            guide_channel=guide_channel,
            contract=contract,
        )
    parent_length = _polyline_length(parent_points)
    role_condition = _role_condition(role, level)
    empirical_opening = _quantile(
        _stat(prior, role_condition, "entry_opening_degrees"),
        quantiles[0],
    )
    if shape_signature == "S":
        opening_key = "s_entry_opening_degrees_range"
    elif role == "flower_support":
        opening_key = "flower_wrap_c_entry_opening_degrees_range"
    else:
        opening_key = "c_entry_opening_degrees_range"
    opening_low, opening_high = [
        float(value) for value in contract["geometry"][opening_key]
    ]
    opening = opening_low + (opening_high - opening_low) * quantiles[0]
    entry = _unit(_rotate(parent_tangent, sign * opening), "child entry")
    ratio = _child_length_ratio(
        prior,
        role,
        level,
        quantiles[1],
        parent_length,
        density_scale,
        contract,
    )
    intended_length = parent_length * ratio
    release = _quantile(
        _stat(prior, role_condition, "exit_release_degrees"),
        quantiles[2],
    )
    handle_ratio = _quantile(
        _stat(prior, role_condition, "handle_ratio"),
        quantiles[3],
    )
    curl_energy = 0.92 + 0.18 * quantiles[4]
    transverse = (-entry[1], entry[0])

    if shape_signature == "S":
        s_turn_low, s_turn_high = [
            float(value)
            for value in contract["geometry"]["s_internal_turn_degrees_range"]
        ]
        s_internal_turn = s_turn_low + (
            s_turn_high - s_turn_low
        ) * quantiles[2]
        segments = _circular_arc_cubics(
            root,
            entry,
            -sign * s_internal_turn,
            intended_length,
        )
    else:
        c_turn_low, c_turn_high = [
            float(value)
            for value in contract["geometry"]["c_internal_turn_degrees_range"]
        ]
        c_internal_turn = c_turn_low + (
            c_turn_high - c_turn_low
        ) * quantiles[2]
        c_handle_low, c_handle_high = [
            float(value)
            for value in contract["geometry"]["c_handle_ratio_range"]
        ]
        handle_ratio = c_handle_low + (
            c_handle_high - c_handle_low
        ) * quantiles[3]
        if role == "flower_support":
            if target_flower is None:
                raise UnitGrammarError(
                    f"{curve_id} flower wrap lacks its target flower"
                )
            center = _point(target_flower["center"], "target_flower.center")
            near_center = min(
                (
                    (center[0] - 1.0, center[1]),
                    center,
                    (center[0] + 1.0, center[1]),
                ),
                key=lambda value: _distance(root, value),
            )
            rx = float(target_flower["rx"])
            ry = float(target_flower["ry"])
            delta = _sub(root, near_center)
            outward = _unit(
                (delta[0] / (rx * rx), delta[1] / (ry * ry)),
                "flower ellipse outward gradient",
            )
            tangent_a = (-outward[1], outward[0])
            tangent_b = (outward[1], -outward[0])
            wrap_tangent = (
                tangent_a
                if _dot(tangent_a, entry) >= _dot(tangent_b, entry)
                else tangent_b
            )
            end_direction = _unit(
                _add(
                    _add(_mul(entry, 0.78), _mul(wrap_tangent, 0.22)),
                    _mul(outward, 0.10),
                ),
                "flower wrap exit",
            )
            tip_direction = _unit(
                _add(_mul(entry, 0.58), _mul(end_direction, 0.42)),
                "flower wrap tip direction",
            )
            tip = _add(
                root,
                _add(
                    _mul(tip_direction, intended_length * 0.88),
                    _mul(outward, intended_length * 0.20),
                ),
            )
        else:
            end_direction = _unit(
                _rotate(entry, -sign * c_internal_turn),
                "child C exit",
            )
            tip_direction = _unit(
                _add(_mul(entry, 0.48), _mul(end_direction, 0.52)),
                "child tip direction",
            )
            tip = _add(
                root,
                _add(
                    _mul(tip_direction, intended_length * 0.92),
                    _mul(
                        transverse,
                        sign * intended_length * 0.05 * curl_energy,
                    ),
                ),
            )
        segments = [
            _cubic(
                root,
                _add(root, _mul(entry, intended_length * handle_ratio)),
                _sub(tip, _mul(end_direction, intended_length * handle_ratio)),
                tip,
            )
        ]

    centerline = _sample_segments(segments, 32)
    actual_length = _polyline_length(centerline)
    return {
        "curve_id": curve_id,
        "branch_unit_id": branch_unit_id,
        "level": f"L{level}",
        "hierarchy_level": level,
        "parent_curve_id": parent_curve["curve_id"],
        "mount_fraction": _round(mount_fraction),
        "semantic_role": semantic_role,
        "shape_signature": shape_signature,
        "turn_sign": sign,
        "entry_opening_degrees": _round(opening),
        "intended_parent_length_ratio": _round(ratio),
        "actual_length": _round(actual_length),
        "cubic_segments": segments,
        "centerline": [_round_point(point) for point in centerline],
        "sampling_trace": {
            "role_condition": role_condition,
            "quantiles": [_round(value) for value in quantiles],
            "empirical_entry_opening_degrees": _round(
                empirical_opening
            ),
            "empirical_exit_release_degrees": _round(release),
            "density_scale": _round(density_scale),
            "generated_once": True,
        },
    }


def _l1_curve(lane: Mapping[str, Any], branch_unit_id: str) -> dict[str, Any]:
    segments = [dict(segment) for segment in lane["segments"]]
    centerline = _sample_segments(segments, 36)
    return {
        "curve_id": f"{branch_unit_id}.L1",
        "branch_unit_id": branch_unit_id,
        "level": "L1",
        "hierarchy_level": 1,
        "parent_curve_id": None,
        "mount_fraction": None,
        "semantic_role": str(lane["role"]),
        "shape_signature": str(lane["curvature_signature"]),
        "turn_sign": 0,
        "entry_opening_degrees": None,
        "intended_parent_length_ratio": None,
        "actual_length": _round(_polyline_length(centerline)),
        "cubic_segments": segments,
        "centerline": [_round_point(point) for point in centerline],
        "sampling_trace": {
            "source": "approved_stage3b_immutable_l1",
            "source_candidate_id": lane["candidate_id"],
        },
    }


def _candidate_quantiles(
    seed: int,
    lane_id: str,
    candidate_index: int,
) -> list[float]:
    bases = (2, 3, 5, 7, 11, 13, 17, 19)
    return [
        _halton(
            candidate_index + 1,
            base,
            _seed_scramble(seed, lane_id, dimension, base),
        )
        for dimension, base in enumerate(bases)
    ]


def _shape_from_stratum(stratum: str, index: int) -> str:
    if "_s" in stratum or stratum in {"nested_s", "subordinate_s"}:
        return "S"
    if "hook" in stratum:
        return "S"
    if stratum == "open_asymmetric" and index == 1:
        return "S"
    return "C"


def _length_quantile_for_stratum(stratum: str, value: float) -> float:
    """Map a low-discrepancy value into the declared empirical length band."""

    if "compact" in stratum:
        low, high = 0.34, 0.54
    elif stratum in {"open_c", "open_asymmetric", "long_c", "long_s"}:
        low, high = 0.72, 0.97
    elif stratum in {
        "outer_hook",
        "nested_s",
        "lower_wrap_s",
        "subordinate_s",
    }:
        low, high = 0.64, 0.88
    else:
        low, high = 0.50, 0.78
    return low + (high - low) * value


def _occupancy_tubes(
    curves: Sequence[Mapping[str, Any]],
    radius: float,
) -> list[dict[str, Any]]:
    tubes: list[dict[str, Any]] = []
    for curve in curves:
        points = [_point(row) for row in curve["centerline"]]
        tubes.append(
            {
                "curve_id": curve["curve_id"],
                "radius": _round(radius),
                "bounds": [
                    _round(min(point[0] for point in points) - radius),
                    _round(min(point[1] for point in points) - radius),
                    _round(max(point[0] for point in points) + radius),
                    _round(max(point[1] for point in points) + radius),
                ],
            }
        )
    return tubes


def _orientation(a: Point, b: Point, c: Point) -> float:
    return _cross(_sub(b, a), _sub(c, a))


def _segments_intersect(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    tolerance = 1e-10
    o1 = _orientation(a0, a1, b0)
    o2 = _orientation(a0, a1, b1)
    o3 = _orientation(b0, b1, a0)
    o4 = _orientation(b0, b1, a1)
    return o1 * o2 < -tolerance and o3 * o4 < -tolerance


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    vector = _sub(end, start)
    denominator = _dot(vector, vector)
    if denominator <= 1e-18:
        return _distance(point, start)
    fraction = max(
        0.0,
        min(1.0, _dot(_sub(point, start), vector) / denominator),
    )
    return _distance(point, _add(start, _mul(vector, fraction)))


def _polyline_distance(
    a: Sequence[Point],
    b: Sequence[Point],
) -> float:
    minimum = float("inf")
    for index in range(1, len(a)):
        for other_index in range(1, len(b)):
            a0, a1 = a[index - 1], a[index]
            b0, b1 = b[other_index - 1], b[other_index]
            if _segments_intersect(a0, a1, b0, b1):
                return 0.0
            minimum = min(
                minimum,
                _point_segment_distance(a0, b0, b1),
                _point_segment_distance(a1, b0, b1),
                _point_segment_distance(b0, a0, a1),
                _point_segment_distance(b1, a0, a1),
            )
    return minimum


def _curve_crosses(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    allowed_junction: Point | None,
) -> bool:
    a_points = [_point(value) for value in a["centerline"]]
    b_points = [_point(value) for value in b["centerline"]]
    for index in range(1, len(a_points)):
        for other_index in range(1, len(b_points)):
            a0, a1 = a_points[index - 1], a_points[index]
            b0, b1 = b_points[other_index - 1], b_points[other_index]
            if not _segments_intersect(a0, a1, b0, b1):
                continue
            if allowed_junction is not None and min(
                _distance(a0, allowed_junction),
                _distance(a1, allowed_junction),
                _distance(b0, allowed_junction),
                _distance(b1, allowed_junction),
            ) <= 0.010:
                continue
            return True
    return False


def _ellipse_value(
    point: Point,
    flower: Mapping[str, Any],
    *,
    protection: bool = True,
) -> float:
    center = _point(flower["center"], "flower.center")
    rx = float(flower["protection_rx"] if protection else flower["rx"])
    ry = float(flower["protection_ry"] if protection else flower["ry"])
    near_x = min(
        (point[0] - 1.0, point[0], point[0] + 1.0),
        key=lambda value: abs(value - center[0]),
    )
    return ((near_x - center[0]) / rx) ** 2 + ((point[1] - center[1]) / ry) ** 2


def _diagnose_candidate(
    candidate: Mapping[str, Any],
    analysis: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    curves = candidate["curves"]
    curve_by_id = {curve["curve_id"]: curve for curve in curves}
    if len(curve_by_id) != len(curves):
        issues.append({"code": "duplicate_curve_id"})
    l1_curves = [curve for curve in curves if curve["level"] == "L1"]
    if len(l1_curves) != 1:
        issues.append({"code": "invalid_l1_count", "actual": len(l1_curves)})

    bounds_by_role = {
        "frontier": contract["geometry"]["frontier_child_parent_length_ratio_range"],
        "flower_support": contract["geometry"][
            "flower_support_child_parent_length_ratio_range"
        ],
        "terminal_flower_support": contract["geometry"][
            "terminal_support_child_parent_length_ratio_range"
        ],
        "ordinary": contract["geometry"]["ordinary_child_parent_length_ratio_range"],
        "tertiary": contract["geometry"]["tertiary_parent_length_ratio_range"],
    }
    openings: list[float] = []
    root_errors: list[float] = []
    departure_distances: list[float] = []
    for curve in curves:
        for segment in curve["cubic_segments"]:
            for key in ("p0", "p1", "p2", "p3"):
                _point(segment[key], f"{curve['curve_id']}.{key}")
        if curve["level"] == "L1":
            continue
        parent_id = curve["parent_curve_id"]
        parent = curve_by_id.get(parent_id)
        if parent is None or parent["hierarchy_level"] + 1 != curve["hierarchy_level"]:
            issues.append(
                {"code": "invalid_parent_graph", "curve_id": curve["curve_id"]}
            )
            continue
        parent_points = [_point(value) for value in parent["centerline"]]
        expected_root, parent_tangent = _sample_polyline(
            parent_points,
            float(curve["mount_fraction"]),
        )
        root = _point(curve["cubic_segments"][0]["p0"])
        root_error = _distance(root, expected_root)
        root_errors.append(root_error)
        if root_error > 2e-6:
            issues.append(
                {
                    "code": "attachment_error",
                    "curve_id": curve["curve_id"],
                    "value": _round(root_error),
                }
            )
        entry = _unit(
            _sub(
                _point(curve["cubic_segments"][0]["p1"]),
                root,
            ),
            "child entry derivative",
        )
        opening = _angle_degrees(parent_tangent, entry)
        openings.append(opening)
        opening_bounds = (
            contract["guided_support_wrap"][
                "root_tangent_error_deg_range"
            ]
            if candidate["grammar_id"] == "TerminalSupport-Wrap"
            else contract["geometry"]["entry_opening_degrees_range"]
        )
        if not float(opening_bounds[0]) - 0.5 <= opening <= float(opening_bounds[1]) + 0.5:
            issues.append(
                {
                    "code": "entry_opening_out_of_range",
                    "curve_id": curve["curve_id"],
                    "value": _round(opening),
                }
            )
        child_points = [_point(value) for value in curve["centerline"]]
        probe_index = max(2, int(len(child_points) * 0.30))
        departure = min(
            _point_segment_distance(
                child_points[probe_index],
                parent_points[index - 1],
                parent_points[index],
            )
            for index in range(1, len(parent_points))
        )
        departure_distances.append(departure)
        minimum_departure = min(
            float(contract["geometry"]["minimum_immediate_departure_distance"]),
            float(curve["actual_length"]) * 0.14,
        )
        if departure < minimum_departure:
            issues.append(
                {
                    "code": "child_does_not_depart_immediately",
                    "curve_id": curve["curve_id"],
                    "value": _round(departure),
                }
            )
        parent_length = float(parent["actual_length"])
        ratio = float(curve["actual_length"]) / parent_length
        if (
            candidate["grammar_id"] == "TerminalSupport-Wrap"
            and curve["level"] == "L2"
        ):
            bounds = contract["guided_support_wrap"][
                "child_parent_length_ratio_range"
            ]
        elif curve["level"] == "L3":
            bounds = bounds_by_role["tertiary"]
        else:
            bounds = bounds_by_role.get(
                str(candidate["role"]),
                bounds_by_role["ordinary"],
            )
        if not float(bounds[0]) * 0.84 <= ratio <= float(bounds[1]) * 1.18:
            issues.append(
                {
                    "code": "hierarchy_length_ratio_out_of_range",
                    "curve_id": curve["curve_id"],
                    "value": _round(ratio),
                }
            )

    l2_mounts = sorted(
        float(curve["mount_fraction"])
        for curve in curves
        if curve["level"] == "L2"
    )
    minimum_mount_gap = min(
        (
            l2_mounts[index] - l2_mounts[index - 1]
            for index in range(1, len(l2_mounts))
        ),
        default=1.0,
    )
    if minimum_mount_gap < float(
        contract["geometry"]["minimum_sibling_mount_separation"]
    ):
        issues.append(
            {
                "code": "sibling_mounts_too_close",
                "value": _round(minimum_mount_gap),
            }
        )

    crossing_count = 0
    for index, curve in enumerate(curves):
        points = [_point(value) for value in curve["centerline"]]
        for first in range(1, len(points)):
            for second in range(first + 2, len(points)):
                if second == first + 1:
                    continue
                if _segments_intersect(
                    points[first - 1],
                    points[first],
                    points[second - 1],
                    points[second],
                ):
                    crossing_count += 1
                    break
        for other in curves[index + 1 :]:
            allowed: Point | None = None
            if other["parent_curve_id"] == curve["curve_id"]:
                allowed = _point(other["cubic_segments"][0]["p0"])
            elif curve["parent_curve_id"] == other["curve_id"]:
                allowed = _point(curve["cubic_segments"][0]["p0"])
            if _curve_crosses(curve, other, allowed):
                crossing_count += 1
    if crossing_count:
        issues.append({"code": "unit_self_crossing", "count": crossing_count})

    backbone = [
        _point(row["point"], "backbone.point")
        for row in analysis["backbone"]["samples"]
    ]
    backbone_crossing_count = 0
    for curve in curves:
        if curve["level"] == "L1":
            continue
        points = [_point(value) for value in curve["centerline"]]
        if _polyline_distance(points, backbone) <= 0.001:
            backbone_crossing_count += 1
    if backbone_crossing_count:
        issues.append(
            {
                "code": "non_root_backbone_crossing",
                "count": backbone_crossing_count,
            }
        )

    reserve_entry_count = 0
    target_flower_id = candidate["flower_relation"]["flower_id"]
    for curve in curves:
        if curve["level"] == "L1":
            continue
        for point in [_point(value) for value in curve["centerline"]][1:]:
            enters = False
            for flower in analysis["flowers"]:
                is_wrap_target = (
                    curve["semantic_role"]
                    in {"flower_wrap", "flower_support_echo"}
                    and flower["flower_id"] == target_flower_id
                )
                if _ellipse_value(
                    point,
                    flower,
                    protection=not is_wrap_target,
                ) < 1.0:
                    enters = True
                    break
            if enters:
                reserve_entry_count += 1
                break
    if reserve_entry_count:
        issues.append(
            {
                "code": "descendant_enters_flower_reserve",
                "count": reserve_entry_count,
            }
        )

    support_contact_error = 0.0
    if candidate["role"] in {"flower_support", "terminal_flower_support"}:
        target_id = candidate["flower_relation"]["flower_id"]
        flower = next(
            (row for row in analysis["flowers"] if row["flower_id"] == target_id),
            None,
        )
        if flower is None:
            issues.append({"code": "support_flower_missing"})
        else:
            endpoint = _point(l1_curves[0]["cubic_segments"][-1]["p3"])
            center = _point(flower["center"])
            rx = float(flower["rx"])
            ry = float(flower["ry"])
            near_x = min(
                (endpoint[0] - 1.0, endpoint[0], endpoint[0] + 1.0),
                key=lambda value: abs(value - center[0]),
            )
            support_contact_error = abs(
                ((near_x - center[0]) / rx) ** 2
                + ((endpoint[1] - center[1]) / ry) ** 2
                - 1.0
            )
            if support_contact_error > 0.035:
                issues.append(
                    {
                        "code": "support_terminal_contact_not_preserved",
                        "value": _round(support_contact_error),
                    }
                )

    periodic_crossing_count = 0
    for curve in curves:
        for other in curves:
            shifted = dict(other)
            shifted["centerline"] = [
                [_round(float(point[0]) + 1.0), _round(float(point[1]))]
                for point in other["centerline"]
            ]
            if _curve_crosses(curve, shifted, None):
                periodic_crossing_count += 1
    if periodic_crossing_count:
        issues.append(
            {
                "code": "periodic_self_crossing",
                "count": periodic_crossing_count,
            }
        )

    return {
        "valid": not issues,
        "issue_count": len(issues),
        "issues": issues,
        "metrics": {
            "maximum_attachment_error": _round(max(root_errors, default=0.0)),
            "minimum_entry_opening_degrees": _round(min(openings, default=0.0)),
            "minimum_immediate_departure": _round(
                min(departure_distances, default=0.0)
            ),
            "minimum_sibling_mount_separation": _round(minimum_mount_gap),
            "unit_self_crossing_count": crossing_count,
            "backbone_crossing_count": backbone_crossing_count,
            "flower_reserve_entry_count": reserve_entry_count,
            "support_contact_error": _round(support_contact_error),
            "periodic_self_crossing_count": periodic_crossing_count,
        },
    }


def _build_candidate(
    *,
    plan: Mapping[str, Any],
    lane: Mapping[str, Any],
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    grammar_id: str,
    stratum: str,
    include_l3: bool,
    candidate_index: int,
) -> dict[str, Any]:
    seed = int(plan["seed"])
    lane_id = str(lane["slot_id"])
    quantiles = _candidate_quantiles(seed, lane_id, candidate_index)
    branch_unit_id = f"{plan['plan_id']}__{lane_id}"
    candidate_id = f"{branch_unit_id}__{grammar_id}__{stratum}"
    l1 = _l1_curve(lane, branch_unit_id)
    curves: list[dict[str, Any]] = [l1]
    grammar = contract["grammar"][grammar_id]
    l2_count = int(grammar["l2_count"])
    role = str(lane["role"])
    role_condition = _role_condition(role, 2)
    l1_points = [_point(value) for value in l1["centerline"]]
    guide_channel = (
        lane.get("flower_wrap_channel")
        if grammar_id == "TerminalSupport-Wrap"
        else None
    )
    if guide_channel is not None:
        mounts = [float(guide_channel["mount_fraction"])]
        signs = [int(guide_channel["wrap_direction"])]
    else:
        preferred_mounts = _mounts(
            prior,
            role_condition,
            l2_count,
            quantiles,
            contract,
        )
        mounts = _contextual_mounts(
            l1_points,
            preferred_mounts,
            lane,
            analysis,
            contract,
            quantiles[7],
        )
        signs = _child_signs(
            l1_points,
            mounts,
            analysis,
            lane,
            float(plan["global_latents"]["asymmetry"]),
        )
    target_flower = next(
        (
            flower
            for flower in analysis["flowers"]
            if flower["flower_id"] == lane["flower_id"]
        ),
        None,
    )
    density_scale = _local_density_scale(lane, plan["lanes"])
    for child_index, (mount, sign) in enumerate(zip(mounts, signs), start=1):
        child_quantiles = [
            quantiles[(child_index + offset) % len(quantiles)]
            for offset in range(5)
        ]
        child_quantiles[1] = _length_quantile_for_stratum(
            stratum,
            child_quantiles[1],
        )
        shape = _shape_from_stratum(stratum, child_index - 1)
        child = _compile_child_curve(
            curve_id=f"{branch_unit_id}.L2.{child_index}",
            branch_unit_id=branch_unit_id,
            parent_curve=l1,
            mount_fraction=mount,
            sign=sign,
            role=role,
            semantic_role=_child_semantic_role(role, guide_channel),
            level=2,
            prior=prior,
            contract=contract,
            quantiles=child_quantiles,
            density_scale=density_scale,
            shape_signature=shape,
            target_flower=target_flower,
            guide_channel=guide_channel,
        )
        curves.append(child)

    if include_l3:
        l2_parent = curves[-1]
        tertiary_quantiles = [
            quantiles[(5 + offset) % len(quantiles)] for offset in range(5)
        ]
        tertiary_mount = _mounts(
            prior,
            "tertiary_lateral",
            1,
            tertiary_quantiles,
            contract,
        )[0]
        tertiary = _compile_child_curve(
            curve_id=f"{branch_unit_id}.L3.1",
            branch_unit_id=branch_unit_id,
            parent_curve=l2_parent,
            mount_fraction=tertiary_mount,
            sign=-int(l2_parent["turn_sign"]),
            role=role,
            semantic_role="tertiary_echo",
            level=3,
            prior=prior,
            contract=contract,
            quantiles=tertiary_quantiles,
            density_scale=density_scale,
            shape_signature="C",
            target_flower=None,
        )
        curves.append(tertiary)

    flower_relation = {
        "flower_id": lane["flower_id"],
        "policy": (
            "sw1_trough_support_with_local_echo"
            if role == "flower_support"
            else "sw3_remote_support_with_guided_flower_wrap"
            if guide_channel is not None
            else "sw3_remote_below_flower_underside_support"
            if role == "terminal_flower_support"
            else "ordinary_descendants_exclude_all_flower_reserves"
        ),
        "l1_contact_point": lane["target"] if lane["flower_id"] else None,
    }
    candidate: dict[str, Any] = {
        "schema": CANDIDATE_SCHEMA,
        "candidate_id": candidate_id,
        "branch_unit_id": branch_unit_id,
        "source_plan_id": plan["plan_id"],
        "source_plan_digest": plan["plan_digest"],
        "source_lane_id": lane_id,
        "source_lane_candidate_id": lane["candidate_id"],
        "prototype_id": plan["prototype_id"],
        "seed": seed,
        "role": role,
        "grammar_id": grammar_id,
        "parameter_stratum": stratum,
        "guide_consumption": (
            {
                "guide_digest": lane["guide_digest"],
                "service_flower_id": lane["service_flower_id"],
                "target_relation": lane["target_relation"],
                "support_channel_consumed": True,
                "flower_wrap_channel_consumed": True,
                "loop_growth_region_consumed": True,
                "path_construction": guide_channel[
                    "path_construction"
                ],
            }
            if guide_channel is not None
            else None
        ),
        "hierarchy": {
            "l1_count": 1,
            "l2_count": l2_count,
            "l3_count": 1 if include_l3 else 0,
            "maximum_level": 3 if include_l3 else 2,
        },
        "curves": curves,
        "parent_graph": [
            {
                "curve_id": curve["curve_id"],
                "parent_curve_id": curve["parent_curve_id"],
                "mount_fraction": curve["mount_fraction"],
            }
            for curve in curves
        ],
        "occupancy_tubes": _occupancy_tubes(
            curves,
            float(contract["geometry"]["occupancy_radius"]),
        ),
        "flower_relation": flower_relation,
        "visual_features": {
            "l1_signature": lane["curvature_signature"],
            "l2_sign_sequence": [
                curve["turn_sign"] for curve in curves if curve["level"] == "L2"
            ],
            "l2_shape_sequence": [
                curve["shape_signature"]
                for curve in curves
                if curve["level"] == "L2"
            ],
            "mount_sequence": [
                curve["mount_fraction"]
                for curve in curves
                if curve["level"] == "L2"
            ],
            "length_sequence": [
                curve["actual_length"] for curve in curves
            ],
        },
        "random_provenance": {
            "method": contract["sampling"]["method"],
            "seed": seed,
            "candidate_index": candidate_index,
            "halton_quantiles": [_round(value) for value in quantiles],
            "validation_guided_retry_count": 0,
            "validation_guided_resample_count": 0,
            "automatic_repair_count": 0,
            "automatic_deletion_count": 0,
            "silent_fallback_count": 0,
        },
    }
    candidate["intrinsic_diagnostics"] = _diagnose_candidate(
        candidate,
        analysis,
        contract,
    )
    digest_source = dict(candidate)
    candidate["candidate_digest"] = canonical_digest(digest_source)
    return candidate


def generate_unit_candidate_inventory(
    plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    if plan.get("schema") != "dynamic_branch_global_l1_flow_plan_v1":
        raise UnitGrammarError("stage-3B plan schema mismatch")
    if analysis.get("schema") != "dynamic_branch_prototype_analysis_v1":
        raise UnitGrammarError("stage-2 analysis schema mismatch")
    if prior.get("schema") != "dynamic_branch_fixed_visual_prior_v1":
        raise UnitGrammarError("stage-3A prior schema mismatch")
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise UnitGrammarError("stage-4 contract schema mismatch")
    if analysis.get("prototype_id") != plan.get("prototype_id"):
        raise UnitGrammarError("analysis/plan prototype mismatch")
    if plan.get("review", {}).get("status") != "l1_flow_pending_visual_review":
        raise UnitGrammarError("approved source plan content was unexpectedly mutated")

    candidates: list[dict[str, Any]] = []
    lane_rows: list[dict[str, Any]] = []
    candidate_index = 0
    for lane in plan["lanes"]:
        lane_candidates: list[dict[str, Any]] = []
        for grammar_id, stratum, include_l3 in _candidate_strata(lane, contract):
            candidate = _build_candidate(
                plan=plan,
                lane=lane,
                analysis=analysis,
                prior=prior,
                contract=contract,
                grammar_id=grammar_id,
                stratum=stratum,
                include_l3=include_l3,
                candidate_index=candidate_index,
            )
            candidate_index += 1
            candidates.append(candidate)
            lane_candidates.append(candidate)
        feasible = [
            candidate
            for candidate in lane_candidates
            if candidate["intrinsic_diagnostics"]["valid"]
        ]
        lane_rows.append(
            {
                "source_lane_id": lane["slot_id"],
                "role": lane["role"],
                "candidate_count": len(lane_candidates),
                "feasible_candidate_count": len(feasible),
                "candidate_ids": [
                    candidate["candidate_id"] for candidate in lane_candidates
                ],
                "feasible_candidate_ids": [
                    candidate["candidate_id"] for candidate in feasible
                ],
                "coverage_complete": True,
            }
        )

    empty_lanes = [
        row["source_lane_id"]
        for row in lane_rows
        if row["feasible_candidate_count"] == 0
    ]
    inventory: dict[str, Any] = {
        "schema": SCHEMA,
        "contract_id": contract["contract_id"],
        "inventory_id": f"{plan['plan_id']}__unit_candidates_v1",
        "prototype_id": plan["prototype_id"],
        "family_id": plan["family_id"],
        "seed": plan["seed"],
        "source_plan_id": plan["plan_id"],
        "source_plan_digest": plan["plan_digest"],
        "source_l1_geometry_policy": "approved_stage3b_l1_is_immutable",
        "global_latents": plan["global_latents"],
        "lane_count": len(plan["lanes"]),
        "candidate_count": len(candidates),
        "feasible_candidate_count": sum(
            candidate["intrinsic_diagnostics"]["valid"]
            for candidate in candidates
        ),
        "invalid_candidate_count": sum(
            not candidate["intrinsic_diagnostics"]["valid"]
            for candidate in candidates
        ),
        "lanes": lane_rows,
        "candidates": candidates,
        "coverage": {
            "declared_grammar_role_strata_complete": True,
            "lanes_without_feasible_candidate": empty_lanes,
            "global_selection_performed": False,
            "experimental_variants_created": False,
        },
        "generation_policy": {
            "generated_once": True,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
            "silent_fallback_used": False,
            "best_of_n_selection_used": False,
        },
        "review": {
            "status": contract["output"]["review_state"],
            "numeric_checks_cannot_auto_approve_visual_gate": True,
            "criteria": [
                "no_straight_radial_chicken_claw",
                "visible_c_and_s_flow",
                "l1_l2_l3_hierarchy",
                "coordinated_sibling_rhythm",
                "immediate_child_departure",
                "sw1_flower_support_wrap_relation",
                "sw3_terminal_support_dominance",
                "fixed_visual_capability_not_degraded",
            ],
        },
    }
    digest_source = dict(inventory)
    inventory["inventory_digest"] = canonical_digest(digest_source)
    validate_unit_candidate_inventory(inventory, contract)
    if empty_lanes:
        raise UnitGrammarError(
            "stage-4 candidate coverage is infeasible for lanes: "
            + ", ".join(str(value) for value in empty_lanes)
        )
    return inventory


def validate_unit_candidate_inventory(
    inventory: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    if inventory.get("schema") != SCHEMA:
        raise UnitGrammarError("candidate inventory schema mismatch")
    if inventory.get("contract_id") != contract.get("contract_id"):
        raise UnitGrammarError("candidate inventory contract mismatch")
    lanes = inventory.get("lanes")
    candidates = inventory.get("candidates")
    if not isinstance(lanes, list) or not isinstance(candidates, list):
        raise UnitGrammarError("candidate inventory arrays are missing")
    if inventory.get("candidate_count") != len(candidates):
        raise UnitGrammarError("candidate inventory count mismatch")
    if any(candidate.get("schema") != CANDIDATE_SCHEMA for candidate in candidates):
        raise UnitGrammarError("candidate schema mismatch")
    if any(
        candidate.get("source_plan_digest") != inventory.get("source_plan_digest")
        for candidate in candidates
    ):
        raise UnitGrammarError("candidate source plan binding mismatch")
    policy = inventory.get("generation_policy", {})
    forbidden = (
        "validation_guided_retry_used",
        "validation_guided_resample_used",
        "automatic_repair_used",
        "automatic_deletion_used",
        "silent_fallback_used",
        "best_of_n_selection_used",
    )
    if any(policy.get(key) is not False for key in forbidden):
        raise UnitGrammarError("forbidden stage-4 generation behavior detected")
    if inventory.get("review", {}).get("status") != contract["output"]["review_state"]:
        raise UnitGrammarError("candidate review state mismatch")
    if inventory.get("coverage", {}).get("global_selection_performed") is not False:
        raise UnitGrammarError("stage-5 global selection leaked into stage 4")
    role_counts = Counter(candidate["role"] for candidate in candidates)
    if not role_counts:
        raise UnitGrammarError("candidate inventory is empty")


def _R5_l1_curve(source: Mapping[str, Any]) -> dict[str, Any]:
    points = [
        _point(value, f"{source['curve_id']}.centerline")
        for value in source["centerline"]
    ]
    return {
        "curve_id": str(source["curve_id"]),
        "level": "L1",
        "hierarchy_level": 1,
        "parent_curve_id": None,
        "mount_fraction": None,
        "semantic_role": str(source["role"]),
        "functional_reason": "frozen_core_or_unit_role",
        "actual_length": _round(_polyline_length(points)),
        "cubic_segments": [
            dict(segment) for segment in source.get("segments", [])
        ],
        "centerline": [_round_point(point) for point in points],
        "source_geometry_digest": str(source["geometry_digest"]),
    }


def _R5_compile_child(
    *,
    curve_id: str,
    parent: Mapping[str, Any],
    level: int,
    mount_fraction: float,
    length_ratio: float,
    turn_sign: int,
    functional_reason: str,
) -> dict[str, Any]:
    parent_points = [
        _point(value, f"{parent['curve_id']}.centerline")
        for value in parent["centerline"]
    ]
    root, tangent = _sample_polyline(parent_points, mount_fraction)
    parent_length = _polyline_length(parent_points)
    child_length = parent_length * length_ratio
    side = _unit(
        _rotate(tangent, turn_sign * 72.0),
        f"{curve_id}.side",
    )
    exit_direction = _unit(
        _rotate(tangent, turn_sign * 84.0),
        f"{curve_id}.exit",
    )
    target = _add(
        _add(root, _mul(tangent, 0.24 * child_length)),
        _mul(side, 0.78 * child_length),
    )
    segment = _cubic(
        root,
        _add(root, _mul(tangent, 0.27 * child_length)),
        _sub(target, _mul(exit_direction, 0.29 * child_length)),
        target,
    )
    centerline = _sample_segments([segment], 42)
    return {
        "curve_id": curve_id,
        "level": f"L{level}",
        "hierarchy_level": level,
        "parent_curve_id": str(parent["curve_id"]),
        "mount_fraction": _round(mount_fraction),
        "semantic_role": functional_reason,
        "functional_reason": functional_reason,
        "turn_sign": turn_sign,
        "root_tangent_inherited": True,
        "entry_opening_degrees": 0.0,
        "intended_parent_length_ratio": _round(length_ratio),
        "actual_length": _round(_polyline_length(centerline)),
        "cubic_segments": [segment],
        "centerline": [
            _round_point(point) for point in centerline
        ],
        "capacity_evidence": {
            "source": "R4_visual_residual_space",
            "role_specific": True,
        },
    }


def _R5_child_rejections(
    child: Mapping[str, Any],
    occupied: Sequence[Mapping[str, Any]],
    analysis: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    root = _point(child["centerline"][0], "R5 child root")
    for other in occupied:
        allowed = (
            root
            if other["curve_id"] == child["parent_curve_id"]
            else None
        )
        if _curve_crosses(child, other, allowed):
            reasons.append(f"intersection_with__{other['curve_id']}")
    child_points = [
        _point(value, "R5 child centerline")
        for value in child["centerline"]
    ]
    if _curve_crosses(child, child, None):
        reasons.append("self_intersection")
    x_min, y_min, x_max, y_max = [
        float(value)
        for value in analysis["coordinate_system"]["canvas_bounds"]
    ]
    if any(
        not (x_min <= point[0] <= x_max and y_min <= point[1] <= y_max)
        for point in child_points
    ):
        reasons.append("out_of_bounds")
    if any(
        _ellipse_value(point, flower, protection=False) < 1.0
        for flower in analysis["flowers"]
        for point in child_points
    ):
        reasons.append("flower_intrusion")
    return reasons


def generate_role_aware_hierarchy(
    layout: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate R5 L1-only, L2, and capacity-backed L3 variants."""

    if layout.get("schema") != "dynamic_branch_R4_global_unit_layout_v2":
        raise UnitGrammarError("R5 requires the accepted R4 layout")
    if layout.get("prototype_id") != analysis.get("prototype_id"):
        raise UnitGrammarError("R5 layout/analysis prototype mismatch")
    l1_curves = [
        _R5_l1_curve(source)
        for source in layout["selected_curves"]
    ]
    balance = next(
        curve
        for curve in l1_curves
        if curve["semantic_role"] == "balance"
    )
    l2_candidates = [
        _R5_compile_child(
            curve_id=f"{balance['curve_id']}.L2.balance_fill.{sign:+d}",
            parent=balance,
            level=2,
            mount_fraction=0.43,
            length_ratio=0.44,
            turn_sign=sign,
            functional_reason="balance_fill",
        )
        for sign in (-1, 1)
    ]
    for candidate in l2_candidates:
        candidate["hard_rejections"] = _R5_child_rejections(
            candidate,
            l1_curves,
            analysis,
        )
    legal_l2 = [
        candidate
        for candidate in l2_candidates
        if not candidate["hard_rejections"]
    ]
    if not legal_l2:
        raise UnitGrammarError("R5 has no legal balance-fill L2")

    def visual_space_score(curve: Mapping[str, Any]) -> float:
        tip = _point(curve["centerline"][-1], "R5 child tip")
        flower_clearance = min(
            math.sqrt(_ellipse_value(tip, flower, protection=True))
            for flower in analysis["flowers"]
        )
        parent_points = [
            _point(value, "R5 balance parent point")
            for value in balance["centerline"]
        ]
        parent_clearance = min(
            _distance(tip, point) for point in parent_points
        )
        return (
            2.5 * parent_clearance
            + flower_clearance
            - 0.10 * abs(tip[0] - 0.5)
        )

    selected_l2 = max(
        legal_l2,
        key=lambda curve: (
            visual_space_score(curve),
            -int(curve["turn_sign"]),
        ),
    )
    selected_l2["selected"] = True
    l3_candidates = [
        _R5_compile_child(
            curve_id=f"{selected_l2['curve_id']}.L3.echo.{sign:+d}",
            parent=selected_l2,
            level=3,
            mount_fraction=0.68,
            length_ratio=0.30,
            turn_sign=sign,
            functional_reason="tertiary_echo_with_space_evidence",
        )
        for sign in (-1, 1)
    ]
    occupied_for_l3 = [*l1_curves, selected_l2]
    for candidate in l3_candidates:
        candidate["hard_rejections"] = _R5_child_rejections(
            candidate,
            occupied_for_l3,
            analysis,
        )
    legal_l3 = [
        candidate
        for candidate in l3_candidates
        if not candidate["hard_rejections"]
    ]
    for candidate in l3_candidates:
        candidate["visual_capacity_gate"] = False
        candidate["visual_rejection_reason"] = (
            "additional split reads as a default mini-Y in this residual lobe"
        )
        candidate["selected"] = False
    selected_l3 = None
    selected_curves = [
        *l1_curves,
        selected_l2,
        *([selected_l3] if selected_l3 is not None else []),
    ]
    variants = [
        {
            "variant_id": "L1_only",
            "curve_ids": [curve["curve_id"] for curve in l1_curves],
            "functional_reason": "preserve_sparse_unit",
            "valid": True,
        },
        {
            "variant_id": "L1_plus_balance_L2",
            "curve_ids": [
                *[curve["curve_id"] for curve in l1_curves],
                selected_l2["curve_id"],
            ],
            "functional_reason": "balance_fill",
            "valid": True,
        },
        {
            "variant_id": "L1_plus_balance_L2_L3",
            "curve_ids": [
                curve["curve_id"] for curve in selected_curves
            ],
            "functional_reason": (
                "tertiary_echo_with_space_evidence"
                if legal_l3
                else "geometry_not_available"
            ),
            "valid": bool(legal_l3),
            "visual_accepted": False,
        },
    ]
    return {
        "schema": "dynamic_branch_R5_role_aware_hierarchy_v2",
        "prototype_id": str(layout["prototype_id"]),
        "source_R4_selection_digest": str(
            layout["selection_digest"]
        ),
        "selected_variant_id": (
            "L1_plus_balance_L2"
        ),
        "selected_curves": selected_curves,
        "candidate_inventory": [
            *l2_candidates,
            *l3_candidates,
        ],
        "variants": variants,
        "core_role_policy": {
            "core_roles_remain_L1": True,
            "L2_substitutes_core_role": False,
            "secondary_wrap_used_as_core_wrap": False,
            "support_wrap_visual_policy": (
                "prefer_continuous_handoff_when_reference_flow_supports_it"
            ),
            "material_reference": (
                "data/merged_real_data/8.png"
            ),
        },
        "generation_policy": {
            "role_reason_required": True,
            "L3_capacity_evidence_required": True,
            "Y_2C_default_used": False,
            "leaf_bud_tendril_generated": False,
            "failed_candidates_retained": True,
        },
        "hierarchy_digest": canonical_digest(
            {
                "source_R4_selection_digest": layout[
                    "selection_digest"
                ],
                "selected_curve_ids": [
                    curve["curve_id"] for curve in selected_curves
                ],
                "selected_geometry": [
                    curve["cubic_segments"] for curve in selected_curves
                ],
            }
        ),
    }
