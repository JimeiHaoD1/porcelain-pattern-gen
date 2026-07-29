from __future__ import annotations

import json
import hashlib
import sys
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import fixed_visual_prior as prior_module  # noqa: E402


BASELINE = ROOT / "artifacts" / "frozen_baselines" / "fixed_depth_7_12_2_v23"
CONTRACT = DYNAMIC_DIR / "FIXED_VISUAL_PRIOR_CONTRACT_V1.json"
FORMAL_OUTPUT = (
    ROOT / "artifacts" / "runs" / "dynamic_branch_stage3a_fixed_visual_prior_v1"
)


@lru_cache(maxsize=1)
def _prior() -> dict:
    return prior_module.build_fixed_visual_prior(BASELINE, CONTRACT)


def test_stage3a_extracts_strict_role_conditioned_prior() -> None:
    prior = _prior()
    prior_module.validate_fixed_visual_prior(prior)
    assert prior["schema"] == prior_module.SCHEMA
    assert prior["paired_baseline_scope"] == {
        "baseline_id": "fixed_depth_7_12_2_v23",
        "prototype_id": "proto_sw_1_3",
        "seeds": [4101, 4102, 4103],
        "topology": {"L1": 7, "L2": 12, "L3": 2},
        "cross_prototype_fixed_baseline_claimed": False,
        "final_pattern_aesthetics_claimed_by_source_gate": False,
    }
    assert set(prior["statistics"]["role_conditioned"]) == {
        "primary_free",
        "primary_balance",
        "primary_flower",
        "secondary_lateral",
        "secondary_frontier",
        "secondary_flower_wrap",
        "tertiary_lateral",
    }
    assert set(prior["paired_primary_templates"]) == {"4101", "4102", "4103"}
    assert all(
        len(rows) == 7 for rows in prior["paired_primary_templates"].values()
    )


def test_stage3a_distributions_are_data_bearing_not_fixed_defaults() -> None:
    prior = _prior()
    primary = prior["statistics"]["primary_geometry"]["actual_length_repeat"]
    descendant = prior["statistics"]["descendant_geometry"][
        "child_to_parent_actual_ratio"
    ]
    root_gap = prior["statistics"]["primary_root_rhythm"]["consecutive_mount_gap"]
    assert primary["count"] == 21
    assert descendant["count"] == 42
    assert root_gap["count"] == 18
    assert primary["min"] < primary["median"] < primary["max"]
    assert descendant["min"] < descendant["median"] < descendant["max"]
    assert root_gap["min"] < root_gap["median"] < root_gap["max"]
    assert prior["generation_use"]["independent_uniform_sampling_allowed"] is False


def test_stage3a_prior_is_deterministic() -> None:
    first = _prior()
    second = prior_module.build_fixed_visual_prior(BASELINE, CONTRACT)
    assert first["prior_digest"] == second["prior_digest"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_stage3a_formal_package_is_complete() -> None:
    manifest = json.loads(
        (FORMAL_OUTPUT / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema"] == "dynamic_branch_stage3a_manifest_v1"
    assert manifest["status"] == "fixed_visual_prior_complete"
    assert manifest["policies"] == {
        "experimental_variants_created": False,
        "silent_fallback_used": False,
        "automatic_repair_used": False,
        "cross_prototype_fixed_baseline_claimed": False,
    }
    for name, row in manifest["files"].items():
        path = FORMAL_OUTPUT / name
        assert path.is_file()
        assert path.stat().st_size == row["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
