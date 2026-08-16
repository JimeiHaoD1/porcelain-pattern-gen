"""Batched float64 geometry primitives for the frozen programmatic chain.

The formulas replicate `branch_unit_grammar_v1._orientation`,
`_segments_intersect`, and `_point_segment_distance` exactly, so batched
results must agree with the scalar results to float64 rounding precision.
This module is additive; it does not change the formal chain by itself.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

Backend = Literal["numpy", "torch_cuda"]

INTERSECTION_TOLERANCE = 1e-10
DEGENERATE_DENOMINATOR_EPSILON = 1e-18


def _lib(backend: Backend):
    if backend == "numpy":
        return np
    import torch

    return torch


def orientation_batch(
    ax,
    ay,
    bx,
    by,
    cx,
    cy,
    *,
    backend: Backend = "numpy",
):
    """Cross((b - a), (c - a)) for batched point triples."""

    lib = _lib(backend)
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def point_segment_distance_batch(
    px,
    py,
    sx,
    sy,
    ex,
    ey,
    *,
    backend: Backend = "numpy",
):
    """Batched point-to-segment distance with the scalar clip semantics."""

    lib = _lib(backend)
    vx = ex - sx
    vy = ey - sy
    denominator = vx * vx + vy * vy
    fraction = (px - sx) * vx + (py - sy) * vy
    if backend == "numpy":
        safe_denominator = np.where(
            denominator <= DEGENERATE_DENOMINATOR_EPSILON,
            1.0,
            denominator,
        )
        fraction = np.clip(fraction / safe_denominator, 0.0, 1.0)
        fraction = np.where(denominator <= DEGENERATE_DENOMINATOR_EPSILON, 0.0, fraction)
    else:
        safe_denominator = lib.where(
            denominator <= DEGENERATE_DENOMINATOR_EPSILON,
            lib.ones_like(denominator),
            denominator,
        )
        fraction = lib.clip(fraction / safe_denominator, 0.0, 1.0)
        fraction = lib.where(
            denominator <= DEGENERATE_DENOMINATOR_EPSILON,
            lib.zeros_like(fraction),
            fraction,
        )
    projection_x = sx + vx * fraction
    projection_y = sy + vy * fraction
    return lib.hypot(px - projection_x, py - projection_y)


def segments_intersect_batch(
    a0x,
    a0y,
    a1x,
    a1y,
    b0x,
    b0y,
    b1x,
    b1y,
    *,
    backend: Backend = "numpy",
):
    """Batched segment intersection with the scalar orientation semantics."""

    lib = _lib(backend)
    tolerance = INTERSECTION_TOLERANCE
    o1 = orientation_batch(a0x, a0y, a1x, a1y, b0x, b0y, backend=backend)
    o2 = orientation_batch(a0x, a0y, a1x, a1y, b1x, b1y, backend=backend)
    o3 = orientation_batch(b0x, b0y, b1x, b1y, a0x, a0y, backend=backend)
    o4 = orientation_batch(b0x, b0y, b1x, b1y, a1x, a1y, backend=backend)
    proper_crossing = (o1 * o2 < -tolerance) & (o3 * o4 < -tolerance)

    def on_segment(px, py, sx, sy, ex, ey):
        return (
            (lib.minimum(sx, ex) - tolerance <= px)
            & (px <= lib.maximum(sx, ex) + tolerance)
            & (lib.minimum(sy, ey) - tolerance <= py)
            & (py <= lib.maximum(sy, ey) + tolerance)
        )

    touching = (
        ((lib.abs(o1) <= tolerance) & on_segment(b0x, b0y, a0x, a0y, a1x, a1y))
        | ((lib.abs(o2) <= tolerance) & on_segment(b1x, b1y, a0x, a0y, a1x, a1y))
        | ((lib.abs(o3) <= tolerance) & on_segment(a0x, a0y, b0x, b0y, b1x, b1y))
        | ((lib.abs(o4) <= tolerance) & on_segment(a1x, a1y, b0x, b0y, b1x, b1y))
    )
    return proper_crossing | touching
