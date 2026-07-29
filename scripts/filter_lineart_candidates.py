#!/usr/bin/env python3
"""Filter wide, mostly monochrome PDF extracts and deduplicate them for review."""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def hashes(image: Image.Image) -> tuple[int, int]:
    gray = np.asarray(image.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32)
    dh_small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    dh_bits = dh_small[:, 1:] > dh_small[:, :-1]
    dhash = sum(int(bit) << index for index, bit in enumerate(dh_bits.ravel()))
    dct = cv2.dct(gray)
    block = dct[:8, :8].copy()
    median = np.median(block.ravel()[1:])
    ph_bits = block > median
    phash = sum(int(bit) << index for index, bit in enumerate(ph_bits.ravel()))
    return dhash, phash


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def metrics(image: Image.Image) -> dict[str, float]:
    rgb = np.asarray(image.convert("RGB").resize((400, max(1, round(image.height * 400 / image.width))), Image.Resampling.LANCZOS))
    gray = rgb.mean(axis=2)
    return {
        "saturation": float((rgb.max(axis=2) - rgb.min(axis=2)).mean()),
        "white_fraction": float((gray > 235).mean()),
        "dark_fraction": float((gray < 90).mean()),
    }


def all_images(roots: list[Path]) -> list[Path]:
    return sorted(path for root in roots for path in root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--existing", nargs="*", type=Path, default=[])
    parser.add_argument("--min-width", type=int, default=200)
    parser.add_argument("--min-height", type=int, default=25)
    parser.add_argument("--min-aspect", type=float, default=2.0)
    parser.add_argument("--max-saturation", type=float, default=18.0)
    parser.add_argument("--min-white", type=float, default=0.35)
    parser.add_argument("--min-dark", type=float, default=0.01)
    parser.add_argument("--near-phash", type=int, default=5)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    existing_hashes: list[tuple[int, int, Path]] = []
    for path in all_images(args.existing):
        try:
            with Image.open(path) as image:
                dhash, phash = hashes(image)
            existing_hashes.append((dhash, phash, path))
        except OSError:
            continue

    kept_hashes: list[tuple[int, int, Path]] = []
    exact_seen: set[str] = set()
    rows: list[dict[str, object]] = []
    kept_index = 0
    for source in all_images(args.inputs):
        try:
            with Image.open(source) as image:
                image.load()
                width, height = image.size
                aspect = width / max(height, 1)
                stat = metrics(image)
                dhash, phash = hashes(image)
        except OSError:
            continue
        sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        rejection = ""
        near_match = ""
        if width < args.min_width or height < args.min_height or aspect < args.min_aspect:
            rejection = "dimension_or_aspect"
        elif stat["saturation"] > args.max_saturation:
            rejection = "too_colorful"
        elif stat["white_fraction"] < args.min_white:
            rejection = "insufficient_white_background"
        elif stat["dark_fraction"] < args.min_dark:
            rejection = "insufficient_line_content"
        elif sha256 in exact_seen:
            rejection = "exact_duplicate_in_batch"
        else:
            for _, existing_phash, existing_path in existing_hashes:
                if hamming(phash, existing_phash) <= args.near_phash:
                    rejection = "near_duplicate_existing"
                    near_match = str(existing_path)
                    break
        if not rejection:
            for _, kept_phash, kept_path in kept_hashes:
                if hamming(phash, kept_phash) <= args.near_phash:
                    rejection = "near_duplicate_in_batch"
                    near_match = str(kept_path)
                    break

        destination = ""
        if not rejection:
            kept_index += 1
            destination_path = args.output / f"candidate_{kept_index:03d}__{source.name}"
            shutil.copy2(source, destination_path)
            destination = destination_path.name
            exact_seen.add(sha256)
            kept_hashes.append((dhash, phash, destination_path))

        rows.append(
            {
                "source": str(source),
                "destination": destination,
                "width": width,
                "height": height,
                "aspect": round(aspect, 4),
                "saturation": round(stat["saturation"], 4),
                "white_fraction": round(stat["white_fraction"], 4),
                "dark_fraction": round(stat["dark_fraction"], 4),
                "sha256": sha256,
                "status": "kept_for_visual_review" if not rejection else "auto_rejected",
                "reason": rejection,
                "near_match": near_match,
            }
        )

    manifest = args.output / "auto_filter_manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    print(f"kept_for_visual_review={kept_index}; inspected={len(rows)}; manifest={manifest}")


if __name__ == "__main__":
    main()
