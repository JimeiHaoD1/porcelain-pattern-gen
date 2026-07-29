#!/usr/bin/env python3
"""Render and retain the V2 joint edge-chain recursive experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

import recursive_branch_unit_v2 as core

# Reuse the V1 evidence renderer without duplicating its drawing code.  Its
# import is deliberately redirected only inside this process.
sys.modules["recursive_branch_unit"] = core
import run_recursive_branch_unit_dev as renderer  # noqa: E402


DEFAULT_OUTPUT = (
    renderer.REPO_ROOT
    / "artifacts"
    / "runs"
    / "_scratch_recursive_branch_unit_v2_joint_edge_chain"
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=renderer.DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(core.DEV_SEEDS))
    args = parser.parse_args(argv)
    manifest = renderer.run(args.profile, args.output, args.seeds)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
