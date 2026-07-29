#!/usr/bin/env python3
"""Shared geometry kernel for the BranchUnit L screening experiment.

This module deliberately has no L0/L1 branch.  Both experimental variants
must enter through the same primary/dependent curve compilers and the same
check-only validator so that parameter coupling is the only changed factor.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Iterable, Sequence


Point = tuple[float, float]
EPSILON = 1e-9
GEOMETRY_KERNEL_ID = "branch_unit_l_shared_geometry_v1"


@dataclass(frozen=True)
class Cubic:
    p0: Point
    p1: Point
    p2: Point
    p3: Point

    def as_dict(self) -> dict[str, list[float]]:
        return {
            "p0": _json_point(self.p0),
            "p1": _json_point(self.p1),
            "p2": _json_point(self.p2),
            "p3": _json_point(self.p3),
        }


@dataclass(frozen=True)
class Curve:
    curve_id: str
    role: str
    parent_id: str
    width: float
    target_length: float
    cubics: tuple[Cubic, ...]
    mount_fraction: float | None = None

    @property
    def root(self) -> Point:
        return self.cubics[0].p0

    @property
    def tip(self) -> Point:
        return self.cubics[-1].p3

    @property
    def entry_tangent(self) -> Point:
        return _norm(sub(self.cubics[0].p1, self.cubics[0].p0))

    @property
    def exit_tangent(self) -> Point:
        return _norm(sub(self.cubics[-1].p3, self.cubics[-1].p2))

    def points(self, samples_per_cubic: int = 64) -> list[Point]:
        points: list[Point] = []
        for index, cubic in enumerate(self.cubics):
            sampled = sample_cubic(cubic, samples_per_cubic)
            points.extend(sampled if index == 0 else sampled[1:])
        return points

    @property
    def length(self) -> float:
        return polyline_length(self.points())

    def as_dict(self) -> dict[str, object]:
        return {
            "curve_id": self.curve_id,
            "role": self.role,
            "parent_id": self.parent_id,
            "width": round(self.width, 6),
            "mount_fraction": None if self.mount_fraction is None else round(self.mount_fraction, 6),
            "target_length": round(self.target_length, 6),
            "actual_length": round(self.length, 6),
            "cubics": [cubic.as_dict() for cubic in self.cubics],
            "points": [_json_point(point) for point in self.points()],
        }


@dataclass(frozen=True)
class ChildSpec:
    mount_fraction: float
    target_length: float
    turn_sign: int
    angle_degrees: float
    bow: float
    width: float = 1.8

    def as_dict(self) -> dict[str, object]:
        return {
            "mount_fraction": round(self.mount_fraction, 6),
            "target_length": round(self.target_length, 6),
            "turn_sign": int(self.turn_sign),
            "angle_degrees": round(self.angle_degrees, 6),
            "bow": round(self.bow, 6),
            "width": round(self.width, 6),
        }


@dataclass(frozen=True)
class TerminalSpec:
    target_length: float
    turn_sign: int
    angle_degrees: float
    bow: float
    width: float = 1.05

    def as_dict(self) -> dict[str, object]:
        return {
            "target_length": round(self.target_length, 6),
            "turn_sign": int(self.turn_sign),
            "angle_degrees": round(self.angle_degrees, 6),
            "bow": round(self.bow, 6),
            "width": round(self.width, 6),
        }


@dataclass(frozen=True)
class BranchUnit:
    unit_id: str
    primary: Curve
    children: tuple[Curve, ...]
    terminal: Curve

    @property
    def curves(self) -> tuple[Curve, ...]:
        return (self.primary, *self.children, self.terminal)

    @property
    def semantic_curve_count(self) -> int:
        return len(self.curves)

    @property
    def cubic_segment_count(self) -> int:
        return sum(len(curve.cubics) for curve in self.curves)

    @property
    def total_length(self) -> float:
        return sum(curve.length for curve in self.curves)

    @property
    def vector_ink(self) -> float:
        return sum(curve.length * curve.width for curve in self.curves)

    def geometry_payload(self) -> dict[str, object]:
        return {
            "geometry_kernel_id": GEOMETRY_KERNEL_ID,
            "primary": self.primary.as_dict(),
            "children": [child.as_dict() for child in self.children],
            "terminal": self.terminal.as_dict(),
        }

    @property
    def geometry_hash(self) -> str:
        payload = json.dumps(self.geometry_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "geometry_kernel_id": GEOMETRY_KERNEL_ID,
            "semantic_curve_count": self.semantic_curve_count,
            "cubic_segment_count": self.cubic_segment_count,
            "total_length": round(self.total_length, 6),
            "vector_ink": round(self.vector_ink, 6),
            "geometry_hash": self.geometry_hash,
            **self.geometry_payload(),
        }


@dataclass(frozen=True)
class FlowerReserve:
    flower_id: str
    center: Point
    rx: float
    ry: float


@dataclass(frozen=True)
class ContextCurve:
    curve_id: str
    role: str
    width: float
    points: tuple[Point, ...]


@dataclass(frozen=True)
class Scene:
    prototype_id: str
    repeat_x_range: tuple[float, float]
    canvas_height: float
    anchor_s: float
    anchor_point: Point
    anchor_tangent: Point
    growth_direction: Point
    max_clearance: float
    backbone: ContextCurve
    guides: tuple[ContextCurve, ...]
    flowers: tuple[FlowerReserve, ...]


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: tuple[str, ...]
    diagnostics: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "issues": list(self.issues),
            "diagnostics": self.diagnostics,
        }


def add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def mul(a: Point, scale: float) -> Point:
    return a[0] * scale, a[1] * scale


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def normal(a: Point) -> Point:
    return -a[1], a[0]


def rotate(a: Point, degrees: float) -> Point:
    radians = math.radians(degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return a[0] * cosine - a[1] * sine, a[0] * sine + a[1] * cosine


def sample_cubic(cubic: Cubic, samples: int = 64) -> list[Point]:
    points: list[Point] = []
    for index in range(samples + 1):
        t = index / samples
        u = 1.0 - t
        points.append(
            (
                u**3 * cubic.p0[0]
                + 3.0 * u * u * t * cubic.p1[0]
                + 3.0 * u * t * t * cubic.p2[0]
                + t**3 * cubic.p3[0],
                u**3 * cubic.p0[1]
                + 3.0 * u * u * t * cubic.p1[1]
                + 3.0 * u * t * t * cubic.p2[1]
                + t**3 * cubic.p3[1],
            )
        )
    return points


def polyline_length(points: Sequence[Point]) -> float:
    return sum(dist(start, end) for start, end in zip(points, points[1:]))


def sample_polyline(points: Sequence[Point], fraction: float) -> tuple[Point, Point]:
    if len(points) < 2:
        raise ValueError("polyline requires at least two points")
    fraction = max(0.0, min(1.0, fraction))
    lengths = [dist(start, end) for start, end in zip(points, points[1:])]
    total = sum(lengths)
    if total <= EPSILON:
        return points[0], (1.0, 0.0)
    target = total * fraction
    traversed = 0.0
    for (start, end), length in zip(zip(points, points[1:]), lengths):
        if traversed + length >= target:
            local = 0.0 if length <= EPSILON else (target - traversed) / length
            point = add(start, mul(sub(end, start), local))
            return point, _norm(sub(end, start))
        traversed += length
    return points[-1], _norm(sub(points[-1], points[-2]))


def compile_primary(
    *,
    root: Point,
    parent_tangent: Point,
    outward: Point,
    target_length: float,
    sweep_depth: float,
    handle_u: float,
    tip_u: float,
    width: float = 3.0,
) -> Curve:
    """Compile one two-cubic primary sweep with an exact G1/C1 joint."""

    tangent = _norm(parent_tangent)
    outward = _orthogonalized(outward, tangent)
    length = max(target_length, 1.0)
    depth = max(0.0, min(0.45, sweep_depth))
    joint = add(root, add(mul(outward, 0.46 * length), mul(tangent, depth * length)))
    tip = add(root, add(mul(outward, 0.90 * length), mul(tangent, -0.45 * depth * length)))
    joint_tangent = _norm(add(mul(outward, 0.82), mul(tangent, 0.58)))
    tip_tangent = _norm(add(mul(outward, 0.35), mul(tangent, -0.94)))

    start_handle = length * (0.095 + 0.025 * _clamp01(handle_u))
    joint_handle = length * (0.175 + 0.035 * _clamp01(tip_u))
    tip_handle = length * (0.155 + 0.035 * (1.0 - _clamp01(handle_u)))
    first = Cubic(
        p0=root,
        p1=add(root, mul(tangent, start_handle)),
        p2=sub(joint, mul(joint_tangent, joint_handle)),
        p3=joint,
    )
    second = Cubic(
        p0=joint,
        p1=add(joint, mul(joint_tangent, joint_handle)),
        p2=sub(tip, mul(tip_tangent, tip_handle)),
        p3=tip,
    )
    scaled = _scale_cubics_to_length((first, second), root, length)
    return Curve(
        curve_id="primary",
        role="primary_sweep",
        parent_id="backbone",
        width=width,
        target_length=length,
        cubics=scaled,
        mount_fraction=None,
    )


def compile_unit(
    *,
    unit_id: str,
    primary: Curve,
    child_specs: Sequence[ChildSpec],
    terminal_spec: TerminalSpec,
) -> BranchUnit:
    """Compile dependents without changing or validating their parameters."""

    primary_points = primary.points(96)
    children: list[Curve] = []
    for index, spec in enumerate(child_specs, start=1):
        root, tangent = sample_polyline(primary_points, spec.mount_fraction)
        cubic = _compile_open_cubic(
            root=root,
            incoming_tangent=tangent,
            target_length=spec.target_length,
            turn_sign=spec.turn_sign,
            angle_degrees=spec.angle_degrees,
            bow=spec.bow,
        )
        children.append(
            Curve(
                curve_id=f"child_{index}",
                role="child_branch",
                parent_id=primary.curve_id,
                width=spec.width,
                target_length=spec.target_length,
                cubics=(cubic,),
                mount_fraction=spec.mount_fraction,
            )
        )

    terminal_cubic = _compile_open_cubic(
        root=primary.tip,
        incoming_tangent=primary.exit_tangent,
        target_length=terminal_spec.target_length,
        turn_sign=terminal_spec.turn_sign,
        angle_degrees=terminal_spec.angle_degrees,
        bow=terminal_spec.bow,
    )
    terminal = Curve(
        curve_id="terminal",
        role="terminal",
        parent_id=primary.curve_id,
        width=terminal_spec.width,
        target_length=terminal_spec.target_length,
        cubics=(terminal_cubic,),
        mount_fraction=1.0,
    )
    return BranchUnit(unit_id=unit_id, primary=primary, children=tuple(children), terminal=terminal)


def primary_summary(primary: Curve) -> dict[str, object]:
    points = primary.points(96)
    cumulative_turn = 0.0
    segment_lengths = [dist(start, end) for start, end in zip(points, points[1:])]
    total_length = sum(segment_lengths)
    traversed = segment_lengths[0]
    turn_samples: list[dict[str, float]] = []
    previous = _norm(sub(points[1], points[0]))
    for index, (start, end) in enumerate(zip(points[1:], points[2:]), start=1):
        current = _norm(sub(end, start))
        local_turn = math.atan2(cross(previous, current), dot(previous, current))
        cumulative_turn += local_turn
        turn_samples.append(
            {
                "s": round(traversed / max(total_length, EPSILON), 8),
                "signed_turn_radians": round(local_turn, 10),
            }
        )
        traversed += segment_lengths[index]
        previous = current
    turn_sign = 1 if cumulative_turn >= 0.0 else -1
    return {
        "path_length": round(primary.length, 6),
        "entry_tangent": _json_point(primary.entry_tangent),
        "exit_tangent": _json_point(primary.exit_tangent),
        "cumulative_turn_radians": round(cumulative_turn, 8),
        "mean_abs_turn_radians": round(
            sum(abs(sample["signed_turn_radians"]) for sample in turn_samples)
            / max(len(turn_samples), 1),
            10,
        ),
        "turn_sign": turn_sign,
        "turn_samples": turn_samples,
    }


def validate_unit(scene: Scene, unit: BranchUnit, expected_child_count: int) -> ValidationResult:
    """Check one generated unit exactly once; this function never repairs it."""

    issues: list[str] = []
    diagnostics: dict[str, object] = {}
    curves = unit.curves

    finite = all(
        math.isfinite(value)
        for curve in curves
        for cubic in curve.cubics
        for point in (cubic.p0, cubic.p1, cubic.p2, cubic.p3)
        for value in point
    )
    if not finite:
        issues.append("non_finite_coordinate")

    if len(unit.primary.cubics) != 2:
        issues.append("primary_segment_count")
    if len(unit.children) != expected_child_count:
        issues.append("child_count_mismatch")
    if len(unit.terminal.cubics) != 1:
        issues.append("terminal_segment_count")

    root_error = point_polyline_distance(unit.primary.root, scene.backbone.points)
    entry_axis_error = axis_angle_degrees(unit.primary.entry_tangent, scene.anchor_tangent)
    diagnostics["primary_root_error"] = round(root_error, 6)
    diagnostics["primary_entry_axis_error_degrees"] = round(entry_axis_error, 6)
    if root_error > 0.5:
        issues.append("primary_root_off_backbone")
    if dist(unit.primary.root, scene.anchor_point) > 0.5:
        issues.append("primary_root_off_registered_anchor")
    if entry_axis_error > 5.0:
        issues.append("primary_entry_tangent")

    first, second = unit.primary.cubics
    joint_error = dist(first.p3, second.p0)
    incoming_joint = sub(first.p3, first.p2)
    outgoing_joint = sub(second.p1, second.p0)
    joint_angle = angle_degrees(incoming_joint, outgoing_joint)
    joint_handle_delta = abs(math.hypot(*incoming_joint) - math.hypot(*outgoing_joint))
    diagnostics["primary_joint_position_error"] = round(joint_error, 6)
    diagnostics["primary_joint_tangent_error_degrees"] = round(joint_angle, 6)
    diagnostics["primary_joint_handle_delta"] = round(joint_handle_delta, 6)
    if joint_error > 0.25:
        issues.append("primary_joint_c0")
    if joint_angle > 5.0 or joint_handle_delta > 0.25:
        issues.append("primary_joint_c1")

    primary_points = unit.primary.points(96)
    attachment_diagnostics: list[dict[str, object]] = []
    for child in unit.children:
        assert child.mount_fraction is not None
        expected_root, expected_tangent = sample_polyline(primary_points, child.mount_fraction)
        root_delta = dist(child.root, expected_root)
        tangent_delta = angle_degrees(child.entry_tangent, expected_tangent)
        attachment_diagnostics.append(
            {
                "curve_id": child.curve_id,
                "root_error": round(root_delta, 6),
                "entry_tangent_error_degrees": round(tangent_delta, 6),
            }
        )
        if root_delta > 0.5:
            issues.append(f"child_root_off_primary:{child.curve_id}")
        if tangent_delta > 10.0:
            issues.append(f"child_entry_tangent:{child.curve_id}")

    terminal_root_error = dist(unit.terminal.root, unit.primary.tip)
    terminal_tangent_error = angle_degrees(unit.terminal.entry_tangent, unit.primary.exit_tangent)
    diagnostics["child_attachments"] = attachment_diagnostics
    diagnostics["terminal_root_error"] = round(terminal_root_error, 6)
    diagnostics["terminal_entry_tangent_error_degrees"] = round(terminal_tangent_error, 6)
    if terminal_root_error > 0.5:
        issues.append("terminal_root_off_primary_tip")
    if terminal_tangent_error > 10.0:
        issues.append("terminal_entry_tangent")

    x0, x1 = scene.repeat_x_range
    for curve in curves:
        half_width = curve.width * 0.5
        points = curve.points()
        if any(
            point[0] < x0 + half_width
            or point[0] > x1 - half_width
            or point[1] < half_width
            or point[1] > scene.canvas_height - half_width
            for point in points
        ):
            issues.append(f"out_of_bounds:{curve.curve_id}")
        for flower in scene.flowers:
            if any(_inside_ellipse(point, flower, half_width + 1.0) for point in points):
                issues.append(f"flower_intrusion:{curve.curve_id}:{flower.flower_id}")
        if _polyline_self_intersects(points):
            issues.append(f"self_intersection:{curve.curve_id}")

    context_curves = (scene.backbone, *scene.guides)
    context_clearances: list[dict[str, object]] = []
    for curve in curves:
        for obstacle in context_curves:
            contact = scene.anchor_point if curve.curve_id == "primary" and obstacle.curve_id == "backbone" else None
            threshold = (curve.width + obstacle.width) * 0.5 + 1.0
            minimum = polyline_pair_distance(
                curve.points(),
                obstacle.points,
                allowed_contact=contact,
                contact_radius=max(7.0, threshold * 2.0) if contact is not None else 0.0,
            )
            context_clearances.append(
                {
                    "curve_id": curve.curve_id,
                    "obstacle_id": obstacle.curve_id,
                    "minimum": round(minimum, 6),
                    "required": round(threshold, 6),
                }
            )
            if minimum + 1e-6 < threshold:
                issues.append(f"context_clearance:{curve.curve_id}:{obstacle.curve_id}")
    diagnostics["context_clearances"] = context_clearances

    pair_clearances: list[dict[str, object]] = []
    for index, first_curve in enumerate(curves):
        for second_curve in curves[index + 1 :]:
            contact: Point | None = None
            if second_curve.parent_id == first_curve.curve_id:
                contact = second_curve.root
            elif first_curve.parent_id == second_curve.curve_id:
                contact = first_curve.root
            threshold = (first_curve.width + second_curve.width) * 0.5 + 1.0
            minimum = polyline_pair_distance(
                first_curve.points(),
                second_curve.points(),
                allowed_contact=contact,
                contact_radius=max(5.0, threshold * 2.0) if contact is not None else 0.0,
            )
            pair_clearances.append(
                {
                    "first": first_curve.curve_id,
                    "second": second_curve.curve_id,
                    "minimum": round(minimum, 6),
                    "required": round(threshold, 6),
                    "allowed_contact": None if contact is None else _json_point(contact),
                }
            )
            if minimum + 1e-6 < threshold:
                issues.append(f"unit_clearance:{first_curve.curve_id}:{second_curve.curve_id}")
    diagnostics["unit_clearances"] = pair_clearances
    diagnostics["check_only"] = True
    diagnostics["geometry_hash_after_check"] = unit.geometry_hash
    return ValidationResult(valid=not issues, issues=tuple(dict.fromkeys(issues)), diagnostics=diagnostics)


def angle_degrees(first: Point, second: Point) -> float:
    first = _norm(first)
    second = _norm(second)
    cosine = max(-1.0, min(1.0, dot(first, second)))
    return math.degrees(math.acos(cosine))


def axis_angle_degrees(first: Point, second: Point) -> float:
    return min(angle_degrees(first, second), angle_degrees(first, mul(second, -1.0)))


def point_polyline_distance(point: Point, polyline: Sequence[Point]) -> float:
    if len(polyline) < 2:
        return math.inf
    return min(_point_segment_distance(point, start, end) for start, end in zip(polyline, polyline[1:]))


def polyline_pair_distance(
    first: Sequence[Point],
    second: Sequence[Point],
    *,
    allowed_contact: Point | None = None,
    contact_radius: float = 0.0,
) -> float:
    minimum = math.inf
    for first_start, first_end in zip(first, first[1:]):
        for second_start, second_end in zip(second, second[1:]):
            if allowed_contact is not None and (
                min(dist(first_start, allowed_contact), dist(first_end, allowed_contact)) <= contact_radius
                and min(dist(second_start, allowed_contact), dist(second_end, allowed_contact)) <= contact_radius
            ):
                continue
            minimum = min(minimum, _segment_distance(first_start, first_end, second_start, second_end))
    return minimum


def _compile_open_cubic(
    *,
    root: Point,
    incoming_tangent: Point,
    target_length: float,
    turn_sign: int,
    angle_degrees: float,
    bow: float,
) -> Cubic:
    incoming = _norm(incoming_tangent)
    sign = 1 if turn_sign >= 0 else -1
    angle = max(20.0, min(72.0, angle_degrees))
    bow = max(0.05, min(0.42, bow))
    length = max(1.0, target_length)
    travel = rotate(incoming, sign * angle)
    exit_direction = rotate(incoming, sign * min(78.0, angle + 14.0 + 20.0 * bow))
    tip = add(root, mul(travel, length * (0.82 + 0.10 * bow)))
    cubic = Cubic(
        p0=root,
        p1=add(root, mul(incoming, length * (0.12 + 0.05 * bow))),
        p2=sub(tip, mul(exit_direction, length * (0.22 + 0.08 * bow))),
        p3=tip,
    )
    return _scale_cubics_to_length((cubic,), root, length)[0]


def _scale_cubics_to_length(cubics: tuple[Cubic, ...], origin: Point, target_length: float) -> tuple[Cubic, ...]:
    points: list[Point] = []
    for index, cubic in enumerate(cubics):
        sampled = sample_cubic(cubic, 96)
        points.extend(sampled if index == 0 else sampled[1:])
    current = polyline_length(points)
    scale = target_length / max(current, EPSILON)

    def scale_point(point: Point) -> Point:
        return add(origin, mul(sub(point, origin), scale))

    return tuple(
        Cubic(
            p0=scale_point(cubic.p0),
            p1=scale_point(cubic.p1),
            p2=scale_point(cubic.p2),
            p3=scale_point(cubic.p3),
        )
        for cubic in cubics
    )


def _orthogonalized(vector: Point, tangent: Point) -> Point:
    projected = sub(vector, mul(tangent, dot(vector, tangent)))
    if math.hypot(*projected) <= EPSILON:
        projected = normal(tangent)
    projected = _norm(projected)
    if dot(projected, vector) < 0.0:
        projected = mul(projected, -1.0)
    return projected


def _inside_ellipse(point: Point, flower: FlowerReserve, padding: float) -> bool:
    rx = max(flower.rx + padding, EPSILON)
    ry = max(flower.ry + padding, EPSILON)
    dx = (point[0] - flower.center[0]) / rx
    dy = (point[1] - flower.center[1]) / ry
    return dx * dx + dy * dy <= 1.0


def _polyline_self_intersects(points: Sequence[Point]) -> bool:
    segments = list(zip(points, points[1:]))
    for first_index, (a, b) in enumerate(segments):
        for second_index in range(first_index + 2, len(segments)):
            if second_index == first_index + 1:
                continue
            c, d = segments[second_index]
            if _segments_intersect(a, b, c, d):
                return True
    return False


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1 = cross(sub(b, a), sub(c, a))
    o2 = cross(sub(b, a), sub(d, a))
    o3 = cross(sub(d, c), sub(a, c))
    o4 = cross(sub(d, c), sub(b, c))
    if (o1 > EPSILON and o2 < -EPSILON or o1 < -EPSILON and o2 > EPSILON) and (
        o3 > EPSILON and o4 < -EPSILON or o3 < -EPSILON and o4 > EPSILON
    ):
        return True
    return (
        abs(o1) <= EPSILON and _on_segment(a, b, c)
        or abs(o2) <= EPSILON and _on_segment(a, b, d)
        or abs(o3) <= EPSILON and _on_segment(c, d, a)
        or abs(o4) <= EPSILON and _on_segment(c, d, b)
    )


def _on_segment(start: Point, end: Point, point: Point) -> bool:
    return (
        min(start[0], end[0]) - EPSILON <= point[0] <= max(start[0], end[0]) + EPSILON
        and min(start[1], end[1]) - EPSILON <= point[1] <= max(start[1], end[1]) + EPSILON
    )


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    segment = sub(end, start)
    length_sq = dot(segment, segment)
    if length_sq <= EPSILON:
        return dist(point, start)
    fraction = max(0.0, min(1.0, dot(sub(point, start), segment) / length_sq))
    projection = add(start, mul(segment, fraction))
    return dist(point, projection)


def _segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _norm(vector: Point) -> Point:
    length = math.hypot(vector[0], vector[1])
    if length <= EPSILON:
        return 1.0, 0.0
    return vector[0] / length, vector[1] / length


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _json_point(point: Point) -> list[float]:
    return [round(point[0], 6), round(point[1], 6)]


def points_from(raw: Iterable[Iterable[float]]) -> tuple[Point, ...]:
    return tuple((float(point[0]), float(point[1])) for point in raw)
