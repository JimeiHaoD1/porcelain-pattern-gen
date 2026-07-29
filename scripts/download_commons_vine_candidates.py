#!/usr/bin/env python3
"""Download Wikimedia Commons web-search candidates for visual review."""

from __future__ import annotations

import csv
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (
    ROOT
    / "data"
    / "source_candidates"
    / "web_independent_batch4_20260715"
    / "original_sources"
    / "commons_search"
)
API = "https://commons.wikimedia.org/w/api.php"
QUERIES = [
    'intitle:border vine ornament -filetype:pdf',
    'intitle:border floral ornament engraving -filetype:pdf',
    'intitle:frieze vine leaves drawing -filetype:pdf',
    'intitle:ornament scroll foliage border -filetype:pdf',
    'intitle:arabesque border floral drawing -filetype:pdf',
    'intitle:ranke ornament band -filetype:pdf',
]


def get_json(params: dict[str, object]) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "StructVine-research/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def get_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "StructVine-research/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def clean(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    return re.sub(r"<[^>]+>", " ", str(value or "")).strip()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT.glob("commons_*"):
        if stale.is_file():
            stale.unlink()

    pages: dict[int, dict] = {}
    for query in QUERIES:
        data = get_json(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": 18,
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": 1200,
                "format": "json",
                "formatversion": 2,
            }
        )
        for page in data.get("query", {}).get("pages", []):
            pages[int(page["pageid"])] = page

    rows: list[dict[str, object]] = []
    for index, page in enumerate(sorted(pages.values(), key=lambda item: item["title"]), start=1):
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        if mime not in {"image/jpeg", "image/png", "image/svg+xml", "image/tiff"}:
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        suffix = ".png" if mime in {"image/png", "image/svg+xml", "image/tiff"} else ".jpg"
        output = OUTPUT / f"commons_{index:03d}_{page['pageid']}{suffix}"
        try:
            output.write_bytes(get_bytes(url))
        except Exception:
            continue
        metadata = info.get("extmetadata", {})
        rows.append(
            {
                "file": output.name,
                "pageid": page["pageid"],
                "title": page["title"],
                "source_page": info.get("descriptionurl", ""),
                "image_url": url,
                "original_width": info.get("width", ""),
                "original_height": info.get("height", ""),
                "license": clean(metadata.get("LicenseShortName")),
                "artist": clean(metadata.get("Artist")),
                "description": clean(metadata.get("ImageDescription")),
            }
        )

    if rows:
        with (OUTPUT / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(f"unique_pages={len(pages)}; downloaded={len(rows)}; output={OUTPUT}")


if __name__ == "__main__":
    main()
