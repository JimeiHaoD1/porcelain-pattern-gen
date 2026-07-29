#!/usr/bin/env python3
"""Render and retain the V3A rule-inheriting recursive experiment."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import recursive_branch_unit_v3 as core

# Reuse only the evidence drawing/layout code.  The process-local redirect
# ensures every plan, validation, and proof still comes from V3A.
sys.modules["recursive_branch_unit"] = core
import run_recursive_branch_unit_dev as renderer  # noqa: E402


DEFAULT_OUTPUT = (
    renderer.REPO_ROOT
    / "artifacts"
    / "runs"
    / "_scratch_recursive_branch_unit_v3a_rule_inheritance_v2_joint_domain"
)


def run(
    profile_path: Path,
    output_dir: Path,
    seeds: Sequence[int] = core.DEV_SEEDS,
) -> dict[str, object]:
    """Retain successful renders and empty-domain failures without resampling."""

    output_dir.mkdir(parents=True, exist_ok=True)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    p0 = core.strip_profile(profile)
    results: dict[int, core.RecursiveResult] = {}
    validations: dict[int, dict[str, object]] = {}
    failures: dict[int, dict[str, str]] = {}
    clean_images = []
    debug_images = []
    unit_images = []
    repeat_images = []

    for seed_value in seeds:
        seed = int(seed_value)
        try:
            result = core.build_recursive(p0, seed)
        except core.PlanningFailure as error:
            failure = {
                "seed": seed,
                "failure_type": type(error).__name__,
                "message": str(error),
                "candidate_count": 1,
                "retry_count": 0,
                "resample_count": 0,
                "repair_count": 0,
            }
            failures[seed] = failure
            renderer._write_json(  # noqa: SLF001 - shared artifact serializer
                output_dir / f"planning_failure_{seed}.json", failure
            )
            continue

        validation = core.validate_result(p0, result)
        results[seed] = result
        validations[seed] = validation
        renderer._write_json(  # noqa: SLF001
            output_dir / f"record_{seed}.json",
            {"result": result.as_dict(), "validation": validation},
        )
        clean = renderer._draw_scene(p0, result, validation, debug=False)  # noqa: SLF001
        debug = renderer._draw_scene(p0, result, validation, debug=True)  # noqa: SLF001
        units = renderer._unit_sheet(p0, result, validation)  # noqa: SLF001
        repeat = renderer._repeat_2x(clean)  # noqa: SLF001
        clean.save(output_dir / f"seed_{seed}.png")
        debug.save(output_dir / f"seed_{seed}_debug.png")
        units.save(output_dir / f"seed_{seed}_units.png")
        repeat.save(output_dir / f"seed_{seed}_repeat_2x.png")
        clean_images.append(clean)
        debug_images.append(debug)
        unit_images.append(units)
        repeat_images.append(repeat)

    artifacts = [f"planning_failure_{seed}.json" for seed in sorted(failures)]
    if clean_images:
        renderer._contact_sheet(clean_images).save(output_dir / "contact_sheet.png")  # noqa: SLF001
        renderer._contact_sheet(debug_images).save(output_dir / "contact_sheet_debug.png")  # noqa: SLF001
        renderer._contact_sheet(unit_images, columns=1).save(  # noqa: SLF001
            output_dir / "contact_sheet_units.png"
        )
        renderer._contact_sheet(repeat_images, columns=1).save(  # noqa: SLF001
            output_dir / "contact_sheet_repeat_2x.png"
        )
        artifacts.extend(
            [
                "contact_sheet.png",
                "contact_sheet_debug.png",
                "contact_sheet_units.png",
                "contact_sheet_repeat_2x.png",
            ]
        )

    replay_by_seed = {}
    for seed, result in results.items():
        replay = core.build_recursive(p0, seed)
        replay_by_seed[str(seed)] = (
            replay.plan.digest == result.plan.digest
            and replay.geometry_hash == result.geometry_hash
        )
    variation = {
        "passes": False,
        "blocked_by_planning_failures": {
            str(seed): failure["message"] for seed, failure in sorted(failures.items())
        },
        "replay_by_successful_seed": replay_by_seed,
        "note": "No failed seed was retried, resampled, repaired, or replaced.",
    }
    renderer._write_json(output_dir / "seed_variation.json", variation)  # noqa: SLF001
    artifacts.append("seed_variation.json")

    manifest = {
        "schema": "recursive_branch_unit_v3a_attempt_manifest_v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "profile": str(profile_path),
        "output_dir": str(output_dir),
        "seeds": [int(seed) for seed in seeds],
        "plan_id": core.PLAN_ID,
        "rule_id": core.RULE_ID,
        "geometry_kernel_id": core.GEOMETRY_KERNEL_ID,
        "successful_seed_ids": sorted(results),
        "planning_failed_seed_ids": sorted(failures),
        "planning_failures": {
            str(seed): failure for seed, failure in sorted(failures.items())
        },
        "structural_valid_by_seed": {
            str(seed): validations[seed]["valid"] if seed in validations else False
            for seed in (int(value) for value in seeds)
        },
        "issues_by_seed": {
            str(seed): (
                validations[seed]["issues"]
                if seed in validations
                else [failures[seed]["message"]]
            )
            for seed in (int(value) for value in seeds)
        },
        "generation_policy": {
            "candidate_count": 1,
            "retry_count": 0,
            "resample_count": 0,
            "repair_count": 0,
            "validation_feedback_consumed": False,
        },
        "seed_variation_pass": False,
        "visual_status": "fail_structural_before_complete_visual_review",
        "decision": "V3A frozen-L1-L2 recursion does not advance to edge-goal propagation.",
        "claim_boundary": (
            "This retained failure tests rule inheritance on frozen v23 L1/L2. "
            "It does not reject recursive growth with capacity-aware L2 planning."
        ),
        "artifacts": artifacts,
    }
    renderer._write_json(output_dir / "manifest.json", manifest)  # noqa: SLF001
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=renderer.DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(core.DEV_SEEDS))
    args = parser.parse_args(argv)
    manifest = run(args.profile, args.output, args.seeds)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
