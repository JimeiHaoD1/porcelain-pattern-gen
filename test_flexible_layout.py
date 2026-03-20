# -*- coding: utf-8 -*-
"""测试灵活布局功能"""
import sys
sys.path.insert(0, 'd:/SD')

from kg_sketch_reasoning_engine import HybridGraphEngine
from pathlib import Path

engine = HybridGraphEngine(Path('d:/SD/MMKG/data_csv/mmkg_final_v53_optimized.csv'))

print("=" * 60)
print("测试灵活布局：生成不同配置的 blueprint")
print("=" * 60)

# 测试 1：完整布局（默认）
print("\n[测试 1] 完整布局（include_border=True, include_base=True）")
bp1 = engine.build_blueprint_v52("祝老板生意兴隆", seed=42, include_border=True, include_base=True)
print(f"槽位数: {len(bp1['slots'])}")
for slot in bp1['slots']:
    print(f"  {slot['role']:10s} {slot['element']:8s}")

# 测试 2：不含边饰
print("\n[测试 2] 不含边饰（include_border=False, include_base=True）")
bp2 = engine.build_blueprint_v52("祝老板生意兴隆", seed=42, include_border=False, include_base=True)
print(f"槽位数: {len(bp2['slots'])}")
for slot in bp2['slots']:
    print(f"  {slot['role']:10s} {slot['element']:8s}")

# 测试 3：不含底纹
print("\n[测试 3] 不含底纹（include_border=True, include_base=False）")
bp3 = engine.build_blueprint_v52("祝老板生意兴隆", seed=42, include_border=True, include_base=False)
print(f"槽位数: {len(bp3['slots'])}")
for slot in bp3['slots']:
    print(f"  {slot['role']:10s} {slot['element']:8s}")

# 测试 4：仅主体和配角
print("\n[测试 4] 仅主体和配角（include_border=False, include_base=False）")
bp4 = engine.build_blueprint_v52("祝老板生意兴隆", seed=42, include_border=False, include_base=False)
print(f"槽位数: {len(bp4['slots'])}")
for slot in bp4['slots']:
    print(f"  {slot['role']:10s} {slot['element']:8s}")

print("\n" + "=" * 60)
print("灵活布局测试完成")
print("=" * 60)
