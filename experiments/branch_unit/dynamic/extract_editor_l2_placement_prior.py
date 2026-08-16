#!/usr/bin/env python3
"""Extract coordinate-free L2 placement evidence from saved editor sessions."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from extract_editor_curve_geometry_prior import (
    ORDINARY_L1_ROLES,
    PROTOTYPE_IDS,
    _distribution,
    _read_json,
    _sample_cubics,
)
from composition_geometry import parallel_co_travel_score


SCHEMA = "dynamic_branch_editor_l2_placement_prior_v1"


class EditorL2PriorError(RuntimeError):
    """Saved editor sessions cannot produce a usable L2 placement prior."""


def _length(points: Sequence[tuple[float, float]]) -> float:
    return sum(
        math.dist(points[index - 1], points[index])
        for index in range(1, len(points))
    )


def _point_set_distance(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
) -> float:
    return min(math.dist(a, b) for a in first for b in second)


def _tangent_at_fraction(
    points: Sequence[tuple[float, float]],
    fraction: float,
) -> tuple[float, float]:
    lengths = [
        math.dist(points[index - 1], points[index])
        for index in range(1, len(points))
    ]
    target = max(0.0, min(1.0, fraction)) * sum(lengths)
    travelled = 0.0
    for index, segment_length in enumerate(lengths, start=1):
        if travelled + segment_length >= target:
            return (
                points[index][0] - points[index - 1][0],
                points[index][1] - points[index - 1][1],
            )
        travelled += segment_length
    return (
        points[-1][0] - points[-2][0],
        points[-1][1] - points[-2][1],
    )


def _departure_turn_sign(
    parent_points: Sequence[tuple[float, float]],
    child_points: Sequence[tuple[float, float]],
    mount_fraction: float,
) -> str:
    parent_tangent = _tangent_at_fraction(parent_points, mount_fraction)
    child_tangent = (
        child_points[1][0] - child_points[0][0],
        child_points[1][1] - child_points[0][1],
    )
    cross = (
        parent_tangent[0] * child_tangent[1]
        - parent_tangent[1] * child_tangent[0]
    )
    return "positive" if cross >= 0.0 else "negative"


def _profile(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise EditorL2PriorError("L2 profile has no edited cases")
    l2_rows = [row for case in rows for row in case["l2_rows"]]
    single_mounts = [
        float(value)
        for case in rows
        for value in case["single_child_mounts"]
    ]
    paired_centers = [
        float(value)
        for case in rows
        for value in case["paired_child_mount_centers"]
    ]
    paired_separations = [
        float(value)
        for case in rows
        for value in case["paired_child_mount_separations"]
    ]
    paired_curve_clearances = [
        float(value)
        for case in rows
        for value in case["paired_child_curve_clearances"]
    ]
    cross_unit_parallel_scores = [
        float(value)
        for case in rows
        for value in case["cross_unit_parallel_co_travel_scores"]
    ]
    if (
        not l2_rows
        or not single_mounts
        or not paired_separations
        or not cross_unit_parallel_scores
    ):
        raise EditorL2PriorError("L2 profile lacks mount evidence")
    child_histogram: Counter[int] = Counter()
    child_turn_histogram: Counter[str] = Counter()
    single_child_turn_histogram: Counter[str] = Counter()
    paired_child_turn_pattern_histogram: Counter[str] = Counter()
    for case in rows:
        child_histogram.update(case["children_per_l1"])
        child_turn_histogram.update(case["child_departure_turn_signs"])
        single_child_turn_histogram.update(
            case["single_child_departure_turn_signs"]
        )
        paired_child_turn_pattern_histogram.update(
            case["paired_child_departure_turn_patterns"]
        )
    mount_deltas = [
        float(row["mount_fraction_delta"])
        for row in l2_rows
        if row["mount_fraction_delta"] is not None
    ]
    return {
        "edited_case_count": len(rows),
        "active_l2_count": len(l2_rows),
        "children_per_l1_histogram": {
            str(key): int(value)
            for key, value in sorted(child_histogram.items())
        },
        "child_departure_turn_sign_histogram": {
            key: int(value)
            for key, value in sorted(child_turn_histogram.items())
        },
        "single_child_departure_turn_sign_histogram": {
            key: int(value)
            for key, value in sorted(single_child_turn_histogram.items())
        },
        "paired_child_departure_turn_pattern_histogram": {
            key: int(value)
            for key, value in sorted(
                paired_child_turn_pattern_histogram.items()
            )
        },
        "mount_fraction": _distribution(
            [float(row["mount_fraction"]) for row in l2_rows]
        ),
        "single_child_mount_fraction": _distribution(single_mounts),
        "paired_child_mount_center": _distribution(paired_centers),
        "paired_child_mount_separation": _distribution(
            paired_separations
        ),
        "paired_child_curve_clearance_unit_ratio": _distribution(
            paired_curve_clearances
        ),
        "mount_fraction_delta": _distribution(mount_deltas),
        "child_length_unit_ratio": _distribution(
            [float(row["child_length_unit_ratio"]) for row in l2_rows]
        ),
        "child_parent_length_ratio": _distribution(
            [float(row["child_parent_length_ratio"]) for row in l2_rows]
        ),
        "nonparent_curve_clearance_unit_ratio": _distribution(
            [
                float(row["nonparent_curve_clearance_unit_ratio"])
                for row in l2_rows
            ]
        ),
        "tip_clearance_unit_ratio": _distribution(
            [float(row["tip_clearance_unit_ratio"]) for row in l2_rows]
        ),
        "cross_unit_parallel_co_travel_score": _distribution(
            cross_unit_parallel_scores
        ),
    }


def extract(session_root: Path) -> dict[str, Any]:
    latest_by_case: dict[tuple[str, int], tuple[Path, dict[str, Any]]] = {}
    for path in sorted(session_root.glob("*/session.json")):
        session = _read_json(path)
        source = session.get("source") or {}
        prototype_id = str(source.get("prototype_id", ""))
        if prototype_id not in PROTOTYPE_IDS:
            continue
        if int((session.get("edit_summary") or {}).get("modified_count", 0)) <= 0:
            continue
        seed = int(source.get("seed", -1))
        key = prototype_id, seed
        if key not in latest_by_case or path.parent.name > latest_by_case[key][0].parent.name:
            latest_by_case[key] = path, session
    if len(latest_by_case) < 10:
        raise EditorL2PriorError(
            f"too few edited cases for L2 placement: {len(latest_by_case)}"
        )

    cases_by_profile: dict[str, list[dict[str, Any]]] = {"global": []}
    provenance: list[dict[str, Any]] = []
    for (prototype_id, seed), (path, session) in sorted(latest_by_case.items()):
        unit_width = float(session["canvas"]["width"])
        if unit_width <= 0.0:
            raise EditorL2PriorError("editor canvas width must be positive")
        active = {
            str(branch["curve_id"]): branch
            for branch in session["branches"]
            if branch.get("status") != "deleted"
        }
        points = {
            curve_id: [
                (point[0] / unit_width, point[1] / unit_width)
                for point in _sample_cubics(branch["edited_cubics"], 48)
            ]
            for curve_id, branch in active.items()
        }
        ordinary_l1_ids = {
            curve_id
            for curve_id, branch in active.items()
            if int(branch["level"]) == 1
            and str(branch.get("role", "")) in ORDINARY_L1_ROLES
        }
        unit_curves: list[
            tuple[str, int, Sequence[tuple[float, float]]]
        ] = []
        for curve_id, branch in active.items():
            level = int(branch["level"])
            if level == 1 and curve_id in ordinary_l1_ids:
                unit_curves.append((curve_id, level, points[curve_id]))
            elif level == 2 and str(branch.get("parent_id")) in ordinary_l1_ids:
                unit_curves.append(
                    (str(branch["parent_id"]), level, points[curve_id])
                )
        cross_unit_parallel_scores = [
            parallel_co_travel_score(first[2], second[2])
            for index, first in enumerate(unit_curves)
            for second in unit_curves[index + 1 :]
            if first[0] != second[0]
            and (first[1] == 2 or second[1] == 2)
        ]
        l2_rows: list[dict[str, Any]] = []
        single_child_mounts: list[float] = []
        paired_centers: list[float] = []
        paired_separations: list[float] = []
        paired_curve_clearances: list[float] = []
        children_per_l1: list[int] = []
        child_departure_turn_signs: list[str] = []
        single_child_departure_turn_signs: list[str] = []
        paired_child_departure_turn_patterns: list[str] = []
        for parent_id, parent in active.items():
            if int(parent["level"]) != 1:
                continue
            children = sorted(
                [
                branch
                for branch in active.values()
                if int(branch["level"]) == 2
                and str(branch.get("parent_id")) == parent_id
                ],
                key=lambda branch: float(branch["mount_fraction"]),
            )
            children_per_l1.append(len(children))
            mounts = sorted(float(child["mount_fraction"]) for child in children)
            turn_signs = [
                _departure_turn_sign(
                    points[parent_id],
                    points[str(child["curve_id"])],
                    float(child["mount_fraction"]),
                )
                for child in children
            ]
            child_departure_turn_signs.extend(turn_signs)
            if len(mounts) == 1:
                single_child_mounts.append(mounts[0])
                single_child_departure_turn_signs.append(turn_signs[0])
            elif len(mounts) == 2:
                paired_centers.append(0.5 * (mounts[0] + mounts[1]))
                paired_separations.append(mounts[1] - mounts[0])
                paired_child_departure_turn_patterns.append(
                    "+".join(turn_signs)
                )
                paired_curve_clearances.append(
                    _point_set_distance(
                        points[str(children[0]["curve_id"])],
                        points[str(children[1]["curve_id"])],
                    )
                )

        for curve_id, branch in active.items():
            if int(branch["level"]) != 2:
                continue
            parent_id = str(branch.get("parent_id"))
            if parent_id not in active or int(active[parent_id]["level"]) != 1:
                continue
            curve_points = points[curve_id]
            parent_points = points[parent_id]
            others = [
                other_points
                for other_id, other_points in points.items()
                if other_id not in {curve_id, parent_id}
            ]
            if not others:
                continue
            child_length = _length(curve_points)
            parent_length = _length(parent_points)
            original_mount = branch.get("original_mount_fraction")
            mount_fraction = float(branch["mount_fraction"])
            l2_rows.append(
                {
                    "mount_fraction": mount_fraction,
                    "mount_fraction_delta": (
                        None
                        if original_mount is None
                        else mount_fraction - float(original_mount)
                    ),
                    "child_length_unit_ratio": child_length,
                    "child_parent_length_ratio": child_length / parent_length,
                    "nonparent_curve_clearance_unit_ratio": min(
                        _point_set_distance(curve_points, other)
                        for other in others
                    ),
                    "tip_clearance_unit_ratio": min(
                        math.dist(curve_points[-1], point)
                        for other in others
                        for point in other
                    ),
                }
            )
        case = {
            "l2_rows": l2_rows,
            "single_child_mounts": single_child_mounts,
            "paired_child_mount_centers": paired_centers,
            "paired_child_mount_separations": paired_separations,
            "paired_child_curve_clearances": paired_curve_clearances,
            "children_per_l1": children_per_l1,
            "child_departure_turn_signs": child_departure_turn_signs,
            "single_child_departure_turn_signs": (
                single_child_departure_turn_signs
            ),
            "paired_child_departure_turn_patterns": (
                paired_child_departure_turn_patterns
            ),
            "cross_unit_parallel_co_travel_scores": (
                cross_unit_parallel_scores
            ),
        }
        cases_by_profile["global"].append(case)
        cases_by_profile.setdefault(prototype_id, []).append(case)
        provenance.append(
            {
                "prototype_id": prototype_id,
                "seed": seed,
                "session_id": path.parent.name,
                "active_l2_count": len(l2_rows),
                "cross_unit_parallel_pair_count": len(
                    cross_unit_parallel_scores
                ),
            }
        )

    return {
        "schema": SCHEMA,
        "prior_id": "saved_editor_l2_placement_20260809",
        "source_policy": {
            "latest_modified_session_per_prototype_seed": True,
            "active_l2_only": True,
            "coordinates_stored": False,
            "all_distances_normalized_by_unit_width": True,
            "mounts_grouped_by_edited_parent_l1": True,
            "cross_unit_parallel_metric": (
                "shorter-curve arc-length occupancy weighted by periodic "
                "nearest-point tangent alignment and relative distance"
            ),
        },
        "edited_case_count": len(provenance),
        "profiles": {
            profile_id: _profile(rows)
            for profile_id, rows in cases_by_profile.items()
        },
        "provenance": provenance,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    payload = extract(args.session_root.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
