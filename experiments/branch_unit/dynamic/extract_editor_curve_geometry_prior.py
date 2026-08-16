#!/usr/bin/env python3
"""Extract parent-backbone-local L1 geometry from saved editor cases."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from composition_geometry import parallel_co_travel_score


DESCRIPTOR_NAMES = (
    "start_handle_chord_ratio",
    "end_handle_chord_ratio",
    "start_angle_abs_deg",
    "end_angle_chord_deg",
    "end_angle_normalized_deg",
    "parent_tangent_departure_deg",
)
ORDINARY_L1_ROLES = frozenset(
    {"frontier", "primary_sweep", "balance", "user_level_1"}
)
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)


class EditorPriorError(RuntimeError):
    """Saved editor cases cannot produce a trustworthy geometry prior."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EditorPriorError(f"JSON root must be an object: {path}")
    return value


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise EditorPriorError("quantile input is empty")
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _sample_cubic(
    segment: Mapping[str, Sequence[float]],
    t: float,
) -> tuple[float, float]:
    points = [segment[name] for name in ("p0", "p1", "p2", "p3")]
    u = 1.0 - t
    weights = (u**3, 3.0 * u * u * t, 3.0 * u * t * t, t**3)
    return (
        sum(float(point[0]) * weight for point, weight in zip(points, weights)),
        sum(float(point[1]) * weight for point, weight in zip(points, weights)),
    )


def _sample_cubics(
    cubics: Sequence[Mapping[str, Sequence[float]]],
    count: int = 96,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for segment_index, segment in enumerate(cubics):
        start = 0 if segment_index == 0 else 1
        points.extend(
            _sample_cubic(segment, index / count)
            for index in range(start, count + 1)
        )
    return points


def _signed_angle_degrees(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return math.degrees(
        math.atan2(
            first[0] * second[1] - first[1] * second[0],
            first[0] * second[0] + first[1] * second[1],
        )
    )


def _unit(
    vector: tuple[float, float],
    label: str,
) -> tuple[float, float]:
    length = math.hypot(*vector)
    if length <= 1e-9:
        raise EditorPriorError(f"degenerate {label}")
    return vector[0] / length, vector[1] / length


def _parent_tangent(
    analysis: Mapping[str, Any],
    mount_fraction: float,
) -> tuple[float, float]:
    samples = analysis.get("backbone", {}).get("samples")
    if not isinstance(samples, Sequence) or len(samples) < 2:
        raise EditorPriorError("prototype analysis lacks backbone samples")
    value = min(1.0, max(0.0, float(mount_fraction)))
    upper = len(samples) - 1
    for index, sample in enumerate(samples):
        if float(sample["s"]) >= value:
            upper = index
            break
    lower = max(0, upper - 1)
    first = samples[lower]
    second = samples[upper]
    first_s = float(first["s"])
    second_s = float(second["s"])
    weight = (
        0.0
        if upper == lower or second_s <= first_s
        else (value - first_s) / (second_s - first_s)
    )
    tangent = (
        float(first["tangent"][0]) * (1.0 - weight)
        + float(second["tangent"][0]) * weight,
        float(first["tangent"][1]) * (1.0 - weight)
        + float(second["tangent"][1]) * weight,
    )
    return _unit(tangent, "interpolated parent tangent")


def _parent_frame_signs(
    cubic: Mapping[str, Sequence[float]],
    parent_tangent: tuple[float, float],
) -> tuple[float, float]:
    p0 = tuple(float(value) for value in cubic["p0"])
    p1 = tuple(float(value) for value in cubic["p1"])
    p3 = tuple(float(value) for value in cubic["p3"])
    chord = (p3[0] - p0[0], p3[1] - p0[1])
    entry = (p1[0] - p0[0], p1[1] - p0[1])
    left_normal = (-parent_tangent[1], parent_tangent[0])
    along_projection = (
        chord[0] * parent_tangent[0] + chord[1] * parent_tangent[1]
    )
    if abs(along_projection) <= 1e-9:
        along_projection = (
            entry[0] * parent_tangent[0] + entry[1] * parent_tangent[1]
        )
    outward_projection = chord[0] * left_normal[0] + chord[1] * left_normal[1]
    if abs(outward_projection) <= 1e-9:
        outward_projection = entry[0] * left_normal[0] + entry[1] * left_normal[1]
    return (
        1.0 if along_projection >= 0.0 else -1.0,
        1.0 if outward_projection >= 0.0 else -1.0,
    )


def _curve_metrics(
    cubics: Sequence[Mapping[str, Sequence[float]]],
) -> dict[str, float]:
    points = _sample_cubics(cubics)
    chord = math.dist(points[0], points[-1])
    length = sum(
        math.dist(points[index - 1], points[index])
        for index in range(1, len(points))
    )
    if chord <= 1e-9 or length <= 1e-9:
        raise EditorPriorError("degenerate edited L1 curve")
    chord_vector = (
        points[-1][0] - points[0][0],
        points[-1][1] - points[0][1],
    )
    maximum_deviation = max(
        abs(
            (point[0] - points[0][0]) * chord_vector[1]
            - (point[1] - points[0][1]) * chord_vector[0]
        )
        / chord
        for point in points
    )
    entry = (
        float(cubics[0]["p1"][0]) - float(cubics[0]["p0"][0]),
        float(cubics[0]["p1"][1]) - float(cubics[0]["p0"][1]),
    )
    exit_direction = (
        float(cubics[-1]["p3"][0]) - float(cubics[-1]["p2"][0]),
        float(cubics[-1]["p3"][1]) - float(cubics[-1]["p2"][1]),
    )
    turns: list[float] = []
    for index in range(1, len(points) - 1):
        incoming = (
            points[index][0] - points[index - 1][0],
            points[index][1] - points[index - 1][1],
        )
        outgoing = (
            points[index + 1][0] - points[index][0],
            points[index + 1][1] - points[index][1],
        )
        turn = _signed_angle_degrees(incoming, outgoing)
        if abs(turn) > 0.02:
            turns.append(turn)
    signs: list[int] = []
    for turn in turns:
        sign = 1 if turn > 0.0 else -1
        if not signs or signs[-1] != sign:
            signs.append(sign)
    return {
        "actual_length": length,
        "bow_ratio": maximum_deviation / length,
        "arc_chord_ratio": length / chord,
        "terminal_turn_degrees": abs(
            _signed_angle_degrees(entry, exit_direction)
        ),
        "total_turn_degrees": sum(abs(turn) for turn in turns),
        "inflection_count": float(max(0, len(signs) - 1)),
    }


def _single_cubic_descriptors(
    cubic: Mapping[str, Sequence[float]],
    parent_tangent: tuple[float, float],
    *,
    along_sign: float | None = None,
    outward_side_sign: float | None = None,
) -> dict[str, float]:
    p0 = tuple(float(value) for value in cubic["p0"])
    p1 = tuple(float(value) for value in cubic["p1"])
    p2 = tuple(float(value) for value in cubic["p2"])
    p3 = tuple(float(value) for value in cubic["p3"])
    chord_vector = (p3[0] - p0[0], p3[1] - p0[1])
    chord = math.hypot(*chord_vector)
    if chord <= 1e-9:
        raise EditorPriorError("degenerate single-cubic L1")
    chord_unit = (chord_vector[0] / chord, chord_vector[1] / chord)
    normal = (-chord_unit[1], chord_unit[0])

    def local(point: tuple[float, float]) -> tuple[float, float]:
        vector = (point[0] - p0[0], point[1] - p0[1])
        return (
            (vector[0] * chord_unit[0] + vector[1] * chord_unit[1]) / chord,
            (vector[0] * normal[0] + vector[1] * normal[1]) / chord,
        )

    first = local(p1)
    second = local(p2)
    start_angle = math.degrees(math.atan2(first[1], first[0]))
    end_angle = math.degrees(math.atan2(-second[1], 1.0 - second[0]))
    orientation_sign = 1.0 if start_angle >= 0.0 else -1.0
    if along_sign is None or outward_side_sign is None:
        along_sign, outward_side_sign = _parent_frame_signs(
            cubic,
            parent_tangent,
        )
    parent_along = (
        parent_tangent[0] * along_sign,
        parent_tangent[1] * along_sign,
    )
    left_normal = (-parent_tangent[1], parent_tangent[0])
    parent_outward = (
        left_normal[0] * outward_side_sign,
        left_normal[1] * outward_side_sign,
    )
    start_handle = (p1[0] - p0[0], p1[1] - p0[1])
    parent_tangent_departure = math.degrees(
        math.atan2(
            start_handle[0] * parent_outward[0]
            + start_handle[1] * parent_outward[1],
            start_handle[0] * parent_along[0]
            + start_handle[1] * parent_along[1],
        )
    )
    return {
        "start_handle_chord_ratio": math.hypot(*first),
        "end_handle_chord_ratio": math.hypot(
            1.0 - second[0],
            -second[1],
        ),
        "start_angle_abs_deg": abs(start_angle),
        "end_angle_chord_deg": end_angle,
        "end_angle_normalized_deg": end_angle * orientation_sign,
        "parent_tangent_departure_deg": parent_tangent_departure,
    }


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(values):
        end = cursor
        while end + 1 < len(values) and values[order[end + 1]] == values[order[cursor]]:
            end += 1
        rank = 0.5 * (cursor + end)
        for index in range(cursor, end + 1):
            ranks[order[index]] = rank
        cursor = end + 1
    return ranks


def _copula_cholesky(rows: Sequence[Mapping[str, float]]) -> list[list[float]]:
    if len(rows) < 5:
        return np.eye(len(DESCRIPTOR_NAMES)).tolist()
    ranked = np.array(
        [_rank([float(row[name]) for row in rows]) for name in DESCRIPTOR_NAMES],
        dtype=float,
    )
    spearman = np.corrcoef(ranked)
    gaussian = 2.0 * np.sin(math.pi * spearman / 6.0)
    eigenvalues, eigenvectors = np.linalg.eigh(gaussian)
    positive = eigenvectors @ np.diag(np.maximum(eigenvalues, 1e-6)) @ eigenvectors.T
    scale = np.sqrt(np.diag(positive))
    positive = positive / np.outer(scale, scale)
    cholesky = np.linalg.cholesky(positive)
    return [[round(float(value), 9) for value in row] for row in cholesky]


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 9),
        "q10": round(_quantile(ordered, 0.10), 9),
        "q25": round(_quantile(ordered, 0.25), 9),
        "median": round(_quantile(ordered, 0.50), 9),
        "q75": round(_quantile(ordered, 0.75), 9),
        "q90": round(_quantile(ordered, 0.90), 9),
        "q95": round(_quantile(ordered, 0.95), 9),
        "max": round(ordered[-1], 9),
        "samples": [round(value, 9) for value in ordered],
    }


def _profile(
    descriptor_rows: Sequence[Mapping[str, float]],
    metric_rows: Sequence[Mapping[str, float]],
    pair_rows: Sequence[Mapping[str, float]],
    segment_counts: Counter[int],
    correction_rows: Sequence[Mapping[str, Any]],
    exemplar_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not descriptor_rows:
        raise EditorPriorError("profile has no single-cubic L1 descriptors")
    if not pair_rows:
        raise EditorPriorError("profile has no edited L1 composition pairs")
    profile = {
        "active_l1_count": len(metric_rows),
        "single_cubic_l1_count": len(descriptor_rows),
        "segment_count_histogram": {
            str(key): int(value) for key, value in sorted(segment_counts.items())
        },
        "descriptor_distributions": {
            name: _distribution([row[name] for row in descriptor_rows])
            for name in DESCRIPTOR_NAMES
        },
        "descriptor_gaussian_copula_cholesky": _copula_cholesky(
            descriptor_rows
        ),
        "observed_geometry": {
            name: _distribution([row[name] for row in metric_rows])
            for name in (
                "bow_ratio",
                "arc_chord_ratio",
                "terminal_turn_degrees",
                "total_turn_degrees",
                "inflection_count",
                "actual_length",
                "actual_length_unit_ratio",
                "stroke_width_unit_ratio",
            )
        },
        "composition_pair_count": len(pair_rows),
        "composition_pair_geometry": {
            "parallel_co_travel_score": _distribution(
                [float(row["parallel_co_travel_score"]) for row in pair_rows]
            )
        },
    }
    if exemplar_rows:
        profile["edited_exemplar_count"] = len(exemplar_rows)
        profile["edited_exemplar_unique_descriptor_count"] = len(
            {
                tuple(
                    round(float(row["edited_descriptors"][name]), 9)
                    for name in DESCRIPTOR_NAMES
                )
                for row in exemplar_rows
            }
        )
        profile["edited_exemplars"] = list(exemplar_rows)
    if correction_rows:
        profile["paired_original_edited_cubic_count"] = len(correction_rows)
        profile["paired_edited_descriptor_unique_count"] = len(
            {
                tuple(
                    round(float(row["edited_descriptors"][name]), 9)
                    for name in DESCRIPTOR_NAMES
                )
                for row in correction_rows
            }
        )
        profile["original_descriptor_distributions"] = {
            name: _distribution(
                [float(row["original_descriptors"][name]) for row in correction_rows]
            )
            for name in DESCRIPTOR_NAMES
        }
        profile["edit_delta_distributions"] = {
            name: _distribution(
                [float(row["edit_delta"][name]) for row in correction_rows]
            )
            for name in DESCRIPTOR_NAMES
        }
        profile["paired_corrections"] = list(correction_rows)
    return profile


def extract(session_root: Path) -> dict[str, Any]:
    latest_by_case: dict[tuple[str, int], tuple[Path, dict[str, Any]]] = {}
    for path in sorted(session_root.glob("*/session.json")):
        session = _read_json(path)
        source = session.get("source") or {}
        prototype_id = str(source.get("prototype_id", ""))
        if prototype_id not in PROTOTYPE_IDS:
            continue
        seed = int(source.get("seed", -1))
        if int((session.get("edit_summary") or {}).get("modified_count", 0)) <= 0:
            continue
        key = (prototype_id, seed)
        if key not in latest_by_case or path.parent.name > latest_by_case[key][0].parent.name:
            latest_by_case[key] = (path, session)
    if len(latest_by_case) < 10:
        raise EditorPriorError(
            f"too few edited cases for a geometry prior: {len(latest_by_case)}"
        )

    descriptor_by_profile: dict[str, list[dict[str, float]]] = {
        "global": []
    }
    metric_by_profile: dict[str, list[dict[str, float]]] = {"global": []}
    pair_by_profile: dict[str, list[dict[str, float]]] = {"global": []}
    segment_by_profile: dict[str, Counter[int]] = {"global": Counter()}
    correction_by_profile: dict[str, list[dict[str, Any]]] = {"global": []}
    exemplar_by_profile: dict[str, list[dict[str, Any]]] = {"global": []}
    provenance: list[dict[str, Any]] = []
    for (prototype_id, seed), (path, session) in sorted(latest_by_case.items()):
        descriptor_by_profile.setdefault(prototype_id, [])
        metric_by_profile.setdefault(prototype_id, [])
        pair_by_profile.setdefault(prototype_id, [])
        segment_by_profile.setdefault(prototype_id, Counter())
        correction_by_profile.setdefault(prototype_id, [])
        exemplar_by_profile.setdefault(prototype_id, [])
        source = session.get("source") or {}
        profile_path = Path(str(source.get("profile_file", "")))
        if not profile_path.is_file():
            raise EditorPriorError(
                f"editor session lacks its prototype analysis: {path}"
            )
        analysis = _read_json(profile_path)
        coordinate_system = analysis.get("coordinate_system") or {}
        if coordinate_system.get("coordinate_system") != "repeat_width_isotropic":
            raise EditorPriorError(
                f"editor parent frame is not isotropic: {profile_path}"
            )
        active_count = 0
        active_ordinary_points: list[list[tuple[float, float]]] = []
        for branch in session["branches"]:
            if int(branch["level"]) != 1 or branch.get("status") == "deleted":
                continue
            role = str(branch.get("role", ""))
            if role not in ORDINARY_L1_ROLES:
                continue
            if branch.get("parent_id") != "backbone":
                raise EditorPriorError(
                    f"ordinary L1 branch has a non-backbone parent: {path}"
                )
            mount_fraction = branch.get("mount_fraction")
            if mount_fraction is None:
                raise EditorPriorError(f"ordinary L1 branch lacks mount_fraction: {path}")
            edited_parent_tangent = _parent_tangent(
                analysis,
                float(mount_fraction),
            )
            cubics = branch["edited_cubics"]
            active_ordinary_points.append(_sample_cubics(cubics))
            original_cubics = branch.get("original_cubics") or []
            metric = _curve_metrics(cubics)
            metric["actual_length_unit_ratio"] = (
                float(metric["actual_length"])
                / float(session["canvas"]["width"])
            )
            metric["stroke_width_unit_ratio"] = (
                float(branch["width"])
                / float(session["canvas"]["width"])
            )
            active_count += 1
            for profile_id in ("global", prototype_id):
                metric_by_profile[profile_id].append(metric)
                segment_by_profile[profile_id][len(cubics)] += 1
            if len(cubics) == 1:
                descriptor = _single_cubic_descriptors(
                    cubics[0],
                    edited_parent_tangent,
                )
                for profile_id in ("global", prototype_id):
                    descriptor_by_profile[profile_id].append(descriptor)
                    exemplar_by_profile[profile_id].append(
                        {
                            "exemplar_id": (
                                f"{prototype_id}:{seed}:{branch['curve_id']}"
                            ),
                            "role": role,
                            "evidence_kind": (
                                "paired_edited_result"
                                if len(original_cubics) == 1
                                else "editor_added_result"
                            ),
                            "edited_descriptors": {
                                name: round(float(descriptor[name]), 9)
                                for name in DESCRIPTOR_NAMES
                            },
                            "edited_bow_ratio": round(
                                float(metric["bow_ratio"]), 9
                            ),
                            "edited_actual_length_unit_ratio": round(
                                float(metric["actual_length_unit_ratio"]),
                                9,
                            ),
                        }
                    )
            if len(original_cubics) == 1 and len(cubics) == 1:
                original_mount_fraction = branch.get(
                    "original_mount_fraction",
                    mount_fraction,
                )
                original_parent_tangent = _parent_tangent(
                    analysis,
                    float(original_mount_fraction),
                )
                along_sign, outward_side_sign = _parent_frame_signs(
                    original_cubics[0],
                    original_parent_tangent,
                )
                original_descriptor = _single_cubic_descriptors(
                    original_cubics[0],
                    original_parent_tangent,
                    along_sign=along_sign,
                    outward_side_sign=outward_side_sign,
                )
                edited_descriptor = _single_cubic_descriptors(
                    cubics[0],
                    edited_parent_tangent,
                    along_sign=along_sign,
                    outward_side_sign=outward_side_sign,
                )
                original_metric = _curve_metrics(original_cubics)
                correction_payload = {
                    "original_descriptors": {
                        name: round(float(original_descriptor[name]), 9)
                        for name in DESCRIPTOR_NAMES
                    },
                    "edit_delta": {
                        name: round(
                            float(edited_descriptor[name])
                            - float(original_descriptor[name]),
                            9,
                        )
                        for name in DESCRIPTOR_NAMES
                    },
                    "edited_descriptors": {
                        name: round(float(edited_descriptor[name]), 9)
                        for name in DESCRIPTOR_NAMES
                    },
                    "original_bow_ratio": round(
                        float(original_metric["bow_ratio"]), 9
                    ),
                    "edited_bow_ratio": round(float(metric["bow_ratio"]), 9),
                    "parent_frame": {
                        "along_sign": int(along_sign),
                        "outward_side_sign": int(outward_side_sign),
                    },
                }
                for profile_id in ("global", prototype_id):
                    correction_by_profile[profile_id].append(correction_payload)
        repeat_width = float(session["canvas"]["width"])
        for index, first in enumerate(active_ordinary_points):
            for second in active_ordinary_points[index + 1 :]:
                pair_payload = {
                    "parallel_co_travel_score": parallel_co_travel_score(
                        first,
                        second,
                        repeat_width=repeat_width,
                    )
                }
                for profile_id in ("global", prototype_id):
                    pair_by_profile[profile_id].append(pair_payload)
        provenance.append(
            {
                "prototype_id": prototype_id,
                "seed": seed,
                "session_id": path.parent.name,
                "modified_count": int(session["edit_summary"]["modified_count"]),
                "ordinary_active_l1_count": active_count,
            }
        )

    profiles = {
        profile_id: _profile(
            descriptor_by_profile[profile_id],
            metric_by_profile[profile_id],
            pair_by_profile[profile_id],
            segment_by_profile[profile_id],
            correction_by_profile[profile_id],
            exemplar_by_profile[profile_id],
        )
        for profile_id in descriptor_by_profile
        if descriptor_by_profile[profile_id]
    }
    return {
        "schema": "dynamic_branch_editor_curve_geometry_prior_v4",
        "prior_id": "saved_editor_parent_local_l1_exemplars_20260811",
        "source_policy": {
            "latest_modified_session_per_prototype_seed": True,
            "active_ordinary_l1_only": True,
            "ordinary_l1_roles": sorted(ORDINARY_L1_ROLES),
            "flower_support_roles_excluded": True,
            "deleted_curves_excluded": True,
            "coordinates_stored": False,
            "fixed_svg_templates_stored": False,
            "descriptor_space": (
                "start direction in parent-backbone local frame; remaining "
                "single-cubic controls normalized by own root-endpoint chord"
            ),
            "parent_tangent_source": (
                "session mount_fraction interpolated on source prototype_analysis "
                "backbone samples"
            ),
            "paired_parent_frame_signs_frozen_from_original_curve": True,
            "paired_original_edited_corrections_included": True,
            "unchanged_paired_curves_retained_as_zero_delta_evidence": True,
            "all_edited_ordinary_l1_results_included_as_exemplars": True,
            "editor_added_l1_results_included": True,
            "composition_pair_metric": (
                "shorter-curve arc-length occupancy weighted by periodic "
                "nearest-point tangent alignment and relative distance"
            ),
            "stroke_width_normalization": (
                "edited branch width divided by repeat canvas width"
            ),
        },
        "descriptor_names": list(DESCRIPTOR_NAMES),
        "edited_case_count": len(provenance),
        "profiles": profiles,
        "provenance": provenance,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = extract(args.session_root.resolve())
    output = args.output.resolve()
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
