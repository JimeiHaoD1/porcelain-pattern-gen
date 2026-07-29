#!/usr/bin/env python3
"""Download visually screened public-domain/CC0 ornament drawings for batch 4."""

from __future__ import annotations

import csv
import html
import pathlib
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


ENTRIES = [
    ("OC01", "core", "Design for Woven Horizontal Border", "https://upload.wikimedia.org/wikipedia/commons/a/a3/Drawing%2C_Design_for_Woven_Horizontal_Border%2C_1800%E2%80%931830_%28CH_18163091%29.jpg", "https://commons.wikimedia.org/wiki/File:Drawing,_Design_for_Woven_Horizontal_Border,_1800%E2%80%931830_(CH_18163091).jpg", "Public Domain"),
    ("OC02", "core", "Design for a Decorative Frieze", "https://images.metmuseum.org/CRDImages/dp/original/DP809214.jpg", "https://www.metmuseum.org/art/collection/search/362199", "CC0"),
    ("OC03", "core", "Frieze with Acanthus Scrolls and Vase", "https://images.metmuseum.org/CRDImages/dp/original/DP833529.jpg", "https://commons.wikimedia.org/wiki/File:Design_for_a_Frieze_with_Acanthus_Scrolls_and_a_Vase_in_the_Center_MET_DP833529.jpg", "CC0"),
    ("OC04", "core", "Design for Frieze of Foliage", "https://images.metmuseum.org/CRDImages/dp/original/DP804853.jpg", "https://www.metmuseum.org/art/collection/search/386403", "CC0"),
    ("OC05", "core", "Design of Rinceaux", "https://images.metmuseum.org/CRDImages/dp/original/DP810375.jpg", "https://www.metmuseum.org/art/collection/search/340739", "CC0"),
    ("OC06", "core", "Two Decorative Borders in Strapwork and Rinceaux", "https://images.metmuseum.org/CRDImages/dp/original/DP811459.jpg", "https://www.metmuseum.org/art/collection/search/385102", "CC0"),
    ("OC07", "core", "Classical Frieze with Vines and Leaves", "https://images.metmuseum.org/CRDImages/dp/original/DP804426.jpg", "https://commons.wikimedia.org/wiki/File:Border_Design_from_a_Classical_Frieze,_Decorated_with_Vines_and_Leaves_MET_DP804426.jpg", "CC0"),
    ("OC08", "core", "Leipzig 1875 Floral Ornament", "https://upload.wikimedia.org/wikipedia/commons/3/3a/Floral_ornament_border_from_S%C3%A6mmtliche_Gedichte_Michelangelo%E2%80%99s%2C_Leipzig_1875%2C_p._11.png", "https://commons.wikimedia.org/wiki/File:Floral_ornament_border_from_S%C3%A6mmtliche_Gedichte_Michelangelo%E2%80%99s,_Leipzig_1875,_p._11.png", "Public Domain"),
    ("OC09", "core", "Frieze with Rinceau", "https://ids.si.edu/ids/deliveryService?id=CHSDM-D7A83E3243B12-000001.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/18526", "CC0"),
    ("OC10", "core", "Fabrique de St. Ruf Horizontal Border", "https://ids.si.edu/ids/deliveryService?id=CHSDM-8572E4D83A4F2-000001.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/25008", "CC0"),
    ("OC11", "core", "Acanthus Rinceau with Floral Band", "https://ids.si.edu/ids/deliveryService?id=CHSDM-160894_01.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/160894", "CC0"),
    ("OC12", "core", "Acanthus Rinceau with Rose Motif", "https://ids.si.edu/ids/deliveryService?id=CHSDM-160590_01-000001.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/160590", "CC0"),
    ("OC13", "core", "Acanthus Rinceau with Flowers", "https://ids.si.edu/ids/deliveryService?id=CHSDM-1972-42-35MattFlynn.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/149106", "CC0"),
    ("OC14", "core", "Linked Floral and Foliate Scrolls", "https://ids.si.edu/ids/deliveryService?id=CHSDM-161117_01-000001.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/161117", "CC0"),
    ("OC15", "core", "Two Layers of Waving Floral Scrolls", "https://ids.si.edu/ids/deliveryService?id=CHSDM-09D97E0ADB432-000001.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/161146", "CC0"),
    ("OC16", "auxiliary", "Metallic Gold and Blue Foliate Rinceau", "https://ids.si.edu/ids/deliveryService?id=CHSDM-161106_01-000001.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/161106", "CC0"),
    ("OC17", "auxiliary", "Large Rinceau with Green Bouquets", "https://ids.si.edu/ids/deliveryService?id=CHSDM-160769_01.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/160769", "CC0"),
    ("OC18", "auxiliary", "Green Floral and Foliate Rinceau", "https://ids.si.edu/ids/deliveryService?id=CHSDM-161113_01-000001.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/161113", "CC0"),
    ("OC19", "auxiliary", "Ochre Acanthus Rinceau on Red", "https://ids.si.edu/ids/deliveryService?id=CHSDM-1972-42-37-aMattFlynn.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/149108", "CC0"),
    ("OC20", "auxiliary", "Stylized Flowers in Foliate Scrolls", "https://ids.si.edu/ids/deliveryService?id=CHSDM-161112_01-000001.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/161112", "CC0"),
    ("OC21", "auxiliary", "Blue Flowers and Grisaille Acanthus", "https://ids.si.edu/ids/deliveryService?id=CHSDM-1954-155-2MattFlynn.jpg", "https://collection.cooperhewitt.org/view/objects/asitem/id/110212", "CC0"),
]


def fetch_image(image_url: str, referer: str) -> tuple[bytes, str]:
    request = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
        content_type = response.headers.get_content_type()
    if not content_type.startswith("image/"):
        raise ValueError(f"unexpected Content-Type {content_type!r}")
    if len(data) < 1000:
        raise ValueError(f"image response too small: {len(data)} bytes")
    return data, content_type


def discover_cooper_hewitt_image(source_page: str) -> str:
    """Find the legacy Cooper Hewitt high-resolution image when IDS is blocked.

    In this environment the IDS endpoint returns a 245-byte request-rejection
    page. The public object page exposes the same CC0 asset on Cooper Hewitt's
    legacy image host; prefer its ``_x`` (largest) rendition.
    """

    request = urllib.request.Request(source_page, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        page = html.unescape(response.read().decode("utf-8", errors="ignore"))
    urls = re.findall(r"https://images\.collection\.cooperhewitt\.org/[^\"'<>\s]+\.jpg", page)
    if not urls:
        raise ValueError("no Cooper Hewitt image URL found on source page")
    unique_urls = list(dict.fromkeys(urls))
    unique_urls.sort(key=lambda url: ("_x.jpg" not in url, "_b.jpg" not in url, url))
    return unique_urls[0]


def download(entry: tuple[str, str, str, str, str, str], output: pathlib.Path) -> dict[str, str]:
    item_id, tier, title, requested_image_url, source_page, rights = entry
    # Remove stale files (notably the old 245-byte HTML error responses) before
    # attempting a fresh download for this item.
    for stale_path in output.glob(f"{item_id}_*"):
        if stale_path.is_file():
            stale_path.unlink()
    actual_image_url = requested_image_url
    fallback_note = ""
    try:
        try:
            data, content_type = fetch_image(actual_image_url, source_page)
        except Exception as primary_exc:  # noqa: BLE001
            if "ids.si.edu/ids/" not in requested_image_url:
                raise
            actual_image_url = discover_cooper_hewitt_image(source_page)
            data, content_type = fetch_image(actual_image_url, source_page)
            fallback_note = f"; IDS rejected, used Cooper Hewitt source-page image ({primary_exc})"
        extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/tiff": ".tif",
        }.get(content_type, ".img")
        filename = f"{item_id}_{tier}{extension}"
        (output / filename).write_bytes(data)
        status = f"downloaded{fallback_note}"
    except Exception as exc:  # noqa: BLE001
        filename = ""
        content_type = ""
        status = f"error: {exc}"
    return {
        "id": item_id,
        "tier": tier,
        "title": title,
        "filename": filename,
        "source_page": source_page,
        "requested_image_url": requested_image_url,
        "direct_image_url": actual_image_url,
        "rights": rights,
        "content_type": content_type,
        "status": status,
    }


def main() -> None:
    output = pathlib.Path(__file__).resolve().parents[1] / "data" / "source_candidates" / "web_independent_batch4_20260715" / "original_sources" / "open_collection_public_domain"
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(download, entry, output) for entry in ENTRIES]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(row["id"], row["status"], row["filename"], flush=True)
    rows.sort(key=lambda row: row["id"])
    with (output / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
