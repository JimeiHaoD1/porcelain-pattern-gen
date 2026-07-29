#!/usr/bin/env python3
"""Validate StructVine/Chanzhi SVG annotations against the v3 convention.

The module intentionally uses only the Python standard library so that it can
be run from Inkscape-oriented workstations without installing geometry tools.
Exit codes are: 0 (valid), 1 (QA errors), and 2 (input/parse/output failure).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


Point = tuple[float, float]

FORMAL_COLORS = {
    "#0000ff": "backbone",
    "#ff00ff": "secondary_backbone",
    "#ff9900": "primary_branch",
    "#00ff00": "leaf_guide",
    "#007800": "flower_support",
    "#ffff00": "wrap_flower",
    "#ff0000": "flower_anchor",
    "#000000": "unit_boundary",
    "#00b7c7": "scroll_branch",
    "#7a3db8": "scroll_branch",
}

LEGACY_COLORS = {
    "#ff7800": ("primary_branch", "#ff9900"),
    "#66cc66": ("leaf_guide", "#00ff00"),
    "#ffcc00": ("wrap_flower", "#ffff00"),
    "#00ffff": ("scroll_branch", "#00b7c7"),
}

ROLE_ALIASES = {
    "backbone": "backbone",
    "secondary_backbone": "secondary_backbone",
    "primary_branch": "primary_branch",
    "scroll_branch": "scroll_branch",
    "leaf_guide": "leaf_guide",
    "flower_support": "flower_support",
    "flower_support_branch": "flower_support",
    "wrap_flower": "wrap_flower",
    "wrap_flower_branch": "wrap_flower",
    "flower_anchor": "flower_anchor",
    "unit_boundary": "unit_boundary",
}

# Legacy colors remain loadable, but are always reported as warnings.  Keeping
# this matrix separate from role inference is important: an explicit data-role
# must never make a wrongly colored object pass QA.
ROLE_COLORS = {
    "backbone": {"#0000ff"},
    "secondary_backbone": {"#ff00ff"},
    "primary_branch": {"#ff9900", "#ff7800"},
    "leaf_guide": {"#00ff00", "#66cc66"},
    "flower_support": {"#007800"},
    "wrap_flower": {"#ffff00", "#ffcc00"},
    "flower_anchor": {"#ff0000"},
    "unit_boundary": {"#000000"},
}

SCROLL_COLORS_BY_GENERATION = {
    1: {"#ff9900", "#ff7800"},
    2: {"#00b7c7", "#00ffff"},
    3: {"#7a3db8"},
}

VALID_FAMILIES = {"leaf_bearing", "scroll_swollen", "hybrid"}
GRAPHIC_TAGS = {"path", "line", "polyline", "polygon", "circle", "ellipse", "rect"}
NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
PATH_TOKEN_RE = re.compile(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass
class SvgObject:
    element_id: str | None
    tag: str
    role: str | None
    raw_role: str | None
    color: str | None
    dashed: bool
    family: str | None
    generation_raw: str | None
    parent_id: str | None
    target_flower_id: str | None
    polylines: list[list[Point]]

    @property
    def generation(self) -> int | None:
        try:
            return int(self.generation_raw) if self.generation_raw is not None else None
        except ValueError:
            return None

    @property
    def start(self) -> Point | None:
        for line in self.polylines:
            if line:
                return line[0]
        return None

    @property
    def end(self) -> Point | None:
        for line in reversed(self.polylines):
            if line:
                return line[-1]
        return None


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _style(value: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in (value or "").split(";"):
        if ":" in part:
            key, val = part.split(":", 1)
            result[key.strip().lower()] = val.strip()
    return result


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def _field(elem: ET.Element, *names: str) -> str | None:
    for name in names:
        value = elem.attrib.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _normalize_ref(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value[1:] if value.startswith("#") else value


def normalize_color(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    named = {
        "blue": "#0000ff", "magenta": "#ff00ff", "red": "#ff0000",
        "black": "#000000", "yellow": "#ffff00", "none": None,
    }
    if value in named:
        return named[value]
    if value.startswith("#"):
        raw = value[1:]
        if len(raw) in {3, 4}:
            raw = "".join(ch * 2 for ch in raw[:3])
        elif len(raw) in {6, 8}:
            raw = raw[:6]
        return f"#{raw}" if re.fullmatch(r"[0-9a-f]{6}", raw) else value
    match = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    if match:
        fields = [part.strip() for part in match.group(1).split(",")][:3]
        if len(fields) == 3:
            channels = []
            for field in fields:
                number = float(field.rstrip("%"))
                channels.append(round(number * 2.55) if field.endswith("%") else round(number))
            if all(0 <= channel <= 255 for channel in channels):
                return "#" + "".join(f"{channel:02x}" for channel in channels)
    return value


def _matrix_multiply(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    a, b, c, d, e, f = left
    g, h, i, j, k, l = right
    return (a*g+c*h, b*g+d*h, a*i+c*j, b*i+d*j, a*k+c*l+e, b*k+d*l+f)


def _parse_transform(value: str | None) -> tuple[float, ...]:
    if value is None or not value.strip():
        return IDENTITY
    result = IDENTITY
    position = 0
    matches = list(re.finditer(r"([A-Za-z]+)\s*\(([^)]*)\)", value))
    if not matches:
        raise ValueError(f"invalid SVG transform: {value!r}")
    for match in matches:
        if value[position:match.start()].strip(" \t\r\n,"):
            raise ValueError(f"invalid SVG transform near {value[position:match.start()]!r}")
        position = match.end()
        name, raw = match.group(1), match.group(2)
        nums = [float(number) for number in NUMBER_RE.findall(raw)]
        lower = name.lower()
        if lower == "matrix" and len(nums) == 6:
            op = tuple(nums)
        elif lower == "translate" and len(nums) in {1, 2}:
            op = (1, 0, 0, 1, nums[0], nums[1] if len(nums) > 1 else 0)
        elif lower == "scale" and len(nums) in {1, 2}:
            op = (nums[0], 0, 0, nums[1] if len(nums) > 1 else nums[0], 0, 0)
        elif lower == "rotate" and len(nums) in {1, 3}:
            angle = math.radians(nums[0]); cos_a, sin_a = math.cos(angle), math.sin(angle)
            rotation = (cos_a, sin_a, -sin_a, cos_a, 0, 0)
            if len(nums) == 3:
                cx, cy = nums[1], nums[2]
                op = _matrix_multiply((1, 0, 0, 1, cx, cy), _matrix_multiply(rotation, (1, 0, 0, 1, -cx, -cy)))
            else:
                op = rotation
        elif lower == "skewx" and len(nums) == 1:
            op = (1, 0, math.tan(math.radians(nums[0])), 1, 0, 0)
        elif lower == "skewy" and len(nums) == 1:
            op = (1, math.tan(math.radians(nums[0])), 0, 1, 0, 0)
        elif lower in {"matrix", "translate", "scale", "rotate", "skewx", "skewy"}:
            raise ValueError(f"invalid argument count for SVG transform {name!r}: {nums}")
        else:
            raise ValueError(f"unsupported SVG transform {name!r}")
        result = _matrix_multiply(result, op)
    if value[position:].strip(" \t\r\n,"):
        raise ValueError(f"invalid SVG transform suffix {value[position:]!r}")
    return result


def _apply(point: Point, matrix: tuple[float, ...]) -> Point:
    a, b, c, d, e, f = matrix
    return a*point[0]+c*point[1]+e, b*point[0]+d*point[1]+f


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1-t
    return (u**3*p0[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t**3*p3[0],
            u**3*p0[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t**3*p3[1])


def _quad(p0: Point, p1: Point, p2: Point, t: float) -> Point:
    u = 1-t
    return (u*u*p0[0]+2*u*t*p1[0]+t*t*p2[0], u*u*p0[1]+2*u*t*p1[1]+t*t*p2[1])


def _path_polylines(data: str) -> list[list[Point]]:
    """Sample common SVG path commands; arcs retain endpoints for QA purposes."""
    tokens = PATH_TOKEN_RE.findall(data or "")
    lines: list[list[Point]] = []
    line: list[Point] = []
    cursor = (0.0, 0.0); start = cursor
    cmd: str | None = None; index = 0
    cubic_control: Point | None = None; quad_control: Point | None = None

    def number() -> float:
        nonlocal index
        if index >= len(tokens) or re.fullmatch(r"[A-Za-z]", tokens[index]):
            raise ValueError("path command lacks numeric arguments")
        value = float(tokens[index]); index += 1
        return value

    def point(relative: bool) -> Point:
        x, y = number(), number()
        return (cursor[0]+x, cursor[1]+y) if relative else (x, y)

    while index < len(tokens):
        if re.fullmatch(r"[A-Za-z]", tokens[index]):
            cmd = tokens[index]; index += 1
        if cmd is None:
            raise ValueError("path starts without a command")
        relative, op = cmd.islower(), cmd.upper()
        if op == "M":
            cursor = point(relative)
            if line: lines.append(line)
            line = [cursor]; start = cursor
            cmd = "l" if relative else "L"
        elif op == "L":
            cursor = point(relative); line.append(cursor)
        elif op == "H":
            x = number(); cursor = (cursor[0]+x if relative else x, cursor[1]); line.append(cursor)
        elif op == "V":
            y = number(); cursor = (cursor[0], cursor[1]+y if relative else y); line.append(cursor)
        elif op == "C":
            p0 = cursor; p1 = point(relative); p2 = point(relative); p3 = point(relative)
            line.extend(_cubic(p0, p1, p2, p3, step/12) for step in range(1, 13))
            cursor, cubic_control = p3, p2
        elif op == "S":
            p0 = cursor
            p1 = (2*p0[0]-cubic_control[0], 2*p0[1]-cubic_control[1]) if cubic_control else p0
            p2 = point(relative); p3 = point(relative)
            line.extend(_cubic(p0, p1, p2, p3, step/12) for step in range(1, 13))
            cursor, cubic_control = p3, p2
        elif op == "Q":
            p0 = cursor; p1 = point(relative); p2 = point(relative)
            line.extend(_quad(p0, p1, p2, step/12) for step in range(1, 13))
            cursor, quad_control = p2, p1
        elif op == "T":
            p0 = cursor
            p1 = (2*p0[0]-quad_control[0], 2*p0[1]-quad_control[1]) if quad_control else p0
            p2 = point(relative)
            line.extend(_quad(p0, p1, p2, step/12) for step in range(1, 13))
            cursor, quad_control = p2, p1
        elif op == "A":
            number(); number(); number(); number(); number()
            cursor = point(relative); line.append(cursor)
        elif op == "Z":
            if cursor != start: line.append(start)
            cursor = start; cmd = None
        else:
            raise ValueError(f"unsupported SVG path command: {cmd}")
        if op not in {"C", "S"}: cubic_control = None
        if op not in {"Q", "T"}: quad_control = None
    if line: lines.append(line)
    return lines


def _geometry(elem: ET.Element, tag: str) -> list[list[Point]]:
    get = lambda name, default="0": float((elem.attrib.get(name, default) or default).replace("px", ""))
    if tag == "path":
        return _path_polylines(elem.attrib.get("d", ""))
    if tag == "line":
        return [[(get("x1"), get("y1")), (get("x2"), get("y2"))]]
    if tag in {"polyline", "polygon"}:
        nums = [float(value) for value in NUMBER_RE.findall(elem.attrib.get("points", ""))]
        points = list(zip(nums[::2], nums[1::2]))
        if tag == "polygon" and points: points.append(points[0])
        return [points]
    if tag in {"circle", "ellipse"}:
        cx, cy = get("cx"), get("cy"); rx = get("r") if tag == "circle" else get("rx"); ry = get("r") if tag == "circle" else get("ry")
        return [[(cx+rx*math.cos(2*math.pi*i/32), cy+ry*math.sin(2*math.pi*i/32)) for i in range(33)]]
    if tag == "rect":
        x, y, width, height = get("x"), get("y"), get("width"), get("height")
        return [[(x,y), (x+width,y), (x+width,y+height), (x,y+height), (x,y)]]
    return []


def _distance_point_segment(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0]-a[0], b[1]-a[1]
    denom = dx*dx+dy*dy
    if denom <= 1e-12: return math.dist(point, a)
    t = max(0.0, min(1.0, ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/denom))
    return math.hypot(point[0]-(a[0]+t*dx), point[1]-(a[1]+t*dy))


def _distance_to_object(point: Point, obj: SvgObject) -> float:
    distances = []
    for line in obj.polylines:
        if len(line) == 1: distances.append(math.dist(point, line[0]))
        distances.extend(_distance_point_segment(point, a, b) for a, b in zip(line, line[1:]))
    return min(distances, default=math.inf)


def _object_extent(obj: SvgObject) -> tuple[float, float, float, float] | None:
    points = [point for line in obj.polylines for point in line]
    if not points:
        return None
    xs = [point[0] for point in points]; ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _flower_scale(obj: SvgObject) -> float:
    extent = _object_extent(obj)
    if extent is None:
        return 0.0
    return max((extent[2]-extent[0])/2, (extent[3]-extent[1])/2)


def _is_chromatic(color: str | None) -> bool:
    if not color or not re.fullmatch(r"#[0-9a-f]{6}", color): return False
    red, green, blue = int(color[1:3],16), int(color[3:5],16), int(color[5:7],16)
    return max(red,green,blue)-min(red,green,blue) > 12


def _collect(root: ET.Element, include_examples: bool) -> tuple[list[SvgObject], list[dict], list[str | None]]:
    objects: list[SvgObject] = []
    parse_issues: list[dict] = []
    example_objects: list[str | None] = []

    def walk(elem: ET.Element, matrix: tuple[float, ...], inherited: dict[str,str], family: str | None,
             ignored: bool, inherited_example: bool) -> None:
        style = dict(inherited)
        for key in ("stroke", "stroke-dasharray", "display", "visibility", "opacity", "stroke-opacity"):
            if key in elem.attrib: style[key] = elem.attrib[key]
        style.update(_style(elem.attrib.get("style")))
        example = inherited_example or _truthy(elem.attrib.get("data-example"))
        hidden = ignored or _truthy(elem.attrib.get("data-qa-ignore"))
        hidden = hidden or style.get("display") == "none" or style.get("visibility") == "hidden"
        local_family = elem.attrib.get("data-terminal-family") or family
        tag = _local_name(elem.tag)
        if tag in GRAPHIC_TAGS and example and not include_examples:
            example_objects.append(elem.attrib.get("id"))
        if example and not include_examples:
            local_transform = IDENTITY
        else:
            try:
                local_transform = _parse_transform(elem.attrib.get("transform"))
            except ValueError as exc:
                local_transform = IDENTITY
                parse_issues.append({"severity":"error", "code":"invalid_transform", "message":str(exc), "element_id":elem.attrib.get("id")})
        combined = _matrix_multiply(matrix, local_transform)
        if tag in GRAPHIC_TAGS and not hidden and (include_examples or not example):
            color = normalize_color(style.get("stroke"))
            dashed = style.get("stroke-dasharray", "").strip().lower() not in {"", "none", "0", "0px"}
            raw_role = _field(elem, "data-role", "role")
            role = ROLE_ALIASES.get((raw_role or "").strip().lower())
            inferred = FORMAL_COLORS.get(color or "") or (LEGACY_COLORS.get(color or "") or (None,))[0]
            if color == "#000000" and not dashed and role is None: inferred = None
            role = role or inferred
            relevant = role is not None or raw_role is not None or _is_chromatic(color)
            if relevant:
                if role == "flower_anchor":
                    shape_supported = tag in {"ellipse", "circle"}
                else:
                    shape_supported = tag == "path"
                if not shape_supported:
                    parse_issues.append({
                        "severity":"error", "code":"unsupported_runtime_shape",
                        "message":f"runtime 不支持 {role or 'annotation'} 使用 <{tag}>；结构对象必须为 path，花位必须为 ellipse/circle",
                        "element_id":elem.attrib.get("id"),
                    })
                if tag == "path" and re.search(r"[Aa]", elem.attrib.get("d", "")):
                    parse_issues.append({
                        "severity":"error", "code":"runtime_unsupported_path",
                        "message":"runtime 不支持 SVG path 的 A/a 圆弧命令",
                        "element_id":elem.attrib.get("id"),
                    })
                try:
                    polylines = [[_apply(point, combined) for point in line] for line in _geometry(elem, tag)]
                except (ValueError, IndexError) as exc:
                    polylines = []
                    parse_issues.append({"severity":"error", "code":"invalid_geometry", "message":str(exc), "element_id":elem.attrib.get("id")})
                objects.append(SvgObject(
                    elem.attrib.get("id"), tag, role, raw_role, color, dashed, local_family,
                    _field(elem, "data-generation", "generation"),
                    _normalize_ref(_field(elem, "data-parent-id", "data-parent_id", "parent_id")),
                    _normalize_ref(_field(elem, "data-target-flower-id", "data-target_flower_id", "target_flower_id", "target-flower-id")),
                    polylines,
                ))
        if not hidden:
            for child in elem:
                walk(child, combined, style, local_family, hidden, example)

    walk(root, IDENTITY, {}, root.attrib.get("data-terminal-family"), False, False)
    return objects, parse_issues, example_objects


def _infer_profile(objects: Iterable[SvgObject]) -> str:
    families = {obj.family for obj in objects if obj.family in VALID_FAMILIES}
    if "hybrid" in families or {"leaf_bearing", "scroll_swollen"}.issubset(families): return "hybrid"
    if len(families) == 1: return next(iter(families))
    colors = {obj.color for obj in objects}
    if colors & {"#00b7c7", "#7a3db8", "#00ffff"}:
        return "hybrid" if colors & {"#00ff00", "#66cc66"} else "scroll_swollen"
    if colors & {"#00ff00", "#66cc66"}: return "leaf_bearing"
    return "unknown"


def _allowed_role_colors(obj: SvgObject) -> set[str] | None:
    if obj.role == "scroll_branch":
        if obj.generation in SCROLL_COLORS_BY_GENERATION:
            return SCROLL_COLORS_BY_GENERATION[obj.generation]
        return set().union(*SCROLL_COLORS_BY_GENERATION.values())
    return ROLE_COLORS.get(obj.role or "")


def audit_svg(path: str | Path, *, profile: str = "auto", attachment_tolerance: float = 8.0,
              flower_tolerance: float | None = None, include_examples: bool = False) -> dict:
    source = Path(path)
    root = ET.parse(source).getroot()
    objects, issues, example_objects = _collect(root, include_examples)
    resolved_profile = _infer_profile(objects) if profile == "auto" else profile

    def issue(severity: str, code: str, message: str, obj: SvgObject | None = None, **details: object) -> None:
        item = {"severity":severity, "code":code, "message":message, "element_id":obj.element_id if obj else None}
        if details: item["details"] = details
        issues.append(item)

    if example_objects and not include_examples:
        issue(
            "error", "example_objects_present",
            f"文件中仍有 {len(example_objects)} 个 data-example=true 图形对象；正式标注必须删除示例",
            count=len(example_objects), element_ids=example_objects,
        )

    ids: dict[str, SvgObject] = {}
    for obj in objects:
        if obj.element_id:
            if obj.element_id in ids: issue("error", "duplicate_id", f"重复 id: {obj.element_id}", obj)
            else: ids[obj.element_id] = obj
        if obj.raw_role and obj.role is None:
            issue("error", "invalid_role", f"未知 data-role: {obj.raw_role}", obj)
        if obj.color in LEGACY_COLORS:
            issue("warning", "legacy_color", f"旧颜色 {obj.color}，新标注应改为 {LEGACY_COLORS[obj.color][1]}", obj, replacement=LEGACY_COLORS[obj.color][1])
        elif obj.color not in FORMAL_COLORS and (obj.raw_role or _is_chromatic(obj.color)):
            issue("error", "illegal_color", f"非法标注颜色: {obj.color or 'missing'}", obj)
        if obj.family and obj.family not in VALID_FAMILIES:
            issue("error", "invalid_terminal_family", f"非法 terminal family: {obj.family}", obj)

    backbones = [obj for obj in objects if obj.role == "backbone"]
    boundaries = [obj for obj in objects if obj.role == "unit_boundary"]
    if not backbones: issue("error", "missing_backbone", "缺少蓝色主干 backbone")
    if len(boundaries) < 2: issue("error", "insufficient_unit_boundaries", "repeat 边界少于两条", count=len(boundaries))
    for boundary in boundaries:
        if boundary.color != "#000000" or not boundary.dashed:
            issue("error", "invalid_unit_boundary_style", "unit boundary 必须是黑色虚线", boundary)
    if len(boundaries) >= 2:
        boundary_extents = [extent for boundary in boundaries if (extent := _object_extent(boundary))]
        boundary_xs = [0.5*(extent[0]+extent[2]) for extent in boundary_extents]
        if len(boundary_xs) >= 2:
            left, right = min(boundary_xs), max(boundary_xs)
            if right-left <= 1e-6:
                issue("error", "unit_boundaries_not_separated", "两条 unit boundary 位于同一位置", separation=right-left)
            elif backbones:
                spans_unit = False
                for backbone in backbones:
                    extent = _object_extent(backbone)
                    if extent and extent[0] <= left+attachment_tolerance and extent[2] >= right-attachment_tolerance:
                        spans_unit = True
                        break
                if not spans_unit:
                    issue(
                        "error", "backbone_does_not_span_unit",
                        "主干未横跨左右 repeat 边界",
                        left_boundary=left, right_boundary=right, tolerance=attachment_tolerance,
                    )

    branch_roles = {"primary_branch", "scroll_branch"}
    expected_generation = {
        "#ff9900":1, "#ff7800":1, "#00b7c7":2, "#00ffff":2, "#7a3db8":3,
    }
    for obj in objects:
        effective_family = obj.family or (resolved_profile if resolved_profile in VALID_FAMILIES else None)
        if obj.role in branch_roles:
            if obj.generation_raw is None:
                issue("error", "missing_generation", "分支缺少 data-generation", obj)
            elif obj.generation not in {1,2,3}:
                issue("error", "invalid_generation", f"非法 data-generation: {obj.generation_raw}", obj)
            expected = expected_generation.get(obj.color or "")
            if expected and obj.generation is not None and obj.generation != expected:
                issue("error", "generation_color_mismatch", f"颜色要求 generation={expected}", obj, expected=expected, actual=obj.generation)
            if obj.role == "primary_branch" and obj.generation not in {None,1}:
                issue("error", "invalid_primary_generation", "primary_branch 只能是一级", obj)
            if effective_family is None or (resolved_profile == "hybrid" and obj.family is None):
                issue("error", "missing_terminal_family", "分支缺少 data-terminal-family", obj)
        if obj.role == "leaf_guide" and not obj.parent_id:
            issue("error", "missing_parent_id", "leaf_guide 缺少 data-parent-id", obj)
        if obj.role in branch_roles and obj.generation in {2,3} and not obj.parent_id:
            issue("error", "missing_parent_id", f"{obj.generation}级分支缺少 data-parent-id", obj)
        if obj.role in {"flower_support", "wrap_flower"} and not obj.target_flower_id:
            issue("error", "missing_target_flower", f"{obj.role} 缺少 target_flower_id", obj)
        if obj.role in {"flower_support", "wrap_flower"} and not obj.parent_id:
            issue("error", "missing_parent_id", f"{obj.role} 缺少 data-parent-id", obj)

        allowed_colors = _allowed_role_colors(obj)
        if allowed_colors is not None and obj.color not in allowed_colors:
            expected_text = ", ".join(sorted(allowed_colors))
            issue(
                "error",
                "role_color_mismatch",
                f"{obj.role} 的颜色应为 {expected_text}，实际为 {obj.color or 'missing'}",
                obj,
                role=obj.role,
                expected_colors=sorted(allowed_colors),
                actual_color=obj.color,
            )

        if effective_family == "leaf_bearing" and obj.color in {"#00b7c7", "#00ffff", "#7a3db8"}:
            issue("error", "profile_a_scroll_color_misuse", "Profile A 不应使用青/紫结构分支", obj)
        if effective_family == "scroll_swollen" and obj.color in {"#00ff00", "#66cc66"}:
            issue("error", "profile_b_leaf_color_misuse", "Profile B 不应使用绿色 leaf_guide", obj)

    # Referential and hierarchy checks.
    for obj in objects:
        if obj.parent_id:
            parent = ids.get(obj.parent_id)
            if parent is None:
                issue("error", "parent_not_found", f"找不到 parent id: {obj.parent_id}", obj)
                continue
            if obj.role in branch_roles and obj.generation == 1 and parent.role not in {"backbone", "secondary_backbone"}:
                issue("error", "wrong_parent_hierarchy", "一级分支的父对象必须是主干", obj)
            if obj.role in branch_roles and obj.generation in {2,3}:
                expected_parent = obj.generation-1
                if parent.role not in branch_roles or parent.generation != expected_parent:
                    issue("error", "wrong_parent_hierarchy", f"{obj.generation}级分支必须绑定{expected_parent}级分支", obj, parent_role=parent.role, parent_generation=parent.generation)
            parent_family = parent.family or (
                resolved_profile if resolved_profile in {"leaf_bearing", "scroll_swollen"} else None
            )
            if obj.role == "leaf_guide" and not (
                parent.role == "primary_branch"
                and parent.generation == 1
                and parent_family == "leaf_bearing"
            ):
                issue("error", "wrong_parent_hierarchy", "leaf_guide 必须绑定 leaf_bearing 一级 primary_branch", obj)
            if obj.role in {"flower_support", "wrap_flower"} and parent.role not in {
                "backbone", "secondary_backbone", "primary_branch", "scroll_branch"
            }:
                issue("error", "wrong_parent_hierarchy", f"{obj.role} 必须绑定主干或结构分支", obj)
        if obj.role in {"flower_support", "wrap_flower"} and obj.target_flower_id:
            target = ids.get(obj.target_flower_id)
            if target is None:
                issue("error", "target_flower_not_found", f"找不到 flower id: {obj.target_flower_id}", obj)
            elif target.role != "flower_anchor":
                issue("error", "target_not_flower", "target_flower_id 未指向 flower_anchor", obj)

    # Geometry: gen-1 starts on a backbone; deeper branches and leaf guides start on their declared parent.
    for obj in objects:
        parents: list[SvgObject] = []
        if obj.role in branch_roles and obj.generation == 1:
            parents = [ids[obj.parent_id]] if obj.parent_id in ids else backbones
        elif (obj.role in branch_roles and obj.generation in {2,3}) or obj.role == "leaf_guide":
            if obj.parent_id in ids: parents = [ids[obj.parent_id]]
        elif obj.role in {"flower_support", "wrap_flower"}:
            if obj.parent_id in ids: parents = [ids[obj.parent_id]]
        if parents and obj.start is not None:
            distance = min(_distance_to_object(obj.start, parent) for parent in parents)
            tolerance = attachment_tolerance
            if (
                obj.role in {"flower_support", "wrap_flower"}
                and obj.target_flower_id in ids
                and ids[obj.target_flower_id].role == "flower_anchor"
            ):
                tolerance = flower_tolerance if flower_tolerance is not None else max(
                    attachment_tolerance, 1.3*_flower_scale(ids[obj.target_flower_id])
                )
            if distance > tolerance:
                issue("error", "detached_branch_start", f"子枝起点距父路径 {distance:.3f}，超过容差 {tolerance:.3f}", obj,
                      distance=round(distance,6), tolerance=tolerance)
        elif parents and obj.start is None:
            issue("error", "missing_geometry", "无法读取分支起点几何", obj)

        if (
            obj.role in {"flower_support", "wrap_flower"}
            and obj.target_flower_id in ids
            and ids[obj.target_flower_id].role == "flower_anchor"
            and obj.end is not None
        ):
            target = ids[obj.target_flower_id]
            tolerance = flower_tolerance if flower_tolerance is not None else max(
                attachment_tolerance, 1.3*_flower_scale(target)
            )
            distance = _distance_to_object(obj.end, target)
            if distance > tolerance:
                issue(
                    "error", "flower_terminal_too_far",
                    f"{obj.role} 末端距目标花位边界 {distance:.3f}，超过容差 {tolerance:.3f}", obj,
                    distance=round(distance,6), tolerance=tolerance,
                    target_flower_id=obj.target_flower_id,
                )

    errors = sum(item["severity"] == "error" for item in issues)
    warnings = sum(item["severity"] == "warning" for item in issues)
    return {
        "schema_version":"chanzhi.annotation_qa.v1",
        "input":str(source.resolve()),
        "profile":resolved_profile,
        "settings":{"attachment_tolerance":attachment_tolerance, "flower_tolerance":flower_tolerance if flower_tolerance is not None else "auto", "include_examples":include_examples},
        "status":"pass" if errors == 0 else "fail",
        "summary":{"errors":errors, "warnings":warnings, "annotation_elements":len(objects), "backbones":len(backbones), "unit_boundaries":len(boundaries)},
        "issues":issues,
        "elements":[{
            "id":obj.element_id, "tag":obj.tag, "role":obj.role, "stroke":obj.color,
            "terminal_family":obj.family, "generation":obj.generation_raw,
            "parent_id":obj.parent_id, "target_flower_id":obj.target_flower_id,
        } for obj in objects],
    }


def _input_error(path: str | Path, message: str) -> dict:
    return {"schema_version":"chanzhi.annotation_qa.v1", "input":str(Path(path).resolve()), "profile":"unknown",
            "status":"input_error", "summary":{"errors":1,"warnings":0,"annotation_elements":0,"backbones":0,"unit_boundaries":0},
            "issues":[{"severity":"error","code":"input_error","message":message,"element_id":None}], "elements":[]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Chanzhi SVG annotation against color spec v3.")
    parser.add_argument("svg", help="input SVG")
    parser.add_argument("-o", "--output", default="-", help="JSON output path; default stdout")
    parser.add_argument("--profile", choices=["auto", "leaf_bearing", "scroll_swollen", "hybrid"], default="auto")
    parser.add_argument("--attachment-tolerance", type=float, default=8.0)
    parser.add_argument("--flower-tolerance", type=float, default=None,
                        help="flower branch attachment/terminal tolerance; default auto-scales to flower size")
    parser.add_argument("--include-examples", action="store_true", help="validate elements marked data-example=true")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.attachment_tolerance < 0: raise ValueError("attachment tolerance must be non-negative")
        if args.flower_tolerance is not None and args.flower_tolerance < 0:
            raise ValueError("flower tolerance must be non-negative")
        report = audit_svg(args.svg, profile=args.profile, attachment_tolerance=args.attachment_tolerance,
                           flower_tolerance=args.flower_tolerance, include_examples=args.include_examples)
        code = 0 if report["status"] == "pass" else 1
    except (OSError, ET.ParseError, ValueError) as exc:
        report = _input_error(args.svg, str(exc)); code = 2
    payload = json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2) + "\n"
    try:
        if args.output == "-": sys.stdout.write(payload)
        else: Path(args.output).write_text(payload, encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"cannot write QA report: {exc}\n")
        return 2
    return code


if __name__ == "__main__":
    raise SystemExit(main())
