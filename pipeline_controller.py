# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import cv2
import numpy as np

import layout_engine as LayoutEngine
from layout_composer import (
    LEGION_FLOW,
    LEGION_FRAME,
    LEGION_IPA_SCALES,
    LEGION_SPIRIT,
    LEGION_SYMBOL,
    ROLE_TO_LEGION,
    LayoutComposer,
    generate_control_signal,
    load_color,
)

try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None


ELEMENT_TRANSLATION = {
    "回纹": "meander pattern, greek key border, geometric band",
    "如意头": "Ruyi scepter pattern, cloud head border",
    "蕉叶": "plantain leaf border pattern",
    "海水": "traditional chinese sea water pattern, crashing ocean waves, repeating surf motif",
    "锦地": "brocade lattice background",
    "八卦符号": "Bagua trigrams, taoist emblem",
    "阴阳鱼": "Yin Yang symbol, tai chi symbol",
    "喜字字符": "Double Happiness chinese character",
    "梵字符号": "Buddhist wan character",
    "璎珞": "jewelry garland border",
    "铜钱": "ancient chinese copper coin motif",
    "八宝": "eight buddhist emblems",
    "缠枝": "intertwining floral vines",
    "卷草": "scrolling grass vines",
    "枝叶": "leafy branches, foliage",
    "水草": "aquatic plants, water weeds",
    "莲花": "lotus flower",
    "牡丹": "peony blossom",
    "石榴": "pomegranate fruit",
    "葡萄": "clusters of grapes",
    "桃": "longevity peaches",
    "梅": "plum blossom",
    "竹": "bamboo stalks and leaves",
    "月季": "chinese rose",
    "忍冬": "honeysuckle vine",
    "灵芝": "lingzhi mushroom",
    "桂花": "osmanthus flowers",
    "菊花": "chrysanthemum",
    "兰花": "orchid",
    "瓜": "melon fruit and trailing vine",
    "松树": "ancient pine tree",
    "葫芦": "gourd",
    "龙": "Chinese dragon, serpentine body, dynamic imperial creature",
    "团龙": "coiled chinese dragon medallion",
    "凤": "Chinese phoenix, fenghuang",
    "孔雀": "peacock with elegant feathers",
    "鹤": "red crowned crane",
    "鸳鸯": "mandarin duck pair",
    "喜鹊": "magpie bird",
    "公鸡": "rooster",
    "蝙蝠": "stylized bat",
    "蝴蝶": "butterfly",
    "松鼠": "squirrel",
    "兔": "rabbit",
    "羊": "goat",
    "鹿": "deer",
    "狮子": "guardian lion",
    "麒麟": "qilin mythical beast",
    "鱼": "carp fish",
    "螃蟹": "crab",
    "山石": "scholar rock, Taihu stone",
    "楼阁": "chinese pavilion",
    "仕女": "ancient chinese lady in hanfu",
    "高士": "ancient chinese scholar",
    "婴儿": "playing child",
    "云": "auspicious cloud pattern",
}

STYLE_PROMPTS = {
    "elegant": "balanced composition, controlled spacing, refined ornament, porcelain linework",
    "ornate": "dense but orderly decoration, imperial symmetry, richly layered ornament",
    "narrative": "asymmetric storytelling composition, scenic ink line drawing, elegant negative space",
}

LAYOUT_PROMPTS = {
    "central": "central medallion composition, stable symmetry, clear focal subject",
    "satellite": "central subject with surrounding attendants, radial balance, ordered satellites",
    "narrative": "scenic storytelling layout, left-right depth, figure and landscape harmony",
    "window": "decorative reserve composition, framed openings, controlled ornamental rhythm",
    "allover": "all-over ornament composition, even distribution, seamless coverage",
}

LAYOUT_STRUCTURE_TAGS = {
    "central": ["中心聚焦式", "边饰"],
    "satellite": ["中心聚焦式", "卫星副纹", "边饰"],
    "narrative": ["通景式", "边饰"],
    "window": ["开光式", "边饰", "满铺"],
    "allover": ["满铺", "边饰"],
}

MAX_SECONDARY_BY_LAYOUT = {
    "central": 4,
    "satellite": 4,
    "narrative": 3,
    "window": 6,
    "allover": 6,
}

ROLE_PRIORITY = {
    "primary": 0,
    "secondary": 1,
    "base": 2,
    "symbol": 3,
    "border": 4,
}

ROLE_CAPABILITY_TABLE: dict[str, set[str]] = {
    "龙": {"primary"},
    "团龙": {"primary"},
    "凤": {"primary"},
    "麒麟": {"primary"},
    "狮子": {"primary"},
    "鹤": {"primary"},
    "鹿": {"primary"},
    "仕女": {"primary"},
    "高士": {"primary"},
    "婴儿": {"primary"},
    "孔雀": {"primary"},
    "鸳鸯": {"primary"},
    "兔": {"primary"},
    "羊": {"primary"},
    "螃蟹": {"primary"},
    "公鸡": {"primary"},
    "牡丹": {"primary", "secondary"},
    "莲花": {"primary", "secondary"},
    "菊花": {"primary", "secondary"},
    "梅": {"primary", "secondary"},
    "兰花": {"secondary"},
    "竹": {"primary", "secondary"},
    "桃": {"primary", "secondary"},
    "石榴": {"primary", "secondary"},
    "葡萄": {"primary", "secondary"},
    "松树": {"primary", "secondary"},
    "月季": {"secondary"},
    "桂花": {"secondary"},
    "灵芝": {"primary", "secondary"},
    "葫芦": {"primary", "secondary"},
    "瓜": {"secondary"},
    "山石": {"primary", "secondary"},
    "楼阁": {"primary", "secondary"},
    "蝙蝠": {"secondary"},
    "蝴蝶": {"secondary"},
    "喜鹊": {"secondary"},
    "松鼠": {"secondary"},
    "鱼": {"secondary"},
    "海水": {"base"},
    "忍冬": {"base"},
    "水草": {"base"},
    "卷草": {"base", "border"},
    "云": {"secondary", "base"},
    "枝叶": {"secondary", "base"},
    "回纹": {"border"},
    "蕉叶": {"border"},
    "如意头": {"border"},
    "璎珞": {"border"},
    "铜钱": {"border"},
    "梵字符号": {"border"},
    "八宝": {"border"},
    "八卦符号": {"symbol"},
    "阴阳鱼": {"symbol"},
    "喜字字符": {"symbol"},
}

DEFAULT_PATTERN_GENERATORS = {
    "海水": "wave",
    "卷草": "scroll",
    "忍冬": "scroll",
    "水草": "scroll",
    "云": "cloud",
    "枝叶": "scroll",
}

DEFAULT_PATTERN_PARAMS = {
    "wave": {"density": 18, "line_thickness_ratio": 0.006, "curl_size": 0.33, "row_overlap": 0.82},
    "scroll": {"density": 8, "line_thickness_ratio": 0.005, "curl_size": 0.28, "row_overlap": 0.78},
    "cloud": {"density": 6, "line_thickness_ratio": 0.005},
}

DEFAULT_NEGATIVE = (
    "deformed, broken body, duplicated limbs, broken pattern, disconnected border, "
    "distorted layout, perspective warping, blurry, low quality"
)

ASSET_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_ASSET_ROOT = Path(__file__).resolve().parent / "MMKG" / "dataset_sketches"

PINYIN_OVERRIDES = {
    "松树": "songshu_tree",
    "松鼠": "songshu_mouse",
}

PINYIN_FALLBACK = {
    "回纹": "huiwen",
    "如意头": "ruyitou",
    "蕉叶": "jiaoye",
    "海水": "haishui",
    "锦地": "jinde",
    "八卦符号": "baguafuhao",
    "阴阳鱼": "yinyangyu",
    "喜字字符": "xizizifu",
    "梵字符号": "fanzifuhao",
    "璎珞": "yingluo",
    "铜钱": "tongqian",
    "八宝": "babao",
    "缠枝": "chanzhi",
    "卷草": "juancao",
    "枝叶": "zhiye",
    "水草": "shuicao",
    "莲花": "lianhua",
    "牡丹": "mudan",
    "石榴": "shiliu",
    "葡萄": "putao",
    "桃": "tao",
    "梅": "mei",
    "竹": "zhu",
    "月季": "yueji",
    "忍冬": "rendong",
    "灵芝": "lingzhi",
    "桂花": "guihua",
    "菊花": "juhua",
    "兰花": "lanhua",
    "瓜": "gua",
    "松树": "songshu_tree",
    "葫芦": "hulu",
    "龙": "long",
    "团龙": "tuanlong",
    "凤": "feng",
    "孔雀": "kongque",
    "鹤": "he",
    "鸳鸯": "yuanyang",
    "喜鹊": "xique",
    "公鸡": "gongji",
    "蝙蝠": "bianfu",
    "蝴蝶": "hudie",
    "松鼠": "songshu_mouse",
    "兔": "tu",
    "羊": "yang",
    "鹿": "lu",
    "狮子": "shizi",
    "麒麟": "qilin",
    "鱼": "yu",
    "螃蟹": "pangxie",
    "山石": "shanshi",
    "楼阁": "louge",
    "仕女": "shinv",
    "高士": "gaoshi",
    "婴儿": "yinger",
    "云": "yun",
}

ASSET_ALIASES = {
    "龙": ["tuanlong"],
    "long": ["tuanlong"],
    "缠枝": ["juancao", "zhiye"],
    "chanzhi": ["juancao", "zhiye"],
    "锦地": ["huiwen", "babao"],
    "jinde": ["huiwen", "babao"],
}


def estimate_tokens(text: str) -> int:
    words = text.replace(",", " ").split()
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return max(len(words), math.ceil(cjk / 1.6), len(text) // 5)


def _ensure_u8(mask: np.ndarray) -> np.ndarray:
    return (mask > 0).astype(np.uint8) * 255


def _ellipse_mask(size: tuple[int, int], center: tuple[int, int], axes: tuple[int, int], angle: float = 0.0) -> np.ndarray:
    w, h = size
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(mask, center, axes, angle, 0, 360, 255, thickness=-1)
    return mask


def _subtract_mask(mask: np.ndarray, subtractors: list[np.ndarray]) -> np.ndarray:
    result = mask.copy()
    for other in subtractors:
        if other is None or other.size == 0:
            continue
        result = cv2.bitwise_and(result, cv2.bitwise_not(_ensure_u8(other)))
    return result


def _ring_centers(
    count: int,
    center: tuple[int, int],
    radius_x: int,
    radius_y: int,
    start_angle_deg: float = -90.0,
) -> list[tuple[int, int]]:
    if count <= 0:
        return []
    cx, cy = center
    centers = []
    for idx in range(count):
        theta = math.radians(start_angle_deg + (360.0 * idx / count))
        x = int(cx + radius_x * math.cos(theta))
        y = int(cy + radius_y * math.sin(theta))
        centers.append((x, y))
    return centers


class PorcelainGenerationPipeline:
    def __init__(
        self,
        canvas_size: tuple[int, int] = (1024, 768),
        asset_root: str | Path | None = None,
        rng_seed: int | None = None,
    ) -> None:
        self.canvas_size = canvas_size
        self.asset_root = self._resolve_asset_root(asset_root)
        self.rng = random.Random(rng_seed)
        self.asset_index = self._build_asset_index()
        self.asset_stats_cache: dict[str, dict[str, float]] = {}
        self.composer = LayoutComposer(canvas_size=self.canvas_size)
        if not self.asset_index:
            print(f"[Warning] Asset index empty. Check asset_root: {self.asset_root}")

    def _resolve_asset_root(self, asset_root: str | Path | None) -> Path:
        if asset_root:
            return Path(asset_root)
        base = Path(__file__).resolve().parent / "MMKG"
        for name in ("dataset_sketches", "dataset-sketches"):
            candidate = base / name
            if candidate.exists():
                return candidate
        return DEFAULT_ASSET_ROOT

    def _build_asset_index(self) -> dict[str, list[Path]]:
        index: dict[str, list[Path]] = {}
        if not self.asset_root.exists():
            return index
        for folder in self.asset_root.iterdir():
            if not folder.is_dir():
                continue
            files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ASSET_EXTS]
            if files:
                index[folder.name] = files
        return index

    def _to_pinyin(self, name: str) -> str | None:
        if name in PINYIN_OVERRIDES:
            return PINYIN_OVERRIDES[name]
        if name.isascii():
            return name
        if not lazy_pinyin:
            return PINYIN_FALLBACK.get(name)
        return "".join(lazy_pinyin(name))

    def _resolve_visual_source(self, element: str | None, preferred: str | Path | None = None) -> Path | None:
        if preferred:
            raw_path = Path(preferred)
            if not raw_path.is_absolute():
                raw_path = Path(__file__).resolve().parent / raw_path
            if raw_path.exists():
                return raw_path

        if not element:
            return None

        keys = [element]
        pinyin = self._to_pinyin(element)
        if pinyin:
            keys.append(pinyin)
        keys.extend(ASSET_ALIASES.get(element, []))
        if pinyin:
            keys.extend(ASSET_ALIASES.get(pinyin, []))

        for key in keys:
            files = self.asset_index.get(key)
            if files:
                return files[0].parent
            candidate = self.asset_root / key
            if candidate.exists():
                return candidate
        return None

    def _pick_asset(self, element: str | None, preferred: str | Path | None = None) -> str | None:
        folder = self._resolve_visual_source(element, preferred)
        if not folder or not folder.exists():
            return None
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ASSET_EXTS]
        if not files:
            return None
        return str(self.rng.choice(files))

    def _candidate_asset_files(self, element: str | None, preferred: str | Path | None = None) -> list[Path]:
        folder = self._resolve_visual_source(element, preferred)
        if not folder or not folder.exists():
            return []
        return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ASSET_EXTS])

    def _measure_asset(self, path: Path) -> dict[str, float]:
        cache_key = str(path)
        if cache_key in self.asset_stats_cache:
            return self.asset_stats_cache[cache_key]

        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            stats = {"aspect": 1.0, "coverage": 0.0, "landscape": 0.0}
        else:
            mask = gray < 220
            ys, xs = np.where(mask)
            if xs.size == 0:
                stats = {"aspect": 1.0, "coverage": 0.0, "landscape": 0.0}
            else:
                bw = float(xs.max() - xs.min() + 1)
                bh = float(ys.max() - ys.min() + 1)
                coverage = float(mask.mean())
                stats = {
                    "aspect": bw / max(1.0, bh),
                    "coverage": coverage,
                    "landscape": 1.0 if bw >= bh else 0.0,
                }
        self.asset_stats_cache[cache_key] = stats
        return stats

    def _pick_asset_for_slot(self, slot: dict) -> str | None:
        if slot.get("asset_path"):
            return str(slot["asset_path"])

        files = self._candidate_asset_files(slot.get("element"), slot.get("visual_source"))
        if not files:
            return None

        role = slot.get("role")
        target_aspect = float((slot.get("pose") or {}).get("aspect_ratio", 1.0))
        element = str(slot.get("element") or "")

        if role == "base":
            ranked = sorted(
                files,
                key=lambda path: (
                    -self._measure_asset(path)["landscape"],
                    -self._measure_asset(path)["coverage"],
                    path.name,
                ),
            )
            return str(ranked[0])

        if role in {"primary", "secondary"} and element in {"龙", "团龙", "凤"}:
            ranked = sorted(
                files,
                key=lambda path: (
                    abs(self._measure_asset(path)["aspect"] - target_aspect),
                    -self._measure_asset(path)["coverage"],
                    path.name,
                ),
            )
            top = ranked[: min(4, len(ranked))]
            return str(self.rng.choice(top))

        return str(self.rng.choice(files))

    def _translate(self, token: str | None, fallback: str = "ornamental motif") -> str:
        if not token:
            return fallback
        return ELEMENT_TRANSLATION.get(token, fallback)

    def _translate_style(self, style: str | None) -> str:
        return STYLE_PROMPTS.get(style or "", "balanced ornamental composition")

    def _roles_for_element(self, element: str) -> set[str]:
        return set(ROLE_CAPABILITY_TABLE.get(element, {"secondary"}))

    def _default_role_for_element(self, element: str) -> str:
        allowed = self._roles_for_element(element)
        for role in ("primary", "base", "border", "symbol", "secondary"):
            if role in allowed:
                return role
        return "secondary"

    def _normalize_secondary(self, secondary) -> list[str]:
        if not secondary:
            return []
        if isinstance(secondary, list):
            return [str(x) for x in secondary if str(x)]
        return [str(secondary)]

    def _legacy_to_slots(self, blueprint: dict) -> list[dict]:
        elements = blueprint.get("elements", {})
        primary = elements.get("primary") or blueprint.get("primary_element")
        border = elements.get("border") or blueprint.get("border_element")
        base = elements.get("base") or blueprint.get("base_element")
        symbol = elements.get("symbol") or blueprint.get("symbol_element")
        secondary = elements.get("secondary") or blueprint.get("secondary_elements")

        slots: list[dict] = []
        if primary:
            slots.append({"element": primary, "role": "primary"})
        if base:
            slots.append({"element": base, "role": "base"})
        if border:
            slots.append({"element": border, "role": "border"})
        if symbol:
            slots.append({"element": symbol, "role": "symbol"})
        for item in self._normalize_secondary(secondary):
            slots.append({"element": item, "role": "secondary"})
        return slots

    def _normalize_canvas(self, blueprint: dict) -> tuple[int, int]:
        canvas = blueprint.get("canvas")
        if isinstance(canvas, dict):
            width = int(canvas.get("width", self.canvas_size[0]))
            height = int(canvas.get("height", self.canvas_size[1]))
            return max(256, width), max(256, height)
        size = blueprint.get("canvas_size")
        if isinstance(size, (list, tuple)) and len(size) >= 2:
            return max(256, int(size[0])), max(256, int(size[1]))
        return self.canvas_size

    def _normalize_slot(self, slot: dict, idx: int, fallbacks: list[str]) -> dict | None:
        element = slot.get("element") or slot.get("family") or slot.get("variant")
        if not element:
            fallbacks.append(f"slot[{idx}] 缺少 element，已跳过")
            return None

        role = str(slot.get("role") or self._default_role_for_element(str(element)))
        allowed_roles = self._roles_for_element(str(element))
        if role not in allowed_roles:
            fallback_role = self._default_role_for_element(str(element))
            fallbacks.append(f"{element} 不允许 role={role}，已改为 {fallback_role}")
            role = fallback_role

        legion = ROLE_TO_LEGION[role]
        slot_id = slot.get("slot_id") or f"{role}_{idx}"
        visual_source = slot.get("visual_source")
        if visual_source is None:
            resolved_folder = self._resolve_visual_source(str(element))
            visual_source = str(resolved_folder) if resolved_folder else None

        normalized = {
            "slot_id": str(slot_id),
            "element": str(element),
            "role": role,
            "legion": legion,
            "pose": slot.get("pose"),
            "pattern_generator": slot.get("pattern_generator"),
            "visual_source": visual_source,
            "meta_ref": slot.get("meta_ref"),
            "asset_path": slot.get("asset_path"),
        }
        if "meta" in slot and isinstance(slot["meta"], dict):
            normalized["meta"] = dict(slot["meta"])
        return normalized

    def _normalize_blueprint(self, blueprint: dict) -> dict:
        layout = str(blueprint.get("layout_archetype") or blueprint.get("layout") or blueprint.get("layout_type") or "central")
        if layout not in MAX_SECONDARY_BY_LAYOUT:
            layout = "central"

        width, height = self._normalize_canvas(blueprint)
        fallbacks: list[str] = list(blueprint.get("debug", {}).get("fallbacks", []))
        slots_in = blueprint.get("slots") or self._legacy_to_slots(blueprint)

        slots: list[dict] = []
        primary_seen = False
        secondary_budget = MAX_SECONDARY_BY_LAYOUT.get(layout, 4)
        secondary_count = 0
        symbol_count = 0
        for idx, raw_slot in enumerate(slots_in):
            normalized = self._normalize_slot(raw_slot, idx, fallbacks)
            if not normalized:
                continue
            if normalized["role"] == "primary":
                if primary_seen:
                    if "secondary" in self._roles_for_element(normalized["element"]) and secondary_count < secondary_budget:
                        fallbacks.append(f"{normalized['element']} 额外 primary 已降级为 secondary")
                        normalized["role"] = "secondary"
                        normalized["legion"] = ROLE_TO_LEGION["secondary"]
                        normalized["slot_id"] = f"secondary_{secondary_count}"
                        secondary_count += 1
                    else:
                        fallbacks.append(f"{normalized['element']} 额外 primary 已跳过")
                        continue
                else:
                    primary_seen = True
                    normalized["slot_id"] = "primary_0"
            elif normalized["role"] == "secondary":
                if secondary_count >= secondary_budget:
                    fallbacks.append(f"{normalized['element']} 超出 secondary 上限，已跳过")
                    continue
                normalized["slot_id"] = f"secondary_{secondary_count}"
                secondary_count += 1
            elif normalized["role"] == "base":
                normalized["slot_id"] = "base_0"
            elif normalized["role"] == "border":
                normalized["slot_id"] = "border_0"
            elif normalized["role"] == "symbol":
                normalized["slot_id"] = f"symbol_{symbol_count}"
                symbol_count += 1
            slots.append(normalized)

        if not primary_seen and slots:
            for slot in slots:
                if "primary" in self._roles_for_element(slot["element"]):
                    fallbacks.append(f"{slot['element']} 被提升为 primary 以补足主纹")
                    slot["role"] = "primary"
                    slot["legion"] = ROLE_TO_LEGION["primary"]
                    slot["slot_id"] = "primary_0"
                    primary_seen = True
                    break

        debug = dict(blueprint.get("debug", {}))
        debug.setdefault("fallbacks", []).extend(fallbacks)

        return {
            "version": str(blueprint.get("version", "5.2")),
            "query": blueprint.get("query", ""),
            "style": blueprint.get("style") or blueprint.get("style_preset") or "elegant",
            "seed": int(blueprint.get("seed", self.rng.randint(0, 2**31 - 1))),
            "canvas": {"width": width, "height": height},
            "layout_archetype": layout,
            "structure_tags": blueprint.get("structure_tags") or LAYOUT_STRUCTURE_TAGS.get(layout, []),
            "slots": slots,
            "debug": debug,
        }

    def _default_meta(self, slot: dict) -> dict:
        element = slot["element"]
        role = slot["role"]
        generator = slot.get("pattern_generator") or DEFAULT_PATTERN_GENERATORS.get(element)
        meta = {
            "prompt": self._translate(element),
            "negative_prompt": DEFAULT_NEGATIVE,
            "crop_mode": "full" if role in {"primary", "secondary", "symbol"} else "tile",
            "quality_score": 0.5,
            "pattern_params": {},
        }
        if generator:
            meta["pattern_generator"] = generator
            meta["pattern_params"] = dict(DEFAULT_PATTERN_PARAMS.get(generator, {}))
        return meta

    def _load_meta(self, slot: dict, asset_path: str | None) -> tuple[dict, str | None]:
        base_meta = self._default_meta(slot)
        if "meta" in slot and isinstance(slot["meta"], dict):
            base_meta.update({k: v for k, v in slot["meta"].items() if v is not None})

        meta_ref = slot.get("meta_ref")
        candidate_paths: list[Path] = []
        if meta_ref:
            path = Path(meta_ref)
            if not path.is_absolute():
                path = Path(__file__).resolve().parent / path
            candidate_paths.append(path)

        visual_source = slot.get("visual_source")
        if visual_source:
            folder = Path(visual_source)
            if not folder.is_absolute():
                folder = Path(__file__).resolve().parent / folder
            candidate_paths.append(folder / "meta.json")

        loaded = {}
        resolved_ref = None
        for path in candidate_paths:
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    resolved_ref = str(path)
                    break
                except Exception:
                    continue

        meta = dict(base_meta)
        meta.update({k: v for k, v in loaded.items() if v is not None})
        generator = slot.get("pattern_generator") or meta.get("pattern_generator") or DEFAULT_PATTERN_GENERATORS.get(slot["element"])
        if generator:
            meta["pattern_generator"] = generator
            pattern_params = dict(DEFAULT_PATTERN_PARAMS.get(generator, {}))
            pattern_params.update(meta.get("pattern_params") or {})
            meta["pattern_params"] = pattern_params
        if asset_path and slot["role"] in {"primary", "secondary", "symbol"}:
            meta.setdefault("crop_mode", "full")
        return meta, resolved_ref

    def infer_spirit_pose(self, element: str, role: str, layout: str, companions: list[str]) -> dict:
        aspect = 1.0
        orientation = 0.0
        size_ratio = 0.42 if role == "primary" else 0.28
        shape = "ellipse"

        if element in {"龙", "团龙"}:
            if "海水" in companions and layout != "central":
                aspect = 1.85
                orientation = -15.0
                size_ratio = 0.45 if role == "primary" else 0.30
            elif layout == "central":
                aspect = 1.0
                orientation = 0.0
                size_ratio = 0.40 if role == "primary" else 0.28
            else:
                aspect = 1.45
                orientation = -8.0
                size_ratio = 0.43 if role == "primary" else 0.30
        elif element == "凤":
            if layout in {"satellite", "narrative"}:
                aspect = 1.8
                orientation = 18.0
                size_ratio = 0.40 if role == "primary" else 0.28
            else:
                aspect = 1.05
                orientation = 0.0
                size_ratio = 0.38 if role == "primary" else 0.26
        elif element in {"鹤", "鹿", "狮子", "麒麟", "孔雀", "鸳鸯", "公鸡"}:
            aspect = 1.18
            orientation = 8.0 if layout in {"satellite", "narrative"} else 0.0
            size_ratio = 0.38 if role == "primary" else 0.26
        elif element in {"高士", "仕女", "婴儿"}:
            aspect = 0.72
            orientation = -4.0 if layout == "narrative" else 0.0
            size_ratio = 0.42 if role == "primary" else 0.25
        elif element in {"山石", "楼阁", "松树", "竹"}:
            aspect = 0.95 if element == "山石" else 0.75
            size_ratio = 0.34 if role == "primary" else 0.24
        elif role == "secondary":
            size_ratio = 0.23

        return {
            "shape": shape,
            "aspect_ratio": round(aspect, 3),
            "orientation": round(orientation, 2),
            "size_ratio": round(size_ratio, 3),
        }

    def _slot_centers_for_layout(self, layout: str, size: tuple[int, int], count: int) -> list[tuple[int, int]]:
        w, h = size
        center = (w // 2, h // 2)
        if count <= 0:
            return []
        if layout == "satellite":
            return _ring_centers(count, center, int(w * 0.28), int(h * 0.22))
        if layout == "central":
            return _ring_centers(count, center, int(w * 0.26), int(h * 0.22), start_angle_deg=-65.0)
        if layout == "window":
            return _ring_centers(count, center, int(w * 0.31), int(h * 0.26))
        if layout == "allover":
            cols = min(3, max(1, math.ceil(math.sqrt(count))))
            rows = max(1, math.ceil(count / cols))
            centers = []
            for idx in range(count):
                col = idx % cols
                row = idx // cols
                x = int((col + 1) * w / (cols + 1))
                y = int((row + 1) * h / (rows + 1))
                centers.append((x, y))
            return centers

        nar = LayoutEngine.get_narrative_masks(size)
        figure_mask = _ensure_u8(nar["figures"])
        ys, xs = np.where(figure_mask > 0)
        main_side = "right" if xs.size > 0 and xs.mean() >= (w / 2.0) else "left"
        if main_side == "right":
            base_centers = [(int(w * 0.28), int(h * 0.32)), (int(w * 0.22), int(h * 0.58)), (int(w * 0.44), int(h * 0.22))]
        else:
            base_centers = [(int(w * 0.72), int(h * 0.32)), (int(w * 0.78), int(h * 0.58)), (int(w * 0.56), int(h * 0.22))]
        return base_centers[:count]

    def _allocate_primary_mask(
        self,
        layout: str,
        size: tuple[int, int],
        primary_slot: dict | None = None,
        has_base: bool = False,
        has_border: bool = False,
        secondary_count: int = 0,
    ) -> np.ndarray:
        w, h = size
        element = str((primary_slot or {}).get("element") or "")
        pose = primary_slot.get("pose") if primary_slot else {}

        if element in {"龙", "团龙", "凤"} and has_base:
            width_ratio = 0.38 if not has_border else 0.34
            if layout == "allover":
                width_ratio = 0.43
            elif layout == "satellite":
                width_ratio = 0.42 if secondary_count == 0 else 0.38
            height_ratio = 0.30 if layout == "allover" else 0.28
            return _ellipse_mask(size, (w // 2, h // 2), (int(w * width_ratio), int(h * height_ratio)))

        if layout == "central":
            return _ellipse_mask(size, (w // 2, h // 2), (int(w * 0.18), int(h * 0.24)))
        if layout == "satellite":
            return _ellipse_mask(size, (w // 2, h // 2), (int(w * 0.17), int(h * 0.22)))
        if layout == "narrative":
            return _ensure_u8(LayoutEngine.get_narrative_masks(size)["figures"])
        if layout == "window":
            return _ellipse_mask(size, (w // 2, h // 2), (int(w * 0.16), int(h * 0.21)))
        return _ellipse_mask(size, (w // 2, h // 2), (int(w * 0.15), int(h * 0.20)))

    def _allocate_secondary_masks(self, layout: str, size: tuple[int, int], count: int, primary_mask: np.ndarray) -> list[np.ndarray]:
        if count <= 0:
            return []
        w, h = size
        masks: list[np.ndarray] = []
        centers = self._slot_centers_for_layout(layout, size, count)
        if layout == "narrative":
            nar = LayoutEngine.get_narrative_masks(size)
            source_masks = [_ensure_u8(nar["landscape"]), _ensure_u8(nar["clouds"])]
            while len(source_masks) < count:
                source_masks.append(_ensure_u8(nar["landscape"]))
            for idx in range(count):
                src = source_masks[idx]
                cx, cy = centers[idx]
                patch = _ellipse_mask(size, (cx, cy), (int(w * 0.10), int(h * 0.14)))
                masks.append(cv2.bitwise_and(src, patch))
            return [_subtract_mask(mask, [primary_mask]) for mask in masks]

        for idx, (cx, cy) in enumerate(centers):
            if layout == "satellite":
                axes = (int(w * 0.085), int(h * 0.11))
            elif layout == "window":
                axes = (int(w * 0.075), int(h * 0.10))
            elif layout == "allover":
                axes = (int(w * 0.07), int(h * 0.09))
            else:
                axes = (int(w * 0.08), int(h * 0.10))
            angle = -18.0 if idx % 2 else 18.0
            masks.append(_ellipse_mask(size, (cx, cy), axes, angle=angle))
        return [_subtract_mask(mask, [primary_mask]) for mask in masks]

    def _allocate_symbol_masks(self, size: tuple[int, int], count: int, occupied: list[np.ndarray]) -> list[np.ndarray]:
        if count <= 0:
            return []
        w, h = size
        presets = [
            (w // 2, int(h * 0.18)),
            (int(w * 0.22), int(h * 0.22)),
            (int(w * 0.78), int(h * 0.22)),
        ]
        masks = []
        for idx in range(count):
            cx, cy = presets[idx] if idx < len(presets) else _ring_centers(1, (w // 2, h // 2), int(w * 0.30), int(h * 0.24))[0]
            mask = _ellipse_mask(size, (cx, cy), (int(w * 0.055), int(h * 0.07)))
            masks.append(_subtract_mask(mask, occupied))
        return masks

    def _split_mask_horizontally(self, mask: np.ndarray, count: int) -> list[np.ndarray]:
        if count <= 0:
            return []
        mask = _ensure_u8(mask)
        h, w = mask.shape[:2]
        slices = []
        for idx in range(count):
            x0 = int(idx * w / count)
            x1 = int((idx + 1) * w / count)
            patch = np.zeros_like(mask)
            patch[:, x0:x1] = mask[:, x0:x1]
            slices.append(patch)
        return slices

    def _allocate_slot_masks(self, slots: list[dict], layout: str, canvas: tuple[int, int]) -> dict[str, np.ndarray]:
        border_slots = [slot for slot in slots if slot["role"] == "border"]
        base_slots = [slot for slot in slots if slot["role"] == "base"]
        primary_slots = [slot for slot in slots if slot["role"] == "primary"]
        secondary_slots = [slot for slot in slots if slot["role"] == "secondary"]
        symbol_slots = [slot for slot in slots if slot["role"] == "symbol"]

        masks: dict[str, np.ndarray] = {}
        w, h = canvas

        border_band = LayoutEngine.get_border_mask(canvas, h_ratio=0.07 if layout in {"satellite", "window"} else 0.08)
        for slot, mask in zip(border_slots, self._split_mask_horizontally(border_band, len(border_slots))):
            masks[slot["slot_id"]] = mask

        primary_mask = (
            self._allocate_primary_mask(
                layout,
                canvas,
                primary_slot=primary_slots[0] if primary_slots else None,
                has_base=bool(base_slots),
                has_border=bool(border_slots),
                secondary_count=len(secondary_slots),
            )
            if primary_slots
            else np.zeros((h, w), dtype=np.uint8)
        )
        if primary_slots:
            masks[primary_slots[0]["slot_id"]] = primary_mask

        secondary_masks = self._allocate_secondary_masks(layout, canvas, len(secondary_slots), primary_mask)
        for slot, mask in zip(secondary_slots, secondary_masks):
            masks[slot["slot_id"]] = mask

        occupied = [primary_mask] + secondary_masks + [masks.get(slot["slot_id"], np.zeros((h, w), dtype=np.uint8)) for slot in border_slots]
        symbol_masks = self._allocate_symbol_masks(canvas, len(symbol_slots), occupied)
        for slot, mask in zip(symbol_slots, symbol_masks):
            masks[slot["slot_id"]] = mask

        if base_slots:
            allover = LayoutEngine.get_allover_mask(canvas)
            flow_canvas = _subtract_mask(allover, [border_band])
            if len(base_slots) == 1:
                masks[base_slots[0]["slot_id"]] = flow_canvas
            else:
                for slot, mask in zip(base_slots, self._split_mask_horizontally(flow_canvas, len(base_slots))):
                    masks[slot["slot_id"]] = mask

        for slot in slots:
            masks.setdefault(slot["slot_id"], np.zeros((h, w), dtype=np.uint8))
        return masks

    def _build_prompt(self, slots: list[dict], style: str, layout: str) -> tuple[str, str]:
        parts = ["blue and white porcelain", LAYOUT_PROMPTS.get(layout, "balanced ornament layout")]
        negatives = [DEFAULT_NEGATIVE]

        sorted_slots = sorted(slots, key=lambda item: (ROLE_PRIORITY.get(item["role"], 99), item["slot_id"]))
        for slot in sorted_slots:
            if slot["legion"] == LEGION_FRAME:
                continue
            meta_prompt = (slot.get("meta") or {}).get("prompt", "").strip()
            if not meta_prompt:
                continue
            candidate = ", ".join(parts + [meta_prompt])
            if estimate_tokens(candidate) <= 70:
                parts.append(meta_prompt)
            negative = (slot.get("meta") or {}).get("negative_prompt")
            if negative:
                negatives.append(negative)

        parts.append(self._translate_style(style))
        parts.append("precise decorative linework")
        parts.append("masterpiece")

        dedup_parts = []
        for item in parts:
            if item and item not in dedup_parts:
                dedup_parts.append(item)

        negative_parts = []
        for item in negatives:
            if item and item not in negative_parts:
                negative_parts.append(item)

        return ", ".join(dedup_parts), ", ".join(negative_parts)

    def _merge_control_images(self, control_layers: list[dict], canvas: tuple[int, int]) -> np.ndarray:
        """合成 lineart_map。

        修复说明：
        1. LEGION_FLOW（底纹）完全排除出 lineart_map——底纹靠 prompt 自由生成，
           重度模糊的灰色团块混入控制图只会干扰 ControlNet 对主体线稿的识别。
        2. secondary mask 面积过小（< 3%）时跳过，避免微小噪声块干扰主体。
        3. base mask 可能超出 canvas，resize 前先 clip 到画布尺寸。
        """
        w, h = canvas
        composite = np.zeros((h, w), dtype=np.uint8)
        canvas_area = w * h

        # 只合成 spirit(primary/secondary) 和 frame(border) 层
        order = {LEGION_SYMBOL: 0, LEGION_SPIRIT: 1, LEGION_FRAME: 2}
        for layer in sorted(control_layers, key=lambda item: order.get(item["legion"], 99)):
            # 完全跳过 flow 层（底纹）
            if layer["legion"] == LEGION_FLOW:
                continue

            img = layer["control_image"]
            if img is None:
                continue

            # secondary 掩码面积过小时跳过（< 3% 画布面积）
            if layer["role"] == "secondary":
                mask = layer.get("mask")
                if mask is not None:
                    area_pct = float((mask > 0).sum()) / canvas_area
                    if area_pct < 0.03:
                        continue

            # clip 到画布尺寸再 resize
            img = img[:h, :w]
            if img.shape[:2] != (h, w):
                img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)

            composite = np.maximum(composite, img)

        return cv2.cvtColor(composite, cv2.COLOR_GRAY2RGB)

    def _choose_lineart_weight(self, control_layers: list[dict]) -> float:
        if not control_layers:
            return 0.55
        # flow 层不再进入 lineart_map，权重只取 spirit 和 frame
        spirit = max((layer["controlnet_weight"] for layer in control_layers if layer["legion"] == LEGION_SPIRIT), default=0.45)
        border = max((layer["controlnet_weight"] for layer in control_layers if layer["legion"] == LEGION_FRAME), default=0.0)
        chosen = max(spirit, min(border, 0.72))
        return round(float(chosen), 3)

    def build_ip_adapter_inputs(self, layers_info: list[dict]) -> list[dict]:
        inputs = []
        for item in layers_info:
            if item["legion"] != LEGION_SPIRIT:
                continue
            asset_path = item.get("asset_path")
            if not asset_path:
                continue
            img = load_color(asset_path)
            if img is None:
                continue
            ipa_scale = item.get("ipa_scale", LEGION_IPA_SCALES.get(LEGION_SPIRIT, 0.6))
            inputs.append(
                {
                    "image": img,
                    "mask": item["mask"],
                    "name": item["element"],
                    "legion": item["legion"],
                    "ipa_scale": ipa_scale,
                }
            )
        return inputs

    def _compose_debug_image(self, slot_masks: dict[str, np.ndarray], slots: list[dict], canvas: tuple[int, int]) -> np.ndarray:
        w, h = canvas
        debug = np.zeros((h, w, 3), dtype=np.uint8)
        color_map = {
            "primary": (255, 80, 80),
            "secondary": (80, 180, 255),
            "base": (120, 220, 120),
            "border": (240, 200, 80),
            "symbol": (220, 120, 220),
        }
        for slot in slots:
            mask = slot_masks.get(slot["slot_id"])
            if mask is None:
                continue
            debug[mask > 0] = np.asarray(color_map.get(slot["role"], (180, 180, 180)), dtype=np.uint8)
        return debug

    def process_blueprint(self, blueprint: dict) -> dict:
        resolved = self._normalize_blueprint(blueprint)
        self.rng.seed(resolved["seed"])
        canvas = (resolved["canvas"]["width"], resolved["canvas"]["height"])
        self.composer = LayoutComposer(canvas_size=canvas)
        layout = resolved["layout_archetype"]
        slots = resolved["slots"]

        companions = [slot["element"] for slot in slots]
        for slot in slots:
            slot["legion"] = ROLE_TO_LEGION[slot["role"]]
            folder = self._resolve_visual_source(slot["element"], slot.get("visual_source"))
            slot["visual_source"] = str(folder) if folder else slot.get("visual_source")
            if slot["legion"] == LEGION_SPIRIT and not slot.get("pose"):
                slot["pose"] = self.infer_spirit_pose(
                    slot["element"],
                    slot["role"],
                    layout,
                    [name for name in companions if name != slot["element"]],
                )
                resolved["debug"].setdefault("pose_inference_log", []).append(
                    {"slot_id": slot["slot_id"], "element": slot["element"], "pose": dict(slot["pose"])}
                )
            if slot["role"] == "base" and not slot.get("pattern_generator"):
                slot["pattern_generator"] = DEFAULT_PATTERN_GENERATORS.get(slot["element"])
            slot["asset_path"] = self._pick_asset_for_slot(slot)
            meta, meta_ref = self._load_meta(slot, slot.get("asset_path"))
            slot["meta"] = meta
            slot["meta_ref"] = meta_ref or slot.get("meta_ref")
            slot["pattern_generator"] = slot.get("pattern_generator") or meta.get("pattern_generator")

        slot_masks = self._allocate_slot_masks(slots, layout, canvas)

        control_layers: list[dict] = []
        for slot in slots:
            mask = slot_masks[slot["slot_id"]]
            sig = generate_control_signal(slot, mask, asset_path=slot.get("asset_path"), meta=slot.get("meta"))
            control_layers.append(
                {
                    "slot_id": slot["slot_id"],
                    "element": slot["element"],
                    "role": slot["role"],
                    "legion": sig["legion"],
                    "mask": mask,
                    "control_image": sig["control_image"],
                    "controlnet_type": sig["controlnet_type"],
                    "controlnet_weight": sig["controlnet_weight"],
                    "ipa_scale": sig["ipa_scale"],
                    "asset_path": slot.get("asset_path"),
                    "meta": slot.get("meta"),
                    "pose": slot.get("pose"),
                }
            )

        lineart_map = self._merge_control_images(control_layers, canvas)
        lineart_weight = self._choose_lineart_weight(control_layers)
        prompt, negative_prompt = self._build_prompt(slots, resolved["style"], layout)
        ip_adapter_inputs = self.build_ip_adapter_inputs(control_layers)

        role_prompts = {
            slot["slot_id"]: {"element": slot["element"], "role": slot["role"], "prompt": slot["meta"].get("prompt", "")}
            for slot in slots
        }

        return {
            "resolved_blueprint": resolved,
            "masks": {slot_id: mask for slot_id, mask in slot_masks.items()},
            "prompts": {
                "global": prompt,
                "negative": negative_prompt,
                "by_slot": role_prompts,
            },
            "assets": {
                slot["slot_id"]: {
                    "element": slot["element"],
                    "visual_source": slot.get("visual_source"),
                    "asset_path": slot.get("asset_path"),
                    "meta_ref": slot.get("meta_ref"),
                }
                for slot in slots
            },
            "control_signals": {
                "lineart_map": lineart_map,
                "lineart_weight": lineart_weight,
                "per_layer": control_layers,
            },
            "ip_adapter_data": ip_adapter_inputs,
            "debug_image": self._compose_debug_image(slot_masks, slots, canvas),
        }


if __name__ == "__main__":
    blueprint = {
        "version": "5.2",
        "query": "祝老板生意兴隆",
        "style": "ornate",
        "layout_archetype": "satellite",
        "canvas": {"width": 1024, "height": 768},
        "slots": [
            {"element": "龙", "role": "primary"},
            {"element": "海水", "role": "base", "pattern_generator": "wave"},
            {"element": "回纹", "role": "border"},
        ],
    }
    pipeline = PorcelainGenerationPipeline()
    output = pipeline.process_blueprint(blueprint)
    print(json.dumps(output["resolved_blueprint"], ensure_ascii=False, indent=2))
