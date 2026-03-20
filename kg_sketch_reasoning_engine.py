# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from layout_composer import ROLE_TO_LEGION
from pipeline_controller import (
    DEFAULT_PATTERN_GENERATORS,
    MAX_SECONDARY_BY_LAYOUT,
    ROLE_CAPABILITY_TABLE,
)

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

# 加载兼容性规则
_COMPAT_RULES_PATH = Path(__file__).parent / "compatibility_rules.json"
_COMPATIBILITY_RULES = {}
if _COMPAT_RULES_PATH.exists():
    with open(_COMPAT_RULES_PATH, 'r', encoding='utf-8') as f:
        _data = json.load(f)
        _COMPATIBILITY_RULES = _data.get("compatibility_rules", {})


INTENT_ANCHORS = {
    "Wealth_Career": {
        "prototypes": ["祝老板生意兴隆", "财源广进", "富贵吉祥", "升职加薪", "功名显达"],
        "kg_targets": ["富贵", "尊贵", "功名", "皇权", "财富", "吉祥"],
        "priors": ["龙", "海水", "回纹", "云", "牡丹", "山石", "麒麟"],
    },
    "Longevity_Health": {
        "prototypes": ["福如东海寿比南山", "松鹤延年", "身体健康", "长命百岁"],
        "kg_targets": ["长寿", "长久", "生机", "福寿绵长"],
        "priors": ["鹤", "松树", "灵芝", "云", "回纹", "竹", "梅"],
    },
    "Auspicious_Blessing": {
        "prototypes": ["大吉大利", "吉祥如意", "平安顺遂", "纳福辟邪"],
        "kg_targets": ["吉祥", "祥瑞", "福气", "护佑", "顺遂"],
        "priors": ["龙", "云", "回纹", "海水", "八宝", "凤", "麒麟"],
    },
    "Family_Fertility": {
        "prototypes": ["早生贵子", "人丁兴旺", "多子多福", "家族兴旺"],
        "kg_targets": ["多子多福", "昌盛", "子嗣绵延", "团圆"],
        "priors": ["婴儿", "石榴", "莲花", "卷草", "回纹", "鸳鸯", "葡萄"],
    },
    "Love_Harmony": {
        "prototypes": ["新婚快乐", "百年好合", "夫妻恩爱", "成双成对"],
        "kg_targets": ["和合", "爱情", "美满", "平衡"],
        "priors": ["鸳鸯", "莲花", "喜字字符", "卷草", "回纹", "牡丹", "云"],
    },
    "Character_Reclusion": {
        "prototypes": ["山里隐居", "清雅高洁", "文人逸趣", "修身养性"],
        "kg_targets": ["高洁", "隐逸", "清雅", "意境"],
        "priors": ["高士", "山石", "松树", "云", "回纹", "竹", "梅", "兰花"],
    },
    "Cosmic_Order": {
        "prototypes": ["天地秩序", "阴阳五行", "宇宙规律", "稳如泰山"],
        "kg_targets": ["秩序", "平衡", "天地运行", "稳固"],
        "priors": ["八卦符号", "阴阳鱼", "云", "回纹", "海水", "山石"],
    },
}

LAYOUT_BY_CATEGORY = {
    "Wealth_Career": ("ornate", "satellite"),
    "Longevity_Health": ("elegant", "central"),
    "Auspicious_Blessing": ("ornate", "satellite"),
    "Family_Fertility": ("ornate", "central"),
    "Love_Harmony": ("elegant", "central"),
    "Character_Reclusion": ("narrative", "narrative"),
    "Cosmic_Order": ("elegant", "window"),
}

LAYOUT_STRUCTURE_TAGS = {
    "central": ["中心聚焦式", "边饰"],
    "satellite": ["中心聚焦式", "卫星副纹", "边饰"],
    "narrative": ["通景式", "边饰"],
    "window": ["开光式", "边饰", "满铺"],
    "allover": ["满铺", "边饰"],
}

DEFAULT_VISUAL_ROOT = "MMKG/dataset_sketches"


def _hash_embed(text: str, dim: int = 256) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    if not text:
        return vec
    lowered = text.lower()
    for idx, ch in enumerate(lowered):
        vec[(hash((ch, idx % 7)) % dim)] += 1.0
    norm = float(np.linalg.norm(vec))
    return vec if norm == 0 else vec / norm


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


class HybridGraphEngine:
    def __init__(self, kg_path: str | Path) -> None:
        self.kg_path = Path(kg_path)
        if not self.kg_path.exists():
            raise FileNotFoundError(f"KG file not found: {self.kg_path}")

        self.kg_df = self._apply_v52_overrides(pd.read_csv(self.kg_path))
        self.encoder = None
        if SentenceTransformer:
            try:
                self.encoder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            except Exception as exc:
                print(f"[warn] sentence-transformers unavailable, fallback to hash embedding: {exc}")

        self.roles_by_element: dict[str, set[str]] = {}
        self.pattern_generator_by_element: dict[str, str] = {}
        self.visual_source_by_element: dict[str, str] = {}
        self.layouts_by_element: dict[str, set[str]] = {}
        self.co_occurs: dict[str, set[str]] = {}
        self.meanings_by_element: dict[str, set[str]] = {}
        self.elements: list[str] = []
        self.element_vectors: dict[str, np.ndarray] = {}

        self._build_graph_views()
        self._build_embeddings()

    def _apply_v52_overrides(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in ("head", "tail"):
            if col in out.columns:
                out[col] = out[col].replace({"团龙": "龙"})

        rows = []
        for element, roles in ROLE_CAPABILITY_TABLE.items():
            head = "龙" if element == "团龙" else element
            for role in sorted(roles):
                rows.append({"head": head, "relation": "Has_Role", "tail": role, "head_type": "Element", "tail_type": "Role"})
        for element, generator in DEFAULT_PATTERN_GENERATORS.items():
            rows.append(
                {
                    "head": element,
                    "relation": "Has_Pattern_Generator",
                    "tail": generator,
                    "head_type": "Element",
                    "tail_type": "PatternType",
                }
            )
        rows.extend(
            [
                {"head": "龙", "relation": "Co_Occurs_With", "tail": "海水", "head_type": "Element", "tail_type": "Element"},
                {"head": "龙", "relation": "Co_Occurs_With", "tail": "山石", "head_type": "Element", "tail_type": "Element"},
            ]
        )

        extra = pd.DataFrame(rows)
        merged = pd.concat([out, extra], ignore_index=True)
        merged = merged.dropna(subset=["head", "tail", "relation"])
        merged["head"] = merged["head"].astype(str).str.strip()
        merged["tail"] = merged["tail"].astype(str).str.strip()
        merged["relation"] = merged["relation"].astype(str).str.strip()
        merged = merged.drop_duplicates(subset=["head", "relation", "tail"])
        return merged

    def _embed_texts(self, texts: list[str]) -> np.ndarray:
        if self.encoder:
            return np.asarray(self.encoder.encode(texts, show_progress_bar=False), dtype=np.float32)
        return np.asarray([_hash_embed(text) for text in texts], dtype=np.float32)

    def _build_graph_views(self) -> None:
        df = self.kg_df
        element_heads = set(
            str(value).strip()
            for value in df.loc[df.get("head_type").astype(str) == "Element", "head"].dropna().tolist()
        ) if "head_type" in df.columns else set()
        for _, row in df.iterrows():
            head = str(row["head"])
            tail = str(row["tail"])
            relation = str(row["relation"])
            head_type = str(row.get("head_type", ""))
            tail_type = str(row.get("tail_type", ""))

            if relation == "Has_Role" and head_type == "Element":
                self.roles_by_element.setdefault(head, set()).add(tail)
            elif relation == "Has_Pattern_Generator" and head_type == "Element":
                self.pattern_generator_by_element[head] = tail
            elif relation == "Has_Visual_Source" and head_type == "Element":
                self.visual_source_by_element[head] = tail
            elif relation == "Fits_Layout" and head_type == "Element":
                self.layouts_by_element.setdefault(head, set()).add(tail)
            elif relation == "Co_Occurs_With" and head_type == "Element" and tail_type == "Element":
                self.co_occurs.setdefault(head, set()).add(tail)
                self.co_occurs.setdefault(tail, set()).add(head)
            elif relation == "Symbolizes" and head_type == "Element":
                self.meanings_by_element.setdefault(head, set()).add(tail)

        elements = set(element_heads)
        elements.update(self.roles_by_element)
        elements.update(self.pattern_generator_by_element)
        elements.update(self.visual_source_by_element)
        elements.update(self.meanings_by_element)
        self.elements = sorted(elements)

        for element in self.elements:
            self.roles_by_element.setdefault(element, set(ROLE_CAPABILITY_TABLE.get(element, {"secondary"})))

    def _build_embeddings(self) -> None:
        texts = []
        for element in self.elements:
            meanings = ", ".join(sorted(self.meanings_by_element.get(element, set())))
            text = f"{element}, {meanings}" if meanings else element
            texts.append(text)
        vectors = self._embed_texts(texts) if texts else np.zeros((0, 256), dtype=np.float32)
        for element, vec in zip(self.elements, vectors):
            self.element_vectors[element] = vec

    def all_elements(self) -> list[str]:
        return list(self.elements)

    def get_roles(self, element: str) -> set[str]:
        return set(self.roles_by_element.get(element, set()))

    def all_role_pairs(self) -> list[tuple[str, str]]:
        pairs = []
        for element, roles in self.roles_by_element.items():
            for role in roles:
                pairs.append((element, role))
        return pairs

    def has_pattern_generator(self, element: str) -> bool:
        return element in self.pattern_generator_by_element

    def get_pattern_generator(self, element: str) -> str | None:
        return self.pattern_generator_by_element.get(element)

    def all_pattern_generators(self) -> list[tuple[str, str]]:
        return sorted(self.pattern_generator_by_element.items())

    def all_visual_sources(self) -> list[tuple[str, str]]:
        return sorted(self.visual_source_by_element.items())

    def _category_vectors(self) -> tuple[list[str], np.ndarray]:
        labels: list[str] = []
        vectors: list[np.ndarray] = []
        for category, data in INTENT_ANCHORS.items():
            for proto in data["prototypes"]:
                labels.append(category)
                vectors.append(self._embed_texts([proto])[0])
        return labels, np.asarray(vectors, dtype=np.float32)

    def infer_intent_prototype(self, user_query: str) -> tuple[str, list[str]]:
        # ── 第一层：精确关键词匹配（最高优先级）────────────────
        # 对每个类别的 prototypes 做子串匹配，命中则直接返回，不走向量路径。
        # 这样可以避免 sentence-transformer 在中文短语上的语义漂移问题。
        query_stripped = user_query.strip()
        for category, data in INTENT_ANCHORS.items():
            for proto in data["prototypes"]:
                # 精确全匹配
                if query_stripped == proto:
                    return category, list(data["kg_targets"])
        for category, data in INTENT_ANCHORS.items():
            for proto in data["prototypes"]:
                # 子串匹配：prototype 包含在 query 里，或 query 包含在 prototype 里
                if proto in query_stripped or query_stripped in proto:
                    return category, list(data["kg_targets"])
        # 关键词匹配：检查 query 是否包含 prototype 中的关键词（2字以上）
        for category, data in INTENT_ANCHORS.items():
            for proto in data["prototypes"]:
                words = [proto[i:i+2] for i in range(len(proto)-1)]
                if any(w in query_stripped for w in words if len(w) >= 2):
                    return category, list(data["kg_targets"])

        # ── 第二层：向量语义相似度（降级路径）───────────────────
        labels, vectors = self._category_vectors()
        if len(labels) == 0:
            return "Auspicious_Blessing", INTENT_ANCHORS["Auspicious_Blessing"]["kg_targets"]
        query_vec = self._embed_texts([user_query])[0]
        # 对每个类别取最高 prototype 分数，而不是全局 argmax
        # 这样避免某个类别 prototypes 数量多而占优势
        category_scores: dict[str, float] = {}
        for label, vec in zip(labels, vectors):
            score = _cosine(query_vec, vec)
            if label not in category_scores or score > category_scores[label]:
                category_scores[label] = score
        category = max(category_scores, key=lambda k: category_scores[k])
        return category, list(INTENT_ANCHORS[category]["kg_targets"])

    def infer_candidate_elements(self, user_query: str, topk: int = 8) -> dict:
        category, target_meanings = self.infer_intent_prototype(user_query)
        query_vec = self._embed_texts([user_query])[0]
        target_vectors = {meaning: self._embed_texts([meaning])[0] for meaning in target_meanings}

        scored: list[dict] = []
        priors = INTENT_ANCHORS[category]["priors"]
        
        # 优化后的权重配置
        element_vec_weight = 0.35
        meaning_bonus_cosine_weight = 0.80
        meaning_bonus_base = 0.20
        prior_bonus_base = 0.25
        prior_bonus_rank_multiplier = 0.015
        cooccurs_bonus = 0.15
        
        for rank, element in enumerate(self.elements):
            element_vec = self.element_vectors.get(element, np.zeros_like(query_vec))
            
            # 向量相似度得分（降低权重）
            element_score = _cosine(query_vec, element_vec) * element_vec_weight
            
            # 语义得分（提高权重）
            meaning_score = 0.0
            for meaning in self.meanings_by_element.get(element, set()):
                if meaning in target_vectors:
                    meaning_score = max(meaning_score, _cosine(query_vec, target_vectors[meaning]) * meaning_bonus_cosine_weight + meaning_bonus_base)
            
            # 先验得分（提高权重）
            prior_score = 0.0
            if element in priors:
                prior_score = prior_bonus_base + max(0.0, (len(priors) - priors.index(element)) * prior_bonus_rank_multiplier)
            
            # 共现关系得分（新增）
            cooccurs_score = 0.0
            # 这里暂时不用，因为还没有 primary_element
            
            score = element_score + meaning_score + prior_score + cooccurs_score
            scored.append({"element": element, "score": round(float(score), 4), "rank": rank})

        scored.sort(key=lambda item: item["score"], reverse=True)
        return {
            "intent_category": category,
            "target_meanings": target_meanings,
            "candidate_elements": [{"element": item["element"], "score": item["score"]} for item in scored[:topk]],
        }

    def _assign_layout(self, category: str) -> tuple[str, str]:
        return LAYOUT_BY_CATEGORY.get(category, ("elegant", "central"))

    def _supplement_pool(self, chosen: list[str], role: str, category: str, primary: str | None) -> list[str]:
        pool: list[str] = []
        priors = INTENT_ANCHORS[category]["priors"]
        for element in priors:
            if element in chosen:
                continue
            if role in self.get_roles(element):
                pool.append(element)
        if primary:
            for partner in sorted(self.co_occurs.get(primary, set())):
                if partner in chosen:
                    continue
                if role in self.get_roles(partner) and partner not in pool:
                    pool.append(partner)
        return pool

    def assign_slots(self, candidates: list[dict], layout_archetype: str, category: str, include_border: bool = True, include_base: bool = True) -> tuple[list[dict], list[dict]]:
        """分配槽位，加入关联度调整逻辑和灵活布局支持。
        
        改进：
        1. 不仅看相似度排序，还考虑已选元素与候选元素的兼容性
        2. 支持灵活布局：可选是否包含 border 和 base 槽位
        """
        ranked = [item["element"] for item in candidates]
        chosen: list[str] = []
        slots: list[dict] = []
        fill_log: list[dict] = []

        def _apply_compatibility_boost(pool: list[str], chosen_elements: list[str]) -> list[str]:
            """根据兼容性规则调整候选池的排序。"""
            if not pool or not chosen_elements:
                return pool
            
            # 计算每个候选元素的兼容性得分
            scores = {}
            for candidate in pool:
                score = 0.0
                compat_rules = _COMPATIBILITY_RULES.get(candidate, {})
                compatible = compat_rules.get("compatible_with", [])
                incompatible = compat_rules.get("incompatible_with", [])
                
                for chosen in chosen_elements:
                    if chosen in compatible:
                        score += 0.3  # 兼容性加分
                    elif chosen in incompatible:
                        score -= 0.5  # 冲突性减分
                
                scores[candidate] = score
            
            # 按兼容性得分排序（高分优先）
            return sorted(pool, key=lambda x: scores.get(x, 0.0), reverse=True)

        def pick_first(role: str, allow_multiple: bool = False) -> list[str]:
            picks: list[str] = []
            for element in ranked:
                if element in chosen and not allow_multiple:
                    continue
                if role in self.get_roles(element):
                    picks.append(element)
                    if not allow_multiple:
                        break
            if not picks:
                supplements = self._supplement_pool(chosen, role, category, slots[0]["element"] if slots else None)
                picks.extend(supplements)
            return picks

        # Primary：主体元素，不调整（直接取排名第一）
        primary_pool = pick_first("primary")
        if primary_pool:
            element = primary_pool[0]
            chosen.append(element)
            slots.append({"element": element, "role": "primary"})
            fill_log.append({"role": "primary", "element": element, "source": "candidate"})

        # Base：底纹，应用兼容性调整，支持灵活布局
        if include_base:
            base_pool = [elem for elem in pick_first("base") if elem not in chosen]
            base_pool = _apply_compatibility_boost(base_pool, chosen)
            if base_pool:
                element = base_pool[0]
                chosen.append(element)
                slots.append({"element": element, "role": "base"})
                fill_log.append({"role": "base", "element": element, "source": "candidate_or_fallback"})

        # Border：边饰，应用兼容性调整，支持灵活布局
        if include_border:
            border_pool = [elem for elem in pick_first("border") if elem not in chosen]
            border_pool = _apply_compatibility_boost(border_pool, chosen)
            if border_pool:
                element = border_pool[0]
                chosen.append(element)
                slots.append({"element": element, "role": "border"})
                fill_log.append({"role": "border", "element": element, "source": "candidate_or_fallback"})

        symbol_pool = [elem for elem in pick_first("symbol") if elem not in chosen]
        # symbol 元素完全禁用：SDXL 无法同时处理太多元素，symbol 贡献有限
        # if symbol_pool and category in {"Love_Harmony", "Cosmic_Order"}: ...

        # Secondary：配角，应用兼容性调整，最多 1 个
        secondary_budget = 1
        secondary_pool = []
        for element in ranked:
            if element in chosen:
                continue
            if "secondary" in self.get_roles(element):
                secondary_pool.append(element)
        if len(secondary_pool) < secondary_budget:
            for element in self._supplement_pool(chosen, "secondary", category, slots[0]["element"] if slots else None):
                if element not in chosen and element not in secondary_pool:
                    secondary_pool.append(element)
        
        # 应用兼容性调整
        secondary_pool = _apply_compatibility_boost(secondary_pool, chosen)

        for idx, element in enumerate(secondary_pool[:secondary_budget]):
            chosen.append(element)
            slots.append({"element": element, "role": "secondary"})
            fill_log.append({"role": "secondary", "element": element, "source": "candidate_or_fallback", "index": idx})

        return slots, fill_log

    def infer_spirit_pose(self, element: str, role: str, layout: str, companions: list[str]) -> dict:
        aspect = 1.0
        orientation = 0.0
        size_ratio = 0.42 if role == "primary" else 0.28
        if element == "龙":
            if "海水" in companions and layout != "central":
                aspect = 1.85
                orientation = -15.0
                size_ratio = 0.45 if role == "primary" else 0.30
            elif layout == "central":
                aspect = 1.0
                size_ratio = 0.40 if role == "primary" else 0.28
            else:
                aspect = 1.45
                orientation = -8.0
                size_ratio = 0.43 if role == "primary" else 0.30
        elif element == "凤":
            aspect = 1.8 if layout in {"satellite", "narrative"} else 1.05
            orientation = 18.0 if layout in {"satellite", "narrative"} else 0.0
            size_ratio = 0.40 if role == "primary" else 0.28
        elif role == "secondary":
            size_ratio = 0.23
        return {
            "shape": "ellipse",
            "aspect_ratio": round(aspect, 3),
            "orientation": round(orientation, 2),
            "size_ratio": round(size_ratio, 3),
        }

    def build_blueprint_v52(self, user_query: str, seed: int = 1234, canvas: tuple[int, int] = (1024, 768), include_border: bool = True, include_base: bool = True) -> dict:
        stage0 = self.infer_candidate_elements(user_query)
        style, layout = self._assign_layout(stage0["intent_category"])
        slots_raw, role_fill_log = self.assign_slots(stage0["candidate_elements"], layout, stage0["intent_category"], include_border=include_border, include_base=include_base)

        slots = []
        pose_log = []
        companions = [slot["element"] for slot in slots_raw]
        role_counters = {"primary": 0, "base": 0, "border": 0, "symbol": 0, "secondary": 0}
        for idx, slot in enumerate(slots_raw):
            role = slot["role"]
            element = slot["element"]
            legion = ROLE_TO_LEGION[role]
            slot_id = f"{role}_{role_counters[role]}"
            role_counters[role] += 1
            visual_source = self.visual_source_by_element.get(element)
            meta_ref = f"{visual_source}/meta.json" if visual_source else None
            pattern_generator = self.get_pattern_generator(element) if role == "base" else None
            pose = None
            if legion == "spirit":
                pose = self.infer_spirit_pose(element, role, layout, [name for name in companions if name != element])
                pose_log.append({"slot_id": slot_id, "element": element, "pose": pose})

            slots.append(
                {
                    "slot_id": slot_id,
                    "element": element,
                    "role": role,
                    "legion": legion,
                    "pose": pose,
                    "visual_source": visual_source,
                    "pattern_generator": pattern_generator,
                    "meta_ref": meta_ref,
                }
            )

        return {
            "version": "5.2",
            "query": user_query,
            "style": style,
            "seed": int(seed),
            "canvas": {"width": int(canvas[0]), "height": int(canvas[1])},
            "layout_archetype": layout,
            "structure_tags": LAYOUT_STRUCTURE_TAGS.get(layout, []),
            "slots": slots,
            "include_border": True,  # 灵活布局：用户可选是否包含边饰
            "include_base": True,    # 灵活布局：用户可选是否包含底纹
            "debug": {
                "intent_category": stage0["intent_category"],
                "target_meanings": stage0["target_meanings"],
                "candidate_elements": stage0["candidate_elements"],
                "role_fill_log": role_fill_log,
                "pose_inference_log": pose_log,
                "fallbacks": [],
            },
        }

    def generate_blueprint(self, user_query: str, seed: int = 1234, canvas: tuple[int, int] = (1024, 768)) -> dict:
        return self.build_blueprint_v52(user_query, seed=seed, canvas=canvas)


def _default_kg_path() -> Path:
    base = Path(__file__).resolve().parent
    candidates = [
        base / "MMKG" / "data_csv" / "mmkg_final_v2.csv",
        base / "mmkg_final_v2.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


if __name__ == "__main__":
    engine = HybridGraphEngine(_default_kg_path())
    for query in ["祝老板生意兴隆", "想去山里隐居", "早生贵子"]:
        blueprint = engine.generate_blueprint(query)
        print(json.dumps(blueprint, ensure_ascii=False, indent=2))
