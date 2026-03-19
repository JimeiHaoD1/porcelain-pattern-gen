# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, 'd:/SD')
from kg_sketch_reasoning_engine import HybridGraphEngine
from pathlib import Path

e = HybridGraphEngine(Path('d:/SD/MMKG/data_csv/mmkg_final_v53_optimized.csv'))
for query in ['祝老板生意兴隆', '早生贵子', '新婚快乐', '想去山里隐居', '松鹤延年']:
    bp = e.build_blueprint_v52(query, seed=42)
    slots = bp['slots']
    print(f"\n[{query}] layout={bp['layout_archetype']} intent={bp['debug']['intent_category']}")
    for s in slots:
        print(f"  {s['role']:10s} {s['element']}")
    print(f"  总槽位数: {len(slots)}")
print('DONE')
