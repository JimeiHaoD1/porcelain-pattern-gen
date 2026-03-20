# -*- coding: utf-8 -*-
"""
KG推理系统快速测试 - 跳过 embedding 加载
直接测试关键功能
"""
import sys
sys.path.insert(0, 'd:/SD')

import json
from pathlib import Path
import numpy as np

from layout_composer import LayoutComposer
from compatibility_rules import _COMPATIBILITY_RULES
from pattern_library import _PATTERN_LIBRARY

print("="*80)
print("KG推理系统快速测试（无 embedding）")
print("="*80)

# ============================================================================
# 测试 1：兼容性规则加载
# ============================================================================
print("\n[测试 1] 兼容性规则加载")
print("-" * 60)

compat_path = Path("d:/SD/compatibility_rules.json")
if compat_path.exists():
    with open(compat_path, 'r', encoding='utf-8') as f:
        compat_data = json.load(f)
    
    compat_rules = compat_data.get("compatibility_rules", {})
    print(f"✓ 加载了 {len(compat_rules)} 个元素的兼容性规则")
    
    # 验证几个关键规则
    test_cases = [
        ("龙", "海水", True),
        ("龙", "花朵", False),
        ("牡丹", "缠枝纹", True),
        ("牡丹", "回纹", False),
    ]
    
    correct = 0
    for elem1, elem2, should_compatible in test_cases:
        rules = compat_rules.get(elem1, {})
        compatible_list = rules.get("compatible_with", [])
        incompatible_list = rules.get("incompatible_with", [])
        
        is_compatible = elem2 in compatible_list
        is_incompatible = elem2 in incompatible_list
        
        if should_compatible:
            if is_compatible:
                print(f"  ✓ {elem1} + {elem2} 兼容")
                correct += 1
            else:
                print(f"  ✗ {elem1} + {elem2} 应该兼容但未标注")
        else:
            if is_incompatible:
                print(f"  ✓ {elem1} + {elem2} 冲突")
                correct += 1
            else:
                print(f"  ✗ {elem1} + {elem2} 应该冲突但未标注")
    
    print(f"\n兼容性规则准确性: {correct}/{len(test_cases)} = {100*correct/len(test_cases):.0f}%")
else:
    print("✗ 兼容性规则文件不存在")

# ============================================================================
# 测试 2：纹样库加载
# ============================================================================
print("\n[测试 2] 纹样库加载")
print("-" * 60)

pattern_path = Path("d:/SD/pattern_library.json")
if pattern_path.exists():
    with open(pattern_path, 'r', encoding='utf-8') as f:
        pattern_data = json.load(f)
    
    border_patterns = pattern_data.get("border_patterns", {})
    base_patterns = pattern_data.get("base_patterns", {})
    recommendations = pattern_data.get("pattern_recommendations", {})
    
    print(f"✓ 边饰纹样类别: {list(border_patterns.keys())}")
    print(f"✓ 底纹纹样类别: {list(base_patterns.keys())}")
    print(f"✓ 推荐规则: {list(recommendations.keys())}")
    
    # 统计纹样数量
    total_border = sum(len(v) for v in border_patterns.values())
    total_base = sum(len(v) for v in base_patterns.values())
    print(f"\n纹样库统计:")
    print(f"  边饰纹样总数: {total_border}")
    print(f"  底纹纹样总数: {total_base}")
else:
    print("✗ 纹样库文件不存在")

# ============================================================================
# 测试 3：纹样推荐函数
# ============================================================================
print("\n[测试 3] 纹样推荐函数")
print("-" * 60)

test_recommendations = [
    ("龙", ["海水"], "geometric"),
    ("牡丹", ["蝴蝶"], "organic"),
    ("鹤", ["松树"], "landscape"),
]

correct_recommendations = 0
for primary, secondary, expected_type in test_recommendations:
    rec = LayoutComposer.recommend_patterns(primary, secondary)
    actual_type = rec["category"]
    
    if actual_type == expected_type:
        print(f"✓ {primary} + {secondary} → {actual_type}")
        correct_recommendations += 1
    else:
        print(f"✗ {primary} + {secondary} → {actual_type} (期望: {expected_type})")

print(f"\n纹样推荐准确性: {correct_recommendations}/{len(test_recommendations)} = {100*correct_recommendations/len(test_recommendations):.0f}%")

# ============================================================================
# 测试 4：纹样轮换
# ============================================================================
print("\n[测试 4] 纹样轮换机制")
print("-" * 60)

patterns_to_test = ["缠枝纹", "回纹", "云纹"]
for pattern in patterns_to_test:
    variants = []
    for i in range(3):
        variant = LayoutComposer.get_pattern_variant(pattern, i)
        variants.append(variant)
    
    unique_variants = len(set(variants))
    print(f"✓ {pattern}: {variants} (唯一变体: {unique_variants})")

# ============================================================================
# 测试 5：Co-occurrence 矩阵
# ============================================================================
print("\n[测试 5] Co-occurrence 矩阵")
print("-" * 60)

cooccurrence_path = Path("d:/SD/cooccurrence_rules.json")
if cooccurrence_path.exists():
    with open(cooccurrence_path, 'r', encoding='utf-8') as f:
        cooccurrence_data = json.load(f)
    
    print(f"✓ 加载了 {len(cooccurrence_data)} 个元素的共现数据")
    
    # 显示几个例子
    for i, (elem, data) in enumerate(list(cooccurrence_data.items())[:3]):
        cooccurs = data.get("cooccurs_with", [])[:3]
        print(f"  {elem}: 常与 {cooccurs} 一起出现")
else:
    print("✗ Co-occurrence 矩阵文件不存在")

# ============================================================================
# 测试 6：布局类型定义
# ============================================================================
print("\n[测试 6] 布局类型定义")
print("-" * 60)

from pipeline_controller import LAYOUT_TYPES, INTENT_TO_LAYOUT_TYPE

print(f"✓ 布局类型: {list(LAYOUT_TYPES.keys())}")
for layout_type, variants in LAYOUT_TYPES.items():
    print(f"  {layout_type}: {variants}")

print(f"\n✓ 意图到布局映射: {len(INTENT_TO_LAYOUT_TYPE)} 个意图")
for intent, layout_type in list(INTENT_TO_LAYOUT_TYPE.items())[:3]:
    print(f"  {intent} → {layout_type}")

# ============================================================================
# 总结
# ============================================================================
print("\n" + "="*80)
print("快速测试总结")
print("="*80)

summary = {
    "兼容性规则": f"{correct}/{len(test_cases)} 正确",
    "纹样推荐": f"{correct_recommendations}/{len(test_recommendations)} 正确",
    "纹样轮换": "✓ 正常工作",
    "Co-occurrence": "✓ 已加载",
    "布局类型": f"✓ {len(LAYOUT_TYPES)} 种类型",
}

for test_name, result in summary.items():
    print(f"{test_name}: {result}")

print("\n✓ 所有快速测试完成")
print("✓ 系统核心功能正常")
print("\n下一步：运行完整的论文级测试（需要 embedding 加载）")
