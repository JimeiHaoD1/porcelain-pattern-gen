"""Verified loader for the frozen BranchUnit-R prototype topology.

R2A owns role topology only.  It deliberately materializes L1 role slots
without constructing regions or curves; later R stages consume those slots.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


ROLE_TABLE_SHA256 = "36dc2aa6be4f404cb44905f01239fb28c3033b2f72834644bb9ca5d587150928"
TOPOLOGY_CONTRACT_DIGEST = (
    "195e214afd784983e4d4b236795b22b0058ca2c8fd16121c8c78effc89003a36"
)
ROLE_TABLE_SCHEMA = "dynamic_branch_R_frozen_prototype_role_table_v2"
PROTOTYPE_TO_FAMILY = {
    "proto_sw_1_1": "SW1",
    "proto_sw_1_3": "SW1",
    "proto_sw_2_3": "SW2",
    "proto_sw_3_1": "SW3",
    "proto_sw_3_2": "SW3",
}


class TopologyContractError(RuntimeError):
    """The committed frozen topology table is missing or has drifted."""


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _role_table_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "artifacts"
        / "runs"
        / "dynamic_branch_R_init_v2"
        / "prototype_role_table.json"
    )


def load_frozen_topology_contract() -> dict[str, Any]:
    """Load the committed interpretation table after byte and semantic checks."""

    path = _role_table_path()
    payload = path.read_bytes()
    byte_digest = hashlib.sha256(payload).hexdigest()
    if byte_digest != ROLE_TABLE_SHA256:
        raise TopologyContractError(
            f"frozen prototype role table drifted: {byte_digest}"
        )
    table = json.loads(payload.decode("utf-8"))
    if table.get("schema") != ROLE_TABLE_SCHEMA:
        raise TopologyContractError("frozen prototype role table schema mismatch")
    topology_source = {
        "families": table.get("families"),
        "global_hard_rules": table.get("global_hard_rules"),
    }
    digest = canonical_digest(topology_source)
    if digest != TOPOLOGY_CONTRACT_DIGEST:
        raise TopologyContractError(
            f"frozen topology canonical digest drifted: {digest}"
        )
    return {
        "schema": ROLE_TABLE_SCHEMA,
        "source_path": path.relative_to(path.parents[3]).as_posix(),
        "source_sha256": byte_digest,
        "topology_contract_digest": digest,
        "families": table["families"],
        "global_hard_rules": table["global_hard_rules"],
    }


def _flower_ids(values: Sequence[object]) -> list[str]:
    result = [str(value) for value in values]
    if len(result) != len(set(result)):
        raise TopologyContractError("service flower ids must be unique")
    return result


def materialize_prototype_topology(
    prototype_id: str,
    service_flower_ids: Sequence[object],
) -> dict[str, Any]:
    """Create frozen role slots without constructing any region or curve."""

    if prototype_id not in PROTOTYPE_TO_FAMILY:
        raise TopologyContractError(f"unsupported prototype id: {prototype_id}")
    contract = load_frozen_topology_contract()
    family = PROTOTYPE_TO_FAMILY[prototype_id]
    family_contract: Mapping[str, Any] = contract["families"][family]
    if prototype_id not in family_contract["prototype_ids"]:
        raise TopologyContractError(
            f"{prototype_id} is absent from its frozen {family} contract"
        )

    flower_ids = _flower_ids(service_flower_ids)
    slots: list[dict[str, Any]] = []
    for flower_index, flower_id in enumerate(flower_ids, start=1):
        for role_spec in family_contract.get("required_l1_roles", []):
            role = str(role_spec["role"])
            slots.append(
                {
                    "slot_id": f"{role}__flower_{flower_index}",
                    "role": role,
                    "region_role": str(role_spec["region_role"]),
                    "level": str(role_spec["level"]),
                    "parent": str(role_spec["parent"]),
                    "parent_curve_id": role_spec["parent_curve_id"],
                    "service_flower_id": flower_id,
                    "sibling_group_id": f"{prototype_id}__flower_{flower_index}",
                    "region_id": None,
                    "curve_id": None,
                    "materialization_state": "topology_only",
                }
            )

    return {
        "schema": "dynamic_branch_R_prototype_topology_v2",
        "prototype_id": prototype_id,
        "family": family,
        "topology_contract_digest": contract["topology_contract_digest"],
        "source_sha256": contract["source_sha256"],
        "required_region_role": family_contract.get("required_region_role"),
        "hard_relations": dict(family_contract["hard_relations"]),
        "slots": slots,
        "stage_scope": {
            "topology_materialized": True,
            "regions_materialized": False,
            "curves_materialized": False,
        },
    }
