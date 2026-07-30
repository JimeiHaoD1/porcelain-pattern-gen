from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_ROOT = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
DIAGNOSTICS_ROOT = DYNAMIC_ROOT / "diagnostics"
for path in (str(DYNAMIC_ROOT), str(DIAGNOSTICS_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from run_stage3b_l1_flow import _load_inputs  # noqa: E402
from stage5_global_unit_selection import (  # noqa: E402
    R6_layout_intersections,
    generate_and_select_R6_layout,
)


def test_r6_all_selected_layouts_have_no_intersections() -> None:
    inputs, _, _, _ = _load_inputs()
    prototypes = [
        ("proto_sw_3_1", "SW3"),
        ("proto_sw_1_1", "SW1"),
        ("proto_sw_3_2", "SW3"),
        ("proto_sw_2_3", "SW2"),
        ("proto_sw_1_3", "SW1"),
    ]
    for prototype_id, family_id in prototypes:
        analysis = inputs[prototype_id]["analysis"]
        for seed in (4101, 4102, 4103):
            selection = generate_and_select_R6_layout(
                analysis,
                family_id,
                seed,
            )
            assert not any(
                R6_layout_intersections(
                    analysis,
                    selection["selected_layout"],
                ).values()
            )
