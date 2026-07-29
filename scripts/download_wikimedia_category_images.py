#!/usr/bin/env python3
"""Download validated preview images from a Wikimedia Commons category."""

from __future__ import annotations

import argparse
import csv
import json
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image


API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "StructVineResearch/1.0 (dataset curation)"


def api_call(params: dict[str, str | int]) -> dict:
    request = Request(f"{API}?{urlencode(params)}", headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def download(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        content_type = response.headers.get_content_type()
        data = response.read()
    if not content_type.startswith("image/") or len(data) < 1_000:
        raise ValueError(f"not a usable image: {content_type}, {len(data)} bytes")
    with Image.open(BytesIO(data)) as image:
        image.verify()
    return data, content_type


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("category", help="Commons category title, with or without Category: prefix")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--title-regex", default=".*")
    parser.add_argument("--prefix", default="WC")
    parser.add_argument("--thumb-width", type=int, default=1800)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    category = args.category if args.category.startswith("Category:") else f"Category:{args.category}"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(args.title_regex, re.IGNORECASE)

    result = api_call(
        {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": category,
            "cmtype": "file",
            "cmlimit": min(args.limit, 500),
        }
    )
    titles = [item["title"] for item in result["query"]["categorymembers"] if pattern.search(item["title"])]

    records: list[dict[str, str | int]] = []
    index = 0
    for start in range(0, len(titles), 50):
        batch = titles[start : start + 50]
        details = api_call(
            {
                "action": "query",
                "format": "json",
                "prop": "imageinfo",
                "iiprop": "url|mime|size",
                "iiurlwidth": args.thumb_width,
                "titles": "|".join(batch),
            }
        )
        pages = sorted(details["query"]["pages"].values(), key=lambda page: page.get("title", ""))
        for page in pages:
            info = page.get("imageinfo", [{}])[0]
            image_url = info.get("thumburl") or info.get("url")
            if not image_url:
                continue
            index += 1
            extension = ".png" if info.get("mime") == "image/png" else ".jpg"
            filename = f"{args.prefix}{index:03d}{extension}"
            status = "ok"
            error = ""
            try:
                data, _ = download(image_url)
                (args.output_dir / filename).write_bytes(data)
            except Exception as exc:  # retain failure details in the manifest
                status = "error"
                error = str(exc)
            records.append(
                {
                    "id": f"{args.prefix}{index:03d}",
                    "filename": filename,
                    "title": page.get("title", ""),
                    "source_page": info.get("descriptionurl", ""),
                    "image_url": image_url,
                    "original_width": info.get("width", ""),
                    "original_height": info.get("height", ""),
                    "status": status,
                    "error": error,
                }
            )

    with (args.output_dir / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()) if records else ["id"])
        writer.writeheader()
        writer.writerows(records)
    print(f"matched={len(titles)} downloaded={sum(row['status'] == 'ok' for row in records)} output={args.output_dir}")


if __name__ == "__main__":
    main()
