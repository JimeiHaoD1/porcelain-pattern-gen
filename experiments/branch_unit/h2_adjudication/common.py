"""Shared frozen utilities for the H2 necessity adjudication harness."""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


ADJUDICATION_DIR = Path(__file__).resolve().parent
BRANCH_UNIT_DIR = ADJUDICATION_DIR.parent
DYNAMIC_DIR = BRANCH_UNIT_DIR / "dynamic"
REPO_ROOT = ADJUDICATION_DIR.parents[2]
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

FIXED_COMMIT = "96100e5e8eaac4bd6869edac652e377d7f4aac49"
BOOTSTRAP_SEED = 20260821
EVALUATOR_VERSION = "h2_independent_geometry_v1"

PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
VARIANT_IDS = ("expanded", "compact", "swept")
DENSITY_LEVELS = ("simple", "medium", "rich")
DENSITY_TARGET_QUANTILES = {"simple": 0.2, "medium": 0.5, "rich": 0.8}
RESOURCE_WEIGHTS = {
    "ordinary_l1_count": 0.30,
    "total_planning_length": 0.45,
    "mean_backbone_excursion": 0.15,
    "mean_vertical_span": 0.10,
}

H2A_CONTRACT_PATH = DYNAMIC_DIR / "STAGE3B_L1_FLOW_CONTRACT_V3.json"
H2A_OLD_CONTRACT_PATH = DYNAMIC_DIR / "STAGE3B_L1_FLOW_CONTRACT_V2.json"
H2B_CONTRACT_PATH = DYNAMIC_DIR / "STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json"
H2B_OLD_CONTRACT_PATH = DYNAMIC_DIR / "STAGE5E_L2_SPARSE_SELECTION_CONTRACT_V1.json"
STAGE4_CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json"
EDITOR_L2_PRIOR_PATH = DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json"


class AdjudicationError(RuntimeError):
    """The frozen adjudication harness cannot execute fairly."""


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AdjudicationError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ensure_empty_output(path: Path) -> None:
    if path.exists():
        raise AdjudicationError(f"output already exists: {path}")
    path.mkdir(parents=True)


def assert_frozen_contracts() -> dict[str, str]:
    contracts = {
        "h2a_old": read_json(H2A_OLD_CONTRACT_PATH),
        "h2a": read_json(H2A_CONTRACT_PATH),
        "h2b_old": read_json(H2B_OLD_CONTRACT_PATH),
        "h2b": read_json(H2B_CONTRACT_PATH),
    }
    expected = {
        "h2a_old": "edit_feedback_conditioned_global_l1_flow_v2",
        "h2a": "soft_density_global_l1_flow_v3",
        "h2b_old": "stage5e_sparse_local_l2_selection_v1",
        "h2b": "stage5e_joint_sparse_local_l2_selection_v2",
    }
    actual = {name: str(value.get("contract_id")) for name, value in contracts.items()}
    if actual != expected:
        raise AdjudicationError(f"frozen contract mismatch: {actual}")
    return actual


def allocate_h2a_seeds(seed_start: int = 100000) -> list[dict[str, Any]]:
    """Take the first two production seeds in each prototype/variant stratum."""

    from run_batch_generation import production_cell

    rows: list[dict[str, Any]] = []
    for prototype_id in PROTOTYPE_IDS:
        chosen = {variant: [] for variant in VARIANT_IDS}
        seed = seed_start
        while any(len(values) < 2 for values in chosen.values()):
            variant, natural_density = production_cell(prototype_id, seed)
            if len(chosen[variant]) < 2:
                chosen[variant].append((seed, natural_density))
            seed += 1
            if seed - seed_start > 100_000:
                raise AdjudicationError(f"H2-A seed allocation exhausted: {prototype_id}")
        for variant in VARIANT_IDS:
            for replicate, (production_seed, natural_density) in enumerate(chosen[variant], 1):
                rows.append(
                    {
                        "prototype_id": prototype_id,
                        "backbone_variant": variant,
                        "replicate": replicate,
                        "production_seed": production_seed,
                        "natural_density": natural_density,
                    }
                )
    return rows


def allocate_h2b_seeds(seed_start: int = 100000) -> list[dict[str, Any]]:
    """Take the first two production seeds in each 5x3x3 fixed stratum."""

    from run_batch_generation import production_cell

    rows: list[dict[str, Any]] = []
    for prototype_id in PROTOTYPE_IDS:
        chosen = {
            (variant, density): []
            for variant in VARIANT_IDS
            for density in DENSITY_LEVELS
        }
        seed = seed_start
        while any(len(values) < 2 for values in chosen.values()):
            cell = production_cell(prototype_id, seed)
            if len(chosen[cell]) < 2:
                chosen[cell].append(seed)
            seed += 1
            if seed - seed_start > 200_000:
                raise AdjudicationError(f"H2-B seed allocation exhausted: {prototype_id}")
        for variant in VARIANT_IDS:
            for density in DENSITY_LEVELS:
                for replicate, production_seed in enumerate(chosen[(variant, density)], 1):
                    rows.append(
                        {
                            "prototype_id": prototype_id,
                            "backbone_variant": variant,
                            "density_level": density,
                            "replicate": replicate,
                            "production_seed": production_seed,
                        }
                    )
    return rows


def linear_quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise AdjudicationError("cannot calculate a quantile from no values")
    return float(np.quantile(np.asarray(values, dtype=float), quantile, method="linear"))


def minmax(value: float, lower: float, upper: float) -> float:
    if upper - lower < 1e-9:
        return 0.5
    return min(1.0, max(0.0, (value - lower) / (upper - lower)))


def median(values: Iterable[float]) -> float | None:
    rows = [float(value) for value in values if math.isfinite(float(value))]
    return float(np.median(rows)) if rows else None


def mean(values: Iterable[float]) -> float | None:
    rows = [float(value) for value in values if math.isfinite(float(value))]
    return float(np.mean(rows)) if rows else None


def bootstrap_median_ci(
    differences: Sequence[float],
    *,
    seed: int = BOOTSTRAP_SEED,
    draws: int = 10_000,
) -> dict[str, Any]:
    values = np.asarray([float(value) for value in differences], dtype=float)
    if values.size == 0:
        return {"n": 0, "paired_median_difference": None, "ci95": [None, None]}
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(draws, values.size), replace=True)
    medians = np.median(samples, axis=1)
    return {
        "n": int(values.size),
        "paired_median_difference": float(np.median(values)),
        "ci95": [float(np.quantile(medians, 0.025)), float(np.quantile(medians, 0.975))],
        "bootstrap_draws": draws,
        "bootstrap_seed": seed,
    }


def prototype_label(prototype_id: str) -> str:
    return {
        "proto_sw_1_1": "SW1-1",
        "proto_sw_1_3": "SW1-3",
        "proto_sw_2_3": "SW2-3",
        "proto_sw_3_1": "SW3-1",
        "proto_sw_3_2": "SW3-2",
    }[prototype_id]
