#!/usr/bin/env python3
"""Assemble the visually approved third image-search batch for user review."""

from __future__ import annotations

import csv
import hashlib
import re
import shutil
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
BATCH_ROOT = (
    ROOT
    / "data"
    / "source_candidates"
    / "strict_2d_lineart_batch3_20260715"
)
AUTO_DIR = BATCH_ROOT / "auto_filtered"
MEYER_DIR = BATCH_ROOT / "meyer_crops"
MET_DIR = BATCH_ROOT / "met_crops"
OUTPUT_DIR = ROOT / "data" / "review_candidates_batch3_20260715"


# Each image below passed a full-sheet visual review.  They were selected for
# a continuous/traceable vine, visible mounted leaves or flowers, and usable
# monochrome line quality.  Near duplicates of the user's existing 67 images
# were excluded before this list was made.
CORE_IDS = [
    61,
    68,
    70,
    76,
    77,
    78,
    80,
    81,
    82,
    149,
    151,
    152,
    153,
    159,
    160,
    161,
    162,
    163,
    172,
    174,
    175,
    177,
    182,
    183,
    184,
    190,
    193,
    194,
    197,
    200,
    201,
    207,
    210,
    212,
]


MEYER_KEEP = [1, 2, 3, 4, 5, 8, 9, 10, 11]
MET_KEEP = [1, 2, 3, 4]


PDF_URL = "https://ygx.sxu.edu.cn/db/%E5%AD%A6%E4%BD%8D/D01448673.pdf"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def indexed_file(directory: Path, prefix: str, index: int) -> Path:
    matches = sorted(directory.glob(f"{prefix}_{index:02d}_*"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one file for {prefix} {index}, found {matches}")
    return matches[0]


def auto_file(index: int) -> Path:
    matches = sorted(AUTO_DIR.glob(f"candidate_{index:03d}__*"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one auto candidate {index}, found {matches}")
    return matches[0]


def page_from_name(name: str) -> str:
    match = re.search(r"_p(\d{3})_", name)
    return match.group(1) if match else ""


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT_DIR.iterdir():
        if stale.is_file():
            stale.unlink()

    rows: list[dict[str, object]] = []
    for review_index, candidate_id in enumerate(CORE_IDS, start=1):
        source = auto_file(candidate_id)
        destination = OUTPUT_DIR / f"A{review_index:02d}__{source.name}"
        shutil.copy2(source, destination)
        width, height = dimensions(destination)
        rows.append(
            {
                "review_file": destination.name,
                "tier": "A_core_chinese",
                "visual_status": "passed",
                "visual_reason": "continuous Chinese-style vine; mounted leaf/flower branch; usable 2D line art",
                "source_file": source.name,
                "source_page_number": page_from_name(source.name),
                "source_page": PDF_URL,
                "rights": "research candidate; source copyright not independently cleared",
                "width": width,
                "height": height,
                "sha256": sha256(destination),
            }
        )

    auxiliary_sources = [
        ("meyer", index, indexed_file(MEYER_DIR, "meyer", index)) for index in MEYER_KEEP
    ] + [("met", index, indexed_file(MET_DIR, "met", index)) for index in MET_KEEP]
    for review_index, (family, _, source) in enumerate(auxiliary_sources, start=1):
        destination = OUTPUT_DIR / f"R{review_index:02d}__{source.name}"
        shutil.copy2(source, destination)
        width, height = dimensions(destination)
        if family == "meyer":
            rights = "Public Domain Mark 1.0; Meyer, A Handbook of Ornament (1898)"
            source_page = "https://commons.wikimedia.org/wiki/Category:Blatt-Rankenband"
        else:
            rights = "The Met Open Access; Public Domain"
            object_match = re.search(r"plate(\d+)", source.name)
            object_id = {"7": "406539", "8": "406540", "9": "406541"}.get(
                object_match.group(1) if object_match else "", ""
            )
            source_page = f"https://www.metmuseum.org/art/collection/search/{object_id}"
        rows.append(
            {
                "review_file": destination.name,
                "tier": "R_cross_cultural_structure",
                "visual_status": "passed_auxiliary",
                "visual_reason": "clean continuous vine and branch hierarchy; keep separate from Chinese-style gold set",
                "source_file": source.name,
                "source_page_number": "",
                "source_page": source_page,
                "rights": rights,
                "width": width,
                "height": height,
                "sha256": sha256(destination),
            }
        )

    with (OUTPUT_DIR / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    readme = f"""# batch3 人工复审说明

- A组：{len(CORE_IDS)} 张。中国纹样论文图版中逐张视觉通过，可优先审查并计入SW核心候选。
- R组：{len(auxiliary_sources)} 张。公共领域的跨文化连续花藤，只适合结构辅助或预训练，暂不与SW金标混合。
- 合计：{len(rows)} 张；均已完成尺寸/单色初筛、与现有67张的自动去重和人工视觉验收。
- 你的操作：直接在本文件夹删除不满意图片即可；`manifest.csv` 保留来源与版权状态。

视觉通过只表示“值得你复审”，不等于自动成为最终训练金标。
"""
    (OUTPUT_DIR / "README.md").write_text(readme, encoding="utf-8")
    print(
        f"core={len(CORE_IDS)}; auxiliary={len(auxiliary_sources)}; "
        f"total={len(rows)}; output={OUTPUT_DIR}"
    )


if __name__ == "__main__":
    main()
