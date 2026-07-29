#!/usr/bin/env python3
"""Run the staged BranchUnit L v3 experiment without touching v2.

Before user confirmation this driver exposes only neutral development fixtures
and their exact verification.  Formal L01-L12 generation is intentionally not
available while the protocol status is draft.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import l_v3_planner as planner  # noqa: E402
import run_l as harness  # noqa: E402
from l_core import BranchUnit, Curve, compile_primary, compile_unit, cross, dot, sub  # noqa: E402


DEV_EXPERIMENT_ID = "branch_unit_L_v3_dev01"
DEFAULT_DEV_DIR = REPO_ROOT / "artifacts" / "runs" / "branch_unit_l_v3_dev01"
PROTOCOL_PATH = SCRIPT_DIR / "L_V3_PROTOCOL.md"
DEV_SPECS = (
    harness.TrialSpec("D0", 0.725, 0.27, 0, 701),
    harness.TrialSpec("D1", 0.725, 0.27, 1, 702),
    harness.TrialSpec("D2", 0.725, 0.27, 2, 703),
)


def neutral_raw() -> dict[str, float]:
    return {token: 0.5 for token in harness.RAW_TOKENS}


def build_case(scene: harness.Scene, spec: harness.TrialSpec) -> dict[str, object]:
    raw = neutral_raw()
    budget = harness.build_budget(spec, raw, scene.max_clearance)
    primary = compile_primary(
        root=scene.anchor_point,
        parent_tangent=scene.anchor_tangent,
        outward=scene.growth_direction,
        target_length=budget.primary_length,
        sweep_depth=spec.sweep_depth,
        handle_u=raw["main.handle"],
        tip_u=raw["main.tip"],
        width=budget.primary_width,
    )
    l0_children, l0_terminal, l0_mapping = planner.map_l0_independent(raw, budget)
    l1_plan = planner.plan_l1_joint(primary, raw, budget)
    l0 = compile_unit(
        unit_id=f"{spec.trial_id}_L0_independent",
        primary=primary,
        child_specs=l0_children,
        terminal_spec=l0_terminal,
    )
    l1 = compile_unit(
        unit_id=f"{spec.trial_id}_L1_joint",
        primary=primary,
        child_specs=l1_plan.children,
        terminal_spec=l1_plan.terminal,
    )
    validation_l0 = harness.validate_unit(scene, l0, spec.child_count)
    validation_l1 = harness.validate_unit(scene, l1, spec.child_count)
    metrics_l0 = harness.unit_metrics(l0, validation_l0.as_dict())
    metrics_l1 = harness.unit_metrics(l1, validation_l1.as_dict())
    fairness = harness.fairness_metrics(l0, l1, metrics_l0, metrics_l1, budget)
    checks = _development_checks(primary, l1, l1_plan, validation_l1.as_dict(), budget)
    return {
        "spec": spec,
        "raw": raw,
        "budget": budget,
        "primary": primary,
        "L0": {
            "unit": l0,
            "mapping": l0_mapping,
            "validation": validation_l0.as_dict(),
            "metrics": metrics_l0,
        },
        "L1": {
            "unit": l1,
            "mapping": l1_plan.as_dict(),
            "validation": validation_l1.as_dict(),
            "metrics": metrics_l1,
        },
        "fairness": fairness,
        "development_checks": checks,
    }


def generate_dev(output_dir: Path) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing development run: {output_dir}")
    output_dir.mkdir(parents=True)
    for relative in ("methods", "pairs", "vectors"):
        (output_dir / relative).mkdir(parents=True, exist_ok=True)

    scene, profile, profile_path = harness.rebuild_scene(output_dir)
    harness._validate_registered_scene(scene, profile)
    cases = [build_case(scene, spec) for spec in DEV_SPECS]
    pair_paths: list[Path] = []
    for case in cases:
        spec: harness.TrialSpec = case["spec"]
        l0: BranchUnit = case["L0"]["unit"]
        l1: BranchUnit = case["L1"]["unit"]
        for variant, label, unit in (
            ("L0", "L0 independent", l0),
            ("L1", "L1 true joint plan", l1),
        ):
            harness.render_method_panel(scene, unit, label, debug=False).save(
                output_dir / "methods" / f"{spec.trial_id}_{variant}.png"
            )
            harness.render_unit_svg(scene, unit, output_dir / "vectors" / f"{spec.trial_id}_{variant}.svg")
        pair = harness.compose_pair(
            harness.render_method_panel(scene, l0, "L0 independent", debug=False),
            harness.render_method_panel(scene, l1, "L1 true joint plan", debug=False),
            header=f"{spec.trial_id} neutral fixture | L0 vs L1",
            subheader="raw tokens=0.5  length_ratio=0.725  sweep_depth=0.27  non-formal",
        )
        pair_path = output_dir / "pairs" / f"{spec.trial_id}.png"
        pair.save(pair_path)
        pair_paths.append(pair_path)
    harness.write_contact_sheet(pair_paths, output_dir / "contact_sheet_dev.png")

    replay_cases = [_replay_case(case) for case in cases]
    replay = {
        "schema": "branch_unit_l_v3_development_replay_v1",
        "experiment_id": DEV_EXPERIMENT_ID,
        "formal_gate_eligible": False,
        "fixture_policy": {
            "trial_ids": [spec.trial_id for spec in DEV_SPECS],
            "raw_tokens": "all_0.5",
            "length_ratio": 0.725,
            "sweep_depth": 0.27,
            "candidate_count_per_variant": 1,
            "replacement_allowed": False,
        },
        "commands": {
            "verify": f'python "{Path(__file__).resolve()}" verify-dev --run-dir "{output_dir.resolve()}"'
        },
        "source_files": _source_records(profile_path),
        "cases": replay_cases,
    }
    harness._write_json(output_dir / "replay_manifest.json", replay)

    automated_pass = all(bool(case["development_checks"]["automated_pass"]) for case in cases)
    manifest = {
        "schema": "branch_unit_l_v3_development_manifest_v1",
        "experiment_id": DEV_EXPERIMENT_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "formal_gate_eligible": False,
        "protocol_status": _protocol_status(),
        "fixture_count": len(cases),
        "all_l1_automated_checks_pass": automated_pass,
        "visual_status": "pending_user_confirmation",
        "formal_generation_locked": True,
        "cases": [
            {
                "trial_id": case["spec"].trial_id,
                "child_count": case["spec"].child_count,
                "L0_hard_valid": case["L0"]["metrics"]["hard_valid"],
                "L1_hard_valid": case["L1"]["metrics"]["hard_valid"],
                "L0_hard_failure_reasons": case["L0"]["metrics"]["hard_failure_reasons"],
                "L1_hard_failure_reasons": case["L1"]["metrics"]["hard_failure_reasons"],
                "fairness": case["fairness"],
                "development_checks": case["development_checks"],
                "pair_image": f"pairs/{case['spec'].trial_id}.png",
            }
            for case in cases
        ],
    }
    harness._write_json(output_dir / "manifest.json", manifest)
    (output_dir / "README.md").write_text(_dev_readme(output_dir, manifest), encoding="utf-8")
    harness._write_json(output_dir / "artifact_hashes.json", harness._artifact_hash_index(output_dir))
    return manifest


def verify_dev(run_dir: Path) -> dict[str, object]:
    replay = json.loads((run_dir / "replay_manifest.json").read_text(encoding="utf-8"))
    profile_path = run_dir / "input_analysis" / harness.PROTOTYPE_ID / "skeleton_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    scene = harness.scene_from_profile(profile)
    rebuilt = [_replay_case(build_case(scene, spec)) for spec in DEV_SPECS]
    geometry_exact = harness._payload_sha(rebuilt) == harness._payload_sha(replay["cases"])

    current_sources = {
        "baseline_svg": harness.BASELINE_SVG,
        "development_runner": Path(__file__).resolve(),
        "joint_planner": Path(planner.__file__).resolve(),
        "protocol": PROTOCOL_PATH,
        "v2_harness": Path(harness.__file__).resolve(),
        "geometry_kernel": SCRIPT_DIR / "l_core.py",
        "skeleton_analyzer": Path(harness.analyzer.__file__).resolve(),
        "svg_skeleton_io": Path(harness.analyzer.eng.__file__).resolve(),
        "rebuilt_profile": profile_path,
    }
    source_checks = {
        key: {
            "expected": replay["source_files"][key]["sha256"],
            "actual": harness._sha256(path),
            "match": replay["source_files"][key]["sha256"] == harness._sha256(path),
        }
        for key, path in current_sources.items()
    }
    artifact_index = json.loads((run_dir / "artifact_hashes.json").read_text(encoding="utf-8"))
    artifact_checks = []
    for record in artifact_index["files"]:
        path = run_dir / record["path"]
        actual = harness._sha256(path) if path.is_file() else None
        artifact_checks.append({"path": record["path"], "match": actual == record["sha256"]})
    report = {
        "schema": "branch_unit_l_v3_development_verification_v1",
        "experiment_id": DEV_EXPERIMENT_ID,
        "geometry_cases_exact": geometry_exact,
        "all_recorded_sources_match": all(item["match"] for item in source_checks.values()),
        "all_indexed_artifacts_match": all(item["match"] for item in artifact_checks),
        "source_checks": source_checks,
        "artifact_check_count": len(artifact_checks),
        "artifact_failures": [item for item in artifact_checks if not item["match"]],
    }
    report["valid"] = bool(
        report["geometry_cases_exact"]
        and report["all_recorded_sources_match"]
        and report["all_indexed_artifacts_match"]
    )
    harness._write_json(run_dir / "verification_report.json", report)
    return report


def _development_checks(
    primary: Curve,
    unit: BranchUnit,
    plan: planner.JointBranchPlan,
    validation: dict[str, object],
    budget: harness.NominalBudget,
) -> dict[str, object]:
    primary_turn = _signed_turn(primary)
    terminal_turn = _signed_turn(unit.terminal)
    terminal_sign = 1 if terminal_turn > 0.0 else -1
    exit_tangent = primary.exit_tangent
    terminal_points = unit.terminal.points(96)
    minimum_forward_dot = min(
        dot(_unit(sub(end, start)), exit_tangent)
        for start, end in zip(terminal_points, terminal_points[1:])
    )
    terminal_release = abs(primary_turn + terminal_turn) < abs(primary_turn)
    terminal_forward = minimum_forward_dot > 0.0

    if len(plan.children) == 2:
        mount_gap = (plan.children[1].mount_fraction - plan.children[0].mount_fraction) * budget.primary_length
        first_direction, second_direction = plan.trace["child_target_directions"]
        target_separation = math.degrees(
            math.acos(
                max(
                    -1.0,
                    min(1.0, dot(tuple(first_direction), tuple(second_direction))),
                )
            )
        )
        hierarchy = plan.children[0].target_length > plan.children[1].target_length
    else:
        mount_gap = None
        target_separation = None
        hierarchy = True
    hard_valid = bool(validation["valid"])
    checks = {
        "hard_valid": hard_valid,
        "terminal_turn_sign_matches_release_side": terminal_sign == plan.release_side,
        "terminal_reduces_primary_cumulative_turn": terminal_release,
        "terminal_minimum_forward_dot": round(minimum_forward_dot, 10),
        "terminal_all_segments_forward": terminal_forward,
        "two_child_mount_gap_world": None if mount_gap is None else round(mount_gap, 10),
        "two_child_mount_gap_in_10_18": mount_gap is None or 10.0 - 1e-8 <= mount_gap <= 18.0 + 1e-8,
        "two_child_target_direction_separation_degrees": (
            None if target_separation is None else round(target_separation, 10)
        ),
        "two_child_long_short_hierarchy": hierarchy,
        "no_internal_or_context_failure": hard_valid,
    }
    checks["automated_pass"] = bool(
        hard_valid
        and checks["terminal_turn_sign_matches_release_side"]
        and terminal_release
        and terminal_forward
        and checks["two_child_mount_gap_in_10_18"]
        and hierarchy
    )
    return checks


def _replay_case(case: dict[str, object]) -> dict[str, object]:
    spec: harness.TrialSpec = case["spec"]
    budget: harness.NominalBudget = case["budget"]
    return {
        "trial": spec.as_dict(),
        "raw_named_random": case["raw"],
        "nominal_budget": budget.as_dict(),
        "primary": case["primary"].as_dict(),
        "L0": {
            "mapping": case["L0"]["mapping"],
            "unit": case["L0"]["unit"].as_dict(),
            "validation": case["L0"]["validation"],
            "metrics": case["L0"]["metrics"],
        },
        "L1": {
            "mapping": case["L1"]["mapping"],
            "unit": case["L1"]["unit"].as_dict(),
            "validation": case["L1"]["validation"],
            "metrics": case["L1"]["metrics"],
        },
        "fairness": case["fairness"],
        "development_checks": case["development_checks"],
        "generation_policy": {
            "candidate_count_per_variant": 1,
            "retry_count": 0,
            "resample_count": 0,
            "repair_count": 0,
        },
    }


def _source_records(profile_path: Path) -> dict[str, object]:
    return {
        "baseline_svg": harness._file_record(harness.BASELINE_SVG),
        "development_runner": harness._file_record(Path(__file__).resolve()),
        "joint_planner": harness._file_record(Path(planner.__file__).resolve()),
        "protocol": harness._file_record(PROTOCOL_PATH),
        "v2_harness": harness._file_record(Path(harness.__file__).resolve()),
        "geometry_kernel": harness._file_record(SCRIPT_DIR / "l_core.py"),
        "skeleton_analyzer": harness._file_record(Path(harness.analyzer.__file__).resolve()),
        "svg_skeleton_io": harness._file_record(Path(harness.analyzer.eng.__file__).resolve()),
        "rebuilt_profile": harness._file_record(profile_path),
    }


def _signed_turn(curve: Curve) -> float:
    points = curve.points(96)
    previous = _unit(sub(points[1], points[0]))
    total = 0.0
    for start, end in zip(points[1:], points[2:]):
        current = _unit(sub(end, start))
        total += math.atan2(cross(previous, current), dot(previous, current))
        previous = current
    return total


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(*vector)
    return vector[0] / length, vector[1] / length


def _protocol_status() -> str:
    first_lines = PROTOCOL_PATH.read_text(encoding="utf-8").splitlines()[:5]
    return next(line.removeprefix("Status: ") for line in first_lines if line.startswith("Status: "))


def _dev_readme(output_dir: Path, manifest: dict[str, object]) -> str:
    return f"""# BranchUnit L v3 neutral development fixtures

These three pairs are non-formal D0/D1/D2 fixtures. They are not L01-L12,
cannot count toward any development gate, and cannot replace a formal result.

- Automated L1 checks passed: {manifest['all_l1_automated_checks_pass']}
- Visual status: `{manifest['visual_status']}`
- Formal generation locked: {manifest['formal_generation_locked']}

Verify exact geometry, source hashes, and artifacts with:

```powershell
python "{Path(__file__).resolve()}" verify-dev --run-dir "{output_dir.resolve()}"
```
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run staged BranchUnit L v3 development fixtures.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dev_parser = subparsers.add_parser("dev", help="generate the three neutral non-formal fixtures")
    dev_parser.add_argument("--output-dir", type=Path, default=DEFAULT_DEV_DIR)
    verify_parser = subparsers.add_parser("verify-dev", help="verify a saved development fixture run")
    verify_parser.add_argument("--run-dir", type=Path, default=DEFAULT_DEV_DIR)
    args = parser.parse_args()
    if args.command == "dev":
        manifest = generate_dev(args.output_dir.resolve())
        print(
            json.dumps(
                {
                    "all_l1_automated_checks_pass": manifest["all_l1_automated_checks_pass"],
                    "visual_status": manifest["visual_status"],
                    "formal_generation_locked": manifest["formal_generation_locked"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if manifest["all_l1_automated_checks_pass"] else 1
    report = verify_dev(args.run_dir.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
