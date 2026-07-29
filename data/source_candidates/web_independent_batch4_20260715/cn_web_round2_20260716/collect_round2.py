from __future__ import annotations

import csv
import hashlib
import io
import pathlib
import shutil
import urllib.request

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = pathlib.Path(__file__).resolve().parent
ORIGINALS = ROOT / "original_sources"
CROPS = ROOT / "crops"
UNIQUE_FINAL = ROOT / "unique_final"

SOURCES = [
    {
        "source_key": f"sina_20230514_{index:02d}",
        "source_page": "https://cj.sina.com.cn/articles/view/3925604985/pe9fbfa79027021c0b",
        "direct_url": url,
        "rights_note": "Sina repost; no open licence found; research screening only",
    }
    for index, url in enumerate(
        [
            "https://k.sinaimg.cn/n/sinakd20122/365/w1645h1920/20230514/2111-6b681279d6bc869359709a1fdd7c89a9.jpg/w700d1q75cms.jpg",
            "https://k.sinaimg.cn/n/sinakd20122/365/w1645h1920/20230514/21c1-bf356f1aac8238015d6fb85abceac21f.jpg/w700d1q75cms.jpg",
            "https://k.sinaimg.cn/n/sinakd20122/365/w1645h1920/20230514/6611-7185846593e60e81d96b6b761f600637.jpg/w700d1q75cms.jpg",
            "https://k.sinaimg.cn/n/sinakd20122/365/w1645h1920/20230514/f74e-a84b6995a64c6eb0f8900cea0f764aaf.jpg/w700d1q75cms.jpg",
            "https://k.sinaimg.cn/n/sinakd20122/365/w1645h1920/20230514/fcb6-c4d9c61106cd06461781648222eefbcd.jpg/w700d1q75cms.jpg",
            "https://k.sinaimg.cn/n/sinakd20122/365/w1645h1920/20230514/478e-5c930f71d7b0351d8e9f258f74d5ef9a.jpg/w700d1q75cms.jpg",
            "https://k.sinaimg.cn/n/sinakd20122/365/w1645h1920/20230514/e114-fe3f1c3404045f917d0b7597751bfede.jpg/w700d1q75cms.jpg",
            "https://k.sinaimg.cn/n/sinakd20122/365/w1645h1920/20230514/111a-6a7c8a1588df25e6ddaea23bceb2e4b4.jpg/w700d1q75cms.jpg",
            "https://k.sinaimg.cn/n/sinakd20122/365/w1645h1920/20230514/5fb8-90de6f362aa52859ab728cb0f57969bb.jpg/w700d1q75cms.jpg",
        ],
        start=1,
    )
]

SOURCES += [
    {
        "source_key": f"sohu_daguan_20241021_{index:02d}",
        "source_page": "https://www.sohu.com/a/818645845_120910862",
        "direct_url": url,
        "rights_note": "Guangdong Daguan Museum article via Sohu; research screening only",
    }
    for index, url in enumerate(
        [
            "https://q6.itc.cn/images01/20241021/9ffd27496b5145ec8f1ab9045bb6cf67.jpeg",
            "https://q5.itc.cn/images01/20241021/08553a98a0c142b6bcb43957f39e6019.jpeg",
            "https://q1.itc.cn/images01/20241021/3176df5675c5484a97bb4cf3e8dbd3da.jpeg",
            "https://q7.itc.cn/images01/20241021/b47db30d50bc4d81a7ab941a9e1d8bbe.jpeg",
            "https://q8.itc.cn/images01/20241021/2dae331518dc47f6aa4bfbabe2eefaba.jpeg",
            "https://q3.itc.cn/images01/20241021/6c76a301a40744a3b5436ad4a1af002c.jpeg",
            "https://q4.itc.cn/images01/20241021/c46a5c3cab934d6a99b050b7647a596c.jpeg",
            "https://q4.itc.cn/images01/20241021/c3ca4db49b73447397145ce68fe26d92.jpeg",
            "https://q5.itc.cn/images01/20241021/a60c58e02c704b0bb06072940722eaea.jpeg",
            "https://q4.itc.cn/images01/20241021/4a58fd84a65b416389ed53d1d816bd27.jpeg",
        ],
        start=1,
    )
]

CROP_SPECS = [
    {
        "id": "R201",
        "source_key": "sina_20230514_01",
        "filename": "r201_camellia_looped_vine.png",
        "box": (18, 20, 682, 151),
        "label": "山茶花边",
        "structure_note": "Looped main vine with alternating flowers and attached leaves",
    },
    {
        "id": "R202",
        "source_key": "sina_20230514_03",
        "filename": "r202_pomegranate_chrysanthemum_scroll.png",
        "box": (0, 451, 700, 587),
        "label": "石榴菊花边",
        "structure_note": "Dense continuous scroll with flowers, leaf lobes and secondary curls",
    },
    {
        "id": "R203",
        "source_key": "sina_20230514_03",
        "filename": "r203_baoxiang_flower_scroll.png",
        "box": (0, 611, 700, 750),
        "label": "宝相花边",
        "structure_note": "Alternating flower anchors on an S-shaped vine with repeated secondary curls",
    },
    {
        "id": "R204",
        "source_key": "sina_20230514_04",
        "filename": "r204_lotus_leaf_loop.png",
        "box": (22, 183, 678, 350),
        "label": "番莲花边",
        "structure_note": "Large leaf loops form a continuous stem around alternating lotus flowers",
    },
    {
        "id": "R205",
        "source_key": "sina_20230514_04",
        "filename": "r205_chrysanthemum_leaf_scroll.png",
        "box": (22, 414, 678, 558),
        "label": "菊花边",
        "structure_note": "Repeated flower nodes connected by large opposing leaf-scroll branches",
    },
    {
        "id": "R206",
        "source_key": "sina_20230514_04",
        "filename": "r206_trumpet_flower_scroll.png",
        "box": (30, 600, 670, 753),
        "label": "喇叭花边",
        "structure_note": "Continuous paired scrolls with clearly mounted trumpet-flower terminals",
    },
    {
        "id": "R207",
        "source_key": "sina_20230514_05",
        "filename": "r207_pomegranate_flower_wave.png",
        "box": (20, 20, 680, 111),
        "label": "石柱花边",
        "structure_note": "Simple wave stem with alternating small flower nodes and hook branches",
    },
    {
        "id": "R208",
        "source_key": "sina_20230514_05",
        "filename": "r208_orchid_branch_wave.png",
        "box": (22, 173, 678, 255),
        "label": "宜草花边",
        "structure_note": "Clean sweeping branch with alternating leaf fans, buds and branch junctions",
    },
    {
        "id": "R209",
        "source_key": "sina_20230514_05",
        "filename": "r209_camellia_flower_vine.png",
        "box": (21, 318, 679, 412),
        "label": "山草花边",
        "structure_note": "Alternating flowers and lobed leaves mounted on a continuous curved vine",
    },
    {
        "id": "R210",
        "source_key": "sina_20230514_05",
        "filename": "r210_fruit_leaf_s_vine.png",
        "box": (17, 480, 683, 581),
        "label": "山茶花边",
        "structure_note": "Long S-vine with fruit clusters, leaves and short secondary tendrils",
    },
    {
        "id": "R211",
        "source_key": "sina_20230514_06",
        "filename": "r211_flower_cloud_vine.png",
        "box": (20, 24, 680, 130),
        "label": "花卉卷草边",
        "structure_note": "Alternating flower heads connected through repeated cloud-like vine curls",
    },
    {
        "id": "R212",
        "source_key": "sina_20230514_06",
        "filename": "r212_hibiscus_leaf_scroll.png",
        "box": (20, 194, 680, 279),
        "label": "扶桑花边",
        "structure_note": "Flower-bearing main stem with large attached leaves and clear junctions",
    },
    {
        "id": "R213",
        "source_key": "sina_20230514_06",
        "filename": "r213_camellia_leaf_scroll.png",
        "box": (20, 343, 680, 435),
        "label": "山茶花边",
        "structure_note": "Repeated flower and leaf modules joined by a visible continuous stem",
    },
]

UNIQUE_IDS = {"R203", "R205"}
EXCLUSIONS = [
    {
        "id": "R202",
        "reason": "duplicate",
        "reference": "staged_cn_unique_20260716/CNU013.png",
        "note": "same pomegranate-chrysanthemum strip",
    },
    {
        "id": "R204",
        "reason": "duplicate",
        "reference": "cn_web_visual20_20260715/crops/cn08_sina_sheet04_row02_lotus.png",
        "note": "same lotus loop strip",
    },
    {
        "id": "R207",
        "reason": "duplicate",
        "reference": "staged_cn_unique_20260716/CNU014.png",
        "note": "same simple flower-wave strip",
    },
    {
        "id": "R208",
        "reason": "manual duplicate",
        "reference": "staged_cn_unique_20260716/CNU015.png",
        "note": "same orchid branch strip; color/crop difference only",
    },
    {
        "id": "R210",
        "reason": "manual duplicate",
        "reference": "staged_cn_unique_20260716/CNU017.png",
        "note": "same fruit-and-flower S-vine; color/crop difference only",
    },
    {
        "id": "R201",
        "reason": "manual duplicate after second audit",
        "reference": "staged_cn_unique_20260716/CNU004.png",
        "note": "same artwork under a different crop; 92 SIFT inliers",
    },
    {
        "id": "R206",
        "reason": "manual duplicate after second audit",
        "reference": "staged_cn_unique_20260716/CNU012.png",
        "note": "same artwork under a different crop; 59 SIFT inliers",
    },
    {
        "id": "R209",
        "reason": "manual duplicate after second audit",
        "reference": "staged_cn_unique_20260716/CNU016.png",
        "note": "same artwork under a different crop; 83 SIFT inliers",
    },
    {
        "id": "R211",
        "reason": "manual duplicate after second audit",
        "reference": "staged_cn_unique_20260716/CNU018.png",
        "note": "same artwork under a different crop; 76 SIFT inliers",
    },
    {
        "id": "R212",
        "reason": "manual duplicate after second audit",
        "reference": "staged_cn_unique_20260716/CNU019.png",
        "note": "same artwork under a different crop; 84 SIFT inliers",
    },
    {
        "id": "R213",
        "reason": "manual duplicate after second audit",
        "reference": "staged_cn_unique_20260716/CNU020.png",
        "note": "visually identical artwork; 28 SIFT inliers",
    },
]

SOURCES += [
    {
        "source_key": f"sohu_aurora_20201022_{index:02d}",
        "source_page": "https://www.sohu.com/a/426496652_786042",
        "direct_url": url,
        "rights_note": "Aurora Museum article via Sohu; research screening only",
    }
    for index, url in enumerate(
        [
            "https://p6.itc.cn/q_70/images03/20201022/706d10adc7d84d9c9209bfd742ca2399.jpeg",
            "https://p8.itc.cn/q_70/images03/20201022/b1fac281ddd54998bb8c055dd6b0e64a.jpeg",
            "https://p2.itc.cn/q_70/images03/20201022/64fbf60c4d934aee834dad611d740e6e.jpeg",
            "https://p6.itc.cn/q_70/images03/20201022/6694e58561844cb5a069bd77f21e419f.jpeg",
            "https://p2.itc.cn/q_70/images03/20201022/4ba8343c330b4394835366d385b68f3e.jpeg",
        ],
        start=1,
    )
]


def download_sources() -> None:
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for item in SOURCES:
        path = ORIGINALS / f"{item['source_key']}.jpg"
        if path.exists() and path.stat().st_size > 1000:
            try:
                with Image.open(path) as existing:
                    existing.verify()
                with Image.open(path) as existing:
                    size = f"{existing.width}x{existing.height}"
                rows.append({**item, "filename": path.name, "size": size, "status": "existing"})
                print(item["source_key"], "existing", size)
                continue
            except Exception:  # noqa: BLE001
                pass
        request = urllib.request.Request(
            item["direct_url"],
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": item["source_page"],
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read()
                content_type = response.headers.get_content_type()
            if not content_type.startswith("image/") or len(data) < 1000:
                raise ValueError(f"bad payload: {content_type}, {len(data)} bytes")
            image = Image.open(io.BytesIO(data))
            image.verify()
            path.write_bytes(data)
            status = "downloaded"
            size = f"{image.width}x{image.height}"
        except Exception as exc:  # noqa: BLE001
            status = f"error: {exc}"
            size = ""
        rows.append({**item, "filename": path.name, "size": size, "status": status})
        print(item["source_key"], status, size)
    with (ORIGINALS / "source_manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def make_contact(source_dir: pathlib.Path, output: pathlib.Path, columns: int = 3) -> None:
    files = sorted(
        path for path in source_dir.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    tile_w, tile_h, label_h = 420, 420, 36
    rows = (len(files) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_w, rows * (tile_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, path in enumerate(files):
        image = Image.open(path).convert("RGB")
        fitted = ImageOps.contain(image, (tile_w - 16, tile_h - 16))
        x = (index % columns) * tile_w + (tile_w - fitted.width) // 2
        y0 = (index // columns) * (tile_h + label_h)
        y = y0 + (tile_h - fitted.height) // 2
        sheet.paste(fitted, (x, y))
        draw.text((index % columns * tile_w + 8, y0 + tile_h + 8), path.stem, fill="black", font=font)
    sheet.save(output, quality=92)


def build_unique_final() -> None:
    UNIQUE_FINAL.mkdir(parents=True, exist_ok=True)
    for stale in UNIQUE_FINAL.iterdir():
        if stale.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            stale.unlink()
    source_by_key = {item["source_key"]: item for item in SOURCES}
    rows: list[dict[str, str]] = []
    for spec in (item for item in CROP_SPECS if item["id"] in UNIQUE_IDS):
        source = source_by_key[spec["source_key"]]
        original_path = ORIGINALS / f"{spec['source_key']}.jpg"
        with Image.open(original_path) as original:
            crop = original.convert("RGB").crop(spec["box"])
            original_size = f"{original.width}x{original.height}"
        output = UNIQUE_FINAL / spec["filename"]
        crop.save(output, optimize=True)
        rows.append(
            {
                "id": spec["id"],
                "file": spec["filename"],
                "source_key": spec["source_key"],
                "source_page": source["source_page"],
                "direct_url": source["direct_url"],
                "original_file": original_path.name,
                "crop_box": ",".join(map(str, spec["box"])),
                "crop_label": spec["label"],
                "source_size": original_size,
                "crop_size": f"{crop.width}x{crop.height}",
                "visual_grade": "A",
                "structure_note": spec["structure_note"],
                "recommendation": "core; unique after second automatic and manual audit",
                "rights_note": source["rights_note"],
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            }
        )
    for manifest_path in (ROOT / "manifest.csv", UNIQUE_FINAL / "manifest.csv"):
        with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    for exclusion_path in (ROOT / "exclusion_log.csv", UNIQUE_FINAL / "exclusion_log.csv"):
        with exclusion_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=EXCLUSIONS[0].keys())
            writer.writeheader()
            writer.writerows(EXCLUSIONS)
    make_contact(UNIQUE_FINAL, ROOT / "contact_sheet.jpg", columns=2)
    shutil.copy2(ROOT / "contact_sheet.jpg", UNIQUE_FINAL / "contact_sheet.jpg")


if __name__ == "__main__":
    download_sources()
    make_contact(ORIGINALS, ROOT / "contact_originals.jpg")
    build_unique_final()
