#!/usr/bin/env python3
"""Create labeled contact sheets for manual image screening."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--per-sheet", type=int, default=20)
    parser.add_argument("--cell-width", type=int, default=360)
    parser.add_argument("--cell-height", type=int, default=210)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in args.input_dir.iterdir() if path.is_file() and path.suffix.lower() in EXTENSIONS)
    font = ImageFont.load_default()
    gutter = 12
    label_height = 44

    for sheet_index, start in enumerate(range(0, len(files), args.per_sheet), start=1):
        batch = files[start : start + args.per_sheet]
        rows = math.ceil(len(batch) / args.columns)
        width = gutter + args.columns * (args.cell_width + gutter)
        height = gutter + rows * (args.cell_height + label_height + gutter)
        canvas = Image.new("RGB", (width, height), "#DADDE1")
        draw = ImageDraw.Draw(canvas)
        for index, path in enumerate(batch):
            row, column = divmod(index, args.columns)
            x = gutter + column * (args.cell_width + gutter)
            y = gutter + row * (args.cell_height + label_height + gutter)
            draw.rectangle((x, y, x + args.cell_width, y + label_height - 2), fill="white")
            short = path.name if len(path.name) <= 52 else path.name[:49] + "..."
            # The bundled bitmap font cannot encode CJK characters.  Keep the
            # sheet generation robust while the original filename remains in
            # the source folder and manifest.
            short = short.encode("ascii", "replace").decode("ascii")
            draw.text((x + 5, y + 5), short, fill="#111111", font=font)
            try:
                with Image.open(path) as image:
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    fitted = ImageOps.contain(image, (args.cell_width - 8, args.cell_height - 8), Image.Resampling.LANCZOS)
                cell = Image.new("RGB", (args.cell_width, args.cell_height), "white")
                cell.paste(fitted, ((args.cell_width - fitted.width) // 2, (args.cell_height - fitted.height) // 2))
                canvas.paste(cell, (x, y + label_height))
            except OSError:
                draw.text((x + 8, y + label_height + 8), "unreadable", fill="#AA0000", font=font)
        output = args.output_dir / f"sheet_{sheet_index:03d}_{start+1:03d}-{start+len(batch):03d}.jpg"
        canvas.save(output, quality=92, optimize=True)
        print(output)


if __name__ == "__main__":
    main()
