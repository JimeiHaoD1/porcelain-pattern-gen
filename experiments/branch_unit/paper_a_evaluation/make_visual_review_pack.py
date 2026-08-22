from __future__ import annotations

import argparse
import csv
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "artifacts"
    / "paper_a_chapter4_v1"
    / "visual_review_all_cases_v1"
    / "visual_review_manifest.csv"
)
BACKGROUND = "#fafafa"


def resolve_repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def load_manifest(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {row["case_id"]: row for row in rows}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "arialbd.ttf" if bold else "arial.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size=size)


def hardlink_or_copy(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"Destination already exists: {destination}")
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def svg_viewbox(svg_path: Path) -> tuple[float, float, float, float]:
    root = ET.fromstring(svg_path.read_bytes())
    values = [float(value) for value in root.attrib["viewBox"].replace(",", " ").split()]
    if len(values) != 4:
        raise RuntimeError(f"Invalid viewBox in {svg_path}")
    return values[0], values[1], values[2], values[3]


def render_svg(svg_path: Path, long_edge: int, central_period: bool) -> Image.Image:
    document = fitz.open(stream=svg_path.read_bytes(), filetype="svg")
    page = document[0]
    clip = page.rect
    if central_period:
        x0, _, width, _ = svg_viewbox(svg_path)
        if not (x0 <= 0.0 and x0 + width >= 1.0):
            raise RuntimeError(f"Central period [0, 1] is outside viewBox in {svg_path}")
        clip = fitz.Rect(
            page.rect.x0 + ((0.0 - x0) / width) * page.rect.width,
            page.rect.y0,
            page.rect.x0 + ((1.0 - x0) / width) * page.rect.width,
            page.rect.y1,
        )
    scale = long_edge / max(clip.width, clip.height)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    document.close()
    return image


def fit_image(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    scale = min(max_width / image.width, max_height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS) if size != image.size else image.copy()


def build_detail(case_id: str, row: dict[str, str], output_path: Path) -> None:
    width = 3200
    margin = 100
    gap = 110
    title_height = 110
    triple_source = resolve_repo_path(row["formal_triple_png"])
    with Image.open(triple_source) as source:
        triple = fit_image(source.convert("RGB"), width - 2 * margin, 1700)

    single_source = resolve_repo_path(row["single_review_source_svg"])
    single = render_svg(
        single_source,
        long_edge=3200,
        central_period=row["single_review_mode"] != "formal_single_svg",
    )
    canvas_height = title_height + margin + triple.height + gap + single.height + margin
    detail = Image.new("RGB", (width, canvas_height), BACKGROUND)
    draw = ImageDraw.Draw(detail)
    draw.text((margin, 25), case_id, font=font(64, bold=True), fill="#111111")
    detail.paste(triple, ((width - triple.width) // 2, title_height + margin))
    detail.paste(single, ((width - single.width) // 2, title_height + margin + triple.height + gap))
    detail.save(output_path, format="PNG", optimize=False)
    triple.close()
    single.close()
    detail.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble a second-round visual review pack from explicit frozen case IDs."
    )
    parser.add_argument("--cases", required=True, help="Comma-separated case IDs, for example A014,A029,B021")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Full-case visual review manifest")
    args = parser.parse_args()

    requested = [value.strip() for value in args.cases.split(",") if value.strip()]
    if not requested:
        parser.error("--cases must contain at least one explicit case ID")
    if len(requested) != len(set(requested)):
        parser.error("--cases contains duplicate case IDs")

    manifest_path = resolve_repo_path(args.manifest)
    manifest = load_manifest(manifest_path)
    unknown = [case_id for case_id in requested if case_id not in manifest]
    if unknown:
        parser.error(f"Unknown case IDs: {','.join(unknown)}")

    output_root = resolve_repo_path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)
    for case_id in requested:
        row = manifest[case_id]
        case_output = output_root / case_id
        if case_output.exists() and any(case_output.iterdir()):
            raise FileExistsError(f"Refusing to overwrite non-empty case directory: {case_output}")
        case_output.mkdir(parents=True, exist_ok=True)
        triple_png = resolve_repo_path(row["formal_triple_png"])
        triple_svg = resolve_repo_path(row["formal_triple_svg"])
        source_case_dir = triple_png.parent
        hardlink_or_copy(triple_png, case_output / "formal_triple.png")
        hardlink_or_copy(triple_svg, case_output / "formal_triple.svg")
        if row.get("formal_single_svg"):
            single_svg = resolve_repo_path(row["formal_single_svg"])
            hardlink_or_copy(single_svg, case_output / "formal_single.svg")
        for source_json in sorted(source_case_dir.glob("*.json")):
            hardlink_or_copy(source_json, case_output / source_json.name)
        build_detail(case_id, row, case_output / "detail_review.png")


if __name__ == "__main__":
    main()
