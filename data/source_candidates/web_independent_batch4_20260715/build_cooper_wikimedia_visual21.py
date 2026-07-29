from __future__ import annotations

import argparse
import csv
import hashlib
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "cooper_wikimedia_visual21_20260715"
ORIGINALS = OUTPUT / "originals"
PRIORITY = OUTPUT / "priority"
AUXILIARY = OUTPUT / "auxiliary"


@dataclass(frozen=True)
class Candidate:
    cid: str
    slug: str
    tier: str
    title: str
    page: str
    direct_url: str
    rights: str
    visual_note: str
    expected_size: tuple[int, int]
    # Crop coordinates are normalized to the image after rotation.
    crop: tuple[float, float, float, float] | None = None
    rotate: int = 0


CANDIDATES = [
    Candidate(
        "CW01", "woven_horizontal_border", "priority",
        "Design for Woven Horizontal Border, 1800-1830",
        "https://commons.wikimedia.org/wiki/File:Drawing,_Design_for_Woven_Horizontal_Border,_1800%E2%80%931830_(CH_18163091).jpg",
        "https://upload.wikimedia.org/wikipedia/commons/a/a3/Drawing%2C_Design_for_Woven_Horizontal_Border%2C_1800%E2%80%931830_%28CH_18163091%29.jpg",
        "Public domain / PDM", "Ink-and-wash horizontal S-rinceaux; clear continuity", (4096, 1603),
    ),
    Candidate(
        "CW02", "decorative_frieze_palmette", "priority",
        "Design for a Decorative Frieze",
        "https://www.metmuseum.org/art/collection/search/362199",
        "https://images.metmuseum.org/CRDImages/dp/original/DP809214.jpg",
        "CC0", "Continuous palmette and foliate scroll drawing", (3873, 1610),
    ),
    Candidate(
        "CW03", "acanthus_scroll_vase", "priority",
        "Design for a Frieze with Acanthus Scrolls and a Vase",
        "https://commons.wikimedia.org/wiki/File:Design_for_a_Frieze_with_Acanthus_Scrolls_and_a_Vase_in_the_Center_MET_DP833529.jpg",
        "https://images.metmuseum.org/CRDImages/dp/original/DP833529.jpg",
        "CC0", "Long acanthus scroll; central vase can be retained as an attachment node", (3913, 1120),
    ),
    Candidate(
        "CW04", "frieze_of_foliage", "priority",
        "Design for Frieze of Foliage",
        "https://www.metmuseum.org/art/collection/search/386403",
        "https://images.metmuseum.org/CRDImages/dp/original/DP804853.jpg",
        "CC0", "Pure botanical symmetrical scroll drawing", (3905, 1949),
    ),
    Candidate(
        "CW05", "design_of_rinceaux", "priority",
        "Design of Rinceaux",
        "https://www.metmuseum.org/art/collection/search/340739",
        "https://images.metmuseum.org/CRDImages/dp/original/DP810375.jpg",
        "CC0", "Low-contrast but clean continuous rinceaux", (3914, 1457),
    ),
    Candidate(
        "CW06", "two_strapwork_rinceaux", "priority",
        "Two Designs for Decorative Borders in Strapwork and Rinceaux",
        "https://www.metmuseum.org/art/collection/search/385102",
        "https://images.metmuseum.org/CRDImages/dp/original/DP811459.jpg",
        "CC0", "Two vertical botanical bands; rotate and isolate the stronger strip", (2596, 3744),
        rotate=90,
    ),
    Candidate(
        "CW07", "classical_vines_leaves", "priority",
        "Border Design from a Classical Frieze, Decorated with Vines and Leaves",
        "https://commons.wikimedia.org/wiki/File:Border_Design_from_a_Classical_Frieze,_Decorated_with_Vines_and_Leaves_MET_DP804426.jpg",
        "https://images.metmuseum.org/CRDImages/dp/original/DP804426.jpg",
        "CC0", "Continuous acanthus and leaf scroll band", (3881, 1731),
    ),
    Candidate(
        "CW08", "leipzig_floral_ornament", "priority",
        "Floral Ornament Border, Leipzig 1875",
        "https://commons.wikimedia.org/wiki/File:Floral_ornament_border_from_S%C3%A6mmtliche_Gedichte_Michelangelo%E2%80%99s,_Leipzig_1875,_p._11.png",
        "https://upload.wikimedia.org/wikipedia/commons/3/3a/Floral_ornament_border_from_S%C3%A6mmtliche_Gedichte_Michelangelo%E2%80%99s%2C_Leipzig_1875%2C_p._11.png",
        "Public domain / PDM", "Black line-art botanical border; exceptionally wide", (7108, 998),
    ),
    Candidate(
        "CW09", "frieze_rinceau_half", "priority",
        "Frieze with Rinceau, 1775-1780",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/18526",
        "https://ids.si.edu/ids/download?id=CHSDM-D7A83E3243B12-000001.jpg",
        "CC0", "Horizontal rinceau line drawing; surviving right half", (6433, 2824),
    ),
    Candidate(
        "CW10", "st_ruf_horizontal_border", "priority",
        "Woven or Embroidered Horizontal Border of the Fabrique de St. Ruf",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/25008",
        "https://ids.si.edu/ids/download?id=CHSDM-8572E4D83A4F2-000001.jpg",
        "CC0", "Two flower-and-leaf spirals with a readable parent vine", (5535, 3038),
    ),
    Candidate(
        "CW11", "acanthus_floral_band", "priority",
        "Frieze: Acanthus Rinceau with Floral Band",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/160894",
        "https://ids.si.edu/ids/download?id=CHSDM-160894_01.jpg",
        "CC0", "Two repeated botanical rows; isolate one horizontal row", (6396, 4265),
    ),
    Candidate(
        "CW12", "acanthus_rose_rinceau", "priority",
        "Frieze: Acanthus Rinceau with Rose Motif",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/160590",
        "https://ids.si.edu/ids/download?id=CHSDM-160590_01-000001.jpg",
        "CC0", "Looped parent vine with flowers and leaves", (7301, 3720),
    ),
    Candidate(
        "CW13", "acanthus_flower_border", "priority",
        "Border: Acanthus Rinceau with Flowers",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/149106",
        "https://ids.si.edu/ids/download?id=CHSDM-1972-42-35MattFlynn.jpg",
        "CC0", "Large continuous acanthus scroll with clear hierarchy", (3000, 1401),
    ),
    Candidate(
        "CW14", "linked_floral_scrolls", "priority",
        "Frieze: Linked Floral and Foliate Scrolls",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/161117",
        "https://ids.si.edu/ids/download?id=CHSDM-161117_01-000001.jpg",
        "CC0", "Two ornate floral rows; isolate the clearer row", (7216, 4392),
    ),
    Candidate(
        "CW15", "waving_floral_scrolls", "priority",
        "Frieze: Two Layers of Waving Floral Scrolls",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/161146",
        "https://ids.si.edu/ids/download?id=CHSDM-09D97E0ADB432-000001.jpg",
        "CC0", "Two pale blue and gold scroll rows; isolate one row", (6421, 3487),
    ),
    Candidate(
        "CW16", "metallic_blue_rinceau", "auxiliary",
        "Frieze: Metallic Gold and Blue Foliate Rinceau",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/161106",
        "https://ids.si.edu/ids/download?id=CHSDM-161106_01-000001.jpg",
        "CC0", "Low-contrast two-row foliate rinceau", (6578, 3832),
    ),
    Candidate(
        "CW17", "green_bouquet_rinceau", "auxiliary",
        "Frieze: Large Rinceau with Green Bouquets",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/160769",
        "https://ids.si.edu/ids/download?id=CHSDM-160769_01.jpg",
        "CC0", "Dense floral bouquets on a continuous rinceau", (7216, 3905),
    ),
    Candidate(
        "CW18", "green_floral_rinceau", "auxiliary",
        "Frieze: Green Floral and Foliate Rinceau",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/161113",
        "https://ids.si.edu/ids/download?id=CHSDM-161113_01-000001.jpg",
        "CC0", "Two green floral rows; isolate one row", (7216, 4386),
    ),
    Candidate(
        "CW19", "ochre_acanthus_red", "auxiliary",
        "Frieze: Ochre Acanthus Rinceau on Red",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/149108",
        "https://ids.si.edu/ids/download?id=CHSDM-1972-42-37-aMattFlynn.jpg",
        "CC0", "Strong continuity but heavy colored fill", (3000, 714),
    ),
    Candidate(
        "CW20", "stylized_flower_scrolls", "auxiliary",
        "Frieze: Stylized Flowers in Foliate Scrolls",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/161112",
        "https://ids.si.edu/ids/download?id=CHSDM-161112_01-000001.jpg",
        "CC0", "Low-contrast two-row foliate scroll", (6664, 3799),
    ),
    Candidate(
        "CW21", "blue_flower_grisaille", "auxiliary",
        "Frieze: Blue Flowers and Grisaille Acanthus",
        "https://collection.cooperhewitt.org/view/objects/asitem/id/110212",
        "https://ids.si.edu/ids/download?id=CHSDM-1954-155-2MattFlynn.jpg",
        "CC0", "Blue flowers attached to a grisaille acanthus scroll", (3000, 987),
    ),
]


def extension_from_url(url: str) -> str:
    lower = url.lower()
    return ".png" if ".png" in lower else ".jpg"


def original_path(candidate: Candidate) -> Path:
    return ORIGINALS / f"{candidate.cid.lower()}__{candidate.slug}{extension_from_url(candidate.direct_url)}"


def processed_path(candidate: Candidate) -> Path:
    folder = PRIORITY if candidate.tier == "priority" else AUXILIARY
    return folder / f"{candidate.cid.lower()}__{candidate.slug}.png"


def valid_image(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


def download(session: requests.Session, candidate: Candidate, refresh: bool) -> Path:
    destination = original_path(candidate)
    if not refresh and valid_image(destination):
        return destination
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, 5):
        try:
            with session.get(candidate.direct_url, timeout=150, stream=True) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for block in response.iter_content(1024 * 1024):
                        if block:
                            handle.write(block)
            if not valid_image(temporary):
                raise RuntimeError("downloaded file is not a valid image")
            temporary.replace(destination)
            return destination
        except Exception:
            if temporary.exists():
                temporary.unlink()
            if attempt == 4:
                raise
            time.sleep(4 * attempt)
    raise AssertionError("unreachable")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_crop_box(
    size: tuple[int, int], crop: tuple[float, float, float, float] | None
) -> tuple[int, int, int, int]:
    width, height = size
    if crop is None:
        return 0, 0, width, height
    left, top, right, bottom = crop
    box = round(left * width), round(top * height), round(right * width), round(bottom * height)
    if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
        raise ValueError(f"Invalid crop {crop} -> {box} for {size}")
    return box


def process(candidate: Candidate) -> dict[str, str]:
    source = original_path(candidate)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        original_size = image.size
        if candidate.rotate:
            image = image.rotate(candidate.rotate, expand=True, fillcolor="white")
        box = normalized_crop_box(image.size, candidate.crop)
        crop = image.crop(box)
        destination = processed_path(candidate)
        crop.save(destination, format="PNG", optimize=True)
        processed_size = crop.size
    return {
        "id": candidate.cid,
        "tier": candidate.tier,
        "file": destination.relative_to(OUTPUT).as_posix(),
        "original_file": source.relative_to(OUTPUT).as_posix(),
        "title": candidate.title,
        "source_page": candidate.page,
        "direct_url": candidate.direct_url,
        "rights": candidate.rights,
        "original_size": f"{original_size[0]}x{original_size[1]}",
        "expected_size": f"{candidate.expected_size[0]}x{candidate.expected_size[1]}",
        "rotation_degrees": str(candidate.rotate),
        "crop_box_after_rotation": ",".join(map(str, box)),
        "processed_size": f"{processed_size[0]}x{processed_size[1]}",
        "sha256_original": sha256(source),
        "visual_note": candidate.visual_note,
    }


def make_contact_sheet(
    candidates: Iterable[Candidate], output_path: Path, use_processed: bool, columns: int = 2
) -> None:
    selected = list(candidates)
    tile_w, tile_h = 950, 300
    rows = math.ceil(len(selected) / columns)
    canvas = Image.new("RGB", (tile_w * columns, tile_h * rows), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, candidate in enumerate(selected):
        col, row = index % columns, index // columns
        x0, y0 = col * tile_w, row * tile_h
        path = processed_path(candidate) if use_processed else original_path(candidate)
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((tile_w - 36, tile_h - 66), Image.Resampling.LANCZOS)
            x = x0 + (tile_w - image.width) // 2
            y = y0 + 44 + (tile_h - 58 - image.height) // 2
            canvas.paste(image, (x, y))
        label = f"{candidate.cid}  {candidate.slug}  {path.name}"
        draw.text((x0 + 12, y0 + 10), label, fill="black", font=font)
        draw.rectangle((x0, y0, x0 + tile_w - 1, y0 + tile_h - 1), outline=(205, 205, 205))
    canvas.save(output_path, format="JPEG", quality=91, optimize=True)


def write_manifest(rows: list[dict[str, str]]) -> None:
    fields = list(rows[0])
    with (OUTPUT / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_readme() -> None:
    content = """# Cooper Hewitt / Wikimedia visual candidates (batch4)

- `priority/`: 15 visually approved primary candidates.
- `auxiliary/`: 6 usable but lower-priority candidates.
- `originals/`: downloaded source files retained for traceability.
- `manifest.csv`: source page, direct URL, rights, dimensions, rotation and crop box.
- `contact_sheet_priority.jpg` and `contact_sheet_auxiliary.jpg`: processed visual review sheets.
- `contact_sheet_originals.jpg`: uncropped source overview used to set crop boxes.

Selection excludes people, birds, animals, reliefs, real-scene photographs, pure geometry,
Meyer Orna093-Orna096, and Met objects 406539-406541. Flat scans of paper designs are kept.
"""
    (OUTPUT / "README.md").write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()

    for directory in (OUTPUT, ORIGINALS, PRIORITY, AUXILIARY):
        directory.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "StructVine-research/1.0 (public-domain image screening)",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
    )
    for candidate in CANDIDATES:
        path = download(session, candidate, args.refresh)
        with Image.open(path) as image:
            print(candidate.cid, image.size, path.name)
        # Keep requests to Wikimedia/Smithsonian polite and avoid burst limiting.
        time.sleep(0.8)

    make_contact_sheet(CANDIDATES, OUTPUT / "contact_sheet_originals.jpg", use_processed=False)
    if args.download_only:
        return

    rows = [process(candidate) for candidate in CANDIDATES]
    write_manifest(rows)
    write_readme()
    make_contact_sheet(
        (candidate for candidate in CANDIDATES if candidate.tier == "priority"),
        OUTPUT / "contact_sheet_priority.jpg",
        use_processed=True,
    )
    make_contact_sheet(
        (candidate for candidate in CANDIDATES if candidate.tier == "auxiliary"),
        OUTPUT / "contact_sheet_auxiliary.jpg",
        use_processed=True,
    )


if __name__ == "__main__":
    main()
