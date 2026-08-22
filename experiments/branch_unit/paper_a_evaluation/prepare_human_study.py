#!/usr/bin/env python3
"""Prepare blinded RQ4 human-evaluation stimuli and empty rating sheets."""

from __future__ import annotations

import argparse
import csv
import itertools
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
METHODS = ("FixedSlot", "LocalGreedy", "Ours")
PROTOTYPES = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
DENSITIES = ("simple", "medium", "rich")
VARIANTS = ("expanded", "compact", "swept")
FORM_NAMES = ("F1", "F2", "F3")


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


def _eligible_contexts(rows: Sequence[Mapping[str, str]], run_root: Path) -> list[dict[str, str]]:
    by_case: dict[str, dict[str, Mapping[str, str]]] = defaultdict(dict)
    for row in rows:
        by_case[str(row["case_id"])][str(row["method"])] = row

    eligible: list[dict[str, str]] = []
    for case_id, method_rows in by_case.items():
        if not all(method in method_rows for method in METHODS):
            continue
        if not all(method_rows[method].get("unit_generation_success") == "1" for method in METHODS):
            continue
        source_files = {
            method: run_root / str(method_rows[method]["method_dir"]) / "formal_triple.png"
            for method in METHODS
        }
        if not all(path.is_file() for path in source_files.values()):
            continue
        anchor = method_rows["Ours"]
        eligible.append(
            {
                "case_id": case_id,
                "prototype_id": str(anchor["prototype_id"]),
                "backbone_variant": str(anchor["backbone_variant"]),
                "density_level": str(anchor["density_level"]),
                "replicate": str(anchor["replicate"]),
                "production_seed": str(anchor["production_seed"]),
                **{f"{method}_png": str(path.resolve()) for method, path in source_files.items()},
            }
        )
    return eligible


def _select_contexts(
    eligible: Sequence[dict[str, str]],
    per_prototype: int,
    seed: int,
) -> list[dict[str, str]]:
    rng = random.Random(seed)
    tie_break = {row["case_id"]: rng.random() for row in eligible}
    selected: list[dict[str, str]] = []
    for prototype in PROTOTYPES:
        candidates = [row for row in eligible if row["prototype_id"] == prototype]
        if len(candidates) < per_prototype:
            raise RuntimeError(
                f"{prototype}: only {len(candidates)} fully paired contexts, need {per_prototype}"
            )
        best_combo: tuple[dict[str, str], ...] | None = None
        best_score: tuple[float, ...] | None = None
        for combo in itertools.combinations(candidates, per_prototype):
            density = Counter(row["density_level"] for row in combo)
            variant = Counter(row["backbone_variant"] for row in combo)
            replicate = Counter(row["replicate"] for row in combo)
            density_penalty = sum(abs(density[level] - per_prototype / 3) for level in DENSITIES)
            variant_penalty = sum(abs(variant[level] - per_prototype / 3) for level in VARIANTS)
            replicate_penalty = sum(abs(replicate[str(level)] - per_prototype / 2) for level in (1, 2))
            duplicate_strata = per_prototype - len(
                {(row["backbone_variant"], row["density_level"]) for row in combo}
            )
            score = (
                density_penalty,
                variant_penalty,
                duplicate_strata,
                replicate_penalty,
                sum(tie_break[row["case_id"]] for row in combo),
            )
            if best_score is None or score < best_score:
                best_score = score
                best_combo = combo
        assert best_combo is not None
        selected.extend(best_combo)

    rng.shuffle(selected)
    used_ids: set[str] = set()
    for row in selected:
        while True:
            blind_id = f"S{rng.randrange(100000, 1000000)}"
            if blind_id not in used_ids:
                used_ids.add(blind_id)
                break
        row["blind_stimulus_id"] = blind_id
        order = list(METHODS)
        rng.shuffle(order)
        row["base_order"] = ";".join(order)
    return selected


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
    ):
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _panel(source_path: Path, width: int = 580) -> Image.Image:
    with Image.open(source_path) as source:
        image = source.convert("RGB")
    # The renderer uses a fixed 1240x618 canvas.  Relative coordinates retain
    # only the central three-period drawing frame, excluding title and IDs.
    crop = image.crop(
        (
            round(image.width * 18 / 1240),
            round(image.height * 88 / 618),
            round(image.width * 1223 / 1240),
            round(image.height * 563 / 618),
        )
    )
    height = round(width * crop.height / crop.width)
    return crop.resize((width, height), Image.Resampling.LANCZOS)


def _render_triplet(
    source_by_method: Mapping[str, Path],
    order: Sequence[str],
    output_path: Path,
) -> None:
    panels = [_panel(source_by_method[method]) for method in order]
    panel_width, panel_height = panels[0].size
    margin = 18
    gap = 14
    header = 52
    footer = 18
    canvas = Image.new(
        "RGB",
        (margin * 2 + panel_width * 3 + gap * 2, header + panel_height + footer),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    font = _font(30)
    for index, (label, panel) in enumerate(zip(("A", "B", "C"), panels)):
        x = margin + index * (panel_width + gap)
        canvas.paste(panel, (x, header))
        box = draw.textbbox((0, 0), label, font=font)
        text_width = box[2] - box[0]
        draw.text((x + (panel_width - text_width) / 2, 8), label, fill="#1f2933", font=font)
        draw.rectangle((x, header, x + panel_width - 1, header + panel_height - 1), outline="#b9c1c9")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=True)


def _cyclic_orders(base_order: Sequence[str]) -> list[tuple[str, str, str]]:
    return [
        tuple(base_order[index:] + base_order[:index])  # type: ignore[return-value]
        for index in range(3)
    ]


def run(
    matrix_c_csv: Path,
    run_root: Path,
    output_dir: Path,
    seed: int,
    participants: int,
    stimuli_per_participant: int,
) -> None:
    rows = _read_csv(matrix_c_csv)
    eligible = _eligible_contexts(rows, run_root)
    selected = _select_contexts(eligible, per_prototype=6, seed=seed)
    if len(selected) != 30:
        raise RuntimeError(f"expected 30 selected contexts, got {len(selected)}")

    stimuli_dir = output_dir / "human_stimuli"
    selected_rows: list[dict[str, object]] = []
    key_rows: list[dict[str, object]] = []
    for row in selected:
        source_by_method = {method: Path(row[f"{method}_png"]) for method in METHODS}
        base_order = row["base_order"].split(";")
        orders = _cyclic_orders(base_order)
        selected_rows.append(
            {
                "blind_stimulus_id": row["blind_stimulus_id"],
                "case_id": row["case_id"],
                "prototype_id": row["prototype_id"],
                "backbone_variant": row["backbone_variant"],
                "density_level": row["density_level"],
                "replicate": row["replicate"],
                "production_seed": row["production_seed"],
            }
        )
        for form_index, order in enumerate(orders):
            form_name = FORM_NAMES[form_index]
            output_path = stimuli_dir / f"{row['blind_stimulus_id']}_{form_name}.png"
            _render_triplet(source_by_method, order, output_path)
            for panel_label, method in zip(("A", "B", "C"), order):
                key_rows.append(
                    {
                        "blind_stimulus_id": row["blind_stimulus_id"],
                        "order_form": form_name,
                        "panel_label": panel_label,
                        "method": method,
                        "case_id": row["case_id"],
                        "prototype_id": row["prototype_id"],
                        "backbone_variant": row["backbone_variant"],
                        "density_level": row["density_level"],
                        "replicate": row["replicate"],
                        "production_seed": row["production_seed"],
                        "stimulus_file": str(output_path.resolve()),
                        "source_png": str(source_by_method[method].resolve()),
                    }
                )

    _write_csv(output_dir / "selected_contexts.csv", selected_rows)
    _write_csv(output_dir / "blind_key.csv", key_rows)

    assignment_rows: list[dict[str, object]] = []
    rating_rows: list[dict[str, object]] = []
    for participant_index in range(participants):
        participant_id = f"P{participant_index + 1:02d}"
        form_name = FORM_NAMES[participant_index % 3]
        assignments = [
            selected[(participant_index + offset) % len(selected)]
            for offset in range(stimuli_per_participant)
        ]
        random.Random(seed + participant_index + 1).shuffle(assignments)
        for sequence, row in enumerate(assignments, start=1):
            stimulus_file = stimuli_dir / f"{row['blind_stimulus_id']}_{form_name}.png"
            assignment = {
                "participant_id": participant_id,
                "presentation_sequence": sequence,
                "blind_stimulus_id": row["blind_stimulus_id"],
                "order_form": form_name,
                "stimulus_file": str(stimulus_file.resolve()),
            }
            assignment_rows.append(assignment)
            for panel_label in ("A", "B", "C"):
                rating_rows.append(
                    {
                        **assignment,
                        "panel_label": panel_label,
                        "structural_coherence_1_5": "",
                        "visual_balance_1_5": "",
                        "vine_scroll_structural_plausibility_1_5": "",
                    }
                )

    _write_csv(output_dir / "participant_assignments.csv", assignment_rows)
    _write_csv(output_dir / "rating_template.csv", rating_rows)
    _write_csv(output_dir / "ratings_raw.csv", rating_rows)
    _write_csv(
        output_dir / "participant_background_template.csv",
        [
            {
                "participant_id": f"P{index + 1:02d}",
                "art_background_yes_no": "",
                "design_background_yes_no": "",
                "ceramics_background_yes_no": "",
                "traditional_pattern_background_yes_no": "",
                "years_of_relevant_experience": "",
            }
            for index in range(participants)
        ],
    )
    _write_csv(
        output_dir / "rating_codebook.csv",
        [
            {
                "field": "structural_coherence_1_5",
                "prompt": "整体枝组是否连贯、协调且没有明显拼贴或拥挤感？",
                "scale": "1=非常差;2=较差;3=一般;4=较好;5=非常好",
            },
            {
                "field": "visual_balance_1_5",
                "prompt": "三周期画面中的疏密、上下分配与视觉重心是否平衡？",
                "scale": "1=非常不平衡;2=较不平衡;3=一般;4=较平衡;5=非常平衡",
            },
            {
                "field": "vine_scroll_structural_plausibility_1_5",
                "prompt": "仅从结构看，该方案是否符合二方连续缠枝纹的组织逻辑？",
                "scale": "1=非常不符合;2=较不符合;3=一般;4=较符合;5=非常符合",
            },
        ],
    )

    # Design-balance table is a direct count, not an acceptance claim.
    context_counts = Counter(row["blind_stimulus_id"] for row in assignment_rows)
    form_counts = Counter((row["blind_stimulus_id"], row["order_form"]) for row in assignment_rows)
    _write_csv(
        output_dir / "assignment_balance.csv",
        [
            {
                "blind_stimulus_id": row["blind_stimulus_id"],
                "participant_ratings": context_counts[row["blind_stimulus_id"]],
                "F1_ratings": form_counts[(row["blind_stimulus_id"], "F1")],
                "F2_ratings": form_counts[(row["blind_stimulus_id"], "F2")],
                "F3_ratings": form_counts[(row["blind_stimulus_id"], "F3")],
            }
            for row in selected
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    default_run_root = (
        REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq2" / "matrix_c_four_methods"
    )
    parser.add_argument("--matrix-c-csv", type=Path, default=default_run_root / "raw_results.csv")
    parser.add_argument("--run-root", type=Path, default=default_run_root)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq4" / "human_evaluation",
    )
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--participants", type=int, default=30)
    parser.add_argument("--stimuli-per-participant", type=int, default=15)
    args = parser.parse_args()
    run(
        args.matrix_c_csv.resolve(),
        args.run_root.resolve(),
        args.output_dir.resolve(),
        args.seed,
        args.participants,
        args.stimuli_per_participant,
    )
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
