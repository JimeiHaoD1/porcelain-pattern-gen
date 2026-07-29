#!/usr/bin/env python3
"""Build the visually screened, de-duplicated Chinese web candidate staging set.

This directory is intentionally separate from the user's final review folder.
It keeps distinct border designs from multi-row source sheets, while recording
the shared source-image unit so they are not misreported as independent finds.
"""

from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "data" / "source_candidates" / "web_independent_batch4_20260715"
OUTPUT = BATCH / "staged_cn_unique_20260716"
CN = BATCH / "cn_web_visual20_20260715" / "crops"
SINA = BATCH / "sina_filtered_v2"
ORIGINALS = BATCH / "original_sources"


@dataclass(frozen=True)
class Candidate:
    source: Path
    source_group: str
    source_page: str
    source_image_unit: str
    tier: str
    visual_note: str
    dedup_note: str
    crop_box: tuple[int, int, int, int] | None = None


SINA_PAGE = "https://cj.sina.com.cn/articles/view/1872762823/p6fa017c702702b0dg"
JICAI_PAGE = "https://www.jicaizhipin.com/a/news/printingdesign/235.html"
SOHU_PAGE = "https://www.sohu.com/a/206052358_780733"


def cn(name: str, group: str, unit: str, tier: str, note: str, dedup: str) -> Candidate:
    pages = {
        "Jicai": JICAI_PAGE,
        "Sina": "https://k.sina.cn/article_1550389102_p5c690f6e027012fbd.html",
        "Baidu": "https://wapbaike.baidu.com/tashuo/browse/content?id=0973544b7b269d26d67cdc38",
        "Nipic": "https://www.nipic.com/show/48796371.html",
    }
    return Candidate(CN / name, group, pages[group], unit, tier, note, dedup)


CANDIDATES: list[Candidate] = [
    cn("cn01_jicai_looped_leaf_vine.png", "Jicai", "jicai_06.jpg", "core", "闭环S形藤与成对叶片挂接清楚", "对67张与batch3无同图匹配"),
    cn("cn02_jicai_crossed_s_vine.png", "Jicai", "jicai_09.jpg", "core", "交叉S形父干与大叶片层次清楚", "对67张与batch3无同图匹配"),
    cn("cn03_jicai_large_leaf_s_vine.png", "Jicai", "jicai_07.jpg", "core", "长距离S形走势稳定", "对67张与batch3无同图匹配"),
    cn("cn04_sina_sheet01_row01_camellia.png", "Sina", "sina_sheet01_1645x1920.jpg", "core", "花位、主藤和卷曲支梢关系完整", "排除了同源candidate_014重复裁切"),
    cn("cn08_sina_sheet04_row02_lotus.png", "Sina", "sina_sheet04_1645x1920.jpg", "core", "莲花与闭合回环藤结构可读", "排除了同图candidate_002重复裁切"),
    cn("cn09_baidu_flower_loop_row.png", "Baidu", "baidu_tashuo_scroll_studies.jpg", "auxiliary", "花叶密集但循环父干成立", "同源图不同设计行；未按独立来源新增"),
    cn("cn10_baidu_grape_s_vine.png", "Baidu", "baidu_tashuo_scroll_studies.jpg", "core", "葡萄、叶片在S形主藤上交替挂接", "同源图不同设计行；未按独立来源新增"),
    cn("cn11_baidu_narrow_leafy_stem.png", "Baidu", "baidu_tashuo_scroll_studies.jpg", "core", "单主干和短叶枝适合作为简化样本", "同源图不同设计行；未按独立来源新增"),
    cn("cn12_nipic_honeysuckle_sweep.png", "Nipic", "nipic_honeysuckle_sheet.jpg", "core", "三线主干连续且叶瓣挂接明确", "同源图不同设计行；未按独立来源新增"),
    cn("cn13_nipic_honeysuckle_spiral.png", "Nipic", "nipic_honeysuckle_sheet.jpg", "core", "重复卷叶单元和父干连续性清楚", "同源图不同设计行；未按独立来源新增"),
    Candidate(SINA / "candidate_001__sina_01_sheet01_row01.png", "Sina", SINA_PAGE, "sina_01.jpg", "core", "花叶沿连续弧形主藤重复", "与CN04及67张不是同一设计"),
    Candidate(SINA / "candidate_004__sina_04_sheet01_row04.png", "Sina", SINA_PAGE, "sina_01.jpg", "auxiliary", "抽象叶瓣闭环重复，父干较简化", "与同源其他行结构不同"),
    Candidate(SINA / "candidate_012__sina_12_sheet03_row04.png", "Sina", SINA_PAGE, "sina_03.jpg", "core", "花朵、卷叶和波形藤连续", "已排除同图杏花、菊花旧候选"),
    Candidate(SINA / "candidate_023__sina_23_sheet06_row01.png", "Sina", SINA_PAGE, "sina_06.jpg", "core", "花果节点沿细波形藤均匀挂接", "对67张与batch3无同图匹配"),
    Candidate(SINA / "candidate_024__sina_24_sheet06_row02.png", "Sina", SINA_PAGE, "sina_06.jpg", "core", "叶片、果实和卷曲支梢沿主藤交替", "同源图不同设计行；未按独立来源新增"),
    Candidate(SINA / "candidate_025__sina_25_sheet06_row03.png", "Sina", SINA_PAGE, "sina_06.jpg", "core", "花朵与短枝形成清楚重复单元", "同源图不同设计行；未按独立来源新增"),
    Candidate(SINA / "candidate_026__sina_26_sheet06_row04.png", "Sina", SINA_PAGE, "sina_06.jpg", "core", "果实花叶由连续细藤连接", "同源图不同设计行；未按独立来源新增"),
    Candidate(SINA / "candidate_028__sina_28_sheet07_row01.png", "Sina", SINA_PAGE, "sina_07.jpg", "core", "花果节点与双向卷枝关系可读", "对67张与batch3无同图匹配"),
    Candidate(SINA / "candidate_029__sina_29_sheet07_row02.png", "Sina", SINA_PAGE, "sina_07.jpg", "core", "大花和叶片沿波形主藤交替", "同源图不同设计行；未按独立来源新增"),
    Candidate(SINA / "candidate_030__sina_30_sheet07_row03.png", "Sina", SINA_PAGE, "sina_07.jpg", "core", "花叶和卷曲侧枝层级简洁", "同源图不同设计行；未按独立来源新增"),
    Candidate(SINA / "candidate_031__sina_31_sheet07_row04.png", "Sina", SINA_PAGE, "sina_07.jpg", "core", "花团由连续卷藤相连", "同源图不同设计行；未按独立来源新增"),
    Candidate(ORIGINALS / "jicai_dunhuang_lineart" / "jicai_03.jpg", "Jicai", JICAI_PAGE, "jicai_03.jpg", "auxiliary", "交替叶片沿单一波形干线重复", "新增设计；对CN01-03无同图匹配"),
    Candidate(ORIGINALS / "jicai_dunhuang_lineart" / "jicai_17.jpg", "Jicai", JICAI_PAGE, "jicai_17.jpg", "auxiliary", "叶片扇形单元沿连续底藤重复", "新增设计；对CN01-03无同图匹配"),
    Candidate(ORIGINALS / "sohu_dunhuang_borders" / "sohu_02.jpeg", "Sohu", SOHU_PAGE, "sohu_02.jpeg", "auxiliary", "上排花叶循环边饰，局部父干较密", "同一源图上排独立设计；不增加独立来源数", (0, 0, 535, 80)),
]


EXCLUSIONS = [
    ("CN05", "duplicate", "review_candidates_all/Snipaste_2026-07-15_13-18-39.png", "同一山茶花设计的高清重裁"),
    ("CN06", "duplicate", "review_candidates_all/Snipaste_2026-07-15_13-17-22.png", "同一杏花边设计"),
    ("CN07", "duplicate", "review_candidates_all/Snipaste_2026-07-15_13-17-49.png", "同一菊花边设计"),
    ("CN14", "hold_highres_replacement", "batch3/paper-source route", "历史图样与batch3同源路线重合，保留原目录但不计新增"),
    ("CN15", "hold_highres_replacement", "batch3/paper-source route", "历史图样与batch3同源路线重合，保留原目录但不计新增"),
    ("CN16", "hold_highres_replacement", "batch3/paper-source route", "历史图样与batch3同源路线重合，保留原目录但不计新增"),
    ("CN17", "hold_highres_replacement", "batch3/paper-source route", "历史图样与batch3同源路线重合，保留原目录但不计新增"),
    ("CN18", "duplicate", "review_candidates_all/035__strict1_B__B05_thesis_mogao217.png", "同一莫高窟217窟果花卷草的高清重裁"),
    ("CN19", "duplicate", "review_candidates_batch3/A34__candidate_212__D01448673_tang_ceiling_pattern_p252_i05_x3231_356x106.png", "同一图样的更宽重裁"),
    ("CN20", "duplicate", "review_candidates_all/032__strict1_B__B02_zsbeike_mogao196_dense_scroll.png", "同一莫高窟196窟卷草，结构匹配0.9749"),
    ("sina_candidate_002", "duplicate", "CNU005/CN08", "同一莲花闭环边饰的不同裁切"),
    ("sina_candidate_003", "duplicate", "CN05/review_candidates_all", "同一山茶花边设计"),
    ("sina_candidate_010", "duplicate", "review_candidates_all/Snipaste_2026-07-15_13-17-22.png", "同一杏花边设计，结构匹配0.9953"),
    ("sina_candidate_011", "duplicate", "review_candidates_all/Snipaste_2026-07-15_13-17-49.png", "同一菊花边设计，结构匹配0.9874"),
    ("sina_candidate_014", "duplicate", "CNU004/CN04", "同一山茶花边设计的带文字裁切"),
    ("sina_candidate_016", "duplicate", "review_candidates_all/Snipaste_2026-07-15_13-18-39.png", "同一山茶花边设计，高SIFT覆盖"),
    ("sina_candidate_017", "duplicate", "review_candidates_all/Snipaste_2026-07-15_13-18-45.png", "同一玫瑰边设计"),
    ("sohu_02_bottom", "duplicate", "review_candidates_all/Snipaste_2026-07-15_13-18-16.png", "同一S形花叶边饰，结构匹配0.8428"),
    ("sohu_05", "duplicate", "review_candidates_all/099__web_U__A03_dunhuang_mogao201_mid_tang.jpeg", "像素级同图，pHash距离0"),
]


def trim_white(image: Image.Image, padding: int = 8) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    gray = image.convert("L")
    mask = gray.point(lambda value: 255 if value < 245 else 0)
    bbox = mask.getbbox()
    if not bbox:
        return image
    left, top, right, bottom = bbox
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(image.width, right + padding)
    bottom = min(image.height, bottom + padding)
    return image.crop((left, top, right, bottom))


def build_contact(files: list[Path], output: Path) -> None:
    columns = 4
    cell_width, cell_height, label_height, gutter = 420, 190, 28, 10
    rows = math.ceil(len(files) / columns)
    canvas = Image.new(
        "RGB",
        (gutter + columns * (cell_width + gutter), gutter + rows * (cell_height + label_height + gutter)),
        "#DADDE1",
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, path in enumerate(files):
        row, column = divmod(index, columns)
        x = gutter + column * (cell_width + gutter)
        y = gutter + row * (cell_height + label_height + gutter)
        draw.rectangle((x, y, x + cell_width, y + label_height), fill="white")
        draw.text((x + 6, y + 7), path.name, fill="#111111", font=font)
        with Image.open(path) as image:
            fitted = ImageOps.contain(image.convert("RGB"), (cell_width - 8, cell_height - 8), Image.Resampling.LANCZOS)
        cell = Image.new("RGB", (cell_width, cell_height), "white")
        cell.paste(fitted, ((cell_width - fitted.width) // 2, (cell_height - fitted.height) // 2))
        canvas.paste(cell, (x, y + label_height))
    canvas.save(output, quality=94, optimize=True)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT.iterdir():
        if stale.is_file() and (stale.name.startswith("CNU") or stale.name in {"manifest.csv", "exclusion_log.csv", "contact_sheet.jpg", "README.md"}):
            stale.unlink()

    rows: list[dict[str, str]] = []
    output_files: list[Path] = []
    for index, candidate in enumerate(CANDIDATES, start=1):
        if not candidate.source.exists():
            raise FileNotFoundError(candidate.source)
        with Image.open(candidate.source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            if candidate.crop_box is not None:
                image = image.crop(candidate.crop_box)
            image = trim_white(image)
            output = OUTPUT / f"CNU{index:03d}.png"
            image.save(output, optimize=True)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        rows.append(
            {
                "id": f"CNU{index:03d}",
                "file": output.name,
                "original_file": str(candidate.source),
                "source_group": candidate.source_group,
                "source_page": candidate.source_page,
                "source_image_unit": candidate.source_image_unit,
                "tier": candidate.tier,
                "visual_note": candidate.visual_note,
                "dedup_note": candidate.dedup_note,
                "crop_box": "" if candidate.crop_box is None else ",".join(map(str, candidate.crop_box)),
                "sha256": digest,
            }
        )
        output_files.append(output)

    with (OUTPUT / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    with (OUTPUT / "exclusion_log.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(["candidate", "status", "matched_reference", "reason"])
        writer.writerows(EXCLUSIONS)

    source_units = len({(row["source_group"], row["source_image_unit"]) for row in rows})
    core_count = sum(row["tier"] == "core" for row in rows)
    (OUTPUT / "README.md").write_text(
        "# 中文网页唯一候选暂存集\n\n"
        f"- 条带设计数：{len(rows)}\n"
        f"- 独立源图单元数：{source_units}\n"
        f"- 核心：{core_count}；辅助：{len(rows) - core_count}\n"
        "- 多行素材中的不同设计可以分别用于结构标注，但共享 `source_image_unit`，不得按多个独立网页发现计数。\n"
        "- 已排除现有67张、batch3以及CN/Sina内部的同图高清重裁。\n"
        "- `exclusion_log.csv` 记录了明确同图和保守留作高清替换的项目。\n"
        "- 网页图片未发现开放训练许可；此目录仅作为研究审查候选。\n",
        encoding="utf-8",
    )
    build_contact(output_files, OUTPUT / "contact_sheet.jpg")
    print(f"candidates={len(rows)}; source_units={source_units}; core={core_count}; auxiliary={len(rows)-core_count}; output={OUTPUT}")


if __name__ == "__main__":
    main()
