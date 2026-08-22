#!/usr/bin/env python3
"""Create deterministic A/B blind visual sheets without assigning ratings."""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from common import ADJUDICATION_DIR, BOOTSTRAP_SEED, prototype_label, read_csv, write_csv, write_json


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    path = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size) if path.is_file() else ImageFont.load_default()


def _crop(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGB")
    if image.height > 140 and image.width > 40:
        image = image.crop((8, 80, image.width - 8, image.height - 40))
    return image


def _make_pair(
    first: Path,
    second: Path,
    output: Path,
    *,
    pair_id: str,
    prototype_id: str,
    density: str,
) -> None:
    width, height = 1800, 610
    header = 72
    half = width // 2
    canvas = Image.new("RGB", (width, height), "#f4f2ed")
    draw = ImageDraw.Draw(canvas)
    title = f"{pair_id}   {prototype_label(prototype_id)}   {density}"
    draw.text((24, 18), title, fill="#1d2a32", font=_font(25, bold=True))
    draw.text((half // 2 - 8, 20), "A", fill="#1d2a32", font=_font(28, bold=True))
    draw.text((half + half // 2 - 8, 20), "B", fill="#1d2a32", font=_font(28, bold=True))
    draw.line((half, header, half, height - 10), fill="#b7c0c5", width=2)
    for panel, path in enumerate((first, second)):
        image = _crop(path)
        image.thumbnail((half - 24, height - header - 18), Image.Resampling.LANCZOS)
        x = panel * half + (half - image.width) // 2
        y = header + (height - header - image.height) // 2
        canvas.paste(image, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def _run_h2a(h2a_dir: Path) -> None:
    rows = read_csv(h2a_dir / "paired_metrics.csv")
    rng = random.Random(20260821)
    key_rows: list[dict[str, Any]] = []
    blind_dir = h2a_dir / "blind_pairs"
    blind_dir.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, 1):
        old_name = row.get("old_render_file", "")
        h2_name = row.get("h2_render_file", "")
        if not old_name or not h2_name:
            continue
        old_path, h2_path = h2a_dir / old_name, h2a_dir / h2_name
        if rng.random() < 0.5:
            methods, paths = ("old", "new"), (old_path, h2_path)
        else:
            methods, paths = ("new", "old"), (h2_path, old_path)
        pair_id = f"A{index:03d}"
        output = blind_dir / f"{pair_id}.png"
        _make_pair(
            paths[0], paths[1], output,
            pair_id=pair_id,
            prototype_id=row["prototype_id"],
            density=row["density_level"],
        )
        key_rows.append(
            {
                "pair_id": pair_id,
                "context_id": row["context_id"],
                "prototype_id": row["prototype_id"],
                "backbone_variant": row["backbone_variant"],
                "density_level": row["density_level"],
                "production_seed": row["production_seed"],
                "A_method": methods[0],
                "B_method": methods[1],
                "blind_image": str(output.relative_to(h2a_dir)).replace("\\", "/"),
            }
        )
    write_csv(
        h2a_dir / "blind_key.csv",
        key_rows,
        (
            "pair_id", "context_id", "prototype_id", "backbone_variant", "density_level",
            "production_seed", "A_method", "B_method", "blind_image",
        ),
    )
    write_json(h2a_dir / "blind_manifest.json", {"randomization_seed": 20260821, "blind_pair_count": len(key_rows)})


def _run_h2b(h2b_dir: Path) -> None:
    cases = read_csv(h2b_dir / "cases.csv")
    rng = random.Random(BOOTSTRAP_SEED)
    key_rows: list[dict[str, Any]] = []
    rating_rows: list[dict[str, Any]] = []
    blind_dir = h2b_dir / "blind_pairs"
    blind_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        old_name = case.get("old_render_file", "")
        h2_name = case.get("h2_render_file", "")
        if not old_name or not h2_name:
            continue
        old_path = h2b_dir / old_name
        h2_path = h2b_dir / h2_name
        if not old_path.is_file() or not h2_path.is_file():
            continue
        if rng.random() < 0.5:
            methods = ("old", "h2")
            paths = (old_path, h2_path)
        else:
            methods = ("h2", "old")
            paths = (h2_path, old_path)
        pair_id = case["pair_id"]
        output = blind_dir / f"{pair_id}.png"
        _make_pair(
            paths[0],
            paths[1],
            output,
            pair_id=pair_id,
            prototype_id=case["prototype_id"],
            density=case["density_level"],
        )
        key_rows.append(
            {
                "pair_id": pair_id,
                "prototype_id": case["prototype_id"],
                "backbone_variant": case["backbone_variant"],
                "density_level": case["density_level"],
                "production_seed": case["production_seed"],
                "A_method": methods[0],
                "B_method": methods[1],
                "blind_image": str(output.relative_to(h2b_dir)).replace("\\", "/"),
            }
        )
        rating_rows.append(
            {
                "pair_id": pair_id,
                "preferred_A_B_tie": "",
                "structural_coherence_A_1to5": "",
                "structural_coherence_B_1to5": "",
                "spatial_balance_A_1to5": "",
                "spatial_balance_B_1to5": "",
                "hierarchy_readability_A_1to5": "",
                "hierarchy_readability_B_1to5": "",
                "overall_quality_A_1to5": "",
                "overall_quality_B_1to5": "",
                "notes": "",
            }
        )
    write_csv(
        h2b_dir / "blind_key.csv",
        key_rows,
        (
            "pair_id", "prototype_id", "backbone_variant", "density_level",
            "production_seed", "A_method", "B_method", "blind_image",
        ),
    )
    write_csv(
        h2b_dir / "visual_rating_template.csv",
        rating_rows,
        (
            "pair_id", "preferred_A_B_tie",
            "structural_coherence_A_1to5", "structural_coherence_B_1to5",
            "spatial_balance_A_1to5", "spatial_balance_B_1to5",
            "hierarchy_readability_A_1to5", "hierarchy_readability_B_1to5",
            "overall_quality_A_1to5", "overall_quality_B_1to5", "notes",
        ),
    )
    write_json(
        h2b_dir / "blind_manifest.json",
        {
            "randomization_seed": BOOTSTRAP_SEED,
            "blind_pair_count": len(key_rows),
            "method_labels_visible_in_images": False,
            "ratings_filled_by_codex": False,
        },
    )


def run(root: Path) -> None:
    _run_h2a(root / "h2a")
    _run_h2b(root / "h2b")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ADJUDICATION_DIR)
    args = parser.parse_args()
    run(args.root.resolve())
    print(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
