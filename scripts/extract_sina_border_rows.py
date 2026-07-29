#!/usr/bin/env python3
"""Crop individual border rows from the Sina traditional-border web gallery."""

from __future__ import annotations

import csv
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "data"
    / "source_candidates"
    / "web_independent_batch4_20260715"
    / "original_sources"
    / "sina_traditional_borders"
)
OUTPUT = (
    ROOT
    / "data"
    / "source_candidates"
    / "web_independent_batch4_20260715"
    / "sina_rows"
)


ROW_BOXES = {
    1: [(20, 45, 680, 185), (20, 210, 680, 355), (20, 380, 680, 530), (20, 555, 680, 715)],
    2: [(20, 45, 680, 185), (20, 210, 680, 355), (20, 380, 680, 530), (20, 555, 680, 715)],
    3: [
        (20, 35, 680, 165),
        (20, 180, 680, 305),
        (20, 325, 680, 450),
        (20, 470, 680, 595),
        (20, 615, 680, 750),
    ],
    4: [(20, 45, 680, 200), (20, 220, 680, 375), (20, 400, 680, 555), (20, 580, 680, 745)],
    5: [
        (20, 45, 680, 175),
        (20, 190, 680, 320),
        (20, 335, 680, 465),
        (20, 480, 680, 610),
        (20, 625, 680, 755),
    ],
    6: [
        (20, 35, 680, 165),
        (20, 180, 680, 310),
        (20, 325, 680, 455),
        (20, 470, 680, 600),
        (20, 615, 680, 755),
    ],
    7: [
        (20, 35, 680, 165),
        (20, 180, 680, 310),
        (20, 325, 680, 455),
        (20, 470, 680, 600),
        (20, 615, 680, 755),
    ],
    8: [
        (20, 35, 680, 165),
        (20, 180, 680, 310),
        (20, 325, 680, 455),
        (20, 470, 680, 600),
        (20, 615, 680, 755),
    ],
    9: [(20, 35, 680, 205), (20, 220, 680, 390), (20, 405, 680, 575), (20, 590, 680, 760)],
}


SOURCE_PAGE = "https://cj.sina.com.cn/articles/view/1872762823/p6fa017c702702b0dg"


def isolate_motif(image: Image.Image) -> Image.Image:
    gray = np.asarray(image.convert("L"))
    mask = gray < 242
    binary = mask.astype(np.uint8)
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, image.width // 4), 1)),
    )
    detection = binary.copy()
    detection[horizontal > 0] = 0
    active_rows = (detection.sum(axis=1) > 2).astype(np.uint8)
    active_rows = cv2.morphologyEx(
        active_rows[:, None], cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9))
    )[:, 0]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(active_rows[:, None], connectivity=8)
    if count > 1:
        bands = []
        for label in range(1, count):
            top = int(stats[label, cv2.CC_STAT_TOP])
            height = int(stats[label, cv2.CC_STAT_HEIGHT])
            bottom = top + height
            score = int(detection[top:bottom].sum())
            bands.append((score, height, top, bottom))
        _, _, top, bottom = max(bands)
        top = max(0, top - 3)
        bottom = min(image.height, bottom + 3)
        mask = mask[top:bottom]
        image = image.crop((0, top, image.width, bottom))
    components = cv2.findNonZero(mask.astype(np.uint8))
    if components is None:
        return image
    x, y, width, height = cv2.boundingRect(components)
    padding = 8
    left = max(0, x - padding)
    top = max(0, y - padding)
    right = min(image.width, x + width + padding)
    bottom = min(image.height, y + height + padding)
    return image.crop((left, top, right, bottom))


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT.glob("sina_*.png"):
        stale.unlink()
    rows: list[dict[str, object]] = []
    output_index = 0
    for sheet_index, boxes in ROW_BOXES.items():
        source = SOURCE / f"sina_{sheet_index:02d}.jpg"
        with Image.open(source) as image:
            for row_index, box in enumerate(boxes, start=1):
                output_index += 1
                crop = image.crop(box).convert("L")
                crop = isolate_motif(ImageOps.autocontrast(crop, cutoff=1))
                crop = ImageOps.expand(crop, border=8, fill=255)
                output = OUTPUT / f"sina_{output_index:02d}_sheet{sheet_index:02d}_row{row_index:02d}.png"
                crop.save(output, optimize=True)
                rows.append(
                    {
                        "file": output.name,
                        "source_file": source.name,
                        "sheet_index": sheet_index,
                        "row_index": row_index,
                        "crop_box": ",".join(map(str, box)),
                        "source_page": SOURCE_PAGE,
                        "rights": "web research candidate; copyright not independently cleared",
                    }
                )
    with (OUTPUT / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"rows={len(rows)}; output={OUTPUT}")


if __name__ == "__main__":
    main()
