#!/usr/bin/env python3
"""Render compact page contact sheets for visually mining image-heavy PDFs."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont


def render_pdf(pdf_path: Path, output_root: Path, *, columns: int, per_sheet: int, thumb_width: int) -> None:
    doc = fitz.open(pdf_path)
    output_dir = output_root / pdf_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default()
    gutter = 12
    label_height = 22
    page_indices = list(range(len(doc)))

    for sheet_index, start in enumerate(range(0, len(page_indices), per_sheet), start=1):
        batch = page_indices[start : start + per_sheet]
        thumbs: list[tuple[int, Image.Image]] = []
        max_height = 0
        for page_index in batch:
            page = doc[page_index]
            scale = thumb_width / page.rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            thumbs.append((page_index + 1, image))
            max_height = max(max_height, image.height)

        rows = math.ceil(len(thumbs) / columns)
        canvas_width = gutter + columns * (thumb_width + gutter)
        canvas_height = gutter + rows * (max_height + label_height + gutter)
        canvas = Image.new("RGB", (canvas_width, canvas_height), "#E4E6E8")
        draw = ImageDraw.Draw(canvas)
        for index, (page_number, image) in enumerate(thumbs):
            row, column = divmod(index, columns)
            x = gutter + column * (thumb_width + gutter)
            y = gutter + row * (max_height + label_height + gutter)
            canvas.paste(image, (x, y + label_height))
            draw.rectangle((x, y, x + thumb_width, y + label_height - 2), fill="#FFFFFF")
            draw.text((x + 6, y + 4), f"page {page_number}", fill="#111111", font=font)

        output = output_dir / f"sheet_{sheet_index:03d}_pages_{batch[0]+1:03d}-{batch[-1]+1:03d}.jpg"
        canvas.save(output, quality=90, optimize=True)
        print(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--columns", type=int, default=5)
    parser.add_argument("--per-sheet", type=int, default=25)
    parser.add_argument("--thumb-width", type=int, default=260)
    args = parser.parse_args()
    for pdf in args.pdfs:
        render_pdf(pdf, args.output_root, columns=args.columns, per_sheet=args.per_sheet, thumb_width=args.thumb_width)


if __name__ == "__main__":
    main()
