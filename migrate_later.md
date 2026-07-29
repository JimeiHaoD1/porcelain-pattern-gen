# chanzhi_sw_clean 条件式后续迁移清单

状态：**不在第一批复制。** 只有满足每项 gate 后才允许选择性迁移；禁止整目录搬运。

| 类别与源路径 | 是否迁移 | 迁移到哪里 | 为什么暂缓 | 可作正式输入 | 只作 reference | 污染风险 |
|---|---|---|---|---|---|---|
| 5 个上游标注源 SVG：`newpipe/data/prototype_library/chanzhi/annotated_svg/{proto_sw_1_1,proto_sw_1_3,proto_sw_2_3,proto_sw_3_1,proto_sw_3_2}.svg` | 条件式迁移 | `data/source_annotations/sw/` | 可用于追溯 baseline 来源，但体量大，且当前 run57 并不直接读取它们 | 否；除非未来重建 baseline 编译链 | 是 | 中；若与 baseline 混放会混淆输入层级 |
| `newpipe/data/prototype_library/chanzhi/index.json` 与对应 5 个 `prototypes/*.json` | 条件式迁移 | `data/source_annotations/sw/metadata/` | 保留原型元数据；审查已发现 semantic tags 空、guide/flower 信息不齐 | 否，未清洗前不可 | 是 | 中 |
| `newpipe/chanzhi_mainline/chanzhi_annotated_svg_pipeline.py` | 条件式迁移 | `tools/baseline_build/` | 只有在新项目决定“可从标注源重新构建 baseline”时才需要 | 否；属于离线构建工具 | 否 | 高；放进运行主包会把旧 13-family 流程带回主线 |
| `paper_experiment/configs/paper_experiment_v1.json`、`README.md`、`tests/` 中与协议有关的内容 | 仅重写后迁移，不得原样复制 | `experiments/paper_v2/` | v1 把 run28/56/57 冻结产物拼成方法输入，并声明 `run57_final_method`；不具备独立生成闭环 | 否 | 否 | 高；会把结果反向当方法输入 |
| `paper_experiment/statistical_analysis.py`、`prepare_user_study.py` 中与结构指标/人评协议独立的部分 | 通过依赖审查后迁移 | `experiments/evaluation/` | 评价工具可能复用，但必须证明不导入 adapter、不读取冻结 run JSON | 否 | 否 | 中 |
| MMKG 最小子集：`newpipe/data/mmkg/motif_flat.csv`、`newpipe/data/mmkg/mmkg_final_v53_optimized.csv` | 只有恢复文本→Spec Card 时迁移 | `optional/semantic/data/` | run57 结构链不依赖 MMKG；当前 KG 为 532 条，旧测试契约仍不一致 | 否；仅可作为可选语义层输入 | 否 | 高；会重新扩大到多纹饰/KG 主线 |
| `newpipe/core/semantic_parser.py`、`chanzhi_spec_compiler.py`、`chanzhi_retriever.py` 及其同步测试 | schema 冻结且测试一致后迁移 | `optional/semantic/` | 当前目标是 SW 结构生成，不需要先引入语义/KG 耦合 | 否；代码模块 | 否 | 中 |
| 后 run57 的 branch-unit 实验：`newpipe/experiments/chanzhi_ordered_branch_unit_{core,experiment,render}.py` 与对应测试 | 视觉 gate 通过后择优迁移 | `experiments/branch_unit/`，成熟后再进入 `src/` | 它针对 run57 的独立曲线/视觉晋升问题，但当前仍属实验路线 | 否 | 否 | 高；未经视觉批准会把未成熟实验升级为主线 |
| 轻量设计文档：`chanzhi_classification_guide.txt`、`chanzhi_annotation_color_spec_v2.txt`、`pipelinev7.txt`、`advisor_progress_report_20260613/claim_register.md` | 清理与去重后迁移 | `docs/design/`、`docs/evidence/` | 可保留 SW 分类、SVG 真值和 claim 边界 | 否 | 其中 claim/report 只作 reference | 低到中 |

## 后续迁移 gate

1. 正式运行配置不允许引用 `newpipe/outputs/chanzhi_transferable_pipeline/run28_*`、`run56_*`、`run57_*`；测试只能显式读取 `tests/fixtures/reference_only/run57_snapshot/` 做回归比较。
2. 不允许导入 `paper_experiment/run57_adapter.py`。
3. 由 baseline SVG 从头运行，必须重新产生分析、布局、几何和终端结果。
4. 结构状态、视觉状态和可发布状态必须是三个显式字段。
5. MMKG 只有在 SW 主线稳定且文本控制成为明确研究变量后再接入。
