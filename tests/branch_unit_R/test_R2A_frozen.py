from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
sys.path.insert(0, str(DYNAMIC))

EXPECTED_SOURCE_SHA256 = (
    "36dc2aa6be4f404cb44905f01239fb28c3033b2f72834644bb9ca5d587150928"
)
EXPECTED_TOPOLOGY_DIGEST = (
    "195e214afd784983e4d4b236795b22b0058ca2c8fd16121c8c78effc89003a36"
)
PROTOTYPES = {
    "proto_sw_1_1": "SW1",
    "proto_sw_1_3": "SW1",
    "proto_sw_2_3": "SW2",
    "proto_sw_3_1": "SW3",
    "proto_sw_3_2": "SW3",
}


def _independent_topology_issues(
    prototype_id: str,
    slots: list[dict[str, object]],
) -> list[str]:
    family = PROTOTYPES[prototype_id]
    issues: list[str] = []
    roles = Counter(str(row["role"]) for row in slots)
    by_flower: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in slots:
        if row["level"] != "L1":
            issues.append("non_L1_core_role")
        if row["parent"] != "backbone" or row["parent_curve_id"] is not None:
            issues.append("core_role_not_parented_to_backbone")
        if row["region_id"] is not None or row["curve_id"] is not None:
            issues.append("R2A_materialized_region_or_curve")
        by_flower[str(row["service_flower_id"])].append(row)

    if family == "SW1":
        for flower_slots in by_flower.values():
            support = [
                row for row in flower_slots if row["role"] == "flower_support"
            ]
            wrap = [row for row in flower_slots if row["role"] == "flower_wrap"]
            balance = [row for row in flower_slots if row["role"] == "balance"]
            if len(support) != 1:
                issues.append("support_role_slot_missing_or_duplicated")
            if len(wrap) != 1:
                issues.append("wrap_role_slot_missing_or_duplicated")
            if len(balance) != 1:
                issues.append("balance_role_slot_missing_or_duplicated")
            if support and wrap:
                if support[0]["sibling_group_id"] != wrap[0]["sibling_group_id"]:
                    issues.append("support_wrap_not_siblings")
                if support[0]["service_flower_id"] != wrap[0]["service_flower_id"]:
                    issues.append("support_wrap_service_different_flowers")
                if wrap[0]["parent_curve_id"] == support[0]["slot_id"]:
                    issues.append("wrap_is_support_child")
    elif family == "SW2":
        if roles["flower_support"] or roles["flower_wrap"]:
            issues.append("forced_SW1_topology")
        if roles["remote_flower_support"]:
            issues.append("forced_SW3_topology")
    elif family == "SW3":
        for flower_slots in by_flower.values():
            if (
                sum(
                    row["role"] == "remote_flower_support"
                    for row in flower_slots
                )
                != 1
            ):
                issues.append("remote_support_slot_missing_or_duplicated")
        if roles["flower_wrap"]:
            issues.append("forced_wrap_slot")
    else:
        issues.append("unsupported_family")
    return issues


def test_R2A_frozen_source_digest_is_independently_recomputed() -> None:
    from topology_contract_loader import load_frozen_topology_contract

    path = (
        REPO_ROOT
        / "artifacts"
        / "runs"
        / "dynamic_branch_R_init_v2"
        / "prototype_role_table.json"
    )
    raw = path.read_bytes()
    source = json.loads(raw.decode("utf-8"))
    digest_source = {
        "families": source["families"],
        "global_hard_rules": source["global_hard_rules"],
    }
    independent_digest = hashlib.sha256(
        json.dumps(
            digest_source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    loaded = load_frozen_topology_contract()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_SOURCE_SHA256
    assert independent_digest == EXPECTED_TOPOLOGY_DIGEST
    assert loaded["topology_contract_digest"] == EXPECTED_TOPOLOGY_DIGEST


def test_R2A_all_prototypes_materialize_only_supported_topologies() -> None:
    from topology_contract_loader import materialize_prototype_topology

    for prototype_id in PROTOTYPES:
        topology = materialize_prototype_topology(
            prototype_id,
            ["flower_1", "flower_2"],
        )
        assert topology["stage_scope"] == {
            "topology_materialized": True,
            "regions_materialized": False,
            "curves_materialized": False,
        }
        assert (
            topology["topology_contract_digest"] == EXPECTED_TOPOLOGY_DIGEST
        )
        assert _independent_topology_issues(
            prototype_id,
            topology["slots"],
        ) == []


def test_R2A_branch_grammar_does_not_replace_core_wrap_with_L2() -> None:
    from branch_unit_grammar_v1 import _candidate_strata, _child_semantic_role

    contract = {
        "candidate_coverage": {
            "terminal_support_strata": ["open_c"],
            "terminal_support_wrap_strata": ["guided_wrap"],
        },
        "grammar": {
            "TerminalSupport-C": {},
            "TerminalSupport-Wrap": {},
        },
    }
    strata = _candidate_strata(
        {
            "role": "terminal_flower_support",
            "flower_wrap_channel": {"legacy": True},
        },
        contract,
    )
    assert strata == [("TerminalSupport-C", "open_c", False)]
    assert _child_semantic_role("flower_support", None) == "flower_support_echo"
    assert _child_semantic_role("flower_support", None) != "flower_wrap"
