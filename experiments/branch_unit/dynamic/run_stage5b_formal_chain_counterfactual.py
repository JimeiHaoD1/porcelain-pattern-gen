#!/usr/bin/env python3
"""One counterfactual proving combined prototype variants reach formal L1 output."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from prototype_strategy_v1 import load_prototype_strategy_registry, resolve_prototype_strategy
from render_global_l1_flow import render_png
from run_stage3b_l1_flow import _load_inputs, generate_prototype_case


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_stage5b_formal_chain_counterfactual_v2"
PROTOTYPE_ID = "proto_sw_1_1"
PRODUCTION_SEED = 4101
VARIANT_IDS = ("expanded", "compact")


class FormalChainCounterfactualError(RuntimeError):
    pass


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _root_signature(plan: Mapping[str, Any]) -> list[float]:
    return [round(float(row["root_s"]), 6) for row in plan["lanes"]]


def _geometry_signature(plan: Mapping[str, Any]) -> list[list[list[float]]]:
    return [
        [
            [round(float(value), 5) for value in point]
            for point in (lane["root"], lane["target"])
        ]
        for lane in plan["lanes"]
    ]


def _candidate_signature(inventory: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (
            str(row["candidate_id"]),
            round(float(row["root_s"]), 6),
            tuple(round(float(value), 5) for value in row["root"]),
            tuple(round(float(value), 5) for value in row["target"]),
            tuple(str(value) for value in row["hard_rejections"]),
        )
        for row in inventory["candidates"]
    ]


def _render_pair(images: Sequence[Path], labels: Sequence[str], output: Path) -> None:
    loaded = [Image.open(path).convert("RGB") for path in images]
    try:
        cell_width = 760
        cell_height = round(loaded[0].height * cell_width / loaded[0].width)
        header = 76
        result = Image.new("RGB", (cell_width * 2, header + cell_height), "#f2f0ea")
        draw = ImageDraw.Draw(result)
        draw.text((24, 15), "5B-4 正式链反事实：同一分支种子，仅替换主干组合变体", font=_font(25, bold=True), fill="#18242d")
        for index, (image, label) in enumerate(zip(loaded, labels)):
            resized = image.resize((cell_width, cell_height), Image.Resampling.LANCZOS)
            result.paste(resized, (index * cell_width, header))
            draw.text((index * cell_width + 24, 49), label, font=_font(15, bold=True), fill="#59666e")
        result.save(output, "PNG", optimize=True)
    finally:
        for image in loaded:
            image.close()


def run(output: Path) -> None:
    if output.exists():
        raise FormalChainCounterfactualError(f"output already exists: {output}")
    registry = load_prototype_strategy_registry()
    strategy = resolve_prototype_strategy({"prototype_id": PROTOTYPE_ID}, registry)
    (
        inputs,
        prior,
        feedback_prior,
        curve_geometry_prior,
        contract,
        stage3_plan_contract,
        _,
    ) = _load_inputs()
    payload = inputs[PROTOTYPE_ID]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage5b_chain_cf_", dir=str(output.parent)) as directory:
        temporary = Path(directory)
        results: dict[str, Mapping[str, Any]] = {}
        images: list[Path] = []
        for variant_id in VARIANT_IDS:
            result = generate_prototype_case(
                payload=payload,
                prototype_strategy=strategy,
                production_seed=PRODUCTION_SEED,
                prior=prior,
                feedback_prior=feedback_prior,
                curve_geometry_prior=curve_geometry_prior,
                contract=contract,
                stage3_plan_contract=stage3_plan_contract,
                backbone_seed_override=4101,
                branch_seed_override=4101,
                backbone_rho=1.0,
                prototype_variant_id=variant_id,
            )
            results[variant_id] = result
            case = temporary / variant_id
            case.mkdir()
            _write_json(case / "strict_p0_variant.json", result["variant_strict"].as_dict())
            _write_json(case / "prototype_analysis_variant.json", result["variant_analysis"])
            _write_json(case / "flower_mount_plan.json", result["flower_mount_plan"])
            _write_json(case / "global_l1_candidate_inventory.json", result["inventory"])
            _write_json(case / "global_l1_flow_plan.json", result["plan"])
            image = case / "formal_l1_flow.png"
            render_png(result["variant_analysis"], result["plan"], image)
            images.append(image)
        first, second = (results[value] for value in VARIANT_IDS)
        checks = {
            "variant_analysis_changed": first["variant_analysis"]["backbone"] != second["variant_analysis"]["backbone"],
            "flower_mount_geometry_changed": first["flower_mount_plan"]["mounts"] != second["flower_mount_plan"]["mounts"],
            "formal_candidate_pool_changed": _candidate_signature(first["inventory"]) != _candidate_signature(second["inventory"]),
            "selected_l1_roots_changed": _root_signature(first["plan"]) != _root_signature(second["plan"]),
            "selected_l1_geometry_changed": _geometry_signature(first["plan"]) != _geometry_signature(second["plan"]),
            "canonical_repeat_layout_changed": first["plan"]["repeat_layout"] != second["plan"]["repeat_layout"],
        }
        if not all(checks.values()):
            failed = [name for name, value in checks.items() if not value]
            raise FormalChainCounterfactualError(
                "combined prototype variant did not propagate through: " + ", ".join(failed)
            )
        _render_pair(
            images,
            [
                f"expanded｜候选 {first['inventory']['candidate_count']}｜选择根位 {_root_signature(first['plan'])}",
                f"compact｜候选 {second['inventory']['candidate_count']}｜选择根位 {_root_signature(second['plan'])}",
            ],
            temporary / "stage5b_formal_chain_counterfactual.png",
        )
        _write_json(
            temporary / "counterfactual.json",
            {
                "schema": "dynamic_branch_stage5b_formal_chain_counterfactual_v1",
                "stage": "5B-4",
                "prototype_id": PROTOTYPE_ID,
                "production_seed": PRODUCTION_SEED,
                "fixed_backbone_seed": 4101,
                "fixed_branch_seed": 4101,
                "changed_variable": "prototype_variant_id",
                "variant_ids": list(VARIANT_IDS),
                "checks": checks,
                "review_gate": {
                    "status": "VISUAL_REVIEW_PENDING",
                    "counterfactual_only_proves_active_chain_consumption": True,
                },
            },
        )
        temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.output.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
