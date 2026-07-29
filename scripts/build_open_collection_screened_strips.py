#!/usr/bin/env python3
"""Crop the visually screened open-collection sources into horizontal strips."""

from __future__ import annotations

import csv
import pathlib
from dataclasses import dataclass

from PIL import Image, ImageOps


@dataclass(frozen=True)
class CropSpec:
    source_id: str
    suffix: str
    tier: str
    crop: tuple[float, float, float, float]
    rotate_degrees: int
    reason: str


# Fractions were selected by visual inspection of the downloaded full-resolution
# images. "core" means a mostly monochrome/line-drawn plant scroll whose stem and
# subordinate foliage remain traceable. "auxiliary" means a flat 2D colour source
# or a structurally weaker border suitable for reconstruction/reference only.
CROPS = [
    CropSpec("OC01", "woven_floral_scroll", "auxiliary", (0.015, 0.04, 0.985, 0.94), 0, "flat colour drawing; clear repeated floral scroll, reconstruction reference only"),
    CropSpec("OC02", "palmette_scroll", "auxiliary", (0.03, 0.08, 0.97, 0.90), 0, "monochrome line drawing, but palmettes dominate and the parent-child vine hierarchy is weak"),
    CropSpec("OC04", "foliage_frieze", "core", (0.05, 0.08, 0.95, 0.84), 0, "monochrome foliage scroll with traceable central and lateral branches"),
    CropSpec("OC05", "rinceaux_inner_band", "core", (0.11, 0.27, 0.91, 0.71), 0, "monochrome continuous vine; outer presentation frames removed"),
    CropSpec("OC06", "left_rinceaux", "core", (0.19, 0.14, 0.52, 0.87), 90, "left vertical plant-scroll study rotated into a horizontal strip"),
    CropSpec("OC06", "right_rinceaux", "auxiliary", (0.58, 0.15, 0.84, 0.86), 90, "right vertical plant-scroll study rotated into a horizontal strip; architectural framework weakens the plant hierarchy; same source as OC06 left"),
    CropSpec("OC07", "acanthus_frieze", "auxiliary", (0.01, 0.19, 0.99, 0.70), 0, "monochrome continuous acanthus band, but dense leaf masses obscure the main stem"),
    CropSpec("OC08", "leipzig_flower_vine", "core", (0.01, 0.02, 0.99, 0.98), 0, "high-contrast black linework with interlaced stems, flowers, and secondary curls"),
    CropSpec("OC09", "architectural_rinceau", "auxiliary", (0.03, 0.12, 0.97, 0.84), 0, "monochrome acanthus rinceau, but architectural, vessel, and fruit details weaken direct structural use"),
    CropSpec("OC10", "white_foliage_border", "auxiliary", (0.02, 0.04, 0.98, 0.96), 0, "flat two-colour foliage border; useful only after line-art reconstruction"),
    CropSpec("OC11", "blue_acanthus_top_repeat", "auxiliary", (0.00, 0.03, 1.00, 0.51), 0, "top copy of a duplicated colour repeat; bottom duplicate removed"),
    CropSpec("OC12", "rose_scroll", "auxiliary", (0.00, 0.04, 1.00, 0.94), 0, "low-contrast colour floral scroll; reconstruction reference only"),
    CropSpec("OC13", "green_acanthus_flowers", "auxiliary", (0.01, 0.05, 0.99, 0.95), 0, "flat colour plant scroll with clear main curls and flower attachments"),
    CropSpec("OC14", "pink_floral_top_repeat", "auxiliary", (0.00, 0.04, 1.00, 0.51), 0, "top copy of a duplicated colour floral scroll; bottom duplicate removed"),
    CropSpec("OC15", "blue_floral_top_repeat", "auxiliary", (0.01, 0.04, 0.99, 0.51), 0, "top copy of a duplicated blue floral scroll; bottom duplicate removed"),
    CropSpec("OC16", "pale_floral_top_repeat", "auxiliary", (0.00, 0.04, 1.00, 0.52), 0, "top copy of a duplicated low-contrast floral band; reconstruction reference only"),
    CropSpec("OC17", "large_bouquet_rinceau", "auxiliary", (0.00, 0.03, 1.00, 0.94), 0, "large flat colour rinceau with visible plant hierarchy but dense bouquet masses"),
    CropSpec("OC18", "green_flower_vine_top_repeat", "auxiliary", (0.00, 0.03, 1.00, 0.50), 0, "top copy of a duplicated green flower-vine repeat; bottom duplicate removed"),
    CropSpec("OC19", "ochre_acanthus", "auxiliary", (0.02, 0.05, 0.98, 0.95), 0, "flat colour acanthus scroll; strong silhouette but not line art"),
    CropSpec("OC20", "stylized_flower_vine_top_repeat", "auxiliary", (0.00, 0.03, 1.00, 0.50), 0, "top copy of a duplicated stylized flower-vine repeat; low contrast"),
    CropSpec("OC21", "blue_flower_acanthus", "auxiliary", (0.02, 0.02, 0.98, 0.98), 0, "flat colour flower-and-acanthus border with clear continuous support stem"),
]

REJECTED = {
    "OC03": "rejected: central vase and paired animals interrupt and dominate the plant-scroll hierarchy",
}


def fractional_box(image: Image.Image, crop: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    width, height = image.size
    left, top, right, bottom = crop
    return (
        round(left * width),
        round(top * height),
        round(right * width),
        round(bottom * height),
    )


def main() -> None:
    project = pathlib.Path(__file__).resolve().parents[1]
    raw_dir = project / "data" / "source_candidates" / "web_independent_batch4_20260715" / "original_sources" / "open_collection_public_domain"
    output_dir = project / "data" / "source_candidates" / "web_independent_batch4_20260715" / "open_collection_screened_strips_20260716"
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.name != "open_collection_screened_strips_20260716":
        raise RuntimeError(f"refusing to clean unexpected output directory: {output_dir}")
    for old_file in output_dir.iterdir():
        if old_file.is_file():
            old_file.unlink()

    with (raw_dir / "manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        raw_rows = {row["id"]: row for row in csv.DictReader(handle)}

    source_files: dict[str, pathlib.Path] = {}
    for source_id in raw_rows:
        matches = sorted(raw_dir.glob(f"{source_id}_*.*"))
        matches = [path for path in matches if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}]
        if matches:
            source_files[source_id] = matches[0]

    manifest_rows: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    for spec in CROPS:
        source_path = source_files.get(spec.source_id)
        if source_path is None:
            raise FileNotFoundError(f"missing validated image file for {spec.source_id}")
        raw_row = raw_rows[spec.source_id]
        with Image.open(source_path) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            box = fractional_box(image, spec.crop)
            strip = image.crop(box)
            if spec.rotate_degrees == 90:
                strip = strip.transpose(Image.Transpose.ROTATE_90)
            elif spec.rotate_degrees:
                strip = strip.rotate(spec.rotate_degrees, expand=True)
            if strip.width > 3600:
                new_height = max(1, round(strip.height * 3600 / strip.width))
                strip = strip.resize((3600, new_height), Image.Resampling.LANCZOS)
            prefix = "CORE" if spec.tier == "core" else "AUX"
            output_name = f"{prefix}_{spec.source_id}_{spec.suffix}.jpg"
            strip.save(output_dir / output_name, "JPEG", quality=94, subsampling=0, optimize=True)

        independent_count = "0" if spec.source_id in seen_sources else "1"
        seen_sources.add(spec.source_id)
        manifest_rows.append(
            {
                "source_id": spec.source_id,
                "source_title": raw_row["title"],
                "source_file": source_path.name,
                "output_file": output_name,
                "tier": spec.tier,
                "decision": "kept",
                "independent_source_count": independent_count,
                "crop_pixels": ",".join(map(str, box)),
                "rotation_degrees_ccw": str(spec.rotate_degrees),
                "source_page": raw_row["source_page"],
                "direct_image_url": raw_row["direct_image_url"],
                "rights": raw_row["rights"],
                "reason": spec.reason,
            }
        )

    for source_id, reason in REJECTED.items():
        raw_row = raw_rows[source_id]
        source_path = source_files.get(source_id)
        manifest_rows.append(
            {
                "source_id": source_id,
                "source_title": raw_row["title"],
                "source_file": source_path.name if source_path else "",
                "output_file": "",
                "tier": "rejected",
                "decision": "rejected",
                "independent_source_count": "0",
                "crop_pixels": "",
                "rotation_degrees_ccw": "0",
                "source_page": raw_row["source_page"],
                "direct_image_url": raw_row["direct_image_url"],
                "rights": raw_row["rights"],
                "reason": reason,
            }
        )

    manifest_rows.sort(key=lambda row: (row["source_id"], row["output_file"]))
    manifest_path = output_dir / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0].keys()), quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(manifest_rows)

    core_count = sum(row["tier"] == "core" for row in manifest_rows)
    auxiliary_count = sum(row["tier"] == "auxiliary" for row in manifest_rows)
    rejected_count = sum(row["decision"] == "rejected" for row in manifest_rows)
    independent_count = sum(int(row["independent_source_count"]) for row in manifest_rows)
    readme = (
        "# Open collection screened strips\n\n"
        f"- Downloaded and validated source objects: {len(source_files)} / {len(raw_rows)}\n"
        f"- Kept independent source objects: {independent_count}\n"
        f"- Kept strip files: {core_count + auxiliary_count} (core {core_count}, auxiliary {auxiliary_count})\n"
        f"- Rejected source objects: {rejected_count}\n"
        "- OC06 yields two different strip files from one museum object; it counts as one independent source.\n"
        "- Core files are predominantly monochrome line/drawing material. AUX files are flat colour or weaker structural references and should be reconstructed before strict training use.\n"
        "- Full source URLs, crop boxes, rotation, rights, and per-item decisions are recorded in manifest.csv.\n"
    )
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    print(output_dir)
    print(f"validated_sources={len(source_files)} kept_sources={independent_count} kept_strips={core_count + auxiliary_count} core={core_count} auxiliary={auxiliary_count} rejected={rejected_count}")


if __name__ == "__main__":
    main()
