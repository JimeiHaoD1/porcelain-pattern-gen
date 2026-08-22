# Paper A 第4章 GitHub 证据阅读指引（网页版 GPT 专用）

## 1. 你的任务

请基于本指引中的 GitHub 代码、CSV、SVG、PNG 和实验协议，核对并协助撰写 Paper A 第4章。工作重点是把论文中的方法描述、实验设置、定量结果和图表解释与真实证据对应起来。

正式生成方法已经冻结。后续写作应使用现有证据，不再设计新生成规则，也不因个别失败案例改动生成器。失败案例属于 RQ1 和 RQ2 的实验结果。

仓库与版本：

- 仓库：[JimeiHaoD1/porcelain-pattern-gen](https://github.com/JimeiHaoD1/porcelain-pattern-gen)
- 分支：[`ds`](https://github.com/JimeiHaoD1/porcelain-pattern-gen/tree/ds)
- 正式实验结果提交：[`2c15c9e`](https://github.com/JimeiHaoD1/porcelain-pattern-gen/commit/2c15c9e4416f1468e3968f05a2791283e4e81ea0)
- 结果总目录：[artifacts/paper_a_chapter4_v1](https://github.com/JimeiHaoD1/porcelain-pattern-gen/tree/ds/artifacts/paper_a_chapter4_v1)
- 实验操作总结：[CHAPTER4_EXPERIMENT_OPERATION_SUMMARY_AND_RESULTS_GUIDE_V1.md](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/paper_a_evaluation/CHAPTER4_EXPERIMENT_OPERATION_SUMMARY_AND_RESULTS_GUIDE_V1.md)

## 2. 冻结的方法身份

Paper A 研究的是二方连续缠枝纹的可控程序化结构生成。正式生产链为：

```text
原型选择
→ 主干变体
→ 花位与承花关系
→ 普通 L1 候选生成
→ density control
→ BranchUnit 候选构建
→ H2-B 联合全局组合
→ 周期结构 SVG
```

论文中的方法身份按以下规则保持一致：

- `Ours`：H2-B 联合 BranchUnit 组合，是正式方法。
- H2-A：保留为普通 `density control`，不作为单独的核心贡献。
- `LocalGreedy`：顺序、不可逆的局部 BranchUnit 选择。
- `IndependentCurve`、`FixedSlot`、`LocalGreedy`、`Ours`：四个固定消融名称，不改名，不合并。

## 3. 推荐阅读顺序

### 第一步：建立实验全貌

先阅读两份总览：

1. [GitHub 结果首页](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/README.md)
2. [实验操作总结与结果指引](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/paper_a_evaluation/CHAPTER4_EXPERIMENT_OPERATION_SUMMARY_AND_RESULTS_GUIDE_V1.md)

两份文档说明实验矩阵、执行顺序、核心结果、文件位置和剩余外部输入。

### 第二步：确认冻结协议

读取：

- [protocol.json](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/protocol/protocol.json)
- [frozen_cases.csv](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/protocol/frozen_cases.csv)
- [metric_parameters.csv](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/protocol/metric_parameters.csv)

三套冻结矩阵为：

| 矩阵 | 案例数 | 用途 |
|---|---:|---|
| Matrix-A | 450 | RQ1 稳定性；RQ3 主干与密度控制 |
| Matrix-B | 50 | RQ3 固定条件下的种子多样性 |
| Matrix-C | 90 | RQ2 四方法消融；RQ4 人工评价刺激 |

`protocol.json` 中的 `FROZEN_INPUTS_PENDING_EXECUTION` 是协议冻结时写入的状态。正式执行结果由各运行目录的 `run_manifest.json` 和结果 CSV 记录。

### 第三步：逐个核对 RQ

#### RQ1：总体结构合法性与稳定性

优先读取：

- [RQ1 汇总](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq1/summary.csv)
- [RQ1 原始结果](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq1/raw_results.csv)
- [RQ1 失败案例](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq1/failure_cases.csv)
- [RQ1 图6成功案例](https://github.com/JimeiHaoD1/porcelain-pattern-gen/tree/ds/artifacts/paper_a_chapter4_v1/rq1/examples_success)
- [RQ1 代表失败案例](https://github.com/JimeiHaoD1/porcelain-pattern-gen/tree/ds/artifacts/paper_a_chapter4_v1/rq1/examples_failure)

核心事实：

- 450/450 个案例生成成功，生成成功率为 1.000。
- 生成成功率的 Wilson 95% 区间为 `[0.9915, 1.0000]`。
- 436/450 个案例通过全部独立机械检查，机械合法率为 0.9689。
- 机械合法率的 Wilson 95% 区间为 `[0.9485, 0.9814]`。
- 14 个机械失败案例由 6 个 Unit 内部相交案例、2 个普通 L1 非根部接触主干案例和 6 个花位区域侵入案例构成。
- Unit 间相交、普通枝与承花枝相交、周期副本相交、净空违规和周期接缝违规均为 0。

RQ1 支持“系统能够稳定生成，且多数输出满足冻结机械约束”。RQ1 不支持“所有输出完全合法”或“零失败”。

#### RQ2：核心结构机制消融

优先读取：

- [RQ2 配对汇总](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq2/summary.csv)
- [RQ2 每案例配对指标](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq2/paired_case_metrics.csv)
- [RQ2 计算开销](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq2/computational_overhead.csv)
- [RQ2 失败清单](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq2/failure_cases.csv)
- [RQ2 图7案例](https://github.com/JimeiHaoD1/porcelain-pattern-gen/tree/ds/artifacts/paper_a_chapter4_v1/rq2/examples_success)

生成结果：

| 方法 | L1 成功 | 完整 Unit 成功 |
|---|---:|---:|
| `IndependentCurve` | 90/90 | 不适用 |
| `FixedSlot` | 70/90 | 69/90 |
| `LocalGreedy` | 90/90 | 90/90 |
| `Ours` | 90/90 | 90/90 |

主要配对证据：

- 相比 `IndependentCurve`，`Ours` 的根位覆盖率配对中位差为 `+0.2121`，bootstrap 95% CI 为 `[+0.1515, +0.2424]`。
- 相比 `IndependentCurve`，`Ours` 的 L1 最小净空配对中位差为 `+0.0601`，bootstrap 95% CI 为 `[+0.0531, +0.0703]`。
- 相比 `FixedSlot`，`Ours` 的根位覆盖率配对中位差为 `+0.0612`，bootstrap 95% CI 为 `[+0.0315, +0.0759]`。
- 相比 `LocalGreedy`，`Ours` 的峰值平行伴行配对中位差为 `-0.0944`，bootstrap 95% CI 为 `[-0.1169, -0.0505]`。
- 相比 `LocalGreedy`，`Ours` 的总平行伴行配对中位差为 `-0.1285`，bootstrap 95% CI 为 `[-0.1673, -0.0856]`。

`IndependentCurve` 是 L1-only baseline，因此不应为它填写完整 Unit 成功率。`FixedSlot` 的失败是消融结果，应保留在 90 个计划上下文的分母中。

#### RQ3：可控性与有效多样性

优先读取：

- [RQ3 汇总](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq3/summary.csv)
- [RQ3 原始结果](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq3/raw_results.csv)
- [RQ3 绘图数据](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq3/figure_data.csv)
- [RQ3 图8案例](https://github.com/JimeiHaoD1/porcelain-pattern-gen/tree/ds/artifacts/paper_a_chapter4_v1/rq3/examples_control)

核心事实：

- 500/500 条 RQ3 记录生成成功。
- `simple ≤ medium ≤ rich` 时，密度资源量、L1 数量和 BranchUnit 数量的单调比例均为 1.000。
- L2 数量的单调比例为 0.7867，普通枝总长度为 0.8867，占用面积为 0.7800，根位覆盖率为 0.7267。
- 每个原型的 10 个种子均产生 10 个不同结构签名。
- 五个原型的平均成对 Gower 结构距离依次为 0.1668、0.1512、0.0842、0.1570 和 0.1208。

密度控制的直接目标是资源量与结构数量。普通枝平均长度、主干偏移量和垂直跨度属于伴随变化量，不应描述为严格随密度单调增长。

#### RQ4：真实结构参照与人工评价

优先读取：

- [真实参照资格裁决](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq4/reference_manifest_adjudicated.csv)
- [真实与生成结构汇总](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq4/summary.csv)
- [指标可比性](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq4/metric_comparability.csv)
- [图9状态](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq4/figure_data.csv)
- [人工评价材料](https://github.com/JimeiHaoD1/porcelain-pattern-gen/tree/ds/artifacts/paper_a_chapter4_v1/rq4/human_evaluation)
- [评分维度](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/artifacts/paper_a_chapter4_v1/rq4/human_evaluation/rating_codebook.csv)

现有 8 个真实标注 SVG 参与过方法校准，并且缺少显式父子关系元数据。它们的正式身份是 `DESCRIPTIVE_ONLY_CALIBRATION_INFORMED`。这些样本支持描述性结构统计，不进入独立假设检验。

人工评价已经准备 90 张盲图、270 条盲码、450 条参与者任务分配和 1350 条评分记录模板。`ratings_raw.csv` 尚无真实参与者评分，人工评价结果处于待回收状态。

RQ4 当前可写内容包括真实样本的描述性结构统计、指标可比性裁决和人工评价设计。正式分布检验与人工评分结果将在取得独立真实 SVG 和参与者评分后补入。

## 4. 方法代码核对入口

先阅读工程交接与机制总览：

- [PAPER_A_ENGINEERING_HANDOFF_V1.md](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/PAPER_A_ENGINEERING_HANDOFF_V1.md)
- [DYNAMIC_BRANCHUNIT_OPTIMIZATION_MECHANISM_V1.md](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/DYNAMIC_BRANCHUNIT_OPTIMIZATION_MECHANISM_V1.md)

生产主链与合同：

| 机制 | 代码或合同 |
|---|---|
| 严格 P0 与周期局部坐标 | [strict_p0_v2.py](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/strict_p0_v2.py) |
| 普通 L1 候选、根位与净空求解 | [global_l1_flow.py](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/global_l1_flow.py) |
| Stage3B 正式入口 | [run_stage3b_l1_flow.py](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/run_stage3b_l1_flow.py) |
| 密度控制合同 | [STAGE3B_L1_FLOW_CONTRACT_V3.json](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/STAGE3B_L1_FLOW_CONTRACT_V3.json) |
| BranchUnit 候选构建 | [run_edit_feedback_branch_units_v2.py](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/run_edit_feedback_branch_units_v2.py) |
| BranchUnit 语法合同 | [STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json) |
| H2-B 联合全局组合 | [STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json) |
| 正式全原型输出 | [run_stage5f_full_integration.py](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/run_stage5f_full_integration.py) |
| NumPy 批处理几何 | [geometry_batch.py](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/dynamic/geometry_batch.py) |

第4章实验代码集中在 [paper_a_evaluation](https://github.com/JimeiHaoD1/porcelain-pattern-gen/tree/ds/experiments/branch_unit/paper_a_evaluation)。其中 `evaluate_formal_cases.py` 从保存的正式几何独立重算机械指标；`run_matrix_c.py` 构造共享上游条件下的四方法消融；三个 `summarize_*.py` 负责论文统计汇总。

## 5. 论文写作时的证据规则

1. 结果数字以各 RQ 的 `summary.csv` 为准，案例级追溯使用 `raw_results.csv` 和 `raw_cases`。
2. 机械合法性来自独立几何评估，不读取生成器自报的 `pass` 或 `valid` 字段作为结论。
3. 失败案例保留在原计划分母中，正文与表格使用同一分母。
4. 图6、图7和图8使用已冻结的 `figure_examples.csv`，不根据画面结果重新挑选更有利案例。
5. 论文将 H2-B 写为联合全局 BranchUnit 组合，将 H2-A 写为密度控制。
6. RQ4 的 8 个真实样本只承担描述性参照角色。正式真实分布比较与人工评分仍待外部输入。

## 6. 建议输出格式

完成阅读后，请按四部分输出：

1. **方法与代码对照表**：论文方法术语、正式代码入口、关键数据对象、最终输出。
2. **RQ1 至 RQ4 证据表**：研究问题、实验矩阵、样本量、指标、核心结果、对应文件。
3. **第4章写作材料**：实验设置、定量结果、图表解释和限制边界，所有数字附 GitHub 文件位置。
4. **待补数据清单**：仅列独立真实结构 SVG 与真实人工评分，不扩展新的生成器实验。

如果论文草稿中的数字、方法名或样本量与本指引冲突，以冻结协议、正式 CSV 和生产代码为准，并逐项指出冲突位置。
