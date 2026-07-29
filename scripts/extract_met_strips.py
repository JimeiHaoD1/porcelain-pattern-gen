#!/usr/bin/env python3
"""Crop public-domain vine borders from three Met ornament plates."""

from __future__ import annotations

import csv
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = (
    ROOT
    / "data"
    / "source_candidates"
    / "strict_2d_lineart_batch3_20260715"
    / "original_sources"
    / "met_public_domain"
)
OUTPUT_DIR = (
    ROOT
    / "data"
    / "source_candidates"
    / "strict_2d_lineart_batch3_20260715"
    / "met_crops"
)


CROPS = [
    ("DP837046_plate7.jpg", (4, 4, 596, 62), "met_01_plate7_top_vine.png", "406539"),
    ("DP837047_plate8.jpg", (4, 4, 596, 60), "met_02_plate8_top_vine.png", "406540"),
    ("DP837047_plate8.jpg", (4, 154, 596, 207), "met_03_plate8_bottom_vine.png", "406540"),
    ("DP837048_plate9.jpg", (4, 153, 596, 207), "met_04_plate9_bottom_vine.png", "406541"),
]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for source_name, box, output_name, object_id in CROPS:
        source = SOURCE_DIR / source_name
        with Image.open(source) as image:
            crop = ImageOps.autocontrast(image.convert("L").crop(box), cutoff=1)
            gray = np.asarray(crop)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            crop = Image.fromarray(binary)
            crop = ImageOps.expand(crop, border=8, fill=255)
            crop.save(OUTPUT_DIR / output_name, optimize=True)
        rows.append(
            {
                "file": output_name,
                "source_file": source_name,
                "crop_box": ",".join(map(str, box)),
                "source_page": f"https://www.metmuseum.org/art/collection/search/{object_id}",
                "rights": "The Met Open Access; Public Domain",
            }
        )

    with (OUTPUT_DIR / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"crops={len(rows)}; output={OUTPUT_DIR}")


if __name__ == "__main__":
    main()
