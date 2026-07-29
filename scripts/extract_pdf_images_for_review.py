#!/usr/bin/env python3
"""Extract wide embedded PDF images for manual visual screening."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

import fitz


def parse_pages(spec: str, page_count: int) -> list[int]:
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(value) for value in part.split("-", 1))
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    return [page - 1 for page in sorted(pages) if 1 <= page <= page_count]


def extract(pdf_path: Path, output_dir: Path, page_spec: str, min_width: int, min_height: int, min_aspect: float) -> None:
    doc = fitz.open(pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, object]] = []
    seen: set[tuple[int, int]] = set()

    for page_index in parse_pages(page_spec, len(doc)):
        page = doc[page_index]
        for image_index, item in enumerate(page.get_images(full=True)):
            xref = int(item[0])
            key = (page_index, xref)
            if key in seen:
                continue
            seen.add(key)
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.colorspace is None:
                    continue
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                width, height = pix.width, pix.height
                aspect = width / max(height, 1)
                if width < min_width or height < min_height or aspect < min_aspect:
                    continue
                filename = f"{pdf_path.stem}_p{page_index+1:03d}_i{image_index:02d}_x{xref}_{width}x{height}.png"
                output = output_dir / filename
                pix.save(output)
                digest = hashlib.sha256(output.read_bytes()).hexdigest()
                rects = page.get_image_rects(xref)
                manifest_rows.append(
                    {
                        "file": filename,
                        "source_pdf": pdf_path.name,
                        "source_page": page_index + 1,
                        "xref": xref,
                        "pixel_width": width,
                        "pixel_height": height,
                        "aspect": round(aspect, 4),
                        "page_rects": " | ".join(str(rect) for rect in rects),
                        "sha256": digest,
                    }
                )
            except RuntimeError:
                continue

    manifest = output_dir / "extraction_manifest.csv"
    fieldnames = [
        "file",
        "source_pdf",
        "source_page",
        "xref",
        "pixel_width",
        "pixel_height",
        "aspect",
        "page_rects",
        "sha256",
    ]
    with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(manifest_rows)
    print(f"{pdf_path.name}: extracted={len(manifest_rows)} -> {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--min-width", type=int, default=100)
    parser.add_argument("--min-height", type=int, default=25)
    parser.add_argument("--min-aspect", type=float, default=1.5)
    args = parser.parse_args()
    extract(args.pdf, args.output_dir, args.pages, args.min_width, args.min_height, args.min_aspect)


if __name__ == "__main__":
    main()
