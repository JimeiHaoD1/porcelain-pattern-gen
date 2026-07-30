from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_ROOT = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
DIAGNOSTICS_ROOT = DYNAMIC_ROOT / "diagnostics"
for path in (str(DYNAMIC_ROOT), str(DIAGNOSTICS_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from branch_unit_grammar_v1 import generate_role_aware_hierarchy  # noqa: E402
from hierarchy_generate_R5_visual import hierarchy_intersection_report  # noqa: E402
from run_stage3b_l1_flow import _load_inputs  # noqa: E402


def test_r5_selected_hierarchy_has_no_intersections() -> None:
    layout = json.loads(
        (
            REPO_ROOT
            / "artifacts"
            / "runs"
            / "dynamic_branch_R4_v2"
            / "selected_layout.json"
        ).read_text(encoding="utf-8")
    )
    inputs, _, _, _ = _load_inputs()
    analysis = inputs["proto_sw_3_1"]["analysis"]
    hierarchy = generate_role_aware_hierarchy(layout, analysis)
    assert not any(
        hierarchy_intersection_report(analysis, hierarchy).values()
    )
