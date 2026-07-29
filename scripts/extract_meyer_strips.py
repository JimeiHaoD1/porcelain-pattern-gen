#!/usr/bin/env python3
"""Crop visually approved vine strips from Meyer public-domain plates."""

from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = (
    ROOT
    / "data"
    / "source_candidates"
    / "strict_2d_lineart_batch3_20260715"
    / "original_sources"
    / "meyer_1898"
)
OUTPUT_DIR = (
    ROOT
    / "data"
    / "source_candidates"
    / "strict_2d_lineart_batch3_20260715"
    / "meyer_crops"
)


# Boxes were set after inspecting each full-resolution plate.  The crop stays
# inside the printed figure frame so page numbers and surrounding figures do
# not become false branches.
CROPS = [
    (94, 7, (105, 1050, 620, 1190), "single_wave_acanthus"),
    (94, 10, (105, 1540, 620, 1695), "s_loop_flower_vine"),
    (94, 12, (105, 1765, 620, 1915), "alternating_leaf_flower_vine"),
    (95, 1, (110, 145, 620, 350), "natural_flower_vine"),
    (95, 2, (675, 145, 1175, 350), "grape_vine"),
    (95, 10, (110, 1670, 620, 1885), "looping_flower_vine"),
    (95, 11, (675, 1670, 1170, 1885), "dense_flower_scroll"),
    (96, 1, (100, 145, 610, 345), "symmetric_spiral_vine"),
    (96, 3, (100, 430, 1160, 685), "continuous_flower_scroll"),
    (96, 5, (650, 760, 1160, 975), "flower_spiral_vine"),
    (96, 7, (650, 1070, 1160, 1290), "grape_leaf_interlace"),
]


PLATE_URLS = {
    94: "https://commons.wikimedia.org/wiki/File:Orna094-Blatt-Rankenband.png",
    95: "https://commons.wikimedia.org/wiki/File:Orna095-Blatt-Rankenband.png",
    96: "https://commons.wikimedia.org/wiki/File:Orna096-Blatt-Rankenband.png",
}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT_DIR.glob("meyer_*.png"):
        stale.unlink()
    rows: list[dict[str, object]] = []
    for index, (plate, figure, box, note) in enumerate(CROPS, start=1):
        source = SOURCE_DIR / f"Orna{plate:03d}-Blatt-Rankenband.png"
        with Image.open(source) as image:
            crop = image.convert("L").crop(box)
            crop = ImageOps.autocontrast(crop, cutoff=1)
            crop = ImageOps.expand(crop, border=10, fill=255)
            output = OUTPUT_DIR / f"meyer_{index:02d}_p{plate}_fig{figure}_{note}.png"
            crop.save(output, optimize=True)
        rows.append(
            {
                "file": output.name,
                "plate": plate,
                "figure": figure,
                "crop_box": ",".join(map(str, box)),
                "visual_note": note,
                "source_file": source.name,
                "source_page": PLATE_URLS[plate],
                "rights": "Public Domain Mark 1.0; Meyer, A Handbook of Ornament (1898)",
            }
        )

    with (OUTPUT_DIR / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"crops={len(rows)}; output={OUTPUT_DIR}")


if __name__ == "__main__":
    main()
