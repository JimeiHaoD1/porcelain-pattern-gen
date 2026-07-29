#!/usr/bin/env python3
"""Rank likely duplicate line-art candidates against one or more reference folders."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def image_paths(roots: list[Path]) -> list[Path]:
    return sorted(
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in EXTENSIONS
    )


def phash(gray: np.ndarray) -> int:
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    block = cv2.dct(small)[:8, :8]
    median = np.median(block.ravel()[1:])
    bits = block > median
    return sum(int(bit) << index for index, bit in enumerate(bits.ravel()))


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def normalize(path: Path, max_width: int = 1200) -> np.ndarray:
    with Image.open(path) as image:
        gray = np.asarray(image.convert("L"))
    if gray.shape[1] > max_width:
        scale = max_width / gray.shape[1]
        gray = cv2.resize(gray, (max_width, max(1, round(gray.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    # Improve feature stability across blue, grey, inverted, and thresholded copies.
    if float(gray.mean()) < 127:
        gray = 255 - gray
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def ink_strip(gray: np.ndarray, target_height: int = 128) -> np.ndarray:
    """Return a tightly cropped, scale-normalized soft ink mask."""
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, ink = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # Border rules and scan-page separators distort scale normalization. Remove
    # only long, nearly straight horizontal runs; curved trunks remain.
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, ink.shape[1] // 8), 1))
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, horizontal_kernel)
    horizontal = cv2.dilate(horizontal, np.ones((3, 3), np.uint8), iterations=1)
    ink = cv2.bitwise_and(ink, cv2.bitwise_not(horizontal))
    # Ignore isolated paper texture while retaining thin drawn lines.
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8), 8)
    cleaned = np.zeros_like(ink)
    for label in range(1, component_count):
        if stats[label, cv2.CC_STAT_AREA] >= 5:
            cleaned[labels == label] = 255
    row_ink = (cleaned > 0).sum(axis=1)
    active = (row_ink >= max(3, cleaned.shape[1] * 0.002)).astype(np.uint8)[:, None]
    active = cv2.morphologyEx(active, cv2.MORPH_CLOSE, np.ones((9, 1), np.uint8))
    run_count, run_labels, _, _ = cv2.connectedComponentsWithStats(active, 8)
    if run_count > 1:
        scored_runs: list[tuple[int, int]] = []
        flat_labels = run_labels[:, 0]
        for run in range(1, run_count):
            scored_runs.append((int(row_ink[flat_labels == run].sum()), run))
        _, best_run = max(scored_runs)
        rows = np.flatnonzero(flat_labels == best_run)
        cleaned = cleaned[rows[0] : rows[-1] + 1]
    points = cv2.findNonZero(cleaned)
    if points is None:
        return np.zeros((target_height, target_height), dtype=np.float32)
    x, y, width, height = cv2.boundingRect(points)
    cropped = cleaned[y : y + height, x : x + width]
    scale = target_height / max(height, 1)
    resized = cv2.resize(
        cropped,
        (max(8, round(width * scale)), target_height),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
    )
    soft = cv2.GaussianBlur(resized.astype(np.float32) / 255.0, (5, 5), 1.0)
    return soft


def strip_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """Match the shorter normalized strip inside the longer one."""
    left_strip = ink_strip(left)
    right_strip = ink_strip(right)
    template, search = (left_strip, right_strip) if left_strip.shape[1] <= right_strip.shape[1] else (right_strip, left_strip)
    if template.shape[1] > search.shape[1] or template.shape[1] < 8:
        return 0.0
    result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    return float(np.nanmax(result)) if result.size else 0.0


@dataclass
class Features:
    path: Path
    gray: np.ndarray
    hash_value: int
    keypoints: list[cv2.KeyPoint]
    descriptors: np.ndarray | None


def extract(path: Path, sift: cv2.SIFT) -> Features:
    gray = normalize(path)
    keypoints, descriptors = sift.detectAndCompute(gray, None)
    return Features(path, gray, phash(gray), keypoints, descriptors)


def pair_score(candidate: Features, reference: Features, matcher: cv2.BFMatcher) -> tuple[int, int, float, float, float]:
    structure_score = strip_similarity(candidate.gray, reference.gray)
    if candidate.descriptors is None or reference.descriptors is None:
        return hamming(candidate.hash_value, reference.hash_value), 0, 0.0, 0.0, structure_score
    pairs = matcher.knnMatch(candidate.descriptors, reference.descriptors, k=2)
    good = [left for left, right in pairs if left.distance < 0.74 * right.distance]
    if len(good) < 4:
        return hamming(candidate.hash_value, reference.hash_value), len(good), 0.0, 0.0, structure_score

    source_points = np.float32([candidate.keypoints[match.queryIdx].pt for match in good]).reshape(-1, 1, 2)
    target_points = np.float32([reference.keypoints[match.trainIdx].pt for match in good]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(source_points, target_points, cv2.RANSAC, 5.0)
    inliers = int(mask.sum()) if mask is not None else 0
    inlier_ratio = inliers / max(len(good), 1)
    feature_coverage = inliers / max(min(len(candidate.keypoints), len(reference.keypoints)), 1)
    return hamming(candidate.hash_value, reference.hash_value), inliers, inlier_ratio, feature_coverage, structure_score


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", nargs="+", type=Path)
    parser.add_argument("--references", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    sift = cv2.SIFT_create(nfeatures=2500, contrastThreshold=0.02)
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    references: list[Features] = []
    for path in image_paths(args.references):
        try:
            references.append(extract(path, sift))
        except (OSError, cv2.error):
            continue

    rows: list[dict[str, object]] = []
    for candidate_path in image_paths(args.candidates):
        try:
            candidate = extract(candidate_path, sift)
        except (OSError, cv2.error):
            continue
        ranked = []
        for reference in references:
            hash_distance, inliers, inlier_ratio, feature_coverage, structure_score = pair_score(candidate, reference, matcher)
            # Strongly reward geometric agreement; pHash helps for low-detail exact crops.
            score = (
                120.0 * structure_score
                + min(inliers, 80) * structure_score
                + 15.0 * inlier_ratio * structure_score
                + max(0, 12 - hash_distance)
            )
            ranked.append((score, hash_distance, inliers, inlier_ratio, feature_coverage, structure_score, reference.path))
        ranked.sort(reverse=True, key=lambda item: item[0])
        for rank, (score, hash_distance, inliers, inlier_ratio, feature_coverage, structure_score, reference_path) in enumerate(
            ranked[: args.top_k], start=1
        ):
            likely = (
                hash_distance <= 8
                or structure_score >= 0.72
                or (structure_score >= 0.58 and inliers >= 12 and inlier_ratio >= 0.35)
            )
            rows.append(
                {
                    "candidate": str(candidate_path),
                    "rank": rank,
                    "reference": str(reference_path),
                    "score": round(score, 4),
                    "phash_distance": hash_distance,
                    "sift_inliers": inliers,
                    "inlier_ratio": round(inlier_ratio, 4),
                    "feature_coverage": round(feature_coverage, 4),
                    "structure_score": round(structure_score, 4),
                    "likely_duplicate": "yes" if likely else "no",
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    print(f"candidates={len(set(row['candidate'] for row in rows))}; references={len(references)}; output={args.output}")


if __name__ == "__main__":
    main()
