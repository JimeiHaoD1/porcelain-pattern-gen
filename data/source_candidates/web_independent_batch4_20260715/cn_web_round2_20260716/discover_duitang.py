from __future__ import annotations

import concurrent.futures
import csv
import html
import pathlib
import re
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "original_sources" / "duitang_discovery"
QUERIES = ["卷草花纹", "缠枝花边", "二方连续 花卉", "忍冬纹 二方连续"]
HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=12) as response:
        return response.read().decode("utf-8", errors="replace")


def search_ids(query: str) -> list[str]:
    url = "https://www.duitang.com/search/?kw=" + urllib.parse.quote(query) + "&type=feed"
    text = fetch_text(url)
    return list(dict.fromkeys(re.findall(r"/blog/\?id=(\d+)", text)))


def resolve_page(pin_id: str) -> dict[str, str] | None:
    page = f"https://www.duitang.com/blog/?id={pin_id}"
    try:
        text = fetch_text(page)
        image_match = re.search(r'<a class="vieworg" href="([^"]+)"', text)
        title_match = re.search(r"<title>(.*?)</title>", text, flags=re.S)
        if not image_match:
            return None
        return {
            "pin_id": pin_id,
            "source_page": page,
            "direct_url": html.unescape(image_match.group(1)),
            "title": html.unescape(title_match.group(1)).split(" - ")[0].strip() if title_match else "",
        }
    except Exception as exc:  # noqa: BLE001
        print("resolve failed", pin_id, exc)
        return None


def download(item: dict[str, str]) -> dict[str, str]:
    pin_id = item["pin_id"]
    suffix = pathlib.Path(urllib.parse.urlparse(item["direct_url"]).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    path = OUT / f"duitang_{pin_id}{suffix}"
    try:
        if not path.exists() or path.stat().st_size < 1000:
            request = urllib.request.Request(
                item["direct_url"],
                headers={**HEADERS, "Referer": item["source_page"]},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read()
                content_type = response.headers.get_content_type()
            if not content_type.startswith("image/") or len(data) < 1000:
                raise ValueError(f"bad payload: {content_type}, {len(data)} bytes")
            path.write_bytes(data)
        with Image.open(path) as image:
            width, height = image.size
        return {**item, "filename": path.name, "size": f"{width}x{height}", "status": "downloaded"}
    except Exception as exc:  # noqa: BLE001
        return {**item, "filename": "", "size": "", "status": f"error: {exc}"}


def make_contact(rows: list[dict[str, str]], output: pathlib.Path) -> None:
    good = [row for row in rows if row["filename"]]
    columns, tile_w, tile_h, label_h = 4, 360, 300, 42
    row_count = (len(good) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_w, row_count * (tile_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, row in enumerate(good):
        path = OUT / row["filename"]
        with Image.open(path) as source:
            image = source.convert("RGB")
        fitted = ImageOps.contain(image, (tile_w - 12, tile_h - 12))
        x0 = (index % columns) * tile_w
        y0 = (index // columns) * (tile_h + label_h)
        sheet.paste(fitted, (x0 + (tile_w - fitted.width) // 2, y0 + (tile_h - fitted.height) // 2))
        label = f"duitang_{row['pin_id']}"
        draw.text((x0 + 6, y0 + tile_h + 8), label, fill="black", font=font)
    sheet.save(output, quality=90)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    query_by_id: dict[str, str] = {}
    for query in QUERIES:
        for pin_id in search_ids(query):
            query_by_id.setdefault(pin_id, query)
    pin_ids = list(query_by_id)[:40]
    print("candidate ids", len(pin_ids))
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        resolved = list(executor.map(resolve_page, pin_ids))
    items = []
    for item in resolved:
        if item:
            item["query"] = query_by_id[item["pin_id"]]
            items.append(item)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        rows = list(executor.map(download, items))
    rows.sort(key=lambda row: (row["query"], int(row["pin_id"])))
    with (OUT / "discovery_manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    make_contact(rows, ROOT / "contact_duitang_discovery.jpg")
    print("downloaded", sum(row["status"] == "downloaded" for row in rows), "of", len(rows))


if __name__ == "__main__":
    main()
