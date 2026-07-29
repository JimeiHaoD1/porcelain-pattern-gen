#!/usr/bin/env python3
"""Run the transferable SW Chanzhi branch pipeline end to end."""

from __future__ import annotations

import argparse
import json
from argparse import Namespace
from pathlib import Path

try:
    from . import chanzhi_branch_geometry as geometry
    from . import chanzhi_branch_layout_grammar as layout
    from . import chanzhi_skeleton_analyzer as analyzer
    from . import chanzhi_terminal_renderer as terminals
except ImportError:
    import chanzhi_branch_geometry as geometry
    import chanzhi_branch_layout_grammar as layout
    import chanzhi_skeleton_analyzer as analyzer
    import chanzhi_terminal_renderer as terminals


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_ROOT = analyzer.DEFAULT_INPUT_ROOT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "newpipe" / "outputs" / "chanzhi_transferable_pipeline" / "run1"
DEFAULT_PROTOTYPE_IDS = analyzer.DEFAULT_PROTOTYPE_IDS


def run(args: argparse.Namespace) -> dict[str, object]:
    output_root = args.output_root.resolve()
    analysis_dir = output_root / "01_skeleton_analysis"
    layout_dir = output_root / "02_branch_layout"
    geometry_dir = output_root / "03_branch_geometry"
    terminal_dir = output_root / "04_terminal_lineart"
    prototype_ids = list(args.prototype_ids)

    analysis_manifest = analyzer.run(
        Namespace(
            input_root=args.input_root,
            output_dir=analysis_dir,
            prototype_ids=prototype_ids,
            repeat_index=args.repeat_index,
            repeat_width=args.repeat_width,
            tile_width=args.tile_width,
        )
    )
    layout_manifest = layout.run(
        Namespace(
            input_root=analysis_dir,
            output_dir=layout_dir,
            prototype_ids=prototype_ids,
        )
    )
    geometry_manifest = geometry.run(
        Namespace(
            profile_root=analysis_dir,
            plan_root=layout_dir,
            output_dir=geometry_dir,
            prototype_ids=prototype_ids,
        )
    )
    terminal_manifest = terminals.run(
        Namespace(
            profile_root=analysis_dir,
            plan_root=layout_dir,
            geometry_root=geometry_dir,
            output_dir=terminal_dir,
            prototype_ids=prototype_ids,
        )
    )

    stage_validity = {
        "analysis": not analysis_manifest["errors"]
        and all(summary["region_graph_valid"] for summary in analysis_manifest["summary"]),
        "layout": not layout_manifest["errors"]
        and all(summary["valid"] for summary in layout_manifest["summary"]),
        "geometry": not geometry_manifest["errors"]
        and all(summary["valid"] for summary in geometry_manifest["summary"]),
        "terminals": not terminal_manifest["errors"]
        and all(summary["valid"] for summary in terminal_manifest["summary"]),
    }
    summary = {
        "schema": "chanzhi_transferable_pipeline_manifest_v1",
        "input_root": str(args.input_root.resolve()),
        "output_root": str(output_root),
        "prototype_ids": prototype_ids,
        "stage_validity": stage_validity,
        "valid": all(stage_validity.values()),
        "artifacts": {
            "analysis_contact_sheet": analysis_manifest["contact_sheet"],
            "layout_contact_sheet": layout_manifest["contact_sheet"],
            "geometry_contact_sheet": geometry_manifest["contact_sheet"],
            "terminal_contact_sheet": terminal_manifest["contact_sheet"],
        },
        "per_prototype": {
            prototype_id: {
                "skeleton_profile": str(analysis_dir / prototype_id / "skeleton_profile.json"),
                "region_graph": str(analysis_dir / prototype_id / "region_graph.json"),
                "branch_layout_plan": str(layout_dir / prototype_id / "branch_layout_plan.json"),
                "branch_geometry": str(geometry_dir / prototype_id / "branch_geometry.json"),
                "terminal_lineart_svg": str(terminal_dir / prototype_id / "terminal_lineart.svg"),
                "terminal_lineart_preview": str(terminal_dir / prototype_id / "terminal_lineart_preview.png"),
            }
            for prototype_id in prototype_ids
        },
    }
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "pipeline_manifest.json"
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {manifest_path}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the transferable SW Chanzhi line-art pipeline.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--prototype-ids", nargs="+", default=list(DEFAULT_PROTOTYPE_IDS))
    parser.add_argument("--repeat-index", type=int, default=0)
    parser.add_argument("--repeat-width", type=float, default=256.0)
    parser.add_argument("--tile-width", type=int, default=512)
    summary = run(parser.parse_args())
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
