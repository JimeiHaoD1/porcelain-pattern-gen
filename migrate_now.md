# chanzhi_sw_clean 第一批迁移清单

状态：**已执行迁移并完成 run57 复现测试。**

范围：保存并延续当前最佳的 run57 方法，包括正式 baseline 输入、可运行代码闭包，以及 run28→run56→run57 的冻结回归快照。`run57` 的输出 SVG/JSON 随项目迁移，但不属于正式生成输入。

第一批实际迁移 **59 个文件、约 4.97 MiB**：5 个 baseline SVG、8 个当前核心源码、40 个 run57 方法链回归文件、6 个历史 run57 Python 3.11 字节码取证文件。

## 1. Baseline SVG（5 个正式输入）

| 源路径 | 是否迁移 | 迁移到哪里 | 为什么 | 可作正式输入 | 只作 reference | 污染风险 |
|---|---|---|---|---|---|---|
| `newpipe/outputs/chanzhi_ready_experiment/from_chanzhidanyuan_20260513_v10/library_build/generated/proto_sw_1_1/proto_sw_1_1_baseline.svg` | 是，第一批 | `data/baselines/sw/proto_sw_1_1/proto_sw_1_1_baseline.svg` | run57 骨架分析器的上游输入；不是 run57 产物 | 是 | 否 | 低；需用 SHA-256 固定版本 |
| `newpipe/outputs/chanzhi_ready_experiment/from_chanzhidanyuan_20260513_v10/library_build/generated/proto_sw_1_3/proto_sw_1_3_baseline.svg` | 是，第一批 | `data/baselines/sw/proto_sw_1_3/proto_sw_1_3_baseline.svg` | 同上 | 是 | 否 | 低 |
| `newpipe/outputs/chanzhi_ready_experiment/from_chanzhidanyuan_20260513_v10/library_build/generated/proto_sw_2_3/proto_sw_2_3_baseline.svg` | 是，第一批 | `data/baselines/sw/proto_sw_2_3/proto_sw_2_3_baseline.svg` | 同上 | 是 | 否 | 低；原审查指出该原型 guide 信息偏弱，需保留数据质量标记 |
| `newpipe/outputs/chanzhi_ready_experiment/from_chanzhidanyuan_20260513_v10/library_build/generated/proto_sw_3_1/proto_sw_3_1_baseline.svg` | 是，第一批 | `data/baselines/sw/proto_sw_3_1/proto_sw_3_1_baseline.svg` | 同上 | 是 | 否 | 低 |
| `newpipe/outputs/chanzhi_ready_experiment/from_chanzhidanyuan_20260513_v10/library_build/generated/proto_sw_3_2/proto_sw_3_2_baseline.svg` | 是，第一批 | `data/baselines/sw/proto_sw_3_2/proto_sw_3_2_baseline.svg` | 同上 | 是 | 否 | 低 |

固定哈希：

| prototype | SHA-256 |
|---|---|
| `proto_sw_1_1` | `2b6ba51feb3190a1bee0cbe38d086ac9b3e07def54bd069c91fadc07583dd54d` |
| `proto_sw_1_3` | `9bc0b3f62faac92772ad9257f558a12b382f95fc4179642958e9437d96ac46ae` |
| `proto_sw_2_3` | `87881b6c46c08497ad02e19bfe8c85e32760c03548b21724fb3f8967b3884a74` |
| `proto_sw_3_1` | `dd2faccef5f23c0fe485e21be087f4043cbeaf950de65e443592eb68f333a39f` |
| `proto_sw_3_2` | `0937474664672233ccb6676d457c6ce5cb47782d37cb0e22c4f54ada22c02442` |

禁止随 baseline 一起复制同目录的 PNG、debug PNG、flower mask、`dense_high`、`sparse_low` 或其他变体。

## 2. chanzhi_mainline 最小核心代码

| 源路径 | 是否迁移 | 迁移到哪里 | 为什么 | 可作正式输入 | 只作 reference | 污染风险 |
|---|---|---|---|---|---|---|
| `newpipe/chanzhi_mainline/__init__.py` | 是，第一批 | `src/chanzhi_sw/__init__.py` | 包边界 | 否，代码不是输入资产 | 否 | 低 |
| `newpipe/chanzhi_mainline/chanzhi_transferable_pipeline.py` | 是，第一批 | `src/chanzhi_sw/chanzhi_transferable_pipeline.py` | 四阶段编排入口；保留原文件名避免改变导入行为 | 否 | 否 | 中；当前默认路径仍需后续配置化 |
| `newpipe/chanzhi_mainline/chanzhi_skeleton_analyzer.py` | 是，第一批 | `src/chanzhi_sw/chanzhi_skeleton_analyzer.py` | baseline SVG 到骨架/区域图 | 否 | 否 | 中；当前默认输入仍指向旧工作区层级 |
| `newpipe/chanzhi_mainline/chanzhi_svg_skeleton_io.py` | 是，第一批 | `src/chanzhi_sw/chanzhi_svg_skeleton_io.py` | SVG 路径解析依赖 | 否 | 否 | 低 |
| `newpipe/chanzhi_mainline/chanzhi_branch_layout_grammar.py` | 是，第一批 | `src/chanzhi_sw/chanzhi_branch_layout_grammar.py` | 区域与分支角色布局 | 否 | 否 | 中；启发式阈值需配置化 |
| `newpipe/chanzhi_mainline/chanzhi_branch_geometry.py` | 是，第一批 | `src/chanzhi_sw/chanzhi_branch_geometry.py` | C/S 曲线、碰撞与候选求解 | 否 | 否 | 中；不得读取 run56 JSON 作为运行时输入 |
| `newpipe/chanzhi_mainline/chanzhi_terminal_primitives.py` | 是，第一批 | `src/chanzhi_sw/chanzhi_terminal_primitives.py` | 末端母题几何原语 | 否 | 否 | 中；模板化视觉需后续视觉 gate |
| `newpipe/chanzhi_mainline/chanzhi_terminal_renderer.py` | 是，第一批 | `src/chanzhi_sw/chanzhi_terminal_renderer.py` | 当前终端线稿实现；测试证明它已不同于历史 run57 | 否 | 否 | 高；不能冒充历史 run57 renderer |

迁移约束：

1. 只迁移上述 8 个文件，不整目录复制 `chanzhi_mainline`。
2. 运行时唯一正式输入根目录为 `data/baselines/sw/`。
3. 代码不得回退读取 `run28`、`run56`、`run57` 或 `paper_experiment`。
4. 新输出必须进入 `artifacts/runs/<run_id>/`，且不得覆盖 baseline。
5. `structural_valid` 与 `visual_approved` 必须分离；没有视觉批准不得标为正式结果。

## 3. run57 方法冻结与回归快照

历史 run57 结果不是由一个完整 run57 目录独立产生的。现有证据链实际为：

`baseline SVG → run28 skeleton/profile + region/layout → run56 branch geometry → run57 terminal render`

因此，保存最佳方法不能只迁移 8 个 Python 文件；还必须迁移这一组合快照，用于后续优化时做结构和视觉回归对照。

| 源路径 | 是否迁移 | 迁移到哪里 | 为什么 | 可作正式输入 | 只作 reference | 污染风险 |
|---|---|---|---|---|---|---|
| `newpipe/outputs/chanzhi_transferable_pipeline/run28_75pct_full_validation/01_skeleton_analysis/` 中 5 个原型的 `skeleton_profile.json`、`region_graph.json` 和阶段 manifest | 是，第一批 | `tests/fixtures/reference_only/run57_snapshot/01_skeleton_analysis/` | 保存 run57 最佳结果实际使用的骨架分析状态 | **否** | 是，回归 fixture | 高；不得被默认 pipeline 读取 |
| `run28_75pct_full_validation/02_branch_layout/` 中 5 个 `branch_layout_plan.json` 和阶段 manifest | 是，第一批 | `tests/fixtures/reference_only/run57_snapshot/02_branch_layout/` | 保存 run57 实际使用的分支布局状态 | **否** | 是，回归 fixture | 高 |
| `run56_soft_curves_full/03_branch_geometry/` 中 5 个 `branch_geometry.json` 和阶段 manifest | 是，第一批 | `tests/fixtures/reference_only/run57_snapshot/03_branch_geometry/` | 保存 run57 实际使用的 soft-curve 几何状态 | **否** | 是，回归 fixture | 高 |
| `run57_smooth_candidate_filter/04_terminal_lineart/` 中 5 个 `terminal_lineart.svg`、5 个 `terminal_lineart_preview.png`、5 个 `terminal_render.json`、manifest 和 contact sheet | 是，第一批 | `tests/fixtures/reference_only/run57_snapshot/04_terminal_lineart/` | 保存当前最佳输出、指标与逐原型视觉对照 | **否** | 是，回归 fixture | **极高**；严禁反向作为生成输入 |

不迁移上述目录中的 `parallel/`、逐阶段 preview PNG 和重复 contact sheet；只保存唯一、可解释的主快照。

注意：run57 输出时间早于部分当前源码的最后修改时间，空 Git 历史无法恢复输出当日的精确源码提交。因此第一阶段应同时冻结“当前代码 + 历史阶段快照”，后续以重新从 baseline 运行并对比快照来建立新的可复现基线，不能宣称现有源码已被证明能逐字节复现历史 run57。

## 4. 历史 run57 精确方法字节码

只读审查发现 `newpipe/__pycache__/` 中保留了 6 个历史 Python 3.11 字节码；其中终端 renderer 的 pyc 源时间为 `2026-06-10 22:33:28`，与 run57 生成时段一致。它已迁移到：

`legacy/run57_exact/runtime/*.pyc`

| 是否迁移 | 迁移到哪里 | 为什么 | 可作正式输入 | 只作 reference | 污染风险 |
|---|---|---|---|---|---|
| 是，6 个 pyc | `legacy/run57_exact/runtime/` | 当前 `.py` 已于 6 月 16–17 日修改；历史 pyc 是唯一发现的精确 run57 方法实现 | 否；它是 Python 3.11 限定的取证执行物 | 是，直到恢复可维护源码 | 高；禁止进入 `src/` 或默认入口 |

复现结果见 `RUN57_REPRODUCTION_TEST.md`：5/5 SVG 和 5/5 PNG 与历史 run57 的 SHA-256 完全一致。

## 第一批边界结论

- MMKG、论文实验、扩散、LoRA、pix2pix、ControlNet、历史 archive、报告/PPT、临时依赖都不是第一批运行依赖。
- run57 的 SVG/JSON 随方法迁移为回归结果证据，但不是输入数据。
- 本清单不授权复制；实际迁移前仍需逐文件核对许可证、相对导入与硬编码路径。
