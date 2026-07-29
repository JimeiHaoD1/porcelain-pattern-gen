from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "cn_web_visual20_20260715"
CROPS = OUTPUT / "crops"
ORIGINALS = ROOT / "original_sources" / "cn_web_visual20_20260715"


@dataclass(frozen=True)
class Source:
    key: str
    filename: str
    page: str
    direct_url: str
    referer: str
    rights: str


@dataclass(frozen=True)
class Candidate:
    cid: str
    filename: str
    source_key: str
    crop_box: tuple[int, int, int, int] | None
    grade: str
    crop_label: str
    structure_note: str
    recommendation: str


SOURCES = {
    "jicai_loop": Source(
        "jicai_loop",
        "jicai_141S42K3-2.jpg",
        "https://www.jicaizhipin.com/a/news/printingdesign/235.html",
        "https://www.jicaizhipin.com/uploads/allimg/250418/141S42K3-2.jpg",
        "https://www.jicaizhipin.com/",
        "ColorPax page; no open licence found; research candidate only",
    ),
    "jicai_cross": Source(
        "jicai_cross",
        "jicai_141S43059-3.jpg",
        "https://www.jicaizhipin.com/a/news/printingdesign/235.html",
        "https://www.jicaizhipin.com/uploads/allimg/250418/141S43059-3.jpg",
        "https://www.jicaizhipin.com/",
        "ColorPax page; no open licence found; research candidate only",
    ),
    "jicai_svine": Source(
        "jicai_svine",
        "jicai_141S42R4-5.jpg",
        "https://www.jicaizhipin.com/a/news/printingdesign/235.html",
        "https://www.jicaizhipin.com/uploads/allimg/250418/141S42R4-5.jpg",
        "https://www.jicaizhipin.com/",
        "ColorPax page; no open licence found; research candidate only",
    ),
    "sina_sheet01": Source(
        "sina_sheet01",
        "sina_sheet01_1645x1920.jpg",
        "https://k.sina.cn/article_1550389102_p5c690f6e027012fbd.html",
        "https://n.sinaimg.cn/sinakd20114/365/w1645h1920/20230817/562d-661b0621fe664d7e75d1f5995db6252f.jpg",
        "https://k.sina.cn/",
        "Sina / uploader '三个设计师'; no open licence found; research candidate only",
    ),
    "sina_sheet03": Source(
        "sina_sheet03",
        "sina_sheet03_1645x1920.jpg",
        "https://k.sina.cn/article_1550389102_p5c690f6e027012fbd.html",
        "https://n.sinaimg.cn/sinakd20114/365/w1645h1920/20230817/791b-b5677d8cf6b5c5b70fcf09817b49c7c4.jpg",
        "https://k.sina.cn/",
        "Sina / uploader '三个设计师'; no open licence found; research candidate only",
    ),
    "sina_sheet04": Source(
        "sina_sheet04",
        "sina_sheet04_1645x1920.jpg",
        "https://k.sina.cn/article_1550389102_p5c690f6e027012fbd.html",
        "https://n.sinaimg.cn/sinakd20114/365/w1645h1920/20230817/7e78-3f4fb7ae82d218617e58ae3c9a8619ab.jpg",
        "https://k.sina.cn/",
        "Sina / uploader '三个设计师'; no open licence found; research candidate only",
    ),
    "baidu_scroll_studies": Source(
        "baidu_scroll_studies",
        "baidu_tashuo_scroll_studies.jpg",
        "https://wapbaike.baidu.com/tashuo/browse/content?id=0973544b7b269d26d67cdc38",
        "https://bkimg.cdn.bcebos.com/pic/30adcbef76094b36acaf8cbd19816bd98d1001e93707",
        "https://wapbaike.baidu.com/",
        "Baidu TA说 / author 庭兰瓷语; attribution requested for reprints; no open licence found",
    ),
    "nipic_honeysuckle": Source(
        "nipic_honeysuckle",
        "nipic_honeysuckle_sheet.jpg",
        "https://www.nipic.com/show/48796371.html",
        "https://pic.nximg.cn/file/20241113/31514895_130936406104_2.jpg",
        "https://www.nipic.com/show/48796371.html",
        "NiPic / uploader lsszyl; learning and exchange only unless separately authorised",
    ),
    "zs_321": Source(
        "zs_321",
        "zsbeike_mogao321_three_scrolls.jpg",
        "https://www.zsbeike.com/tp/7588183.html",
        "https://imgs.zsbeike.com/imgs/P/P05009/P05009_tm.txt.d2d42a.jpg",
        "https://www.zsbeike.com/",
        "Creator-uploaded on 知识贝壳; page says copyright belongs to creator; no open licence found",
    ),
    "zs_tang_ceramic": Source(
        "zs_tang_ceramic",
        "zsbeike_tang_ceramic_scroll.jpg",
        "https://www.zsbeike.com/tp/6300796.html",
        "https://imgs.zsbeike.com/imgs/C/C08131/c08131.0080.fdce02.jpg",
        "https://www.zsbeike.com/",
        "Creator-uploaded on 知识贝壳; page says copyright belongs to creator; no open licence found",
    ),
    "zs_217": Source(
        "zs_217",
        "zsbeike_mogao217_border.jpg",
        "https://www.zsbeike.com/tp/7588200.html",
        "https://imgs.zsbeike.com/imgs/P/P05009/P05009_tm.txt.d2d504.jpg",
        "https://www.zsbeike.com/",
        "Creator-uploaded on 知识贝壳; page says copyright belongs to creator; no open licence found",
    ),
    "zs_225": Source(
        "zs_225",
        "zsbeike_mogao225_scroll.jpg",
        "https://www.zsbeike.com/tp/7588251.html",
        "https://imgs.zsbeike.com/imgs/P/P05009/P05009_tm.txt.d2d6c3.jpg",
        "https://www.zsbeike.com/",
        "Creator-uploaded on 知识贝壳; page says copyright belongs to creator; no open licence found",
    ),
    "zs_196": Source(
        "zs_196",
        "zsbeike_mogao196_scroll.jpg",
        "https://www.zsbeike.com/tp/7588265.html",
        "https://imgs.zsbeike.com/imgs/P/P05009/P05009_tm.txt.d2d757.jpg",
        "https://www.zsbeike.com/",
        "Creator-uploaded on 知识贝壳; page says copyright belongs to creator; no open licence found",
    ),
}


# Sina boxes were first checked on the site's 700x818 delivery.  They are
# mapped to the 1645x1920 originals at runtime so the review crops keep the
# higher-resolution linework.
def sina_box(box_700: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    sx = 1645 / 700
    sy = 1920 / 818
    return tuple(round(value * (sx if index % 2 == 0 else sy)) for index, value in enumerate(box_700))  # type: ignore[return-value]


CANDIDATES = [
    Candidate("CN01", "cn01_jicai_looped_leaf_vine.png", "jicai_loop", None, "A", "whole strip", "Looped S-vine with attached paired leaves", "core; clear trunk and repeated branch attachment"),
    Candidate("CN02", "cn02_jicai_crossed_s_vine.png", "jicai_cross", None, "A", "whole strip", "Crossed S-stems with large alternating leaves", "core; useful for crossing and parent-child labels"),
    Candidate("CN03", "cn03_jicai_large_leaf_s_vine.png", "jicai_svine", None, "A", "whole strip", "Long crossed S-vine with large side leaves", "core; strong long-range flow"),
    Candidate("CN04", "cn04_sina_sheet01_row01_camellia.png", "sina_sheet01", sina_box((20, 45, 680, 185)), "A", "row 1 / 山茶花边", "Large looped flower vine", "core; keep flowers as terminal nodes"),
    Candidate("CN05", "cn05_sina_sheet01_row03_camellia.png", "sina_sheet01", sina_box((20, 380, 680, 530)), "A", "row 3 / 山茶花边", "Simpler wavy flower-bearing branch", "core; easier first-pass annotation"),
    Candidate("CN06", "cn06_sina_sheet03_row02_apricot.png", "sina_sheet03", sina_box((20, 180, 680, 275)), "A", "row 2 / 杏花边", "Open wave vine with regularly spaced flowers", "core; clean branch and flower-position supervision"),
    Candidate("CN07", "cn07_sina_sheet03_row03_chrysanthemum.png", "sina_sheet03", sina_box((20, 325, 680, 415)), "A", "row 3 / 菊花边", "Flower, leaf and spiral hierarchy on one continuous stem", "core; strongest hierarchy among Sina rows"),
    Candidate("CN08", "cn08_sina_sheet04_row02_lotus.png", "sina_sheet04", sina_box((20, 220, 680, 350)), "A", "row 2 / 番莲花边", "Repeated looped lotus vine", "core; useful closed-loop topology"),
    Candidate("CN09", "cn09_baidu_flower_loop_row.png", "baidu_scroll_studies", (120, 680, 1125, 820), "B", "first line-drawing row below photo", "Flowers and leaves enclosed by repeated vine loops", "auxiliary; topology is valid but dense"),
    Candidate("CN10", "cn10_baidu_grape_s_vine.png", "baidu_scroll_studies", (120, 820, 1125, 915), "A", "second line-drawing row below photo", "Grape clusters and leaves alternating on an S-vine", "core; high-value grape hierarchy"),
    Candidate("CN11", "cn11_baidu_narrow_leafy_stem.png", "baidu_scroll_studies", (120, 920, 1125, 995), "A", "third narrow line-drawing row below photo", "Single narrow leafy continuous stem", "core; simple branch-order baseline"),
    Candidate("CN12", "cn12_nipic_honeysuckle_sweep.png", "nipic_honeysuckle", (0, 435, 896, 625), "A", "row 3", "Sweeping triple-line S-stem with attached leaf lobes", "core; clear main-trunk continuity"),
    Candidate("CN13", "cn13_nipic_honeysuckle_spiral.png", "nipic_honeysuckle", (0, 650, 896, 835), "A", "row 4", "Repeated spiral-leaf waves on one stem", "core; good repeated branch units"),
    Candidate("CN14", "cn14_zs321_dense_flower_scroll.png", "zs_321", (0, 100, 2550, 700), "A", "top row", "Dense flowers/leaves tied by large vine arcs", "core after annotation pilot; complex occlusion"),
    Candidate("CN15", "cn15_zs321_open_flower_scroll.png", "zs_321", (0, 880, 2550, 1340), "A", "middle row", "Open flower scroll with readable parent arcs", "core; high-quality historical line drawing"),
    Candidate("CN16", "cn16_zs321_round_flower_scroll.png", "zs_321", (0, 1560, 2550, 2040), "B", "bottom row", "Rounded flower masses linked by recurring scroll stems", "auxiliary; denser local ambiguity"),
    Candidate("CN17", "cn17_tang_ceramic_scroll.png", "zs_tang_ceramic", None, "A", "whole strip", "Tang ceramic flower scroll with alternating major leaf fans", "core; clean full-width historical strip"),
    Candidate("CN18", "cn18_zs217_fruit_flower_scroll.png", "zs_217", (0, 210, 2600, 930), "A", "upper botanical row; exclude bead band", "Fruit and flowers on a long undulating parent stem", "core; strong branching and terminal placement"),
    Candidate("CN19", "cn19_zs225_bottom_botanical_scroll.png", "zs_225", (0, 1110, 2520, 1980), "A", "bottom row; exclude winged figure", "Dense botanical scroll with large enclosing stem loop", "core but advanced; annotate after simpler rows"),
    Candidate("CN20", "cn20_zs196_continuous_scroll.png", "zs_196", None, "A", "whole strip", "Continuous fine scroll with small terminal flower", "core; excellent long-range trunk supervision"),
]


REVIEW_ZH = {
    "CN01": "核心。主干闭环和重复挂接都清楚，适合标主干与一级叶枝。",
    "CN02": "核心。交叉 S 形主干明显，适合验证交叉处的父子归属。",
    "CN03": "核心。长距离走势稳定，适合训练整体流向与周期连续性。",
    "CN04": "核心。花朵作为末端节点保留，适合花位与分支关系标注。",
    "CN05": "核心且优先。结构最简洁，建议列入第一批人工标注。",
    "CN06": "核心且优先。波形主干与花位规则，适合花位监督。",
    "CN07": "核心且优先。主干、叶片、花朵和卷曲末梢层级最完整。",
    "CN08": "核心。闭合回环较多，适合补充环状拓扑，但标注难度略高。",
    "CN09": "辅助。结构成立，但花叶密集、父干局部遮挡，暂不作为首批标注。",
    "CN10": "核心且优先。葡萄、叶片在 S 形主干上交替，层级价值高。",
    "CN11": "核心且优先。单主干最简单，可作为分支阶次基线样本。",
    "CN12": "核心且优先。粗主干连续、挂接位置明确，适合先标。",
    "CN13": "核心。重复卷叶单元清楚，适合学习局部分支模块。",
    "CN14": "核心但后标。历史线描质量高，遮挡和局部密度较大。",
    "CN15": "核心且优先。父级弧线可读，适合历史卷草结构。",
    "CN16": "辅助。局部花团之间的父干存在歧义，放入困难样本而非首批。",
    "CN17": "核心。交替叶扇与连续骨架清楚，可补充高密度样式。",
    "CN18": "核心。长波形主干、果实和花叶末端兼具，适合作为进阶样本。",
    "CN19": "核心但后标。大回环明确，内部细节密集，建议简单样本稳定后再标。",
    "CN20": "核心且优先。长距离主干连续，末端花位清楚，适合整体结构监督。",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(session: requests.Session, source: Source) -> Path:
    destination = ORIGINALS / source.filename
    response = session.get(
        source.direct_url,
        timeout=45,
        headers={
            "Referer": source.referer,
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/jpeg,image/png,image/*;q=0.8",
        },
    )
    response.raise_for_status()
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(response.content)
    with Image.open(temporary) as image:
        image.verify()
    temporary.replace(destination)
    return destination


def crop_candidate(candidate: Candidate, source_path: Path) -> tuple[Path, str, tuple[int, int]]:
    with Image.open(source_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        box = candidate.crop_box or (0, 0, image.width, image.height)
        left, top, right, bottom = box
        if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
            raise ValueError(f"{candidate.cid}: invalid crop {box} for {image.size}")
        crop = image.crop(box)
        output_path = CROPS / candidate.filename
        crop.save(output_path, format="PNG", optimize=True)
        return output_path, ",".join(map(str, box)), image.size


def contact_sheet(crop_rows: list[dict[str, str]]) -> Path:
    columns = 2
    tile_w, tile_h = 900, 245
    rows = math.ceil(len(crop_rows) / columns)
    canvas = Image.new("RGB", (columns * tile_w, rows * tile_h), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, row in enumerate(crop_rows):
        col, grid_row = index % columns, index // columns
        x0, y0 = col * tile_w, grid_row * tile_h
        image = Image.open(CROPS / row["file"]).convert("RGB")
        image.thumbnail((tile_w - 32, tile_h - 52), Image.Resampling.LANCZOS)
        paste_x = x0 + (tile_w - image.width) // 2
        paste_y = y0 + 28 + (tile_h - 45 - image.height) // 2
        canvas.paste(image, (paste_x, paste_y))
        draw.text((x0 + 12, y0 + 8), f'{row["id"]}  grade={row["visual_grade"]}  {row["file"]}', fill="black", font=font)
        draw.rectangle((x0, y0, x0 + tile_w - 1, y0 + tile_h - 1), outline=(190, 190, 190), width=1)
    output_path = OUTPUT / "contact_sheet_cn_web_visual20.jpg"
    canvas.save(output_path, quality=92, optimize=True)
    return output_path


def write_readme(rows: list[dict[str, str]]) -> None:
    lines = [
        "# Chinese independent-web visual shortlist (20 crops)",
        "",
        "All 20 crops were visually checked as 2D continuous botanical line art. Grade A is the core structural set; Grade B is still usable but has denser or less explicit parent-stem topology.",
        "",
        "Rights warning: none of these pages supplied an open training/commercial licence. Keep them in source_candidates for research review until the intended dataset use is cleared.",
        "",
        "| ID | Grade | File | Crop | Recommendation |",
        "|---|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(f'| {row["id"]} | {row["visual_grade"]} | `{row["file"]}` | {row["crop_label"]} | {row["recommendation"]} |')
    lines.extend(
        [
            "",
            "See `manifest.csv` for source_page, direct_url, original file, exact crop_box, dimensions, SHA-256, visual rationale and rights notes.",
            "",
        ]
    )
    (OUTPUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def write_review_guide_zh(rows: list[dict[str, str]]) -> None:
    lines = [
        "# 中文网页候选 20 条：逐图审查建议",
        "",
        "- A：可进入结构候选核心集；B：结构可用，但父干较密或局部歧义较大。",
        "- 建议第一批标注：CN05、CN06、CN07、CN10、CN11、CN12、CN15、CN20。",
        "- 这批网页均未发现开放训练或商用许可；在明确用途与授权前，只放在 source_candidates 中审查。",
        "",
        "| ID | 级别 | 文件 | 建议 |",
        "|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(f'| {row["id"]} | {row["visual_grade"]} | `{row["file"]}` | {REVIEW_ZH[row["id"]]} |')
    lines.append("")
    (OUTPUT / "逐图审查建议.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    CROPS.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    source_paths = {key: download(session, source) for key, source in SOURCES.items()}

    rows: list[dict[str, str]] = []
    for candidate in CANDIDATES:
        source = SOURCES[candidate.source_key]
        crop_path, crop_box, source_size = crop_candidate(candidate, source_paths[candidate.source_key])
        with Image.open(crop_path) as crop:
            crop_size = crop.size
        rows.append(
            {
                "id": candidate.cid,
                "file": candidate.filename,
                "source_key": candidate.source_key,
                "source_page": source.page,
                "direct_url": source.direct_url,
                "original_file": source.filename,
                "crop_box": crop_box,
                "crop_label": candidate.crop_label,
                "source_size": f"{source_size[0]}x{source_size[1]}",
                "crop_size": f"{crop_size[0]}x{crop_size[1]}",
                "visual_grade": candidate.grade,
                "structure_note": candidate.structure_note,
                "recommendation": candidate.recommendation,
                "rights_note": source.rights,
                "sha256": sha256(crop_path),
            }
        )

    fieldnames = list(rows[0])
    with (OUTPUT / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    contact_sheet(rows)
    write_readme(rows)
    write_review_guide_zh(rows)
    print(f"sources={len(SOURCES)} crops={len(rows)} output={OUTPUT}")


if __name__ == "__main__":
    main()
