#!/usr/bin/env python3
"""Generate and verify the two non-formal multi-branch L fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import multibranch_l as core  # noqa: E402
from l_core import Cubic, Point  # noqa: E402


EXPERIMENT_ID = "multibranch_L_dev05"
PROTOCOL_PATH = SCRIPT_DIR / "MULTIBRANCH_L_DEV_PROTOCOL.md"
SOURCE_PROFILE = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "run57_reproduction"
    / "01_skeleton_analysis"
    / "proto_sw_1_3"
    / "skeleton_profile.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "runs" / "multibranch_l_dev05"
DEV_CASES = ((4, 2404), (5, 2505))


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json"
    }


def _transform(p0: core.StrippedP0, size: tuple[int, int], top: int = 0) -> tuple[float, float, float]:
    width, height = size
    x0, x1 = p0.repeat_x_range
    scale = min(width / (x1 - x0), (height - top) / p0.canvas_height)
    offset_x = 0.5 * (width - (x1 - x0) * scale) - x0 * scale
    offset_y = top + 0.5 * ((height - top) - p0.canvas_height * scale)
    return scale, offset_x, offset_y


def _tx(point: Point, transform: tuple[float, float, float]) -> tuple[int, int]:
    scale, offset_x, offset_y = transform
    return (round(point[0] * scale + offset_x), round(point[1] * scale + offset_y))


def _draw_polyline(
    draw: ImageDraw.ImageDraw,
    points: Sequence[Point],
    transform: tuple[float, float, float],
    color: str,
    width: float,
) -> None:
    mapped = [_tx(point, transform) for point in points]
    stroke = max(1, round(width * transform[0]))
    draw.line(mapped, fill=color, width=stroke, joint="curve")
    radius = stroke // 2
    if radius:
        for point in (mapped[0], mapped[-1]):
            draw.ellipse((point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius), fill=color)


def render_p0(p0: core.StrippedP0, output_path: Path) -> None:
    image = Image.new("RGB", (560, 700), "#fffefb")
    draw = ImageDraw.Draw(image)
    draw.text((18, 14), "P0 input: backbone + flower positions + repeat bounds", fill="#18212a", font=_font(18, True))
    draw.text((18, 40), "Inherited SVG branch count consumed: 0", fill="#50606c", font=_font(14))
    transform = _transform(p0, image.size, top=72)
    x0, x1 = p0.repeat_x_range
    left = _tx((x0, 0.0), transform)[0]
    right = _tx((x1, 0.0), transform)[0]
    top = _tx((x0, 0.0), transform)[1]
    bottom = _tx((x0, p0.canvas_height), transform)[1]
    draw.rectangle((left, top, right, bottom), outline="#8d969d", width=2)
    for flower in p0.flowers:
        center = _tx(flower.center, transform)
        rx = flower.rx * transform[0]
        ry = flower.ry * transform[0]
        draw.ellipse(
            (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry),
            fill="#fff5f4",
            outline="#cf6971",
            width=2,
        )
    _draw_polyline(draw, p0.backbone_points, transform, "#4e5962", 5.0)
    image.save(output_path)


def render_method(
    p0: core.StrippedP0,
    branch_set: core.BranchSet,
    validation: dict[str, object],
    label: str,
    *,
    debug: bool = False,
) -> Image.Image:
    image = Image.new("RGB", (560, 700), "#fffefb")
    draw = ImageDraw.Draw(image)
    draw.text((18, 12), label, fill="#18212a", font=_font(20, True))
    status = "structural valid" if validation["valid"] else f"structural issues: {len(validation['issues'])}"
    draw.text(
        (18, 40),
        f"branches={len(branch_set.branches)} | old guides=0 | {status}",
        fill="#52616b" if validation["valid"] else "#aa3d35",
        font=_font(14),
    )
    transform = _transform(p0, image.size, top=72)
    x0, x1 = p0.repeat_x_range
    left = _tx((x0, 0.0), transform)[0]
    right = _tx((x1, 0.0), transform)[0]
    top = _tx((x0, 0.0), transform)[1]
    bottom = _tx((x0, p0.canvas_height), transform)[1]
    draw.rectangle((left, top, right, bottom), outline="#8d969d", width=2)
    for flower in p0.flowers:
        center = _tx(flower.center, transform)
        rx = flower.rx * transform[0]
        ry = flower.ry * transform[0]
        draw.ellipse(
            (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry),
            fill="#fff5f4",
            outline="#cf6971",
            width=2,
        )
    _draw_polyline(draw, p0.backbone_points, transform, "#69747c", 5.0)
    colors = {"flower": "#111820", "free": "#111820"}
    if debug:
        colors = {"flower": "#1f6f54", "free": "#173f6d"}
    diagnostic_by_id = {
        item["curve_id"]: item for item in validation["diagnostics"]["branches"]
    }
    for branch in branch_set.branches:
        _draw_polyline(draw, branch.curve.points(128), transform, colors[branch.role.kind], branch.curve.width)
        if debug:
            root = _tx(branch.curve.root, transform)
            tip = _tx(branch.curve.tip, transform)
            draw.ellipse((root[0] - 4, root[1] - 4, root[0] + 4, root[1] + 4), fill="#d64a3a")
            bend_count = diagnostic_by_id[branch.curve.curve_id]["bend_audit"]["bend_count"]
            draw.text((tip[0] + 4, tip[1] - 8), f"b{bend_count}", fill=colors[branch.role.kind], font=_font(11, True))
            for cubic in branch.curve.cubics:
                controls = [_tx(point, transform) for point in (cubic.p0, cubic.p1, cubic.p2, cubic.p3)]
                draw.line(controls, fill="#c6929c", width=1)
    return image


def compose_pair(left: Image.Image, right: Image.Image, title: str, subtitle: str) -> Image.Image:
    result = Image.new("RGB", (1140, 760), "#f7f5ef")
    draw = ImageDraw.Draw(result)
    draw.text((24, 12), title, fill="#18212a", font=_font(21, True))
    draw.text((24, 40), subtitle, fill="#596874", font=_font(14))
    result.paste(left, (5, 58))
    result.paste(right, (575, 58))
    return result


def _cubic_svg_path(cubic: Cubic, *, first: bool) -> str:
    prefix = f"M {cubic.p0[0]:.8f},{cubic.p0[1]:.8f} " if first else ""
    return (
        prefix
        + f"C {cubic.p1[0]:.8f},{cubic.p1[1]:.8f} "
        + f"{cubic.p2[0]:.8f},{cubic.p2[1]:.8f} {cubic.p3[0]:.8f},{cubic.p3[1]:.8f}"
    )


def render_svg(p0: core.StrippedP0, branch_set: core.BranchSet, output_path: Path) -> None:
    x0, x1 = p0.repeat_x_range
    backbone_points = " ".join(f"{point[0]:.8f},{point[1]:.8f}" for point in p0.backbone_points)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.3f} 0 {x1-x0:.3f} {p0.canvas_height:.3f}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#fffefb"/>',
        f'<polyline id="p0_backbone" points="{backbone_points}" fill="none" stroke="#69747c" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>',
    ]
    for flower in p0.flowers:
        lines.append(
            f'<ellipse id="{flower.flower_id}" cx="{flower.center[0]:.8f}" cy="{flower.center[1]:.8f}" '
            f'rx="{flower.rx:.8f}" ry="{flower.ry:.8f}" fill="#fff5f4" stroke="#cf6971" stroke-width="1.2"/>'
        )
    for branch in branch_set.branches:
        path = " ".join(_cubic_svg_path(cubic, first=index == 0) for index, cubic in enumerate(branch.curve.cubics))
        target = "" if branch.role.flower_id is None else f' data-target-flower-id="{branch.role.flower_id}"'
        lines.append(
            f'<path id="{branch.curve.curve_id}" data-source="program_generated" '
            f'data-role="{branch.role.kind}"{target} d="{path}" fill="none" stroke="#111820" '
            f'stroke-width="{branch.curve.width:.3f}" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    lines.append("</svg>")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _case_summary(case: dict[str, object]) -> dict[str, object]:
    serial = core.serializable_case(case)
    return {
        "case_id": serial["case_id"],
        "branch_count": serial["branch_count"],
        "seed": serial["seed"],
        "token_digest": serial["token_digest"],
        "target_role_lengths": serial["target_role_lengths"],
        "L0_geometry_hash": serial["L0"]["branch_set"]["geometry_hash"],
        "L1_geometry_hash": serial["L1"]["branch_set"]["geometry_hash"],
        "L0_valid": serial["L0"]["validation"]["valid"],
        "L1_valid": serial["L1"]["validation"]["valid"],
        "L0_issues": serial["L0"]["validation"]["issues"],
        "L1_issues": serial["L1"]["validation"]["issues"],
        "fairness": serial["fairness"],
    }


def generate(output_dir: Path) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite development run: {output_dir}")
    for relative in ("input", "methods", "debug", "pairs", "vectors", "records"):
        (output_dir / relative).mkdir(parents=True, exist_ok=True)

    profile = json.loads(SOURCE_PROFILE.read_text(encoding="utf-8"))
    p0 = core.strip_profile(profile)
    intervention = core.profile_intervention_proof(profile)
    if not intervention["identical"]:
        raise RuntimeError("ignored profile fields changed stripped P0")
    _write_json(output_dir / "input" / "stripped_p0.json", {**p0.as_dict(), "input_digest": p0.digest})
    _write_json(output_dir / "input" / "ignored_field_intervention.json", intervention)
    render_p0(p0, output_dir / "input" / "stripped_p0.png")

    cases: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    for branch_count, seed in DEV_CASES:
        case = core.build_case(p0, branch_count, seed)
        cases.append(case)
        serial = core.serializable_case(case)
        _write_json(output_dir / "records" / f"D{branch_count}.json", serial)
        summaries.append(_case_summary(case))
        for variant in ("L0", "L1"):
            branch_set = case[variant]["branch_set"]
            validation = case[variant]["validation"]
            label = "L0 independent branches" if variant == "L0" else "L1 jointly mapped branch set"
            normal = render_method(p0, branch_set, validation, label, debug=False)
            debug = render_method(p0, branch_set, validation, f"{label} | geometry audit", debug=True)
            normal.save(output_dir / "methods" / f"D{branch_count}_{variant}.png")
            debug.save(output_dir / "debug" / f"D{branch_count}_{variant}.png")
            render_svg(p0, branch_set, output_dir / "vectors" / f"D{branch_count}_{variant}.svg")
        pair = compose_pair(
            Image.open(output_dir / "methods" / f"D{branch_count}_L0.png"),
            Image.open(output_dir / "methods" / f"D{branch_count}_L1.png"),
            f"D{branch_count}: {branch_count} program-generated first-level branches",
            "P0 consumes backbone + two flower positions + repeat only | non-formal visual gate",
        )
        pair.save(output_dir / "pairs" / f"D{branch_count}.png")

    formal_blocked = True
    structural_summary = {
        "all_fairness_budgets_match": all(item["fairness"]["budget_match"] for item in summaries),
        "all_l0_structurally_valid": all(item["L0_valid"] for item in summaries),
        "all_l1_structurally_valid": all(item["L1_valid"] for item in summaries),
        "visual_status": "pending_user_review",
        "formal_generation_blocked": formal_blocked,
    }
    manifest = {
        "schema": "multibranch_l_dev_manifest_v1",
        "experiment_id": EXPERIMENT_ID,
        "status": "development_only_pending_visual_gate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prototype_id": p0.prototype_id,
        "input_policy": p0.policy_id,
        "input_digest": p0.digest,
        "source_profile": {
            "path": str(SOURCE_PROFILE.resolve()),
            "sha256": _file_sha256(SOURCE_PROFILE),
            "source_existing_guide_count_observed_but_not_consumed": len(profile.get("existing_guides", [])),
        },
        "profile_intervention_proof": intervention,
        "topology": {
            "allowed_branch_counts": [4, 5],
            "flower_branches": 2,
            "free_branches": "N-2",
            "child_branches": 0,
            "inherited_branches": 0,
        },
        "bend_contract": {
            "maximum_effective_turn_lobes": 2,
            "maximum_curvature_sign_reversals": 1,
            "maximum_cubic_segments": 2,
            "minimum_visible_turn_degrees": core.MIN_VISIBLE_TURN_DEGREES,
            "minimum_visible_turn_length_ratio": core.MIN_VISIBLE_TURN_LENGTH_RATIO,
        },
        "variants": {"L0": "independent_row_mapping", "L1": "joint_center_gap_set_mapping"},
        "generation_policy": {
            "candidate_count_per_variant_per_case": 1,
            "retry_count": 0,
            "resample_count": 0,
            "repair_count": 0,
            "selection_count": 1,
        },
        "cases": summaries,
        "structural_summary": structural_summary,
        "excluded": [
            "inherited_svg_branches",
            "secondary_or_tertiary_branches",
            "formal_12_pair_matrix",
            "blind_scoring",
            "context_C_experiment",
            "global_G_experiment",
            "density_field",
            "candidate_search",
            "beam_search",
            "backtracking",
            "model_training",
        ],
        "source_files": {
            "protocol": {"path": str(PROTOCOL_PATH.resolve()), "sha256": _file_sha256(PROTOCOL_PATH)},
            "runner": {"path": str(Path(__file__).resolve()), "sha256": _file_sha256(Path(__file__).resolve())},
            "kernel": {"path": str(Path(core.__file__).resolve()), "sha256": _file_sha256(Path(core.__file__).resolve())},
        },
    }
    _write_json(output_dir / "manifest.json", manifest)
    (output_dir / "README.md").write_text(
        "# Multi-branch L development fixtures\n\n"
        "This run is a non-formal visual gate.  Open `input/stripped_p0.png`, then "
        "compare `pairs/D4.png` and `pairs/D5.png`.  Formal generation remains blocked "
        "until the input stripping, four/five-branch composition, flower relation, and "
        "two-bend cap are visually accepted.\n",
        encoding="utf-8",
    )
    _write_json(output_dir / "artifact_hashes.json", _artifact_hashes(output_dir))
    return manifest


def verify(run_dir: Path) -> dict[str, object]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    profile = json.loads(SOURCE_PROFILE.read_text(encoding="utf-8"))
    p0 = core.strip_profile(profile)
    issues: list[str] = []
    if p0.digest != manifest["input_digest"]:
        issues.append("input_digest_mismatch")
    proof = core.profile_intervention_proof(profile)
    if not proof["identical"]:
        issues.append("ignored_field_intervention_failed")
    regenerated = {
        f"D{branch_count}": core.serializable_case(core.build_case(p0, branch_count, seed))
        for branch_count, seed in DEV_CASES
    }
    for summary in manifest["cases"]:
        case_id = summary["case_id"]
        record = json.loads((run_dir / "records" / f"{case_id}.json").read_text(encoding="utf-8"))
        replay = regenerated[case_id]
        if record["L0"]["branch_set"]["geometry_hash"] != replay["L0"]["branch_set"]["geometry_hash"]:
            issues.append(f"{case_id}:L0_geometry_replay")
        if record["L1"]["branch_set"]["geometry_hash"] != replay["L1"]["branch_set"]["geometry_hash"]:
            issues.append(f"{case_id}:L1_geometry_replay")
        for variant in ("L0", "L1"):
            svg = (run_dir / "vectors" / f"{case_id}_{variant}.svg").read_text(encoding="utf-8")
            for forbidden in ("guide_", "#d5d9dd", "#ff7800", "#00ff00", "#007800"):
                if forbidden in svg:
                    issues.append(f"{case_id}:{variant}:forbidden_inherited_marker:{forbidden}")
            if svg.count('data-source="program_generated"') != int(summary["branch_count"]):
                issues.append(f"{case_id}:{variant}:generated_branch_count")
    saved_hashes = json.loads((run_dir / "artifact_hashes.json").read_text(encoding="utf-8"))
    current_hashes = _artifact_hashes(run_dir)
    if saved_hashes != current_hashes:
        issues.append("artifact_hash_mismatch")
    result = {
        "schema": "multibranch_l_dev_verification_v1",
        "run_dir": str(run_dir.resolve()),
        "valid": not issues,
        "issues": issues,
        "input_digest": p0.digest,
        "profile_intervention_proof": proof,
        "case_geometry_hashes": {
            case_id: {
                "L0": payload["L0"]["branch_set"]["geometry_hash"],
                "L1": payload["L1"]["branch_set"]["geometry_hash"],
            }
            for case_id, payload in regenerated.items()
        },
    }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--run-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    if args.command == "generate":
        manifest = generate(args.output_dir.resolve())
        print(json.dumps(manifest["structural_summary"], ensure_ascii=False, indent=2))
        return 0
    result = verify(args.run_dir.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
