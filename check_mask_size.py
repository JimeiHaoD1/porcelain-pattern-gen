# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, 'd:/SD')
import numpy as np
from pathlib import Path
from kg_sketch_reasoning_engine import HybridGraphEngine
from pipeline_controller import PorcelainGenerationPipeline

CANVAS = (768, 768)
KG_PATH = Path('d:/SD/MMKG/data_csv/mmkg_final_v53_optimized.csv')

engine = HybridGraphEngine(KG_PATH)
porcelain = PorcelainGenerationPipeline(canvas_size=CANVAS, rng_seed=42)

for query in ['祝老板生意兴隆', '松鹤延年']:
    bp = engine.build_blueprint_v52(query, seed=42)
    out = porcelain.process_blueprint(bp)
    masks = out['masks']
    slots = out['resolved_blueprint']['slots']
    W, H = CANVAS
    print(f'\n[{query}]')
    for slot in slots:
        sid = slot['slot_id']
        mask = masks.get(sid)
        if mask is None:
            print(f'  {slot["role"]:10s} {slot["element"]:8s}  NO MASK')
            continue
        area = int((mask > 0).sum())
        pct = area / (W * H) * 100
        ys, xs = np.where(mask > 0)
        if xs.size:
            bw = int(xs.max() - xs.min() + 1)
            bh = int(ys.max() - ys.min() + 1)
        else:
            bw = bh = 0
        print(f'  {slot["role"]:10s} {slot["element"]:8s}  bbox={bw}x{bh}  area={pct:.1f}%')
print('DONE')
