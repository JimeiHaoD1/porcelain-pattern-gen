#!/usr/bin/env python3
"""Validated stage-2.5 flower/branch morphology semantics.

This module deliberately sits beside StrictP0 rather than inside it. StrictP0
remains the geometry-only source of truth; this contract states how a branch
system should *read* before stage 3 is allowed to select slots or make a plan.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


CONTRACT_SCHEMA = "dynamic_branch_morphology_contract_v1"
PROFILE_SCHEMA = "dynamic_branch_morphology_profile_v1"
PROFILE_POLICY_ID = "flower_branch_relation_plus_instance_priors_v1"
STAGE2_ANALYSIS_SCHEMA = "dynamic_branch_prototype_analysis_v1"
REVIEW_STATES = (
    "morphology_pending_review",
    "morphology_approved",
    "morphology_needs_revision",
    "morphology_rejected",
)


class MorphologyContractError(ValueError):
    """Raised when morphology semantics are incomplete or inconsistent."""

    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MorphologyContractError(path, "must be an object")
    return value


def _sequence(value: object, path: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise MorphologyContractError(path, "must be an array")
    return value


def _required(mapping: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise MorphologyContractError(f"{path}.{key}", "missing required field")
    return mapping[key]


def _nonempty_string(value: object, path: str) -> str:
    text = str(value).strip()
    if not text:
        raise MorphologyContractError(path, "must be a non-empty string")
    return text


def _string_list(value: object, path: str, *, allow_empty: bool = False) -> list[str]:
    rows = _sequence(value, path)
    result = [
        _nonempty_string(row, f"{path}[{index}]")
        for index, row in enumerate(rows)
    ]
    if not allow_empty and not result:
        raise MorphologyContractError(path, "must not be empty")
    if len(set(result)) != len(result):
        raise MorphologyContractError(path, "must not contain duplicates")
    return result


def _nonnegative_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MorphologyContractError(path, "must be a non-negative integer")
    return value


def load_morphology_contract(
    source: Path | Mapping[str, Any],
    *,
    expected_prototype_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Load and strictly validate the curated morphology contract."""

    if isinstance(source, Path):
        try:
            raw: object = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MorphologyContractError(str(source), f"cannot read JSON: {exc}") from exc
    else:
        raw = copy.deepcopy(source)
    root = _mapping(raw, "contract")
    if root.get("schema") != CONTRACT_SCHEMA:
        raise MorphologyContractError("contract.schema", "schema mismatch")
    _nonempty_string(_required(root, "contract_id", "contract"), "contract.contract_id")

    axes = _mapping(
        _required(root, "classification_axes", "contract"),
        "contract.classification_axes",
    )
    pattern_axis = _mapping(
        _required(axes, "pattern_skeleton_class", "contract.classification_axes"),
        "contract.classification_axes.pattern_skeleton_class",
    )
    if pattern_axis.get("consumed_by_stage_3_v1") is not False:
        raise MorphologyContractError(
            "contract.classification_axes.pattern_skeleton_class.consumed_by_stage_3_v1",
            "must remain false in stage 2.5",
        )
    professional_values = _string_list(
        _required(
            pattern_axis,
            "professional_allowed_values",
            "contract.classification_axes.pattern_skeleton_class",
        ),
        "contract.classification_axes.pattern_skeleton_class.professional_allowed_values",
    )

    relation_axis = _mapping(
        _required(axes, "flower_branch_relation", "contract.classification_axes"),
        "contract.classification_axes.flower_branch_relation",
    )
    if relation_axis.get("consumed_by_stage_3_v1") is not True:
        raise MorphologyContractError(
            "contract.classification_axes.flower_branch_relation.consumed_by_stage_3_v1",
            "must be true",
        )
    allowed_family_ids = _string_list(
        _required(
            relation_axis,
            "allowed_family_ids",
            "contract.classification_axes.flower_branch_relation",
        ),
        "contract.classification_axes.flower_branch_relation.allowed_family_ids",
    )

    policies = _mapping(_required(root, "policies", "contract"), "contract.policies")
    required_policy_values = {
        "strict_p0_remains_geometry_only": True,
        "category_rules_are_not_prototype_id_topology": True,
        "source_branch_geometry_consumed": False,
        "source_counts_are_evidence_priors_not_generation_targets": True,
        "legacy_unit_type_consumed": False,
        "candidate_slots_present": False,
        "dynamic_branch_plan_present": False,
        "curve_geometry_present": False,
        "visual_review_required": True,
    }
    for key, expected in required_policy_values.items():
        if policies.get(key) is not expected:
            raise MorphologyContractError(
                f"contract.policies.{key}",
                f"must be {str(expected).lower()}",
            )

    families = _mapping(_required(root, "families", "contract"), "contract.families")
    if set(families) != set(allowed_family_ids):
        raise MorphologyContractError(
            "contract.families",
            "family keys must exactly match flower_branch_relation.allowed_family_ids",
        )
    for family_id in allowed_family_ids:
        family_path = f"contract.families.{family_id}"
        family = _mapping(families[family_id], family_path)
        for key in ("label_zh", "label_en", "flower_binding", "visual_guide_mode"):
            _nonempty_string(_required(family, key, family_path), f"{family_path}.{key}")
        for key in (
            "required_relationships",
            "preferred_attachment_contexts",
            "growth_direction_policy",
            "forbidden_patterns",
        ):
            _string_list(_required(family, key, family_path), f"{family_path}.{key}")
        role_policy = _mapping(
            _required(family, "role_policy", family_path),
            f"{family_path}.role_policy",
        )
        if not role_policy:
            raise MorphologyContractError(
                f"{family_path}.role_policy",
                "must contain at least one role rule",
            )
        for role_key, roles in role_policy.items():
            _string_list(
                roles,
                f"{family_path}.role_policy.{role_key}",
                allow_empty=False,
            )

    instances = _mapping(_required(root, "instances", "contract"), "contract.instances")
    instance_ids = list(instances)
    if expected_prototype_ids is not None and instance_ids != list(expected_prototype_ids):
        raise MorphologyContractError(
            "contract.instances",
            "prototype ids or order do not match the implementation contract",
        )
    for prototype_id, raw_instance in instances.items():
        instance_path = f"contract.instances.{prototype_id}"
        instance = _mapping(raw_instance, instance_path)
        if "unit_type" in instance:
            raise MorphologyContractError(
                f"{instance_path}.unit_type",
                "legacy unit_type is not a morphology input",
            )
        family_id = _nonempty_string(
            _required(instance, "family_id", instance_path),
            f"{instance_path}.family_id",
        )
        if family_id not in families:
            raise MorphologyContractError(
                f"{instance_path}.family_id",
                "unknown family id",
            )
        skeleton = _mapping(
            _required(instance, "pattern_skeleton_class", instance_path),
            f"{instance_path}.pattern_skeleton_class",
        )
        _nonempty_string(
            _required(skeleton, "legacy_value", f"{instance_path}.pattern_skeleton_class"),
            f"{instance_path}.pattern_skeleton_class.legacy_value",
        )
        professional_value = _nonempty_string(
            _required(
                skeleton,
                "professional_value",
                f"{instance_path}.pattern_skeleton_class",
            ),
            f"{instance_path}.pattern_skeleton_class.professional_value",
        )
        if professional_value not in professional_values:
            raise MorphologyContractError(
                f"{instance_path}.pattern_skeleton_class.professional_value",
                "unknown professional class",
            )

        style = _mapping(
            _required(instance, "instance_style", instance_path),
            f"{instance_path}.instance_style",
        )
        for key in (
            "density_class",
            "primary_sweep_class",
            "side_rhythm",
            "flower_relation_emphasis",
            "description_zh",
        ):
            _nonempty_string(
                _required(style, key, f"{instance_path}.instance_style"),
                f"{instance_path}.instance_style.{key}",
            )

        priors = _mapping(
            _required(instance, "evidence_priors", instance_path),
            f"{instance_path}.evidence_priors",
        )
        for key in ("flower_anchor_count", "branch_guide_count", "primary_branch_count"):
            _nonnegative_int(
                _required(priors, key, f"{instance_path}.evidence_priors"),
                f"{instance_path}.evidence_priors.{key}",
            )
        for group_key in ("branch_side_counts", "structural_role_counts"):
            group = _mapping(
                _required(priors, group_key, f"{instance_path}.evidence_priors"),
                f"{instance_path}.evidence_priors.{group_key}",
            )
            for key, value in group.items():
                _nonnegative_int(
                    value,
                    f"{instance_path}.evidence_priors.{group_key}.{key}",
                )

        sources = _mapping(
            _required(instance, "evidence_sources", instance_path),
            f"{instance_path}.evidence_sources",
        )
        for key in ("source_image", "legacy_annotation", "legacy_node_rule"):
            _nonempty_string(
                _required(sources, key, f"{instance_path}.evidence_sources"),
                f"{instance_path}.evidence_sources.{key}",
            )
        if sources["legacy_node_rule"] != family_id:
            raise MorphologyContractError(
                f"{instance_path}.evidence_sources.legacy_node_rule",
                "must agree with family_id",
            )

    return copy.deepcopy(dict(root))


@dataclass(frozen=True)
class BranchMorphologySpec:
    """One prototype's reviewed semantic bridge from stage 2 to stage 3."""

    prototype_id: str
    contract_id: str
    source_analysis_digest: str
    classification: Mapping[str, Any]
    family_rule: Mapping[str, Any]
    instance_priors: Mapping[str, Any]
    evidence: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        core: dict[str, Any] = {
            "schema": PROFILE_SCHEMA,
            "policy_id": PROFILE_POLICY_ID,
            "prototype_id": self.prototype_id,
            "morphology_contract_id": self.contract_id,
            "source_stage2_analysis_digest": self.source_analysis_digest,
            "classification": copy.deepcopy(dict(self.classification)),
            "family_rule": copy.deepcopy(dict(self.family_rule)),
            "instance_priors": copy.deepcopy(dict(self.instance_priors)),
            "evidence": copy.deepcopy(dict(self.evidence)),
            "generation_boundary": {
                "strict_p0_modified": False,
                "source_branch_geometry_copied": False,
                "evidence_counts_are_generation_targets": False,
                "candidate_slots_present": False,
                "dynamic_branch_plan_present": False,
                "curve_geometry_present": False,
                "visual_guides_are_non_selecting_semantic_annotations": True,
            },
            "review": {
                "status": "morphology_pending_review",
                "allowed_states": list(REVIEW_STATES),
                "visual_gate_required": True,
                "criteria": [
                    "family_assignment_matches_source",
                    "flower_branch_binding_matches_source",
                    "required_relationships_match_source",
                    "instance_density_and_rhythm_match_source",
                    "forbidden_patterns_are_correct",
                    "no_old_branch_geometry_is_being_copied",
                ],
            },
        }
        core["morphology_digest"] = _canonical_digest(core)
        return core

    @property
    def digest(self) -> str:
        return self.as_dict()["morphology_digest"]


def materialize_branch_morphology_spec(
    analysis: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> BranchMorphologySpec:
    """Bind one validated family/instance rule to one stage-2 analysis."""

    root = load_morphology_contract(contract)
    if analysis.get("schema") != STAGE2_ANALYSIS_SCHEMA:
        raise MorphologyContractError("analysis.schema", "stage-2 schema mismatch")
    prototype_id = _nonempty_string(
        _required(analysis, "prototype_id", "analysis"),
        "analysis.prototype_id",
    )
    analysis_digest = _nonempty_string(
        _required(analysis, "analysis_digest", "analysis"),
        "analysis.analysis_digest",
    )
    instances = _mapping(root["instances"], "contract.instances")
    if prototype_id not in instances:
        raise MorphologyContractError(
            "analysis.prototype_id",
            "prototype has no morphology assignment",
        )
    instance = _mapping(instances[prototype_id], f"contract.instances.{prototype_id}")
    family_id = str(instance["family_id"])
    family = _mapping(root["families"][family_id], f"contract.families.{family_id}")
    flower_count = len(_sequence(_required(analysis, "flowers", "analysis"), "analysis.flowers"))
    evidence_priors = _mapping(
        instance["evidence_priors"],
        f"contract.instances.{prototype_id}.evidence_priors",
    )
    if evidence_priors["flower_anchor_count"] != flower_count:
        raise MorphologyContractError(
            f"contract.instances.{prototype_id}.evidence_priors.flower_anchor_count",
            "does not match StrictP0-derived stage-2 flower count",
        )

    skeleton = _mapping(
        instance["pattern_skeleton_class"],
        f"contract.instances.{prototype_id}.pattern_skeleton_class",
    )
    classification = {
        "flower_branch_relation": {
            "family_id": family_id,
            "label_zh": family["label_zh"],
            "label_en": family["label_en"],
            "generation_control": True,
        },
        "pattern_skeleton_class": {
            "legacy_value": skeleton["legacy_value"],
            "professional_value": skeleton["professional_value"],
            "generation_control_in_stage_3_v1": False,
        },
    }
    family_rule = {
        key: copy.deepcopy(family[key])
        for key in (
            "flower_binding",
            "visual_guide_mode",
            "required_relationships",
            "role_policy",
            "preferred_attachment_contexts",
            "growth_direction_policy",
            "forbidden_patterns",
        )
    }
    instance_priors = {
        **copy.deepcopy(dict(instance["instance_style"])),
        "source_observation_counts": copy.deepcopy(dict(evidence_priors)),
        "count_usage": "evidence_prior_not_fixed_generation_target",
    }
    evidence = {
        "sources": copy.deepcopy(dict(instance["evidence_sources"])),
        "legacy_node_rule_used_only_for_family_provenance": True,
        "legacy_unit_type_consumed": False,
        "legacy_branch_geometry_consumed": False,
    }
    return BranchMorphologySpec(
        prototype_id=prototype_id,
        contract_id=str(root["contract_id"]),
        source_analysis_digest=analysis_digest,
        classification=classification,
        family_rule=family_rule,
        instance_priors=instance_priors,
        evidence=evidence,
    )

