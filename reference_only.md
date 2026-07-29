# chanzhi_sw_clean 只读参考资产清单

定义：这些资产不得进入 `src/`、`data/baselines/`、默认配置或运行时搜索路径。run57 方法链所需的冻结快照已迁移到 `tests/fixtures/reference_only/run57_snapshot/`；其他历史资料只在原工作区查阅或进入 `references/immutable/`。

| 类别与源路径 | 是否迁移 | 迁移到哪里 | 为什么 | 可作正式输入 | 只作 reference | 污染风险 |
|---|---|---|---|---|---|---|
| run57 final reference：`newpipe/outputs/chanzhi_transferable_pipeline/run57_smooth_candidate_filter/04_terminal_lineart/` 下 5 个 `terminal_lineart.svg`、5 个 `terminal_lineart_preview.png`、5 个 `terminal_render.json`、`terminal_render_manifest.json`、contact sheet | **是，第一批迁移** | `tests/fixtures/reference_only/run57_snapshot/04_terminal_lineart/` | 记录当前最佳结果和逐原型视觉/指标基准，供继续优化时回归对比 | 否，明确禁止 | 是 | **极高**；必须阻断运行时读取 |
| run28 骨架与布局快照：5 个原型的 `skeleton_profile.json`、`region_graph.json`、`branch_layout_plan.json` 及阶段 manifest | **是，第一批迁移** | `tests/fixtures/reference_only/run57_snapshot/{01_skeleton_analysis,02_branch_layout}/` | 它们是历史 run57 结果实际使用的上游状态，保存方法证据链 | 否 | 是 | 高；只能用于回归和问题定位 |
| run56 几何快照：5 个 `branch_geometry.json` 及阶段 manifest | **是，第一批迁移** | `tests/fixtures/reference_only/run57_snapshot/03_branch_geometry/` | 它是历史 run57 终端结果实际使用的 soft-curve 几何状态 | 否 | 是 | 高 |
| run28/56/57 的 `parallel/`、preview、重复 PNG 和未被最佳链引用的其他阶段产物 | 不迁移 | 无 | 不属于保存最佳方法所需的唯一快照 | 否 | 原路径可查阅 | 高 |
| `newpipe/chanzhi_archive/` | 不迁移代码；保留原工作区路径作外部参考 | 无；继续位于 `D:/sdxl/newpipe/chanzhi_archive/` | 旧实验、模板研究和 baseline 历史对理解路线有用，但不是当前主线 | 否 | 是 | 高；其中 slot-search 被 paper baseline_runner 直接调用，易重建旧耦合 |
| MMKG 全库：`MMKG/` | 不迁移全库；留在原工作区查阅 | 无；外部 reference | 295 MiB、54 类/625 图，专门缠枝素材少，且不被 run57 结构链引用 | 否 | 是 | 高；会把 clean 项目重新扩为多纹饰知识图谱工程 |
| 全量审查 Markdown：`project_audit_20260625/D_sdxl项目全量审查与工作汇报_20260625.md` | 可迁移一份只读 Markdown | `references/immutable/audits/` | 是本清单的主要证据源 | 否 | 是 | 低 |
| `advisor_progress_report_20260613/claim_register.md` | 可迁移只读副本或在设计文档中引用 | `references/immutable/claims/` | 保留“可说/不可说”的事实边界 | 否 | 是 | 低 |
| DOCX/PDF/PPTX、导师汇报多版、审查附件、论文草稿 | 默认不复制；在原工作区查阅 | 无；若论文阶段需要则放仓库外文档归档 | 对历史与汇报有价值，但不参与 SVG 生成 | 否 | 是 | 中；版本重复且容易把计划表述成已完成结果 |
| 扩散、LoRA、pix2pix、ControlNet 的少量代表结果图 | 不进 clean 项目；论文对比时从原路径只读引用 | 无；外部 reference | 只能证明结构生成不应交给黑盒扩散 | 否 | 是 | 中；若混入主线会模糊“SVG 是结构真值” |

## run57 参考的解释边界

- run57 报告的 `valid`、0 crossing、0 flower overlap、0 boundary violation、0 abrupt curve 仅是自定义几何约束结果。
- 人工审查仍指出花头悬浮/占位、挂接生硬、层级与节奏不足、叶形模板化。
- run57 目录没有独立 `pipeline_manifest.json`；当前 paper 配置实际依赖 run28 骨架/布局、run56 几何和 run57 终端结果。因此它是“冻结证据组合”，不是可迁移的正式输入包。
