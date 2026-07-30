from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
sys.path.insert(0, str(DYNAMIC))


def test_R2D_selected_geometry_has_no_intersections() -> None:
    from global_l1_flow import _polyline_crossing_count
    from run_stage3b_l1_flow import _load_inputs

    selected = json.loads(
        (
            REPO_ROOT
            / "artifacts"
            / "runs"
            / "dynamic_branch_R2D_v2"
            / "selected_support.json"
        ).read_text(encoding="utf-8")
    )
    analysis = _load_inputs(
        DYNAMIC / "R1_L1_MOTION_CONTRACT_V1.json"
    )[0]["proto_sw_3_1"]["analysis"]
    backbone = [
        row["point"] for row in analysis["backbone"]["samples"]
    ]
    assert (
        _polyline_crossing_count(
            selected["centerline"],
            selected["centerline"],
        )
        == 0
    )
    assert (
        _polyline_crossing_count(
            selected["centerline"][1:],
            backbone,
        )
        == 0
    )
