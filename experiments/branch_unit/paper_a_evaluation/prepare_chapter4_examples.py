#!/usr/bin/env python3
"""Collect the pre-registered Chapter 4 visual examples without aesthetic cherry-picking."""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1"
FIGURE_PROTOTYPES = ("proto_sw_1_1", "proto_sw_2_3", "proto_sw_3_1")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _copy_case_assets(case_dir: Path, output_dir: Path, stem: str) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}
    for suffix in ("png", "svg"):
        source = case_dir / f"formal_triple.{suffix}"
        if source.is_file():
            destination = output_dir / f"{stem}.{suffix}"
            shutil.copy2(source, destination)
            result[suffix] = str(destination.resolve())
    return result


def _formal_case_dir(formal_run: Path, row: Mapping[str, str]) -> Path:
    return formal_run / str(row["case_dir"])


def _rq1_examples(formal_rows: Sequence[dict[str, str]], formal_run: Path, output_root: Path) -> None:
    display = [
        row
        for row in formal_rows
        if row["matrix_id"] == "A"
        and row["backbone_variant"] == "expanded"
        and row["replicate"] == "1"
    ]
    display.sort(key=lambda row: (row["prototype_id"], ("simple", "medium", "rich").index(row["density_level"])))
    display_rows: list[dict[str, object]] = []
    for row in display:
        stem = f"{row['case_id']}__{row['prototype_id']}__{row['density_level']}"
        copied = _copy_case_assets(
            _formal_case_dir(formal_run, row), output_root / "examples_success", stem
        )
        display_rows.append(
            {
                "figure_panel": "6a",
                "selection_rule": "expanded backbone; replicate 1; all five prototypes and three densities",
                "case_id": row["case_id"],
                "prototype_id": row["prototype_id"],
                "density_level": row["density_level"],
                **{f"output_{key}": value for key, value in copied.items()},
            }
        )
    _write_csv(output_root / "figure_examples.csv", display_rows)

    failures = _read_csv(output_root / "failure_cases.csv")
    representatives: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in failures:
        code = row["violation_codes"]
        if code not in seen:
            seen.add(code)
            representatives.append(row)
    failure_rows: list[dict[str, object]] = []
    for row in representatives:
        case_dir = formal_run / row["case_dir"]
        stem = f"{row['case_id']}__{row['violation_codes']}"
        copied = _copy_case_assets(case_dir, output_root / "examples_failure", stem)
        failure_rows.append({**row, **{f"output_{key}": value for key, value in copied.items()}})
    _write_csv(output_root / "examples_failure" / "representative_failures.csv", failure_rows)


def _rq2_examples(matrix_run: Path, output_root: Path) -> None:
    figure_rows = _read_csv(output_root / "figure_data.csv")
    copied_rows: list[dict[str, object]] = []
    for row in figure_rows:
        panel = row["figure_panel"]
        for method in ("IndependentCurve", "FixedSlot", "LocalGreedy", "Ours"):
            relative = row.get(f"{method}_png", "")
            if not relative:
                continue
            source = matrix_run / relative
            destination = output_root / "examples_success" / f"figure_{panel}_{row['case_id']}__{method}.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            svg_source = source.with_suffix(".svg")
            svg_destination = destination.with_suffix(".svg")
            if svg_source.is_file():
                shutil.copy2(svg_source, svg_destination)
            copied_rows.append(
                {
                    "figure_panel": panel,
                    "case_id": row["case_id"],
                    "method": method,
                    "selection_metric": row["selection_metric"],
                    "output_png": str(destination.resolve()),
                    "output_svg": str(svg_destination.resolve()) if svg_destination.is_file() else "",
                }
            )
    _write_csv(output_root / "figure_examples.csv", copied_rows)

    failures = _read_csv(output_root / "failure_cases.csv")
    representatives: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in failures:
        key = (row["error_type"], row["error_message"])
        if key not in seen:
            seen.add(key)
            representatives.append(row)
    failure_rows: list[dict[str, object]] = []
    for row in representatives:
        case_id = row["case_id"]
        case_root = matrix_run / "raw_cases" / case_id / "methods"
        copied: dict[str, str] = {}
        for method in (row["method"], "Ours"):
            assets = _copy_case_assets(
                case_root / method,
                output_root / "examples_failure",
                f"{case_id}__{row['error_type']}__{method}",
            )
            for suffix, path in assets.items():
                copied[f"{method}_{suffix}"] = path
        failure_rows.append({**row, **copied})
    _write_csv(output_root / "examples_failure" / "representative_failures.csv", failure_rows)


def _rq3_examples(formal_rows: Sequence[dict[str, str]], formal_run: Path, output_root: Path) -> None:
    selections: list[tuple[str, dict[str, str]]] = []
    for row in formal_rows:
        if row["prototype_id"] not in FIGURE_PROTOTYPES:
            continue
        if (
            row["matrix_id"] == "A"
            and row["replicate"] == "1"
            and row["density_level"] == "medium"
            and row["backbone_variant"] in {"expanded", "compact", "swept"}
        ):
            selections.append(("8a_backbone", row))
        if (
            row["matrix_id"] == "A"
            and row["replicate"] == "1"
            and row["backbone_variant"] == "expanded"
            and row["density_level"] in {"simple", "medium", "rich"}
        ):
            selections.append(("8b_density", row))
        if row["matrix_id"] == "B" and int(row["replicate"]) <= 4:
            selections.append(("8c_seed", row))

    output_rows: list[dict[str, object]] = []
    for figure_panel, row in selections:
        condition = (
            row["backbone_variant"]
            if figure_panel == "8a_backbone"
            else row["density_level"]
            if figure_panel == "8b_density"
            else f"seed_bundle_{row['replicate']}"
        )
        stem = f"{row['case_id']}__{row['prototype_id']}__{condition}"
        copied = _copy_case_assets(
            _formal_case_dir(formal_run, row), output_root / "examples_control" / figure_panel, stem
        )
        output_rows.append(
            {
                "figure_panel": figure_panel,
                "selection_rule": "P1/P3/P4; replicate 1; condition fixed before viewing outputs",
                "case_id": row["case_id"],
                "prototype_id": row["prototype_id"],
                "backbone_variant": row["backbone_variant"],
                "density_level": row["density_level"],
                "production_seed": row["production_seed"],
                **{f"output_{key}": value for key, value in copied.items()},
            }
        )
    _write_csv(output_root / "figure_examples.csv", output_rows)


def run(artifact_root: Path) -> None:
    formal_run = artifact_root / "rq1_rq3" / "formal_ours"
    formal_rows = _read_csv(artifact_root / "rq3" / "raw_results.csv")
    _rq1_examples(formal_rows, formal_run, artifact_root / "rq1")
    _rq2_examples(artifact_root / "rq2" / "matrix_c_four_methods", artifact_root / "rq2")
    _rq3_examples(formal_rows, formal_run, artifact_root / "rq3")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    args = parser.parse_args()
    run(args.artifact_root.resolve())
    print(args.artifact_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
