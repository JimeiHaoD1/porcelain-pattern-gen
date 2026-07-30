from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_R2C_v2"
SVG = RUN / "editable_full_branchunit.svg"
HANDOFF = RUN / "editor_handoff.json"
SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
FROZEN_R2B_DIGEST = (
    "880a0a03c3cf4321ed750eadb15d02d07e50f98442f55b61ed24ca7e71541688"
)


def test_R2C_editable_svg_is_complete_layered_and_region_aware() -> None:
    root = ET.parse(SVG).getroot()
    groups = {
        group.attrib["id"]: group
        for group in root.findall(f"{{{SVG_NS}}}g")
    }
    assert set(groups) == {
        "canvas_and_seams",
        "role_region_planning",
        "backbone_layer",
        "flowers_layer",
        "global_l1_context",
        "editable_target_group",
        "unselected_region_candidates",
        "editor_annotations",
    }
    assert "display:none" not in groups["role_region_planning"].attrib.get(
        "style",
        "",
    )
    assert groups["role_region_planning"].attrib[
        f"{{{INKSCAPE_NS}}}label"
    ] == "02 Role region planning (keep)"
    assert len(
        groups["role_region_planning"].findall(f"{{{SVG_NS}}}path")
    ) >= 8
    assert len(groups["flowers_layer"].findall(f"{{{SVG_NS}}}ellipse")) == 2
    assert groups["backbone_layer"].find(
        f"{{{SVG_NS}}}path[@id='backbone']"
    ) is not None
    assert len(
        groups["global_l1_context"].findall(f"{{{SVG_NS}}}path")
    ) == 7
    assert not root.findall(f".//{{{SVG_NS}}}image")


def test_R2C_editor_targets_are_semantic_cubic_paths() -> None:
    root = ET.parse(SVG).getroot()
    support = root.find(
        f".//{{{SVG_NS}}}path[@id='editable_flower_support_L1']"
    )
    wrap = root.find(
        f".//{{{SVG_NS}}}path[@id='editable_flower_wrap_L1']"
    )
    assert support is not None and wrap is not None
    assert support.attrib["data-role"] == "flower_support"
    assert wrap.attrib["data-role"] == "flower_wrap"
    assert support.attrib["data-source-region-plan-digest"] == FROZEN_R2B_DIGEST
    assert wrap.attrib["data-source-region-plan-digest"] == FROZEN_R2B_DIGEST
    assert support.attrib["d"].startswith("M ")
    assert wrap.attrib["d"].startswith("M ")
    assert support.attrib["d"].count("C ") >= 4
    assert wrap.attrib["d"].count("C ") >= 4
    assert support.attrib["d"] != wrap.attrib["d"]


def test_R2C_editor_handoff_matches_svg_and_frozen_artifacts() -> None:
    handoff = json.loads(HANDOFF.read_text(encoding="utf-8"))
    acceptance = json.loads(
        (RUN / "acceptance_report.json").read_text(encoding="utf-8")
    )
    selected = json.loads(
        (RUN / "selected_pair.json").read_text(encoding="utf-8")
    )
    assert handoff["status"] == "AWAITING_USER_EDIT"
    assert handoff["branch_geometry_is_user_unapproved"] is True
    assert handoff["region_plan_digest"] == FROZEN_R2B_DIGEST
    assert handoff["pair_digest_before_user_edit"] == selected["pair_digest"]
    assert handoff["editor_target_ids"] == [
        "editable_flower_support_L1",
        "editable_flower_wrap_L1",
    ]
    assert handoff["svg_sha256_before_user_edit"] == hashlib.sha256(
        SVG.read_bytes()
    ).hexdigest()
    assert acceptance["stage_status"] == "AWAITING_USER_EDIT"
    assert acceptance["numeric_acceptance_pass"] is True
    assert acceptance["user_visual_approved"] is False
    assert acceptance["editable_svg_handoff_present"] is True
