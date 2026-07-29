#!/usr/bin/env python3
"""Assemble the visually screened, cross-source web batch into one review folder."""

from __future__ import annotations

import csv
import hashlib
import shutil
from collections import Counter
from pathlib import Path


ROOT = Path(r"D:\sdxl\chanzhi_sw_clean")
BASE = ROOT / "data/source_candidates/web_independent_batch4_20260715"
OUTPUT = ROOT / "data/review_candidates_web_batch4_20260716"

SOURCES = {
    "cn1": BASE / "staged_cn_unique_20260716",
    "open": BASE / "open_collection_screened_strips_20260716",
    "cn2": BASE / "cn_web_round2_20260716/unique_final",
    "nga": BASE / "nga_screened_20260716",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_records() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []

    for row in read_csv(SOURCES["cn1"] / "manifest.csv"):
        records.append(
            {
                "tier": row["tier"],
                "group": "CN_WEB_1",
                "original_id": row["id"],
                "source_path": str(SOURCES["cn1"] / row["file"]),
                "source_group": row["source_group"],
                "source_image_unit": row["source_image_unit"],
                "source_page": row["source_page"],
                "direct_url": "",
                "rights": "No open licence found; research screening only",
                "visual_note": row["visual_note"],
                "dedup_note": row["dedup_note"],
                "crop_box": row["crop_box"],
                "independent_source_count": "1" if row["source_image_unit"] not in {
                    prior["source_image_unit"] for prior in records if prior["group"] == "CN_WEB_1"
                } else "0",
            }
        )

    for row in read_csv(SOURCES["open"] / "manifest.csv"):
        if row["decision"] != "kept":
            continue
        records.append(
            {
                "tier": row["tier"],
                "group": "OPEN_COLLECTION",
                "original_id": row["source_id"],
                "source_path": str(SOURCES["open"] / row["output_file"]),
                "source_group": "Met / Cooper Hewitt / Wikimedia Commons",
                "source_image_unit": row["source_id"],
                "source_page": row["source_page"],
                "direct_url": row["direct_image_url"],
                "rights": row["rights"],
                "visual_note": row["reason"],
                "dedup_note": "No likely duplicate against the prior 67, batch3, or CN_WEB_1",
                "crop_box": row["crop_pixels"],
                "independent_source_count": row["independent_source_count"],
            }
        )

    for row in read_csv(SOURCES["cn2"] / "manifest.csv"):
        records.append(
            {
                "tier": "core",
                "group": "CN_WEB_2",
                "original_id": row["id"],
                "source_path": str(SOURCES["cn2"] / row["file"]),
                "source_group": "Sina",
                "source_image_unit": row["source_key"],
                "source_page": row["source_page"],
                "direct_url": row["direct_url"],
                "rights": row["rights_note"],
                "visual_note": row["structure_note"],
                "dedup_note": "Passed corrected cross-batch audit; six sibling crops were excluded as duplicates",
                "crop_box": row["crop_box"],
                "independent_source_count": "1",
            }
        )

    for row in read_csv(SOURCES["nga"] / "manifest.csv"):
        records.append(
            {
                "tier": row["tier"],
                "group": "NGA",
                "original_id": row["id"],
                "source_path": str(SOURCES["nga"] / row["file"]),
                "source_group": row["source_group"],
                "source_image_unit": row["source_image_unit"],
                "source_page": row["source_page"],
                "direct_url": row["direct_url"],
                "rights": row["rights"],
                "visual_note": row["visual_note"],
                "dedup_note": row["dedup_note"],
                "crop_box": row["crop_box"],
                "independent_source_count": "1",
            }
        )

    return records


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite existing review folder: {OUTPUT}")
    OUTPUT.mkdir(parents=True)

    records = normalized_records()
    assert len(records) == 48, f"Expected 48 screened candidates, found {len(records)}"
    assert Counter(row["tier"] for row in records) == Counter({"core": 25, "auxiliary": 23})
    assert sum(int(row["independent_source_count"]) for row in records) == 37

    tier_numbers: Counter[str] = Counter()
    final_rows: list[dict[str, str]] = []
    ordered = sorted(records, key=lambda row: (row["tier"] != "core", row["group"], row["original_id"]))
    for global_index, row in enumerate(ordered, start=1):
        tier_numbers[row["tier"]] += 1
        source = Path(row.pop("source_path"))
        if not source.is_file():
            raise FileNotFoundError(source)
        tier_prefix = "01_CORE" if row["tier"] == "core" else "02_AUX"
        filename = f"{tier_prefix}_{tier_numbers[row['tier']]:03d}__{row['group']}__{row['original_id']}{source.suffix.lower()}"
        destination = OUTPUT / filename
        shutil.copy2(source, destination)
        final_rows.append(
            {
                "final_id": f"W{global_index:03d}",
                "final_file": filename,
                **row,
                "sha256": sha256(destination),
            }
        )

    write_csv(OUTPUT / "manifest.csv", final_rows)

    source_summary: list[dict[str, str]] = []
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in final_rows:
        key = (row["group"], row["source_image_unit"], row["source_page"])
        grouped.setdefault(key, []).append(row)
    for (group, source_unit, source_page), items in sorted(grouped.items()):
        source_summary.append(
            {
                "group": group,
                "source_image_unit": source_unit,
                "source_page": source_page,
                "candidate_files": ";".join(item["final_file"] for item in items),
                "candidate_count": str(len(items)),
                "core_count": str(sum(item["tier"] == "core" for item in items)),
                "auxiliary_count": str(sum(item["tier"] == "auxiliary" for item in items)),
            }
        )
    write_csv(OUTPUT / "source_units.csv", source_summary)
    assert len(source_summary) == 37

    audit_dir = OUTPUT / "audit"
    audit_dir.mkdir()
    shutil.copy2(SOURCES["cn1"] / "exclusion_log.csv", audit_dir / "cn_web_1_exclusion_log.csv")
    shutil.copy2(SOURCES["cn2"] / "exclusion_log.csv", audit_dir / "cn_web_2_exclusion_log.csv")
    shutil.copy2(ROOT / "artifacts/batch4_open21_near_duplicate_report.csv", audit_dir / "open_collection_near_duplicate_report.csv")
    shutil.copy2(ROOT / "artifacts/batch4_final3_near_duplicate_report.csv", audit_dir / "final_added_near_duplicate_report.csv")

    readme = f"""# 第四批网络候选（用户删除审查目录）

- 图片条数：48（核心 25；辅助 23）
- 独立源图单元：37；同一源图裁出的多条不会重复计算来源数
- 与此前 67 张合计：115 张
- 图片都平铺在本目录：`01_CORE_` 开头的是优先线稿/结构样本，`02_AUX_` 是彩色、低对比度、枝干较弱或跨文化参考
- 你可以直接删除不满意的图片；删完告诉我，我会按剩余文件重建 manifest 并进入标注准备
- `manifest.csv`：逐图来源、等级、视觉理由和去重说明
- `source_units.csv`：按独立源图单元汇总，防止同页多裁片虚增数量
- `contact_sheets/`：快速总览
- `audit/`：明确排除项与近重复比对结果

审查硬标准：保留能追出连续主藤、花位/节点及至少一级分支的二维边饰；优先保留有二级卷曲或枝叶挂接的样本。纯几何、独立团花、浮雕/照片感、主体被花瓶/动物切断、主干不可追踪的图应删除。网页转载图未必带开放训练许可，因此中文网页图暂限研究审查；馆藏图的开放权利见 `manifest.csv`。
"""
    (OUTPUT / "README_先看这里.md").write_text(readme, encoding="utf-8")
    print(f"output={OUTPUT}; images={len(final_rows)}; core=25; auxiliary=23; source_units={len(source_summary)}")


if __name__ == "__main__":
    main()
