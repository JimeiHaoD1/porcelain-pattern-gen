#!/usr/bin/env python3
"""Export the current full SW1 BranchUnit as a layered editable SVG."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.sax.saxutils import escape


REPO_ROOT = Path(__file__).resolve().parents[4]
DYNAMIC = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
if str(DYNAMIC) not in sys.path:
    sys.path.insert(0, str(DYNAMIC))

from global_l1_flow import generate_global_l1_flow_plan
from role_region_plan import validate_role_region_plan
from run_stage3b_l1_flow import _load_inputs


OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_R2C_v2"
SVG_PATH = OUTPUT / "editable_full_branchunit.svg"
HANDOFF_PATH = OUTPUT / "editor_handoff.json"
FROZEN_R2B_DIGEST = (
    "880a0a03c3cf4321ed750eadb15d02d07e50f98442f55b61ed24ca7e71541688"
)
FROZEN_HASHES = {
    "goal": "071547dc89259b17e285b14c5c06b5ca9ec73b2fb82ffd79904cff4932d8421e",
    "acceptance": "b815fccf1e47ae8cb7575498a0b89fb311e99d573d0dbb280ba62a4735d2e77a",
    "roles": "70c4fb6e5c12e34424a3f477d5d5a3a23f0583617743f961ba370f99a8a85872",
}
SCALE = 1000.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _number(value: object) -> str:
    return f"{float(value) * SCALE:.3f}".rstrip("0").rstrip(".")


def _point(value: Sequence[object]) -> str:
    return f"{_number(value[0])},{_number(value[1])}"


def _polyline_path(points: Sequence[Sequence[object]], close: bool = False) -> str:
    if not points:
        raise RuntimeError("SVG polyline path cannot be empty")
    commands = [f"M {_point(points[0])}"]
    commands.extend(f"L {_point(point)}" for point in points[1:])
    if close:
        commands.append("Z")
    return " ".join(commands)


def _cubic_path(segments: Sequence[Mapping[str, Sequence[object]]]) -> str:
    if not segments:
        raise RuntimeError("SVG cubic path cannot be empty")
    commands = [f"M {_point(segments[0]['p0'])}"]
    commands.extend(
        (
            f"C {_point(segment['p1'])} {_point(segment['p2'])} "
            f"{_point(segment['p3'])}"
        )
        for segment in segments
    )
    return " ".join(commands)


def _path(
    *,
    element_id: str,
    d: str,
    css_class: str,
    attributes: Mapping[str, object] | None = None,
) -> str:
    extras = "".join(
        f' data-{escape(str(key))}="{escape(str(value))}"'
        for key, value in (attributes or {}).items()
    )
    return (
        f'<path id="{escape(element_id)}" class="{escape(css_class)}" '
        f'd="{escape(d)}"{extras}/>'
    )


def _layer(
    layer_id: str,
    label: str,
    contents: Sequence[str],
    *,
    style: str | None = None,
) -> str:
    style_attribute = (
        f' style="{escape(style)}"' if style is not None else ""
    )
    return (
        f'<g id="{escape(layer_id)}" inkscape:groupmode="layer" '
        f'inkscape:label="{escape(label)}"{style_attribute}>'
        + "".join(contents)
        + "</g>"
    )


def _build_svg(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    region_plan = plan["role_region_plan"]
    pair = plan["region_driven_sw1_pair"]
    if region_plan is None or pair is None:
        raise RuntimeError("editable SVG requires the integrated R2B/R2C data")
    validate_role_region_plan(region_plan)
    if region_plan["region_plan_digest"] != FROZEN_R2B_DIGEST:
        raise RuntimeError("editable SVG region digest drifted")
    if pair["source_region_plan_digest"] != FROZEN_R2B_DIGEST:
        raise RuntimeError("editable SVG pair does not consume frozen regions")

    bounds = [float(value) for value in region_plan["unit_bounds"]]
    width = (bounds[2] - bounds[0]) * SCALE
    height = (bounds[3] - bounds[1]) * SCALE
    metadata = {
        "schema": "dynamic_branch_R2C_editable_full_svg_v2",
        "prototype_id": "proto_sw_1_1",
        "seed": 4101,
        "canvas_bounds": bounds,
        "global_plan_digest": plan["plan_digest"],
        "region_plan_digest": region_plan["region_plan_digest"],
        "pair_digest": pair["pair_digest"],
        "coordinate_scale": SCALE,
        "editor_target_ids": [
            "editable_flower_support_L1",
            "editable_flower_wrap_L1",
        ],
        "region_layer_id": "role_region_planning",
        "branch_geometry_is_user_unapproved": True,
    }

    styles = """
      .canvas { fill:#fffdf9; }
      .unit-boundary { fill:none; stroke:#98a2b3; stroke-width:1.5; stroke-dasharray:10 8; vector-effect:non-scaling-stroke; }
      .seam { fill:none; stroke:#667085; stroke-width:2; stroke-dasharray:12 8; vector-effect:non-scaling-stroke; }
      .backbone { fill:none; stroke:#263750; stroke-width:7; stroke-linecap:round; stroke-linejoin:round; vector-effect:non-scaling-stroke; }
      .flower { fill:#fff8fc; stroke:#9747ff; stroke-width:4; vector-effect:non-scaling-stroke; }
      .context-l1 { fill:none; stroke:#667085; stroke-width:3; stroke-linecap:round; stroke-linejoin:round; opacity:.58; vector-effect:non-scaling-stroke; }
      .target-support { fill:none; stroke:#07815f; stroke-width:7; stroke-linecap:round; stroke-linejoin:round; vector-effect:non-scaling-stroke; }
      .target-wrap { fill:none; stroke:#cb6e05; stroke-width:7; stroke-linecap:round; stroke-linejoin:round; vector-effect:non-scaling-stroke; }
      .candidate-support { fill:none; stroke:#07815f; stroke-width:2.5; stroke-dasharray:7 6; opacity:.55; vector-effect:non-scaling-stroke; }
      .candidate-wrap { fill:none; stroke:#cb6e05; stroke-width:2.5; stroke-dasharray:7 6; opacity:.55; vector-effect:non-scaling-stroke; }
      .region-support { fill:#1b9e77; fill-opacity:.14; stroke:#1b9e77; stroke-width:2; vector-effect:non-scaling-stroke; }
      .region-wrap { fill:#d9871b; fill-opacity:.14; stroke:#d9871b; stroke-width:2; vector-effect:non-scaling-stroke; }
      .region-balance { fill:#377eb8; fill-opacity:.12; stroke:#377eb8; stroke-width:2; vector-effect:non-scaling-stroke; }
      .region-hard { fill:#d92d20; fill-opacity:.035; stroke:#d92d20; stroke-width:1.5; stroke-dasharray:7 5; vector-effect:non-scaling-stroke; }
      .region-backbone { fill:#344054; fill-opacity:.045; stroke:#344054; stroke-width:1.2; stroke-dasharray:5 5; vector-effect:non-scaling-stroke; }
      .guide { fill:none; stroke-width:2; stroke-dasharray:10 7; vector-effect:non-scaling-stroke; }
      .guide-support { stroke:#087f5b; }
      .guide-wrap { stroke:#c66b05; }
      .guide-balance { stroke:#2563eb; }
      .root-marker { fill:#fff; stroke-width:4; vector-effect:non-scaling-stroke; }
      .root-support { stroke:#087f5b; }
      .root-wrap { stroke:#c66b05; }
      .annotation { font-family:'Segoe UI',Arial,sans-serif; font-size:18px; fill:#344054; }
    """

    background = _layer(
        "canvas_and_seams",
        "01 Canvas and repeat seams",
        [
            f'<rect class="canvas" x="0" y="0" width="{width:g}" height="{height:g}"/>',
            f'<rect class="unit-boundary" x="0" y="0" width="{width:g}" height="{height:g}"/>',
            f'<path class="seam" d="M 1,0 L 1,{height:g}"/>',
            f'<path class="seam" d="M {width - 1:g},0 L {width - 1:g},{height:g}"/>',
        ],
    )

    region_styles = {
        "support_region": "region-support",
        "wrap_region": "region-wrap",
        "balance_region": "region-balance",
        "flower_forbidden_region": "region-hard",
        "backbone_protection_region": "region-backbone",
    }
    guide_styles = {
        "support_region": "guide guide-support",
        "wrap_region": "guide guide-wrap",
        "balance_region": "guide guide-balance",
    }
    region_contents: list[str] = []
    for region in region_plan["regions"]:
        role = str(region["role"])
        region_contents.append(
            _path(
                element_id=str(region["region_id"]),
                d=_polyline_path(region["boundary"], close=True),
                css_class=region_styles[role],
                attributes={
                    "role": role,
                    "region-plan-digest": region_plan[
                        "region_plan_digest"
                    ],
                },
            )
        )
        if role in guide_styles:
            region_contents.append(
                _path(
                    element_id=f"{region['region_id']}__guide",
                    d=_polyline_path(region["guide_centerline"]),
                    css_class=guide_styles[role],
                    attributes={
                        "role": role,
                        "geometry-kind": "guide_centerline",
                    },
                )
            )
    regions_layer = _layer(
        "role_region_planning",
        "02 Role region planning (keep)",
        region_contents,
    )

    backbone_points = [
        row["point"] for row in analysis["backbone"]["samples"]
    ]
    backbone_layer = _layer(
        "backbone_layer",
        "03 Backbone",
        [
            _path(
                element_id="backbone",
                d=_polyline_path(backbone_points),
                css_class="backbone",
                attributes={"role": "backbone", "locked-structure": True},
            )
        ],
    )

    flower_contents = [
        (
            f'<ellipse id="{escape(str(flower["flower_id"]))}" '
            f'class="flower" cx="{_number(flower["center"][0])}" '
            f'cy="{_number(flower["center"][1])}" '
            f'rx="{_number(flower["rx"])}" ry="{_number(flower["ry"])}" '
            f'data-role="flower" data-locked-structure="true"/>'
        )
        for flower in analysis["flowers"]
    ]
    flowers_layer = _layer(
        "flowers_layer",
        "04 Flowers",
        flower_contents,
    )

    context_contents = [
        _path(
            element_id=f"context_{lane['candidate_id']}",
            d=_cubic_path(lane["segments"]),
            css_class="context-l1",
            attributes={
                "role": lane["role"],
                "root-s": lane["root_s"],
                "flower-id": lane.get("flower_id") or "",
                "source": "global_l1_context",
            },
        )
        for lane in plan["lanes"]
    ]
    context_layer = _layer(
        "global_l1_context",
        "05 Current global L1 context",
        context_contents,
    )

    selected = {
        row["role"]: row for row in pair["selected_curves"]
    }
    support = selected["flower_support"]
    wrap = selected["flower_wrap"]
    target_layer = _layer(
        "editable_target_group",
        "06 EDIT THESE - flower_1 support and wrap",
        [
            _path(
                element_id="editable_flower_support_L1",
                d=_cubic_path(support["segments"]),
                css_class="target-support",
                attributes={
                    "role": "flower_support",
                    "curve-id": support["curve_id"],
                    "root-s": support["root_s"],
                    "region-id": support["region_id"],
                    "source-region-plan-digest": support[
                        "source_region_plan_digest"
                    ],
                    "geometry-digest-before-user-edit": support[
                        "geometry_digest"
                    ],
                },
            ),
            _path(
                element_id="editable_flower_wrap_L1",
                d=_cubic_path(wrap["segments"]),
                css_class="target-wrap",
                attributes={
                    "role": "flower_wrap",
                    "curve-id": wrap["curve_id"],
                    "root-s": wrap["root_s"],
                    "region-id": wrap["region_id"],
                    "source-region-plan-digest": wrap[
                        "source_region_plan_digest"
                    ],
                    "geometry-digest-before-user-edit": wrap[
                        "geometry_digest"
                    ],
                },
            ),
        ],
    )

    candidate_contents = [
        _path(
            element_id=f"candidate_{candidate['candidate_id']}",
            d=_cubic_path(candidate["segments"]),
            css_class=(
                "candidate-support"
                if candidate["role"] == "flower_support"
                else "candidate-wrap"
            ),
            attributes={
                "role": candidate["role"],
                "selected": candidate["selected"],
                "geometry-digest": candidate["geometry_digest"],
            },
        )
        for candidate in pair["candidate_inventory"]
        if not candidate["selected"]
    ]
    candidates_layer = _layer(
        "unselected_region_candidates",
        "07 Alternate region candidates (hidden)",
        candidate_contents,
        style="display:none",
    )

    support_root = support["centerline"][0]
    wrap_root = wrap["centerline"][0]
    annotation_layer = _layer(
        "editor_annotations",
        "08 Root markers and editor notes",
        [
            (
                f'<circle id="support_root_marker" class="root-marker root-support" '
                f'cx="{_number(support_root[0])}" cy="{_number(support_root[1])}" r="9"/>'
            ),
            (
                f'<circle id="wrap_root_marker" class="root-marker root-wrap" '
                f'cx="{_number(wrap_root[0])}" cy="{_number(wrap_root[1])}" r="9"/>'
            ),
            (
                '<text class="annotation" x="22" y="34">'
                "Edit paths in layer 06; keep semantic ids and region layer 02."
                "</text>"
            ),
        ],
    )

    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" '
        f'width="{width:g}" height="{height:g}" '
        f'viewBox="0 0 {width:g} {height:g}" '
        'version="1.1">\n'
        f"<metadata id=\"branchunit_metadata\"><![CDATA[{json.dumps(metadata, ensure_ascii=False, sort_keys=True)}]]></metadata>"
        f"<defs><style><![CDATA[{styles}]]></style></defs>"
        + background
        + regions_layer
        + backbone_layer
        + flowers_layer
        + context_layer
        + target_layer
        + candidates_layer
        + annotation_layer
        + "</svg>\n"
    )
    return svg, metadata


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inputs, prior, contract, _ = _load_inputs(
        DYNAMIC / "R1_L1_MOTION_CONTRACT_V1.json"
    )
    payload = inputs["proto_sw_1_1"]
    plan, _ = generate_global_l1_flow_plan(
        payload["strict"],
        payload["analysis"],
        payload["morphology"],
        prior,
        contract,
        4101,
    )
    svg, metadata = _build_svg(payload["analysis"], plan)
    SVG_PATH.write_text(svg, encoding="utf-8", newline="\n")
    handoff = {
        "schema": "dynamic_branch_R2C_editor_handoff_v2",
        "status": "AWAITING_USER_EDIT",
        "prototype_id": "proto_sw_1_1",
        "seed": 4101,
        "svg_path": str(SVG_PATH.relative_to(REPO_ROOT)).replace(
            "\\",
            "/",
        ),
        "svg_sha256_before_user_edit": _sha256(SVG_PATH),
        "preview_path": (
            "artifacts/runs/dynamic_branch_R2C_v2/"
            "editable_full_branchunit_preview.png"
        ),
        "editor_target_layer": "06 EDIT THESE - flower_1 support and wrap",
        "editor_target_ids": metadata["editor_target_ids"],
        "region_planning_layer": "02 Role region planning (keep)",
        "region_layer_id": metadata["region_layer_id"],
        "region_plan_digest": metadata["region_plan_digest"],
        "pair_digest_before_user_edit": metadata["pair_digest"],
        "global_plan_digest": metadata["global_plan_digest"],
        "branch_geometry_is_user_unapproved": True,
        "instructions": [
            "Edit the two target paths in layer 06.",
            "Keep the target element ids unchanged.",
            "Keep the role-region planning layer in the SVG; it may be toggled while editing.",
            "Save the edited result as editable_full_branchunit_user_edited.svg in the same artifact directory.",
        ],
        "frozen_contract_hashes": FROZEN_HASHES,
    }
    _write_json(HANDOFF_PATH, handoff)
    acceptance_path = OUTPUT / "acceptance_report.json"
    acceptance = json.loads(
        acceptance_path.read_text(encoding="utf-8")
    )
    acceptance.update(
        {
            "stage_status": "AWAITING_USER_EDIT",
            "numeric_acceptance_pass": True,
            "semantic_topology_pass": True,
            "user_visual_approved": False,
            "user_visual_status": (
                "REJECTED_PENDING_EDITOR_TEACHING"
            ),
            "editable_svg_handoff_present": True,
            "editable_svg_sha256": handoff[
                "svg_sha256_before_user_edit"
            ],
        }
    )
    _write_json(acceptance_path, acceptance)
    (OUTPUT / "stage_summary.md").write_text(
        "# R2C stage summary\n\n"
        "Status: **AWAITING_USER_EDIT**\n\n"
        "- Frozen numeric, topology, legality, reproducibility, and anti-shortcut checks remain passed.\n"
        "- The user explicitly rejected the current automatic wrap geometry; it is not visually approved.\n"
        "- `editable_full_branchunit.svg` contains the full current BranchUnit and keeps the frozen role-region planning as a named editor layer.\n"
        "- Edit `editable_flower_support_L1` and `editable_flower_wrap_L1` in layer 06 while preserving their ids.\n"
        "- Automatic R2D work is paused until the edited SVG is returned and its visual delta is translated back into planning rules.\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest_path = OUTPUT / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage_status"] = "AWAITING_USER_EDIT"
    manifest["editor_handoff"] = {
        "status": handoff["status"],
        "svg_path": handoff["svg_path"],
        "svg_sha256_before_user_edit": handoff[
            "svg_sha256_before_user_edit"
        ],
        "handoff_path": str(
            HANDOFF_PATH.relative_to(REPO_ROOT)
        ).replace("\\", "/"),
        "handoff_sha256": _sha256(HANDOFF_PATH),
        "region_plan_digest": handoff["region_plan_digest"],
        "user_visual_approved": False,
    }
    manifest["supplemental_artifacts"] = [
        "editable_full_branchunit.svg",
        "editable_full_branchunit_preview.png",
        "editor_handoff.json",
    ]
    manifest["source_files"][
        str(Path(__file__).relative_to(REPO_ROOT)).replace("\\", "/")
    ] = _sha256(Path(__file__))
    editable_test = (
        REPO_ROOT
        / "tests"
        / "branch_unit_R"
        / "test_R2C_editable_svg.py"
    )
    manifest["source_files"][
        str(editable_test.relative_to(REPO_ROOT)).replace("\\", "/")
    ] = _sha256(editable_test)
    manifest["artifacts"] = {
        path.name: _sha256(path)
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "run_manifest.json"
    }
    _write_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "status": handoff["status"],
                "svg": str(SVG_PATH),
                "svg_sha256": handoff["svg_sha256_before_user_edit"],
                "region_plan_digest": handoff["region_plan_digest"],
                "target_ids": handoff["editor_target_ids"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
