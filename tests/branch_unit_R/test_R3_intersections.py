from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_ROOT = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
DIAGNOSTICS_ROOT = DYNAMIC_ROOT / "diagnostics"
for path in (str(DYNAMIC_ROOT), str(DIAGNOSTICS_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from global_l1_flow import (  # noqa: E402
    _polyline_crossing_count,
    generate_sw1_region_l1_group,
    generate_sw3_region_l1_group,
)
from role_region_plan import (  # noqa: E402
    build_sw1_role_region_plan,
    build_sw3_group_region_plan,
)
from run_stage3b_l1_flow import _load_inputs  # noqa: E402
from topology_contract_loader import (  # noqa: E402
    materialize_prototype_topology,
)


def _assert_no_intersections(
    analysis: Mapping[str, Any],
    group: Mapping[str, Any],
) -> None:
    curves = list(group["selected_curves"])
    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    for curve in curves:
        assert (
            _polyline_crossing_count(
                curve["centerline"],
                curve["centerline"],
            )
            == 0
        )
        assert (
            _polyline_crossing_count(
                curve["centerline"][1:],
                backbone,
            )
            == 0
        )
    for left in range(len(curves)):
        for right in range(left + 1, len(curves)):
            assert (
                _polyline_crossing_count(
                    curves[left]["centerline"],
                    curves[right]["centerline"],
                )
                == 0
            )


def test_r3_selected_groups_have_no_intersections() -> None:
    inputs, _, _, _ = _load_inputs()
    cases = (
        (
            "proto_sw_1_1",
            build_sw1_role_region_plan,
            generate_sw1_region_l1_group,
        ),
        (
            "proto_sw_3_1",
            build_sw3_group_region_plan,
            generate_sw3_region_l1_group,
        ),
    )
    for prototype_id, planner, generator in cases:
        analysis = inputs[prototype_id]["analysis"]
        topology = materialize_prototype_topology(
            prototype_id,
            [row["flower_id"] for row in analysis["flowers"]],
        )
        plan = planner(analysis, topology, "flower_1")
        group = generator(analysis, plan)
        _assert_no_intersections(analysis, group)
