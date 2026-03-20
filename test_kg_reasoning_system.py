# -*- coding: utf-8 -*-
"""
KG推理系统论文级测试框架 - 第一部分
包括：测试数据集和基础测试类
"""
import sys
sys.path.insert(0, 'd:/SD')

import json
import time
from pathlib import Path
import numpy as np

from kg_sketch_reasoning_engine import HybridGraphEngine
from layout_composer import LayoutComposer

# ============================================================================
# 测试数据集
# ============================================================================

TEST_DATASET = {
    "element_recommendation": [
        {"query": "祝老板生意兴隆", "intent": "Wealth_Career", "correct_elements": ["龙", "麒麟", "凤"]},
        {"query": "松鹤延年", "intent": "Longevity_Health", "correct_elements": ["鹤", "松树", "灵芝"]},
        {"query": "新婚快乐", "intent": "Love_Harmony", "correct_elements": ["鸳鸯", "牡丹", "莲花"]},
        {"query": "早生贵子", "intent": "Family_Fertility", "correct_elements": ["石榴", "莲花", "葡萄"]},
        {"query": "大吉大利", "intent": "Auspicious_Blessing", "correct_elements": ["龙", "云", "如意"]},
    ],
    "compatibility_reasoning": [
        {"primary": "龙", "compatible": ["海水", "云纹"], "incompatible": ["花朵", "蝴蝶"]},
        {"primary": "鹤", "compatible": ["松树", "灵芝"], "incompatible": ["海水", "龙"]},
        {"primary": "牡丹", "compatible": ["缠枝纹", "卷草"], "incompatible": ["回纹", "龙"]},
    ],
    "layout_flexibility": ["祝老板生意兴隆", "松鹤延年", "新婚快乐"],
    "pattern_recommendation": [
        {"primary": "龙", "secondary": ["海水"], "expected_type": "geometric"},
        {"primary": "牡丹", "secondary": ["蝴蝶"], "expected_type": "organic"},
        {"primary": "鹤", "secondary": ["松树"], "expected_type": "landscape"},
    ],
    "boundary_cases": {
        "normal": ["祝老板生意兴隆", "松鹤延年"],
        "ambiguous": ["好看的陶瓷", "传统风格"],
        "contradictory": ["龙和花朵一起", "长寿和财富"],
        "out_of_domain": ["现代陶瓷", "西方风格"],
    }
}


class TestElementRecommendation:
    """元素推荐准确性测试"""
    
    def __init__(self, engine):
        self.engine = engine
        self.results = {"precision_at_1": [], "recall_at_5": [], "mrr": []}
    
    def test_precision_at_1(self):
        """测试 Precision@1"""
        dataset = TEST_DATASET["element_recommendation"]
        
        for case in dataset:
            query = case["query"]
            correct_elements = set(case["correct_elements"])
            
            try:
                blueprint = self.engine.build_blueprint_v52(query, seed=42)
                primary = blueprint["slots"][0]["element"]
                is_correct = primary in correct_elements
                self.results["precision_at_1"].append({"query": query, "score": 1.0 if is_correct else 0.0})
            except Exception as e:
                self.results["precision_at_1"].append({"query": query, "score": 0.0})
        
        return np.mean([r["score"] for r in self.results["precision_at_1"]])
    
    def run_all(self):
        """运行所有测试"""
        print("\n" + "="*60)
        print("测试维度 1：元素推荐准确性")
        print("="*60)
        
        p1 = self.test_precision_at_1()
        print(f"\nPrecision@1: {p1:.2%}")
        
        return {"precision_at_1": p1}


class TestCompatibilityReasoning:
    """兼容性推理测试"""
    
    def __init__(self, engine):
        self.engine = engine
        self.results = {"compatibility_score": []}
    
    def test_compatibility_score(self):
        """测试兼容性得分"""
        dataset = TEST_DATASET["compatibility_reasoning"]
        
        for case in dataset:
            primary = case["primary"]
            compatible = set(case["compatible"])
            incompatible = set(case["incompatible"])
            
            try:
                query = f"{primary}和配角"
                blueprint = self.engine.build_blueprint_v52(query, seed=42)
                secondary_elements = [s["element"] for s in blueprint["slots"] if s["role"] == "secondary"]
                
                score = 0
                for sec in secondary_elements:
                    if sec in compatible:
                        score += 1
                    elif sec in incompatible:
                        score -= 1
                
                normalized = max(0, min(1, (score + 1) / 2))
                self.results["compatibility_score"].append({"primary": primary, "score": normalized})
            except Exception as e:
                self.results["compatibility_score"].append({"primary": primary, "score": 0.0})
        
        return np.mean([r["score"] for r in self.results["compatibility_score"]])
    
    def run_all(self):
        """运行所有测试"""
        print("\n" + "="*60)
        print("测试维度 2：兼容性推理")
        print("="*60)
        
        compat_score = self.test_compatibility_score()
        print(f"\n兼容性得分: {compat_score:.2%}")
        
        return {"compatibility_score": compat_score}


class TestLayoutFlexibility:
    """布局灵活性测试"""
    
    def __init__(self, engine):
        self.engine = engine
        self.results = {"layout_diversity": []}
    
    def test_layout_diversity(self):
        """测试布局多样性"""
        dataset = TEST_DATASET["layout_flexibility"]
        
        for query in dataset:
            configs = {
                "full": {"include_border": True, "include_base": True},
                "no_border": {"include_border": False, "include_base": True},
                "no_base": {"include_border": True, "include_base": False},
                "primary_only": {"include_border": False, "include_base": False},
            }
            
            success_count = 0
            for config_name, config_params in configs.items():
                try:
                    blueprint = self.engine.build_blueprint_v52(query, seed=42, **config_params)
                    success_count += 1
                except:
                    pass
            
            diversity_score = success_count / len(configs)
            self.results["layout_diversity"].append({"query": query, "score": diversity_score})
        
        return np.mean([r["score"] for r in self.results["layout_diversity"]])
    
    def run_all(self):
        """运行所有测试"""
        print("\n" + "="*60)
        print("测试维度 3：布局灵活性")
        print("="*60)
        
        diversity = self.test_layout_diversity()
        print(f"\n布局多样性: {diversity:.2%} (目标: 100%)")
        
        return {"layout_diversity": diversity}


class TestPatternRecommendation:
    """纹样推荐测试"""
    
    def __init__(self, engine):
        self.engine = engine
        self.results = {"pattern_matching": []}
    
    def test_pattern_matching(self):
        """测试纹样推荐匹配度"""
        dataset = TEST_DATASET["pattern_recommendation"]
        
        for case in dataset:
            primary = case["primary"]
            secondary = case["secondary"]
            expected_type = case["expected_type"]
            
            recommendation = LayoutComposer.recommend_patterns(primary, secondary)
            is_match = recommendation["category"] == expected_type
            
            self.results["pattern_matching"].append({
                "primary": primary,
                "score": 1.0 if is_match else 0.0
            })
        
        return np.mean([r["score"] for r in self.results["pattern_matching"]])
    
    def run_all(self):
        """运行所有测试"""
        print("\n" + "="*60)
        print("测试维度 4：纹样推荐")
        print("="*60)
        
        matching = self.test_pattern_matching()
        print(f"\n纹样匹配度: {matching:.2%} (目标: >85%)")
        
        return {"pattern_matching": matching}


class TestBoundaryAnalysis:
    """边界分析测试"""
    
    def __init__(self, engine):
        self.engine = engine
        self.results = {"normal": [], "ambiguous": [], "contradictory": [], "out_of_domain": []}
    
    def test_boundary_cases(self):
        """测试系统边界情况"""
        dataset = TEST_DATASET["boundary_cases"]
        
        for category, queries in dataset.items():
            for query in queries:
                try:
                    blueprint = self.engine.build_blueprint_v52(query, seed=42)
                    self.results[category].append({"query": query, "success": True, "score": 1.0})
                except:
                    self.results[category].append({"query": query, "success": False, "score": 0.0})
        
        success_rates = {}
        for category, results in self.results.items():
            success_count = sum(1 for r in results if r["success"])
            success_rates[category] = success_count / len(results) if results else 0
        
        return success_rates
    
    def run_all(self):
        """运行所有测试"""
        print("\n" + "="*60)
        print("测试维度 5：系统边界分析")
        print("="*60)
        
        success_rates = self.test_boundary_cases()
        
        for category, rate in success_rates.items():
            print(f"\n{category} 查询成功率: {rate:.2%}")
        
        return success_rates


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*80)
    print("KG推理系统论文级测试框架")
    print("="*80)
    
    engine = HybridGraphEngine(Path('d:/SD/MMKG/data_csv/mmkg_final_v53_optimized.csv'))
    
    results = {}
    results["element_recommendation"] = TestElementRecommendation(engine).run_all()
    results["compatibility_reasoning"] = TestCompatibilityReasoning(engine).run_all()
    results["layout_flexibility"] = TestLayoutFlexibility(engine).run_all()
    results["pattern_recommendation"] = TestPatternRecommendation(engine).run_all()
    results["boundary_analysis"] = TestBoundaryAnalysis(engine).run_all()
    
    print("\n" + "="*80)
    print("测试总结")
    print("="*80)
    
    output_path = Path("d:/SD/test_results.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n测试结果已保存到: {output_path}")


if __name__ == "__main__":
    run_all_tests()
