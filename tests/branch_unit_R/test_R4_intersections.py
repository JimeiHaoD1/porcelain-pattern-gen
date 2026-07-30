from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_ROOT = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
DIAGNOSTICS_ROOT = DYNAMIC_ROOT / "diagnostics"
for path in (str(DYNAMIC_ROOT), str(DIAGNOSTICS_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from global_generate_R4_visual import _intersection_report  # noqa: E402
from global_l1_flow import generate_sw3_global_unit_layout  # noqa: E402
from role_region_plan import build_sw3_global_unit_region_plan  # noqa: E402
from run_stage3b_l1_flow import _load_inputs  # noqa: E402
from topology_contract_loader import materialize_prototype_topology  # noqa: E402


def test_r4_global_unit_has_no_intersections() -> None:
    inputs, _, _, _ = _load_inputs()
    analysis = inputs["proto_sw_3_1"]["analysis"]
    topology = materialize_prototype_topology(
        "proto_sw_3_1",
        [row["flower_id"] for row in analysis["flowers"]],
    )
    plan = build_sw3_global_unit_region_plan(
        analysis,
        topology,
        "flower_1",
    )
    layout = generate_sw3_global_unit_layout(analysis, plan)
    assert not any(_intersection_report(analysis, layout).values())
