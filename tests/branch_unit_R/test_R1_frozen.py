from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
sys.path.insert(0, str(DYNAMIC))


def test_R1_tangent_led_path_rejects_fixed_geometry_prior() -> None:
    from global_l1_flow import _fixed_warp_candidates

    assert (
        _fixed_warp_candidates(
            {},
            {},
            {},
            4101,
            {"mode": "tangent_led_v1"},
        )
        == []
    )


def test_R1_published_outputs_contain_no_fixed_prior_channel() -> None:
    module_path = DYNAMIC / "diagnostics" / "l1_finalize_R1_v2.py"
    spec = importlib.util.spec_from_file_location("l1_finalize_R1_v2", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._fixed_prior_files(module.OUTPUT) == []
