# chanzhi_sw_clean 禁止迁移清单

这些资产不得复制到新项目。需要历史核对时，只从 `D:\sdxl` 原位置只读访问。

| 类别与源路径 | 是否迁移 | 迁移到哪里 | 为什么 | 可作正式输入 | 只作 reference | 污染风险 |
|---|---|---|---|---|---|---|
| `paper_experiment/run57_adapter.py` 及 `__pycache__/run57_adapter*.pyc` | **否** | 无 | 它读取 run28/56/57 冻结 JSON/SVG，复制并扰动 motif，再将结果标为 `run57_final_method`；不是从 baseline 独立生成 | 否 | 仅在原工作区审计代码时查阅，不复制 | **极高** |
| `paper_experiment/outputs/`、`figures/`、`metrics/`、`manifests/` 以及由 adapter 产生的 `final.svg`、`geometry_ir.json` 等 | **否** | 无 | 属于基于冻结结果再加工的论文产物，不能反向成为方法资产 | 否 | 否；必要时只引用原路径 | **极高** |
| 原样的 `paper_experiment/configs/paper_experiment_v1.json` 与 `run_experiment.py` | **否，原样禁止** | 无 | 配置显式把 run28/56/57 产物列为 `frozen_sources`，runner 直接导入 adapter | 否 | 可在原工作区审计 | **极高** |
| 扩散/SDXL/IP-Adapter/ControlNet 代码、缓存、模型与输出：`newpipe/outputs/pure_sdxl_chanzhi/`、`controlnet_*`、`chanzhi_diff_*`、`stage_b/` 等 | **否** | 无 | 当前目标是结构可控 SVG；审查证明扩散不能稳定长结构 | 否 | 结果图最多外部 reference | 高 |
| LoRA：`lora_output/`、`train_lora.py`、相关 checkpoint/`.safetensors`/训练状态 | **否** | 无 | 约 249 MiB，存在重复权重，只学到宽泛卷草风格；明确不是结构核心 | 否 | 结果图最多外部 reference | 高 |
| pix2pix：`newpipe/pix2pix/` 全目录，包括数据、11 个检查点、训练/推理输出 | **否** | 无 | 约 8.85 GiB，是主要体积来源；效果不合格，且用户明确禁止迁入数据 | 否 | 结果图最多外部 reference | **极高** |
| run28/run56/run57 中未进入最佳方法快照的 `parallel/`、preview PNG、重复 contact sheet、run28 旧 geometry/terminal 等产物 | **否** | 无 | 第一批已经保存唯一的 run28 分析/布局、run56 几何、run57 终端链；其余是冗余阶段缓存 | 否 | 原路径可查阅 | 高 |
| `newpipe/chanzhi_mainline/ordered_lineart_outputs/`、`secondary_branch_growth_tests/`、`secondary_branch_iteration_archive/`、debug sheet、当前自动生成模板目录 | **否，除非以后通过 migrate_later gate 重新选择源码** | 无 | 属于后续实验输出/调试资产，不属于 run57 最小闭包 | 否 | 可从原路径查阅 | 高 |
| `newpipe/chanzhi_archive/` 的代码与输出副本 | **否** | 无 | 历史路线已经物理隔离，不应重新并入 clean 仓库 | 否 | 原位置只读 reference | 高 |
| MMKG 全库 `MMKG/`、`dataset_sketches/`、SQLite/图片素材 | **否** | 无 | 范围过宽且与当前 SW 结构链无直接依赖；只允许未来评估两个最小 CSV | 否 | 原位置只读 reference | 高 |
| DOCX/PDF/PPTX 多版本、`advisor_progress_report_20260613` 预览/contact sheet、`project_audit_20260625/extracted_documents/` | **否** | 无 | 重复、体积和版本噪声高；新仓库只需要少量 Markdown 事实边界 | 否 | 原位置只读 reference | 中 |
| `.codex_tmp/` | **否** | 无 | 浏览器/PDF/临时审计文件；审查发现其中有 0 字节损坏 PNG | 否 | 否 | 高 |
| `.deps/` | **否** | 无 | 本地依赖副本，不应作为项目源码；应由依赖清单重建 | 否 | 否 | 高 |
| `.pytest_cache/`、普通 `__pycache__/`、普通 `.pyc`、临时截图、`tmp_*` | **否** | 无 | 缓存与临时文件通常不具备资产价值 | 否 | 否 | 高；唯一例外是已验证能精确复现 run57 的 6 个历史 pyc，隔离在 `legacy/run57_exact/` |
| `project_audit_20260625/duplicate_files.csv` 标识的重复 PNG 实例、各 run 中不变中间图、报告图复制件 | **否** | 无 | 全量审查发现 1,264 个重复组、约 239.7 MB 额外占用；复制会直接把冗余带入新项目 | 否 | 否 | 高 |
| AC/DI 原型与相关输出 | **否，当前阶段** | 无 | 当前研究目标明确限定 SW；AC/DI 尚无同等级生成和验证 | 否 | 可在原型库外部查阅 | 中 |

## 硬性阻断规则

迁移实施时，只要发现下列任一情况即停止该项：

1. 文件位于 `run57_*`，却被计划放入 `data/baselines/` 或运行时配置。
2. Python 代码导入 `run57_adapter`，或配置包含 `frozen_sources.run57_*`。
3. 文件扩展名为 `.ckpt`、`.pth`、`.pt`、`.safetensors`，或位于 pix2pix 数据/检查点目录。
4. 源路径包含 `.codex_tmp`、`.deps`、`__pycache__`、`.pytest_cache`。
5. PNG/SVG/JSON 只是 run 中间产物，却没有独立、上游可复现来源。
