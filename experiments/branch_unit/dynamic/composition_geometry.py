#!/usr/bin/env python3
"""Coordinate-free composition geometry shared by priors and production solvers."""

from __future__ import annotations

import bisect
import functools
import math
from typing import Sequence

import numpy as np


Point = tuple[float, float]


def _point(value: Sequence[float]) -> Point:
    return float(value[0]), float(value[1])


@functools.lru_cache(maxsize=16384)
def _resample_polyline_cached(
    points: tuple[Point, ...],
    count: int = 48,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return arc-length samples, unit tangents, and total length."""

    if len(points) < 2:
        raise ValueError("parallel co-travel requires two-point polylines")
    cumulative = [0.0]
    for index in range(1, len(points)):
        cumulative.append(cumulative[-1] + math.dist(points[index - 1], points[index]))
    length = cumulative[-1]
    if length <= 1e-9:
        raise ValueError("parallel co-travel received a degenerate polyline")

    sampled: list[Point] = []
    for sample_index in range(count):
        distance = length * sample_index / (count - 1)
        upper = min(len(points) - 1, bisect.bisect_left(cumulative, distance))
        lower = max(0, upper - 1)
        span = cumulative[upper] - cumulative[lower]
        weight = 0.0 if span <= 1e-12 else (distance - cumulative[lower]) / span
        sampled.append(
            (
                points[lower][0] * (1.0 - weight) + points[upper][0] * weight,
                points[lower][1] * (1.0 - weight) + points[upper][1] * weight,
            )
        )

    tangents: list[Point] = []
    for index in range(count):
        first = sampled[max(0, index - 1)]
        second = sampled[min(count - 1, index + 1)]
        vector = second[0] - first[0], second[1] - first[1]
        magnitude = math.hypot(*vector)
        if magnitude <= 1e-12:
            tangents.append(tangents[-1] if tangents else (1.0, 0.0))
        else:
            tangents.append((vector[0] / magnitude, vector[1] / magnitude))
    return np.asarray(sampled), np.asarray(tangents), length


def _resample_polyline(
    values: Sequence[Sequence[float]],
    count: int = 48,
) -> tuple[np.ndarray, np.ndarray, float]:
    return _resample_polyline_cached(
        tuple(_point(value) for value in values),
        count,
    )


def parallel_co_travel_score(
    first: Sequence[Sequence[float]],
    second: Sequence[Sequence[float]],
    *,
    repeat_width: float = 1.0,
    repeat_shifts: Sequence[float] | None = None,
) -> float:
    """Measure sustained near-parallel occupancy without a distance cutoff.

    The shorter curve is the measuring domain.  Nearest-point distance is
    normalized by that curve's own length, while the eighth-power tangent term
    suppresses local proximity that is not visually co-linear.  Periodic copies
    are included so the same measure applies at repeat boundaries.
    """

    if repeat_width <= 0.0:
        raise ValueError("repeat_width must be positive")
    points_a, tangents_a, length_a = _resample_polyline(first)
    points_b, tangents_b, length_b = _resample_polyline(second)
    if length_a > length_b:
        points_a, points_b = points_b, points_a
        tangents_a, tangents_b = tangents_b, tangents_a
        length_a, length_b = length_b, length_a

    shifts = (
        tuple(float(value) for value in repeat_shifts)
        if repeat_shifts is not None
        else (-repeat_width, 0.0, repeat_width)
    )
    nearest_distance = np.full(len(points_a), np.inf)
    nearest_alignment = np.zeros(len(points_a))
    for shift_x in shifts:
        shifted = points_b + np.asarray((shift_x, 0.0))
        distances = np.linalg.norm(
            points_a[:, None, :] - shifted[None, :, :],
            axis=2,
        )
        indices = np.argmin(distances, axis=1)
        distances = distances[np.arange(len(points_a)), indices]
        alignments = np.abs(
            np.sum(tangents_a * tangents_b[indices], axis=1)
        )
        closer = distances < nearest_distance
        nearest_distance[closer] = distances[closer]
        nearest_alignment[closer] = alignments[closer]
    normalized_distance = nearest_distance / length_a
    return float(
        np.mean(
            nearest_alignment**8 / (1.0 + normalized_distance**4)
        )
    )
