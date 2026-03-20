# -*- coding: utf-8 -*-
"""测试关联度推理效果"""
import sys
sys.path.insert(0, 'd:/SD')

from kg_sketch_reasoning_engine import HybridGraphEngine
from pathlib import Path

engine = HybridGraphEngine(Path('d:/SD/MMKG/data_csv/mmkg_final_v53_optimized.csv'))

# 测试场景 1：花朵主题
# 预期：缠枝纹应该排名提升（与花朵兼容），回纹应该排名下降（与花朵冲突）
print("=" * 60)
print("测试场景 1：花朵主题")
print("=" * 60)

bp1 = engine.build_blueprint_v52("新婚快乐", seed=42)
print(f"\n意图: {bp1['debug']['intent_category']}")
print(f"主体元素: {bp1['slots'][0]['element']}")
print(f"\n推荐的槽位:")
for slot in bp1['slots']:
    print(f"  {slot['role']:10s} {slot['element']:8s}")

# 测试场景 2：龙主题
# 预期：海水应该排名提升（与龙兼容），花朵应该排名下降（与龙冲突）
print("\n" + "=" * 60)
print("测试场景 2：龙主题")
print("=" * 60)

bp2 = engine.build_blueprint_v52("祝老板生意兴隆", seed=42)
print(f"\n意图: {bp2['debug']['intent_category']}")
print(f"主体元素: {bp2['slots'][0]['element']}")
print(f"\n推荐的槽位:")
for slot in bp2['slots']:
    print(f"  {slot['role']:10s} {slot['element']:8s}")

# 测试场景 3：鹤主题
# 预期：灵芝应该排名提升（与鹤兼容），海水应该排名下降（与鹤冲突）
print("\n" + "=" * 60)
print("测试场景 3：鹤主题")
print("=" * 60)

bp3 = engine.build_blueprint_v52("松鹤延年", seed=42)
print(f"\n意图: {bp3['debug']['intent_category']}")
print(f"主体元素: {bp3['slots'][0]['element']}")
print(f"\n推荐的槽位:")
for slot in bp3['slots']:
    print(f"  {slot['role']:10s} {slot['element']:8s}")

print("\n" + "=" * 60)
print("关联度推理测试完成")
print("=" * 60)
