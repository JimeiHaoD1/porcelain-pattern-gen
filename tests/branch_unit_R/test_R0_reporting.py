from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT
    / "experiments"
    / "branch_unit"
    / "dynamic"
    / "reporting"
    / "finalize_R0_v2.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("finalize_R0_v2", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_report():
    rows = []
    values = {
        "case_count": 15,
        "missing_case_count": 0,
        "required_metric_missing_count": 0,
        "unresolved_failure_reference_count": 0,
        "baseline_geometry_changed": False,
        "baseline_selection_changed": False,
        "geometry_digest_run1_equals_run2": True,
        "selection_digest_run1_equals_run2": True,
    }
    for name, value in values.items():
        rows.append(
            {
                "metric_name": name,
                "measured_value": value,
                "pass": True,
                "evidence_file": "metrics.json",
            }
        )
    return {"metrics": rows, "reproducibility_pass": True}


def test_R0_acceptance_requires_every_gate() -> None:
    module = _module()
    accepted = module.build_acceptance(
        _source_report(),
        anti_shortcut_pass=True,
        required_artifacts_complete=True,
        frozen_unchanged=True,
    )
    assert accepted["stage_status"] == "PASSED"
    rejected = module.build_acceptance(
        _source_report(),
        anti_shortcut_pass=False,
        required_artifacts_complete=True,
        frozen_unchanged=True,
    )
    assert rejected["stage_status"] == "FAILED_RETRYING"


def test_R0_frozen_hash_manifest_matches_worktree() -> None:
    module = _module()
    actual = {
        path.name: module._sha256(path)
        for path in sorted(module.FROZEN_DIR.iterdir())
        if path.is_file()
    }
    assert actual == module.EXPECTED_HASHES
