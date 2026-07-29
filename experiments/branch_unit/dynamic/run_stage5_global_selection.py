#!/usr/bin/env python3
"""Run deterministic cross-Unit conflict selection for all fifteen tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from render_stage4_unit_atlas import render_contact_sheet
from render_stage5_global_selection import render_global_selection
from stage5_global_unit_selection import (
    Stage5SelectionError,
    build_conflict_graph,
    select_global_units,
    validate_global_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
STAGE2_ROOT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage2_analysis_v1"
STAGE4_ROOT = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage4_unit_candidates_v1"
)
APPROVAL_PATH = STAGE4_ROOT / "stage4_approval.json"
CONTRACT_PATH = DYNAMIC_DIR / "STAGE5_GLOBAL_SELECTION_CONTRACT_V1.json"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage5_global_unit_selection_v1"
)
PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
SEEDS = (4101, 4102, 4103)


class Stage5RunError(RuntimeError):
    """The formal stage-5 package cannot be produced."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5RunError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_readme(path: Path) -> None:
    path.write_text(
        """# 阶段5全局Unit约束组合

- 输入：用户明确验收并冻结的阶段4完整Unit候选池。
- 操作：建立跨Unit与跨repeat冲突图，每个枝位恰选一个完整Unit。
- 硬约束：只选阶段4内部合法候选；后代不得穿过其他Unit的L1或后代。
- 不做：不移动、缩短、删改或重新生成任何曲线；不按视觉分数做best-of-N。
- 求解：声明顺序下的确定性约束回溯；首个完整合法解即停止。
- 无解：保存阻断枝位和全部冲突，不发布部分组合，不自动修复。
- 范围：仅枝条骨架，不包含叶片、芽头或卷头。
- 状态：完整组合仍需人工视觉验收。
""",
        encoding="utf-8",
        newline="\n",
    )


def _load_inputs() -> tuple[
    dict[str, Any],
    dict[tuple[str, int], dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    contract = _read_json(CONTRACT_PATH)
    if contract.get("schema") != (
        "dynamic_branch_stage5_global_selection_contract_v1"
    ):
        raise Stage5RunError("stage-5 contract schema mismatch")
    approval = _read_json(APPROVAL_PATH)
    if approval.get("schema") != (
        "dynamic_branch_stage4_unit_candidate_approval_v1"
    ):
        raise Stage5RunError("stage-4 approval schema mismatch")
    if not approval.get("stage5_unlocked"):
        raise Stage5RunError("stage-4 approval does not unlock stage 5")
    manifest_path = STAGE4_ROOT / str(approval["stage4_manifest_path"])
    if _sha256(manifest_path) != approval["stage4_manifest_sha256"]:
        raise Stage5RunError("approved stage-4 manifest hash mismatch")

    inventories: dict[tuple[str, int], dict[str, Any]] = {}
    for row in approval["approved_tasks"]:
        prototype_id = str(row["prototype_id"])
        seed = int(row["seed"])
        path = STAGE4_ROOT / str(row["inventory_path"])
        if _sha256(path) != row["inventory_sha256"]:
            raise Stage5RunError(
                f"{prototype_id} seed {seed} inventory hash mismatch"
            )
        inventory = _read_json(path)
        if inventory.get("inventory_digest") != row["inventory_digest"]:
            raise Stage5RunError(
                f"{prototype_id} seed {seed} inventory digest mismatch"
            )
        inventories[(prototype_id, seed)] = inventory
    expected = {
        (prototype_id, seed)
        for prototype_id in PROTOTYPE_IDS
        for seed in SEEDS
    }
    if set(inventories) != expected:
        raise Stage5RunError("approved stage-4 launch matrix mismatch")

    analyses = {
        prototype_id: _read_json(
            STAGE2_ROOT / prototype_id / "prototype_analysis.json"
        )
        for prototype_id in PROTOTYPE_IDS
    }
    provenance = {
        "stage2_manifest_sha256": _sha256(STAGE2_ROOT / "manifest.json"),
        "stage4_manifest_sha256": _sha256(manifest_path),
        "stage4_approval_sha256": _sha256(APPROVAL_PATH),
        "stage5_contract_sha256": _sha256(CONTRACT_PATH),
    }
    return contract, inventories, analyses, provenance


def run(output: Path) -> None:
    if output.exists():
        raise Stage5RunError(f"formal stage-5 output already exists: {output}")
    contract, inventories, analyses, provenance = _load_inputs()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="stage5_global_selection_",
        dir=str(output.parent),
    ) as directory:
        temporary = Path(directory)
        task_rows: list[dict[str, Any]] = []
        triple_previews: list[Path] = []
        total_edges = 0
        total_selected = 0
        complete_count = 0
        unresolved_count = 0
        blocking_pair_counts: Counter[str] = Counter()

        for prototype_id in PROTOTYPE_IDS:
            for seed in SEEDS:
                inventory = inventories[(prototype_id, seed)]
                try:
                    conflict_graph = build_conflict_graph(inventory, contract)
                    selection = select_global_units(
                        inventory,
                        conflict_graph,
                        contract,
                    )
                    validate_global_selection(selection, conflict_graph)
                except Stage5SelectionError as exc:
                    raise Stage5RunError(
                        f"{prototype_id} seed {seed} selection failed: {exc}"
                    ) from exc

                case = temporary / prototype_id / f"seed_{seed}"
                case.mkdir(parents=True)
                graph_path = case / "candidate_conflict_graph.json"
                selection_path = case / "global_unit_selection.json"
                single_path = case / "global_unit_selection.png"
                triple_path = case / "global_unit_selection_triple_repeat.png"
                _write_json(graph_path, conflict_graph)
                _write_json(selection_path, selection)
                render_global_selection(
                    analyses[prototype_id],
                    inventory,
                    conflict_graph,
                    selection,
                    single_path,
                    triple_repeat=False,
                )
                render_global_selection(
                    analyses[prototype_id],
                    inventory,
                    conflict_graph,
                    selection,
                    triple_path,
                    triple_repeat=True,
                )
                triple_previews.append(triple_path)

                total_edges += conflict_graph["edge_count"]
                total_selected += selection["selected_candidate_count"]
                if selection["feasible"]:
                    complete_count += 1
                else:
                    unresolved_count += 1
                    for pair in selection["blocking_lane_pairs"]:
                        blocking_pair_counts[
                            (
                                f'{prototype_id}:'
                                f'{pair["first_lane_id"]}×'
                                f'{pair["second_lane_id"]}'
                            )
                        ] += 1
                files = [
                    graph_path,
                    selection_path,
                    single_path,
                    triple_path,
                ]
                task_rows.append(
                    {
                        "task_id": (
                            f"{prototype_id}__seed_{seed}"
                            "__global_unit_selection_v1"
                        ),
                        "prototype_id": prototype_id,
                        "seed": seed,
                        "state": selection["status"],
                        "feasible": selection["feasible"],
                        "lane_count": selection["lane_count"],
                        "selected_candidate_count": selection[
                            "selected_candidate_count"
                        ],
                        "conflict_edge_count": conflict_graph["edge_count"],
                        "blocking_lane_pairs": selection[
                            "blocking_lane_pairs"
                        ],
                        "selection_digest": selection["selection_digest"],
                        "conflict_graph_digest": conflict_graph[
                            "conflict_graph_digest"
                        ],
                        "files": {
                            path.name: {
                                "path": str(path.relative_to(temporary)).replace(
                                    "\\",
                                    "/",
                                ),
                                "sha256": _sha256(path),
                            }
                            for path in files
                        },
                    }
                )

        contact_sheet = temporary / "stage5_global_selection_contact_sheet.png"
        render_contact_sheet(
            triple_previews,
            contact_sheet,
            columns=3,
            cell_size=(680, 390),
        )
        _write_readme(temporary / "README.md")
        manifest = {
            "schema": "dynamic_branch_stage5_global_selection_manifest_v1",
            "stage": "5",
            "contract_id": contract["contract_id"],
            "prototype_ids": list(PROTOTYPE_IDS),
            "seeds": list(SEEDS),
            "task_count": len(task_rows),
            "processed_task_count": len(task_rows),
            "processing_failure_count": 0,
            "complete_composition_count": complete_count,
            "unresolved_composition_count": unresolved_count,
            "total_selected_candidate_count": total_selected,
            "total_cross_unit_conflict_edge_count": total_edges,
            "blocking_pair_counts": dict(sorted(blocking_pair_counts.items())),
            "scope": {
                "global_unit_selection_present": True,
                "whole_composition_outputs_present": complete_count,
                "unresolved_conflicts_preserved": unresolved_count,
                "new_curve_generation_present": False,
                "curve_mutation_present": False,
                "leaves_present": False,
                "buds_present": False,
                "curl_heads_present": False,
            },
            "selection_policy": {
                **contract["selection"],
                "partial_composition_published_for_infeasible_task": False,
            },
            "review_gate": {
                "status": "global_unit_selection_pending_visual_review",
                "numeric_checks_cannot_auto_approve_visual_gate": True,
                "stage6_unlocked": False,
            },
            "contact_sheet": {
                "path": contact_sheet.name,
                "sha256": _sha256(contact_sheet),
            },
            "provenance": provenance,
            "tasks": task_rows,
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.replace(output)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    run(args.output.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage5RunError as exc:
        raise SystemExit(f"stage-5 run error: {exc}") from exc
