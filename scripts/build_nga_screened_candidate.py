#!/usr/bin/env python3
"""Crop and document the one NGA border that passed StructVine screening."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(r"D:\sdxl\chanzhi_sw_clean")
SOURCE = ROOT / "data/source_candidates/web_independent_batch4_20260715/original_sources/nga_independent/NGA02_wall_paper_border.jpg"
OUTPUT = ROOT / "data/source_candidates/web_independent_batch4_20260715/nga_screened_20260716"
DESTINATION = OUTPUT / "AUX_NGA02_flat_flower_vine_border.jpg"
CROP_BOX = (35, 580, 2965, 1300)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        crop = image.crop(CROP_BOX)
        crop.save(DESTINATION, quality=95, optimize=True)

    digest = hashlib.sha256(DESTINATION.read_bytes()).hexdigest()
    row = {
        "id": "NGA02",
        "file": DESTINATION.name,
        "tier": "auxiliary",
        "source_group": "National Gallery of Art",
        "source_image_unit": "NGA artwork 28168 / accession 1943.8.16077",
        "source_page": "https://www.nga.gov/artworks/28168-wall-paper-border",
        "direct_url": "https://api.nga.gov/iiif/dc3c3d12-1545-46fb-9b69-9b48fb4a46a4/full/full/0/default.jpg",
        "rights": "Public domain; NGA Open Access",
        "crop_box": ",".join(map(str, CROP_BOX)),
        "visual_note": "Flat painted repeat with a visible winding stem, attached leaves, and repeated flower nodes; color reference only.",
        "dedup_note": "Visually screened; source-independent from the Chinese and Cooper Hewitt groups.",
        "sha256": digest,
    }
    with (OUTPUT / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    (OUTPUT / "README.md").write_text(
        "# NGA 辅助候选\n\n"
        "仅 1 条彩色平面设计。主藤、叶片连接和花位可辨，但不是单色线稿，"
        "只能作为重制/结构参考，不能并入严格线稿训练集。\n",
        encoding="utf-8",
    )
    print(DESTINATION)


if __name__ == "__main__":
    main()
