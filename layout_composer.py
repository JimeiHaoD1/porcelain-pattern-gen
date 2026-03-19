# -*- coding: utf-8 -*-
from __future__ import annotations

import math

import cv2
import numpy as np

from pattern_generators import get_pattern_generator


LEGION_FRAME = "frame"
LEGION_SYMBOL = "symbol"
LEGION_SPIRIT = "spirit"
LEGION_FLOW = "flow"

ROLE_TO_LEGION = {
    "primary": LEGION_SPIRIT,
    "secondary": LEGION_SPIRIT,
    "base": LEGION_FLOW,
    "border": LEGION_FRAME,
    "symbol": LEGION_SYMBOL,
}

FALLBACK_BORDER = {"回纹", "蕉叶", "如意头", "璎珞", "铜钱", "梵字符号", "八宝"}
FALLBACK_SYMBOL = {"八卦符号", "阴阳鱼", "喜字字符"}
FALLBACK_FLOW = {"海水", "卷草", "忍冬", "水草", "云", "枝叶"}

LEGION_CN_WEIGHTS = {
    LEGION_FRAME: 0.85,
    LEGION_SYMBOL: 0.65,
    LEGION_SPIRIT: 0.45,
    LEGION_FLOW: 0.55,
}

LEGION_IPA_SCALES = {
    LEGION_FRAME: 0.0,
    LEGION_SYMBOL: 0.40,
    LEGION_SPIRIT: 0.65,
    LEGION_FLOW: 0.0,
}


def classify_element(name: str | None) -> str | None:
    if not name:
        return None
    if name in FALLBACK_BORDER:
        return LEGION_FRAME
    if name in FALLBACK_SYMBOL:
        return LEGION_SYMBOL
    if name in FALLBACK_FLOW:
        return LEGION_FLOW
    return LEGION_SPIRIT


def is_geometric(name: str | None) -> bool:
    return classify_element(name) in (LEGION_FRAME, LEGION_SYMBOL)


def is_organic(name: str | None) -> bool:
    return classify_element(name) in (LEGION_SPIRIT, LEGION_FLOW)


def load_gray(path):
    if not path:
        return None
    return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)


def load_color(path):
    if not path:
        return None
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return None
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def mask_bbox(mask):
    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        return None
    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max())
    y1 = int(ys.max())
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def _make_odd(k):
    k = max(3, k)
    return k if k % 2 == 1 else k + 1


def _to_lineart(gray: np.ndarray) -> np.ndarray:
    inv = 255 - gray
    _, lineart = cv2.threshold(inv, 30, 255, cv2.THRESH_BINARY)
    return lineart


def crop_min_repeat_unit(img_color: np.ndarray, target_ratio: float = 0.25) -> np.ndarray:
    h, w = img_color.shape[:2]
    crop_size = max(64, int(min(h, w) * math.sqrt(target_ratio)))
    cx, cy = w // 2, h // 2
    x0 = max(0, cx - crop_size // 2)
    y0 = max(0, cy - crop_size // 2)
    return img_color[y0:y0 + crop_size, x0:x0 + crop_size]


def crop_single_border_unit(img_color: np.ndarray) -> np.ndarray:
    h, w = img_color.shape[:2]
    if w >= h:
        return img_color[:, : max(64, w // 3)]
    return img_color[: max(64, h // 3), :]


def _derive_legion(slot) -> str:
    if isinstance(slot, dict):
        legion = slot.get("legion")
        if legion:
            return legion
        role = slot.get("role")
        if role in ROLE_TO_LEGION:
            return ROLE_TO_LEGION[role]
        return classify_element(slot.get("element")) or LEGION_SPIRIT
    return classify_element(slot) or LEGION_SPIRIT


def _resize_and_rotate(lineart: np.ndarray, width: int, height: int, angle: float) -> np.ndarray:
    resized = cv2.resize(lineart, (max(1, width), max(1, height)), interpolation=cv2.INTER_CUBIC)
    if abs(angle) < 1e-3:
        return resized
    h, w = resized.shape[:2]
    center = (w / 2.0, h / 2.0)
    rot = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos = abs(rot[0, 0])
    sin = abs(rot[0, 1])
    bound_w = int((h * sin) + (w * cos))
    bound_h = int((h * cos) + (w * sin))
    rot[0, 2] += bound_w / 2 - center[0]
    rot[1, 2] += bound_h / 2 - center[1]
    return cv2.warpAffine(resized, rot, (bound_w, bound_h), flags=cv2.INTER_CUBIC, borderValue=0)


def _paste_with_mask(canvas: np.ndarray, patch: np.ndarray, mask: np.ndarray, center: tuple[int, int]) -> np.ndarray:
    h, w = canvas.shape[:2]
    ph, pw = patch.shape[:2]
    cx, cy = center
    x0 = max(0, cx - pw // 2)
    y0 = max(0, cy - ph // 2)
    x1 = min(w, x0 + pw)
    y1 = min(h, y0 + ph)
    patch = patch[: y1 - y0, : x1 - x0]
    slot_mask = mask[y0:y1, x0:x1]
    if patch.size == 0 or slot_mask.size == 0:
        return canvas
    clipped = cv2.bitwise_and(patch, patch, mask=slot_mask)
    canvas[y0:y1, x0:x1] = np.maximum(canvas[y0:y1, x0:x1], clipped)
    return canvas


def _asset_lineart(asset_path: str | None) -> np.ndarray | None:
    gray = load_gray(asset_path)
    if gray is None:
        return None
    return _to_lineart(gray)


def _crop_lineart_content(lineart: np.ndarray, pad: int = 6) -> np.ndarray:
    ys, xs = np.where(lineart > 0)
    if xs.size == 0:
        return lineart
    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(lineart.shape[1], int(xs.max()) + pad + 1)
    y1 = min(lineart.shape[0], int(ys.max()) + pad + 1)
    return lineart[y0:y1, x0:x1]


def _fit_asset_to_mask(asset_path: str | None, mask: np.ndarray, pose: dict | None, fallback_outline: bool = False) -> np.ndarray:
    h, w = mask.shape[:2]
    canvas = np.zeros((h, w), dtype=np.uint8)
    bbox = mask_bbox(mask)
    if not bbox:
        return canvas
    bx, by, bw, bh = bbox
    cx = bx + bw // 2
    cy = by + bh // 2

    pose = pose or {}
    aspect = float(pose.get("aspect_ratio", 1.0))
    size_ratio = float(pose.get("size_ratio", 0.65))
    angle = float(pose.get("orientation", 0))
    shape = str(pose.get("shape", "ellipse"))

    target_h = max(12, int(bh * size_ratio))
    target_w = max(12, int(target_h * aspect))
    target_w = min(target_w, max(16, int(bw * 0.96)))
    target_h = min(target_h, max(16, int(bh * 0.96)))

    lineart = _asset_lineart(asset_path)
    if lineart is not None:
        lineart = _crop_lineart_content(lineart)
        patch = _resize_and_rotate(lineart, target_w, target_h, angle)
        return _paste_with_mask(canvas, patch, mask, (cx, cy))

    if fallback_outline:
        thickness = max(1, min(bw, bh) // 40)
        axes = (max(8, target_w // 2), max(8, target_h // 2))
        if shape == "circle":
            cv2.circle(canvas, (cx, cy), min(axes), 255, thickness, lineType=cv2.LINE_AA)
        else:
            cv2.ellipse(canvas, (cx, cy), axes, angle, 0, 360, 255, thickness, lineType=cv2.LINE_AA)
        canvas = cv2.bitwise_and(canvas, mask)
    return canvas


def _fit_flow_asset(asset_path: str | None, mask: np.ndarray) -> np.ndarray | None:
    lineart = _asset_lineart(asset_path)
    if lineart is None:
        return None
    lineart = _crop_lineart_content(lineart, pad=2)
    h, w = mask.shape[:2]
    canvas = np.zeros((h, w), dtype=np.uint8)
    bbox = mask_bbox(mask)
    if not bbox:
        return canvas
    bx, by, bw, bh = bbox
    resized = cv2.resize(lineart, (max(1, bw), max(1, bh)), interpolation=cv2.INTER_CUBIC)
    canvas[by:by + bh, bx:bx + bw] = resized
    return cv2.bitwise_and(canvas, (mask > 0).astype(np.uint8) * 255)


def generate_frame_control(slot, mask: np.ndarray, asset_path: str | None = None, meta: dict | None = None) -> np.ndarray:
    h, w = mask.shape[:2]
    canvas = np.zeros((h, w), dtype=np.uint8)
    mask_u8 = (mask > 0).astype(np.uint8) * 255
    bbox = mask_bbox(mask_u8)
    if not bbox:
        return canvas
    _, _, _, bh = bbox

    tile = _asset_lineart(asset_path)
    if tile is None:
        canvas[mask_u8 > 0] = 220
        return cv2.GaussianBlur(canvas, (3, 3), 0)

    rows = np.where(mask_u8.sum(axis=1) > 0)[0]
    if rows.size == 0:
        return canvas

    segments = []
    start = rows[0]
    prev = rows[0]
    for row in rows[1:]:
        if row != prev + 1:
            segments.append((start, prev))
            start = row
        prev = row
    segments.append((start, prev))

    th, tw = tile.shape[:2]
    for y0, y1 in segments:
        seg_h = y1 - y0 + 1
        cols = np.where(mask_u8[y0:y1 + 1].sum(axis=0) > 0)[0]
        if cols.size == 0:
            continue
        x0 = int(cols.min())
        seg_w = int(cols.max()) - x0 + 1
        scale = seg_h / float(max(1, th))
        resized = cv2.resize(tile, (max(1, int(tw * scale)), seg_h), interpolation=cv2.INTER_CUBIC)
        reps = max(1, (seg_w + resized.shape[1] - 1) // resized.shape[1] + 1)
        tiled = np.tile(resized, (1, reps))[:, :seg_w]
        canvas[y0:y0 + seg_h, x0:x0 + seg_w] = np.maximum(canvas[y0:y0 + seg_h, x0:x0 + seg_w], tiled)

    canvas = cv2.GaussianBlur(canvas, (_make_odd(min(7, max(3, bh // 12))),) * 2, 0)
    return cv2.bitwise_and(canvas, mask_u8)


def generate_symbol_control(slot, mask: np.ndarray, asset_path: str | None = None, meta: dict | None = None) -> np.ndarray:
    return _fit_asset_to_mask(asset_path, mask, slot.get("pose"), fallback_outline=True)


def generate_spirit_control(slot, mask: np.ndarray, asset_path: str | None = None, meta: dict | None = None) -> np.ndarray:
    pose = dict(slot.get("pose") or {})
    if slot.get("role") == "secondary" and "size_ratio" not in pose:
        pose["size_ratio"] = 0.42
    elif "size_ratio" not in pose:
        pose["size_ratio"] = 0.70
    return _fit_asset_to_mask(asset_path, mask, pose, fallback_outline=True)


def generate_flow_control(slot, mask: np.ndarray, asset_path: str | None = None, meta: dict | None = None) -> np.ndarray:
    h, w = mask.shape[:2]
    mask_u8 = (mask > 0).astype(np.uint8) * 255
    meta = meta or {}
    generator_name = slot.get("pattern_generator") or meta.get("pattern_generator")
    if asset_path and generator_name == "wave":
        asset_canvas = _fit_flow_asset(asset_path, mask_u8)
        if asset_canvas is not None and np.any(asset_canvas):
            return asset_canvas
    generator = get_pattern_generator(generator_name)
    pattern = generator.generate(w, h, meta.get("pattern_params", {}))
    dist = cv2.distanceTransform(mask_u8, cv2.DIST_L2, 5)
    feather = max(10, min(h, w) // 10)
    alpha = np.clip(dist / float(feather), 0.0, 1.0)
    return (pattern.astype(np.float32) * alpha).astype(np.uint8)


def generate_control_signal(slot_or_name, mask, asset_path=None, meta=None):
    slot = slot_or_name if isinstance(slot_or_name, dict) else {"element": slot_or_name}
    legion = _derive_legion(slot)

    if legion == LEGION_FRAME:
        img = generate_frame_control(slot, mask, asset_path, meta)
    elif legion == LEGION_SYMBOL:
        img = generate_symbol_control(slot, mask, asset_path, meta)
    elif legion == LEGION_FLOW:
        img = generate_flow_control(slot, mask, asset_path, meta)
    else:
        img = generate_spirit_control(slot, mask, asset_path, meta)

    return {
        "control_image": img,
        "controlnet_type": "lineart",
        "controlnet_weight": LEGION_CN_WEIGHTS.get(legion, 0.5),
        "ipa_scale": LEGION_IPA_SCALES.get(legion, 0.0),
        "legion": legion,
    }


class LayoutComposer:
    def __init__(self, canvas_size=(1024, 768)):
        self.canvas_size = canvas_size

    @staticmethod
    def _load_asset_gray(path):
        return load_gray(path)

    @staticmethod
    def _load_asset_color(path):
        return load_color(path)

    @staticmethod
    def _mask_bbox(mask):
        return mask_bbox(mask)

    def generate_control_signal(self, slot, mask, asset_path=None, meta=None):
        return generate_control_signal(slot, mask, asset_path, meta)
