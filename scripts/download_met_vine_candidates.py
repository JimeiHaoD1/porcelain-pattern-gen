#!/usr/bin/env python3
"""Download public-domain Met web candidates for visual vine-border review."""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (
    ROOT
    / "data"
    / "source_candidates"
    / "web_independent_batch4_20260715"
    / "original_sources"
    / "met_independent_objects"
)

API = "https://collectionapi.metmuseum.org/public/collection/v1"
QUERIES = [
    "border vines flowers",
    "ornamental border vine",
    "scrolling vine ornament",
    "foliate border design",
    "acanthus vine border",
    "frieze vines leaves drawing",
]
SEED_IDS = {367192, 367194, 822704, 387060}


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "StructVine-research/1.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def get_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "StructVine-research/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def relevant(record: dict) -> bool:
    if not record.get("isPublicDomain") or not record.get("primaryImageSmall"):
        return False
    searchable = " ".join(
        str(record.get(field, ""))
        for field in ("title", "objectName", "classification", "medium")
    ).lower()
    include = ("border", "vine", "foliate", "acanthus", "frieze", "ornament", "scroll")
    drawing = ("ink", "graphite", "etch", "engrav", "woodcut", "print", "drawing", "chalk")
    reject = ("photograph", "sculpture", "ceramic", "tile", "textile", "carpet", "limestone")
    return any(word in searchable for word in include) and any(word in searchable for word in drawing) and not any(
        word in searchable for word in reject
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-only", action="store_true")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT.glob("met_*.jpg"):
        stale.unlink()
    for stale in OUTPUT.glob("met_*.png"):
        stale.unlink()

    object_ids = set(SEED_IDS)
    if not args.seed_only:
        for query in QUERIES:
            encoded = urllib.parse.urlencode({"hasImages": "true", "departmentId": 9, "q": query})
            data = get_json(f"{API}/search?{encoded}")
            object_ids.update((data.get("objectIDs") or [])[:12])
            time.sleep(0.1)

    records: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(get_json, f"{API}/objects/{object_id}"): object_id for object_id in object_ids}
        for future in as_completed(futures):
            try:
                record = future.result()
            except Exception:
                continue
            if relevant(record):
                records.append(record)

    rows: list[dict[str, object]] = []
    for record in sorted(records, key=lambda item: int(item["objectID"])):
        object_id = int(record["objectID"])
        image_url = record.get("primaryImageSmall") or record.get("primaryImage")
        suffix = ".png" if ".png" in image_url.lower() else ".jpg"
        output = OUTPUT / f"met_{object_id}{suffix}"
        try:
            output.write_bytes(get_bytes(image_url))
        except Exception:
            continue
        rows.append(
            {
                "file": output.name,
                "object_id": object_id,
                "title": record.get("title", ""),
                "object_name": record.get("objectName", ""),
                "classification": record.get("classification", ""),
                "medium": record.get("medium", ""),
                "date": record.get("objectDate", ""),
                "culture": record.get("culture", ""),
                "source_page": record.get("objectURL", ""),
                "image_url": image_url,
                "rights": "The Met Open Access; Public Domain",
            }
        )

    if rows:
        with (OUTPUT / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(f"searched_ids={len(object_ids)}; downloaded={len(rows)}; output={OUTPUT}")


if __name__ == "__main__":
    main()
