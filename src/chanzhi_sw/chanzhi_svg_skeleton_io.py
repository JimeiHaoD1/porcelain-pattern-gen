#!/usr/bin/env python3
"""Read annotated Chanzhi skeleton SVGs for the current structural pipeline."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


Point = tuple[float, float]
Transform = tuple[float, float, float, float, float, float]
IDENTITY_TRANSFORM: Transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

ROLE_BY_STROKE = {
    "#0000ff": "backbone",
    "#ff00ff": "secondary_backbone",
    "#ff9900": "primary_branch",
    "#ff7800": "primary_branch",
    "#00b7c7": "scroll_branch",
    "#00ffff": "scroll_branch",
    "#7a3db8": "scroll_branch",
    "#00ff00": "leaf_guide",
    "#66cc66": "leaf_guide",
    "#007800": "structural_branch",
    "#ffff00": "wrap_flower",
    "#ffcc00": "wrap_flower",
}

GENERATION_BY_STROKE = {
    "#ff9900": 1,
    "#ff7800": 1,
    "#00b7c7": 2,
    "#00ffff": 2,
    "#7a3db8": 3,
}

_BRANCH_STROKES = frozenset(GENERATION_BY_STROKE)
_SEMANTIC_ATTRIBUTES = (
    "data-role",
    "data-terminal-family",
    "data-generation",
    "data-parent-id",
)
_TARGET_FLOWER_ATTRIBUTES = (
    "data-target-flower-id",
    "data-target_flower_id",
    "target_flower_id",
    "target-flower-id",
)
_TARGET_FLOWER_CANONICAL = "data-target-flower-id"
_PRESENTATION_ATTRIBUTES = ("stroke", "stroke-width", "stroke-dasharray")
_ROLE_ALIASES = {
    "flower_support_branch": "flower_support",
    "wrap_flower_branch": "wrap_flower",
    "leaf_bearing_primary": "primary_branch",
    "scroll_primary": "scroll_branch",
    "scroll_secondary": "scroll_branch",
    "scroll_tertiary": "scroll_branch",
    "unit_bbox": "unit_boundary",
}
_GENERATION_BY_ROLE = {
    "primary_branch": 1,
    "leaf_bearing_primary": 1,
    "scroll_primary": 1,
    "scroll_secondary": 2,
    "scroll_tertiary": 3,
}


@dataclass
class PathFeature:
    role: str
    stroke: str
    d: str
    points: list[Point]
    unit: int
    source_index: int
    element_id: str | None = None
    terminal_family: str = "unknown"
    generation: int | None = None
    parent_id: str | None = None
    stroke_width: float | None = None
    legacy_ambiguous_terminal: bool = False
    transform: Transform = IDENTITY_TRANSFORM
    target_flower_id: str | None = None


@dataclass
class FlowerReserve:
    cx: float
    cy: float
    rx: float
    ry: float
    unit: int
    element_id: str | None = None
    role: str = "flower_anchor"
    transform: Transform = IDENTITY_TRANSFORM


def _float(value: str | float | int | None, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(str(value).replace("px", ""))


def _optional_float(value: str | float | int | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return _float(value)
    except ValueError:
        return None


def _style_properties(style: str | None) -> dict[str, str]:
    properties: dict[str, str] = {}
    if not style:
        return properties
    for declaration in style.split(";"):
        name, separator, value = declaration.partition(":")
        if separator and name.strip():
            properties[name.strip().lower()] = value.strip()
    return properties


def _normalize_stroke(value: str | None) -> str:
    if not value:
        return ""
    color = value.strip().lower()
    if color in {"", "none", "transparent"}:
        return ""
    if re.fullmatch(r"#[0-9a-f]{3}", color):
        return "#" + "".join(character * 2 for character in color[1:])
    if re.fullmatch(r"#[0-9a-f]{6}", color):
        return color

    match = re.fullmatch(r"rgb\(\s*([^,]+)\s*,\s*([^,]+)\s*,\s*([^\)]+)\s*\)", color)
    if match:
        channels: list[int] = []
        for raw_channel in match.groups():
            channel = raw_channel.strip()
            try:
                numeric = float(channel[:-1]) * 2.55 if channel.endswith("%") else float(channel)
            except ValueError:
                return color
            channels.append(max(0, min(255, round(numeric))))
        return "#" + "".join(f"{channel:02x}" for channel in channels)
    return color


def _normalize_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = re.sub(r"[-\s]+", "_", value.strip().lower())
    return token or None


def _normalize_reference(value: str | None) -> str | None:
    if value is None:
        return None
    reference = value.strip()
    if reference.startswith("#"):
        reference = reference[1:]
    return reference or None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_generation(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        numeric = float(value)
    except ValueError:
        return None
    integer = int(numeric)
    return integer if numeric == integer else None


def _compose_transform(left: Transform, right: Transform) -> Transform:
    """Return the affine transform ``left(right(point))``."""

    la, lb, lc, ld, le, lf = left
    ra, rb, rc, rd, re_, rf = right
    return (
        la * ra + lc * rb,
        lb * ra + ld * rb,
        la * rc + lc * rd,
        lb * rc + ld * rd,
        la * re_ + lc * rf + le,
        lb * re_ + ld * rf + lf,
    )


def _apply_transform(transform: Transform, point: Point) -> Point:
    a, b, c, d, e, f = transform
    return a * point[0] + c * point[1] + e, b * point[0] + d * point[1] + f


def _transform_numbers(value: str) -> list[float]:
    return [
        float(number)
        for number in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", value)
    ]


def _parse_transform(value: str | None) -> Transform:
    if value is None or not value.strip():
        return IDENTITY_TRANSFORM

    result = IDENTITY_TRANSFORM
    position = 0
    matches = list(re.finditer(r"([A-Za-z]+)\s*\(([^)]*)\)", value))
    if not matches:
        raise ValueError(f"invalid SVG transform: {value!r}")

    for match in matches:
        if value[position : match.start()].strip(" \t\r\n,"):
            raise ValueError(f"invalid SVG transform near {value[position:match.start()]!r}")
        position = match.end()
        name = match.group(1).lower()
        numbers = _transform_numbers(match.group(2))

        if name == "matrix" and len(numbers) == 6:
            operation: Transform = tuple(numbers)  # type: ignore[assignment]
        elif name == "translate" and len(numbers) in {1, 2}:
            tx = numbers[0]
            ty = numbers[1] if len(numbers) == 2 else 0.0
            operation = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif name == "scale" and len(numbers) in {1, 2}:
            sx = numbers[0]
            sy = numbers[1] if len(numbers) == 2 else sx
            operation = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate" and len(numbers) in {1, 3}:
            angle = math.radians(numbers[0])
            cosine = math.cos(angle)
            sine = math.sin(angle)
            rotation: Transform = (cosine, sine, -sine, cosine, 0.0, 0.0)
            if len(numbers) == 3:
                cx, cy = numbers[1], numbers[2]
                operation = _compose_transform(
                    (1.0, 0.0, 0.0, 1.0, cx, cy),
                    _compose_transform(rotation, (1.0, 0.0, 0.0, 1.0, -cx, -cy)),
                )
            else:
                operation = rotation
        elif name == "skewx" and len(numbers) == 1:
            operation = (1.0, 0.0, math.tan(math.radians(numbers[0])), 1.0, 0.0, 0.0)
        elif name == "skewy" and len(numbers) == 1:
            operation = (1.0, math.tan(math.radians(numbers[0])), 0.0, 1.0, 0.0, 0.0)
        elif name in {"matrix", "translate", "scale", "rotate", "skewx", "skewy"}:
            raise ValueError(f"invalid argument count for SVG transform {match.group(1)!r}: {numbers}")
        else:
            raise ValueError(f"unsupported SVG transform {match.group(1)!r}")

        # SVG transform lists are matrix-multiplied in textual order.
        result = _compose_transform(result, operation)

    if value[position:].strip(" \t\r\n,"):
        raise ValueError(f"invalid SVG transform suffix {value[position:]!r}")
    return result


def _resolved_semantics(
    semantics: dict[str, str],
    stroke: str,
    stroke_dasharray: str,
) -> tuple[str | None, str, int | None, bool]:
    """Resolve v3 semantics, preferring metadata and using color as fallback.

    The returned role is canonicalized to the v3 role vocabulary.  Old files
    still get their historical color-only roles, while cyan/purple paths are
    represented as ``scroll_branch`` with generation 2/3.
    """

    raw_role = _normalize_token(semantics.get("data-role"))
    explicit_role = _ROLE_ALIASES.get(raw_role, raw_role) if raw_role else None
    terminal_family = _normalize_token(semantics.get("data-terminal-family")) or "unknown"
    generation = _parse_generation(semantics.get("data-generation"))

    if generation is None and raw_role:
        generation = _GENERATION_BY_ROLE.get(raw_role)
    if generation is None and (explicit_role is None or explicit_role in {"primary_branch", "scroll_branch"}):
        generation = GENERATION_BY_STROKE.get(stroke)

    if explicit_role is not None:
        role = explicit_role
    else:
        color_role = ROLE_BY_STROKE.get(stroke)
        if stroke == "#000000" and stroke_dasharray.strip().lower() not in {"", "none", "0"}:
            color_role = "unit_boundary"

        # terminal_family outranks generation and color for branch strokes.
        if stroke in _BRANCH_STROKES and terminal_family == "leaf_bearing":
            role = "primary_branch"
        elif stroke in _BRANCH_STROKES and terminal_family in {"scroll_swollen", "hybrid"}:
            role = "scroll_branch"
        elif stroke in _BRANCH_STROKES and generation in {2, 3}:
            role = "scroll_branch"
        else:
            role = color_role

    if (
        terminal_family == "unknown"
        and stroke in {"#00b7c7", "#00ffff", "#7a3db8"}
        and (explicit_role is None or explicit_role == "scroll_branch")
    ):
        terminal_family = "scroll_swollen"

    legacy_ambiguous = explicit_role is None and stroke in {"#00ff00", "#66cc66"}
    return role, terminal_family, generation, legacy_ambiguous


def _norm(v: Point) -> Point:
    length = math.hypot(v[0], v[1])
    if length < 1e-9:
        return 1.0, 0.0
    return v[0] / length, v[1] / length


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _path_length(points: list[Point]) -> float:
    return sum(_distance(a, b) for a, b in zip(points, points[1:]))


def _sample_polyline(points: list[Point], fraction: float) -> tuple[Point, Point]:
    if len(points) < 2:
        return points[0], (1.0, 0.0)
    target = max(0.0, min(1.0, fraction)) * _path_length(points)
    walked = 0.0
    for idx, (a, b) in enumerate(zip(points, points[1:])):
        seg_len = _distance(a, b)
        if walked + seg_len >= target:
            local = 0.0 if seg_len < 1e-9 else (target - walked) / seg_len
            point = (a[0] + (b[0] - a[0]) * local, a[1] + (b[1] - a[1]) * local)
            before = points[max(0, idx - 2)]
            after = points[min(len(points) - 1, idx + 3)]
            return point, _norm(_sub(after, before))
        walked += seg_len
    return points[-1], _norm(_sub(points[-1], points[-2]))


def _cubic_point(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    mt = 1.0 - t
    return (
        mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
        mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1],
    )


def _quadratic_point(p0: Point, p1: Point, p2: Point, t: float) -> Point:
    mt = 1.0 - t
    return (
        mt**2 * p0[0] + 2 * mt * t * p1[0] + t**2 * p2[0],
        mt**2 * p0[1] + 2 * mt * t * p1[1] + t**2 * p2[1],
    )


def _dedupe_points(points: list[Point]) -> list[Point]:
    clean: list[Point] = []
    for point in points:
        if not clean or _distance(point, clean[-1]) > 0.05:
            clean.append(point)
    return clean


def _parse_svg_path(d: str, samples_per_cubic: int = 28) -> list[Point]:
    tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", d)
    subpath_count = sum(token in {"M", "m"} for token in tokens)
    if subpath_count > 1:
        raise ValueError(
            f"compound SVG path contains {subpath_count} subpaths; split it into separate <path> "
            "elements so each annotation has one connected centerline"
        )
    points: list[Point] = []
    cursor: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    cmd: str | None = None
    previous_op: str | None = None
    last_cubic_control: Point | None = None
    last_quadratic_control: Point | None = None
    idx = 0

    def is_cmd(token: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z]", token))

    def require_parameters(count: int) -> None:
        if idx + count > len(tokens) or any(is_cmd(token) for token in tokens[idx : idx + count]):
            raise ValueError(f"SVG path command {cmd!r} requires {count} numeric parameters")

    def point_from_pair(x: float, y: float, absolute: bool) -> Point:
        return (x, y) if absolute else (cursor[0] + x, cursor[1] + y)

    while idx < len(tokens):
        if is_cmd(tokens[idx]):
            cmd = tokens[idx]
            idx += 1
        if cmd is None:
            raise ValueError(f"path starts without command: {d}")

        absolute = cmd.isupper()
        op = cmd.upper()
        if op == "M":
            require_parameters(2)
            x = float(tokens[idx])
            y = float(tokens[idx + 1])
            idx += 2
            cursor = point_from_pair(x, y, absolute)
            start = cursor
            points.append(cursor)
            cmd = "L" if absolute else "l"
            previous_op = "M"
            last_cubic_control = None
            last_quadratic_control = None
            continue
        if op == "L":
            require_parameters(2)
            x = float(tokens[idx])
            y = float(tokens[idx + 1])
            idx += 2
            cursor = point_from_pair(x, y, absolute)
            points.append(cursor)
            previous_op = "L"
            last_cubic_control = None
            last_quadratic_control = None
            continue
        if op == "H":
            require_parameters(1)
            x = float(tokens[idx])
            idx += 1
            cursor = (x, cursor[1]) if absolute else (cursor[0] + x, cursor[1])
            points.append(cursor)
            previous_op = "H"
            last_cubic_control = None
            last_quadratic_control = None
            continue
        if op == "V":
            require_parameters(1)
            y = float(tokens[idx])
            idx += 1
            cursor = (cursor[0], y) if absolute else (cursor[0], cursor[1] + y)
            points.append(cursor)
            previous_op = "V"
            last_cubic_control = None
            last_quadratic_control = None
            continue
        if op == "C":
            require_parameters(6)
            raw = [float(tokens[idx + offset]) for offset in range(6)]
            idx += 6
            p1 = point_from_pair(raw[0], raw[1], absolute)
            p2 = point_from_pair(raw[2], raw[3], absolute)
            p3 = point_from_pair(raw[4], raw[5], absolute)
            for step in range(1, samples_per_cubic + 1):
                points.append(_cubic_point(cursor, p1, p2, p3, step / samples_per_cubic))
            cursor = p3
            previous_op = "C"
            last_cubic_control = p2
            last_quadratic_control = None
            continue
        if op == "S":
            require_parameters(4)
            raw = [float(tokens[idx + offset]) for offset in range(4)]
            idx += 4
            if previous_op in {"C", "S"} and last_cubic_control is not None:
                p1 = (2 * cursor[0] - last_cubic_control[0], 2 * cursor[1] - last_cubic_control[1])
            else:
                p1 = cursor
            p2 = point_from_pair(raw[0], raw[1], absolute)
            p3 = point_from_pair(raw[2], raw[3], absolute)
            for step in range(1, samples_per_cubic + 1):
                points.append(_cubic_point(cursor, p1, p2, p3, step / samples_per_cubic))
            cursor = p3
            previous_op = "S"
            last_cubic_control = p2
            last_quadratic_control = None
            continue
        if op == "Q":
            require_parameters(4)
            raw = [float(tokens[idx + offset]) for offset in range(4)]
            idx += 4
            p1 = point_from_pair(raw[0], raw[1], absolute)
            p2 = point_from_pair(raw[2], raw[3], absolute)
            for step in range(1, samples_per_cubic + 1):
                points.append(_quadratic_point(cursor, p1, p2, step / samples_per_cubic))
            cursor = p2
            previous_op = "Q"
            last_cubic_control = None
            last_quadratic_control = p1
            continue
        if op == "T":
            require_parameters(2)
            raw = [float(tokens[idx]), float(tokens[idx + 1])]
            idx += 2
            if previous_op in {"Q", "T"} and last_quadratic_control is not None:
                p1 = (
                    2 * cursor[0] - last_quadratic_control[0],
                    2 * cursor[1] - last_quadratic_control[1],
                )
            else:
                p1 = cursor
            p2 = point_from_pair(raw[0], raw[1], absolute)
            for step in range(1, samples_per_cubic + 1):
                points.append(_quadratic_point(cursor, p1, p2, step / samples_per_cubic))
            cursor = p2
            previous_op = "T"
            last_cubic_control = None
            last_quadratic_control = p1
            continue
        if op == "Z":
            points.append(start)
            cursor = start
            cmd = None
            previous_op = "Z"
            last_cubic_control = None
            last_quadratic_control = None
            continue
        raise ValueError(
            f"unsupported SVG path command {cmd!r}; supported commands are M/L/H/V/C/S/Q/T/Z"
        )
    return _dedupe_points(points)


def _load_skeleton(
    svg_path: Path,
    tile_width: int,
    include_examples: bool = False,
) -> tuple[int, int, list[PathFeature], list[FlowerReserve]]:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    view_box = root.attrib.get("viewBox", "")
    if view_box:
        parts = [float(part) for part in view_box.replace(",", " ").split()]
        width = int(round(parts[2]))
        height = int(round(parts[3]))
    else:
        width = int(round(_float(root.attrib.get("width"), 1024)))
        height = int(round(_float(root.attrib.get("height"), 304)))

    paths: list[PathFeature] = []
    flowers: list[FlowerReserve] = []
    source_index = 0

    def walk(
        elem: ET.Element,
        inherited_semantics: dict[str, str],
        inherited_presentation: dict[str, str],
        inherited_transform: Transform,
        inherited_example: bool,
    ) -> None:
        nonlocal source_index

        is_example = inherited_example or _truthy(elem.attrib.get("data-example"))
        if is_example and not include_examples:
            return

        local_transform = _parse_transform(elem.attrib.get("transform"))
        transform = _compose_transform(inherited_transform, local_transform)

        semantics = dict(inherited_semantics)
        for name in _SEMANTIC_ATTRIBUTES:
            if name in elem.attrib:
                semantics[name] = elem.attrib[name]
        # Canonicalize aliases while walking so a value declared directly on
        # the object always overrides any spelling inherited from its group.
        for name in _TARGET_FLOWER_ATTRIBUTES:
            if name in elem.attrib:
                semantics[_TARGET_FLOWER_CANONICAL] = elem.attrib[name]
                break

        presentation = dict(inherited_presentation)
        for name in _PRESENTATION_ATTRIBUTES:
            if name in elem.attrib:
                presentation[name] = elem.attrib[name]
        style = _style_properties(elem.attrib.get("style"))
        for name in _PRESENTATION_ATTRIBUTES:
            if name in style:
                presentation[name] = style[name]

        tag = elem.tag.split("}")[-1]
        stroke = _normalize_stroke(presentation.get("stroke"))
        dasharray = presentation.get("stroke-dasharray", "")
        role, terminal_family, generation, legacy_ambiguous = _resolved_semantics(
            semantics,
            stroke,
            dasharray,
        )

        if tag == "path" and role is not None:
            d = elem.attrib.get("d", "")
            points = _dedupe_points([_apply_transform(transform, point) for point in _parse_svg_path(d)])
            if len(points) >= 2:
                unit = max(0, int(min(point[0] for point in points) // tile_width))
                parent_id = semantics.get("data-parent-id") or None
                paths.append(
                    PathFeature(
                        role=role,
                        stroke=stroke,
                        d=d,
                        points=points,
                        unit=unit,
                        source_index=source_index,
                        element_id=elem.attrib.get("id") or None,
                        terminal_family=terminal_family,
                        generation=generation,
                        parent_id=parent_id,
                        stroke_width=_optional_float(presentation.get("stroke-width")),
                        legacy_ambiguous_terminal=legacy_ambiguous,
                        transform=transform,
                        target_flower_id=_normalize_reference(
                            semantics.get(_TARGET_FLOWER_CANONICAL)
                        ),
                    )
                )
                source_index += 1
        elif tag in {"ellipse", "circle"}:
            raw_role = _normalize_token(semantics.get("data-role"))
            flower_role = _ROLE_ALIASES.get(raw_role, raw_role) if raw_role else None
            # An explicit role outranks the traditional red-stroke fallback.
            is_flower = flower_role == "flower_anchor" if flower_role else stroke == "#ff0000"
            if is_flower:
                raw_cx = _float(elem.attrib.get("cx"))
                raw_cy = _float(elem.attrib.get("cy"))
                if tag == "circle":
                    raw_rx = raw_ry = _float(elem.attrib.get("r"))
                else:
                    raw_rx = _float(elem.attrib.get("rx"))
                    raw_ry = _float(elem.attrib.get("ry"))
                cx, cy = _apply_transform(transform, (raw_cx, raw_cy))
                a, b, c, d, _, _ = transform
                rx = math.hypot(a * raw_rx, c * raw_ry)
                ry = math.hypot(b * raw_rx, d * raw_ry)
                unit = max(0, int(cx // tile_width))
                flowers.append(
                    FlowerReserve(
                        cx=cx,
                        cy=cy,
                        rx=rx,
                        ry=ry,
                        unit=unit,
                        element_id=elem.attrib.get("id") or None,
                        transform=transform,
                    )
                )

        for child in elem:
            walk(child, semantics, presentation, transform, is_example)

    walk(root, {}, {}, IDENTITY_TRANSFORM, False)
    return width, height, paths, flowers
