# Paper A 第4章实验操作总结与结果指引 V1

## 1. 本轮交付状态

本轮完成了 Paper A 第4章的正式实验执行、独立几何评估、结果汇总、论文案例整理和人工评价材料准备。正式方法保持冻结状态：`Ours` 对应 H2-B 联合 BranchUnit 组合；H2-A 仅作为普通 `density control`。本轮没有修改生产生成器，也没有在正式运行后针对失败案例补规则或替换种子。

冻结协议共含 590 个案例：Matrix-A 450 个，Matrix-B 50 个，Matrix-C 90 个。实际得到 500 条 `Ours` 正式生成记录和 360 条四方法消融记录。所有计划案例均保留在分母中。

当前可以直接用于论文第4章的内容包括 RQ1、RQ2、RQ3 的定量结果和图例，以及 RQ4 的描述性真实结构统计与完整盲评材料。RQ4 的正式真实参照检验和人工评分汇总仍需外部数据，因此没有生成虚构结果。

## 2. 冻结实验设计

| 矩阵 | 规模 | 变量 | 用途 |
|---|---:|---|---|
| Matrix-A | 450 | 5 个原型 × 3 个主干变体 × 3 个密度档 × 10 个种子 | RQ1 稳定性；RQ3 主干与密度控制 |
| Matrix-B | 50 | 5 个原型 × 10 个种子，固定 `expanded + medium` | RQ3 种子多样性 |
| Matrix-C | 90 | 5 个原型 × 3 个主干变体 × 3 个密度档 × 2 次重复 | RQ2 四方法消融；RQ4 人工评价刺激 |

四个方法名称及边界保持不变：

| 方法 | 实验含义 |
|---|---|
| `IndependentCurve` | 从同一普通 L1 候选池按单曲线分数选择，仅评价 L1，不生成完整 Unit |
| `FixedSlot` | 使用旧固定槽位式普通 L1 入口，匹配 `Ours` 的 L1 数量，不做修复或重采样 |
| `LocalGreedy` | 与 `Ours` 共享 Stage3B 计划和 Stage4 候选库存，先选 L1，再不可逆地局部升级 L2 |
| `Ours` | H2-B 联合 BranchUnit 组合，在共享候选库存上进行全局选择 |

冻结协议位于 `artifacts/paper_a_chapter4_v1/protocol/`。其中 `protocol.json` 的 `FROZEN_INPUTS_PENDING_EXECUTION` 记录的是冻结时点，不是当前执行状态；实际完成状态以各运行目录的 `run_manifest.json` 和正式 CSV 为准。

## 3. 本轮代码入口

所有第4章入口位于 `experiments/branch_unit/paper_a_evaluation/`：

| 文件 | 作用 |
|---|---|
| `freeze_protocol.py` | 冻结三套案例矩阵、种子、度量参数和真实参照清单 |
| `run_formal_cases.py` | 执行 Matrix-A 和 Matrix-B 的 `Ours` 正式生成 |
| `evaluate_formal_cases.py` | 从保存的正式几何独立重算机械合法性和结构指标 |
| `run_matrix_c.py` | 在共享上游条件下执行四方法 Matrix-C 消融 |
| `summarize_rq1_rq3.py` | 汇总 RQ1、RQ3，并计算 Wilson 区间、单调性和结构距离 |
| `summarize_rq2.py` | 汇总配对消融、bootstrap 置信区间、失败案例和计算开销 |
| `audit_real_references.py` | 审核真实 SVG 的来源独立性、角色语义和可比指标 |
| `prepare_human_study.py` | 生成随机盲化图、循环位置分配、评分表和评分说明 |
| `summarize_human_study.py` | 在真实评分回填后执行参与者层面的统计汇总 |
| `prepare_chapter4_examples.py` | 按预先固定的案例规则整理图6、图7、图8素材 |

`experiments/branch_unit/h2_adjudication/` 保存 H2 裁决代码与历史对照产物。它用于说明 H2-B 的冻结来源，不应再扩展成新的 H2-A 专项实验。

## 4. 本轮实际执行链

以下命令从仓库根目录 `D:\sdxl\chanzhi_sw_clean_oldmain_opt` 执行。正式批量生成使用 8 个 CPU worker。

```powershell
python experiments\branch_unit\paper_a_evaluation\freeze_protocol.py

python experiments\branch_unit\paper_a_evaluation\run_formal_cases.py `
  --matrix A --matrix B --workers 8 `
  --output-dir artifacts\paper_a_chapter4_v1\rq1_rq3\formal_ours

python experiments\branch_unit\paper_a_evaluation\evaluate_formal_cases.py `
  --run-dir artifacts\paper_a_chapter4_v1\rq1_rq3\formal_ours

python experiments\branch_unit\paper_a_evaluation\summarize_rq1_rq3.py

python experiments\branch_unit\paper_a_evaluation\run_matrix_c.py `
  --workers 8 `
  --output-dir artifacts\paper_a_chapter4_v1\rq2\matrix_c_four_methods

python experiments\branch_unit\paper_a_evaluation\summarize_rq2.py
python experiments\branch_unit\paper_a_evaluation\audit_real_references.py
python experiments\branch_unit\paper_a_evaluation\prepare_human_study.py
python experiments\branch_unit\paper_a_evaluation\prepare_chapter4_examples.py
```

完整重跑时应使用新的 `--output-dir`，保留本轮正式结果不变。只需重建汇总表或论文案例时，直接运行对应的 `summarize_*.py` 或 `prepare_chapter4_examples.py`，无需重新生成 500 个正式案例。

## 5. RQ1：总体结构合法性与稳定性

Matrix-A 的 450 个案例全部生成成功，生成成功率为 1.000，Wilson 95% 区间为 `[0.9915, 1.0000]`。独立机械评估判定 436 个案例满足全部已列机械约束，比例为 0.9689，Wilson 95% 区间为 `[0.9485, 0.9814]`。

14 个失败案例按原计划保留：

| 机械问题 | 事件数 | 案例数 |
|---|---:|---:|
| Unit 内部相交 | 7 | 6 |
| 普通 L1 与主干发生非根部接触 | 2 | 2 |
| 普通曲线侵入花位区域 | 6 | 6 |
| Unit 之间相交 | 0 | 0 |
| 普通枝与承花枝相交 | 0 | 0 |
| 周期副本相交 | 0 | 0 |
| 净空违规 | 0 | 0 |
| 周期接缝违规 | 0 | 0 |

正式方法的平均 L1 数量为 5.589，平均 L2 数量为 1.696。完整单周期生产链的单案例运行时间中位数为 24.849 秒；L1 候选数中位数为 1352.5，BranchUnit 候选数中位数为 150，全局搜索节点数中位数为 361。450 个案例均未触及搜索节点上限。

结果入口：

- 主表：`artifacts/paper_a_chapter4_v1/rq1/raw_results.csv`
- 分组汇总与置信区间：`artifacts/paper_a_chapter4_v1/rq1/summary.csv`
- 失败案例：`artifacts/paper_a_chapter4_v1/rq1/failure_cases.csv`
- 论文表格数据：`artifacts/paper_a_chapter4_v1/rq1/figure_data.csv`
- 图6成功案例：`artifacts/paper_a_chapter4_v1/rq1/examples_success/`
- 三类代表失败：`artifacts/paper_a_chapter4_v1/rq1/examples_failure/`
- 每例完整生成几何：`artifacts/paper_a_chapter4_v1/rq1_rq3/formal_ours/raw_cases/`

## 6. RQ2：核心结构机制消融

Matrix-C 完成 90 个共享上下文和 360 条方法记录。

| 方法 | L1 成功 | 完整 Unit 成功 | 说明 |
|---|---:|---:|---|
| `IndependentCurve` | 90/90 | 不适用 | 冻结为 L1-only baseline |
| `FixedSlot` | 70/90 | 69/90 | 失败种子不替换 |
| `LocalGreedy` | 90/90 | 90/90 | 与 `Ours` 共享 Stage4 对象 |
| `Ours` | 90/90 | 90/90 | H2-B 联合组合 |

主要配对统计如下，差值方向均为 `Ours - baseline`：

| 比较 | 指标 | 配对中位差 | bootstrap 95% CI |
|---|---|---:|---:|
| `Ours` vs `IndependentCurve` | 根位覆盖率 `Qcov` | +0.2121 | `[+0.1515, +0.2424]` |
| `Ours` vs `IndependentCurve` | L1 最小净空 | +0.0601 | `[+0.0531, +0.0703]` |
| `Ours` vs `FixedSlot` | 根位覆盖率 `Qcov` | +0.0612 | `[+0.0315, +0.0759]` |
| `Ours` vs `FixedSlot` | L1 最小净空 | +0.0045 | `[-0.0055, +0.0140]` |
| `Ours` vs `LocalGreedy` | 峰值平行伴行 | -0.0944 | `[-0.1169, -0.0505]` |
| `Ours` vs `LocalGreedy` | 总平行伴行 | -0.1285 | `[-0.1673, -0.0856]` |

`Ours` 与 `LocalGreedy` 的所选父 lane 状态每例中位差异数为 2，说明两种选择策略并非只在元数据上不同。`FixedSlot` 的 21 个完整失败包括 18 个“全局候选池无完整兼容分配”、2 个“指定槽位无可行候选”和 1 个“无完整合法 BranchUnit 组合”。

结果入口：

- 主表：`artifacts/paper_a_chapter4_v1/rq2/raw_results.csv`
- 配对统计：`artifacts/paper_a_chapter4_v1/rq2/summary.csv`
- 每案例配对指标：`artifacts/paper_a_chapter4_v1/rq2/paired_case_metrics.csv`
- 计算开销：`artifacts/paper_a_chapter4_v1/rq2/computational_overhead.csv`
- 失败清单：`artifacts/paper_a_chapter4_v1/rq2/failure_cases.csv`
- 图7数据：`artifacts/paper_a_chapter4_v1/rq2/figure_data.csv`
- 图7案例：`artifacts/paper_a_chapter4_v1/rq2/examples_success/`
- 四方法完整原始对象：`artifacts/paper_a_chapter4_v1/rq2/matrix_c_four_methods/raw_cases/`

图7a 使用 C050，对比 `IndependentCurve`、`FixedSlot` 与 `Ours` 的根位组织；图7b 使用 C083，对比 `LocalGreedy` 与 `Ours` 的平行伴行。

## 7. RQ3：可控性与有效多样性

RQ3 使用 Matrix-A 的 450 条记录分析主干变体和密度控制，使用 Matrix-B 的 50 条记录分析固定条件下的种子差异。500 条记录全部生成成功。

密度从 `simple` 到 `medium` 再到 `rich` 时，150 个配对三元组的单调比例为：

| 指标 | 单调比例 |
|---|---:|
| 密度资源量 `D` | 1.0000 |
| L1 数量 | 1.0000 |
| BranchUnit 数量 | 1.0000 |
| L2 数量 | 0.7867 |
| 普通枝总长度 | 0.8867 |
| 占用面积 | 0.7800 |
| 根位覆盖率 | 0.7267 |

普通枝平均长度、主干偏移量和垂直跨度没有被定义为密度控制目标，其单调比例分别为 0.2533、0.3467 和 0.3867。结果应据此区分“密度直接控制量”和“伴随变化量”。

在固定 `expanded + medium` 条件下，每个原型的 10 个种子均得到 10 个不同的四舍五入结构签名。各原型的平均成对 Gower 结构距离为：

| 原型 | 平均成对结构距离 |
|---|---:|
| `proto_sw_1_1` | 0.1668 |
| `proto_sw_1_3` | 0.1512 |
| `proto_sw_2_3` | 0.0842 |
| `proto_sw_3_1` | 0.1570 |
| `proto_sw_3_2` | 0.1208 |

结果入口：

- 主表：`artifacts/paper_a_chapter4_v1/rq3/raw_results.csv`
- 分层汇总、单调性和种子距离：`artifacts/paper_a_chapter4_v1/rq3/summary.csv`
- 论文绘图数据：`artifacts/paper_a_chapter4_v1/rq3/figure_data.csv`
- 图8案例索引：`artifacts/paper_a_chapter4_v1/rq3/figure_examples.csv`
- 图8主干、密度和种子案例：`artifacts/paper_a_chapter4_v1/rq3/examples_control/`

图8采用预先固定的 P1、P3、P4 和 replicate 1：9 个主干变体案例、9 个密度案例和 12 个种子案例，共 30 个 PNG/SVG 对照。

## 8. RQ4：真实结构参照与人工评价

### 8.1 真实结构参照

现有 8 个真实标注 SVG 均参与过方法规则或参数校准，并且不含显式父子关系元数据。因此本轮将它们判定为 `DESCRIPTIVE_ONLY_CALIBRATION_INFORMED`：保留描述性统计，不用于独立假设检验。

可直接比较的描述性指标包括 L1 数量、L2 数量、L2/L1、归一化总长度、平均长度、垂直跨度和占用面积。根位、根间距、层级状态和上下分配依赖显式父关系，目前只保留探索性推断。

图9的正式分布距离检验状态为 `NOT_RUN_NO_INDEPENDENT_REFERENCE`。当前独立真实样本数为 0，描述性真实样本数为 8，生成侧规范样本数为 50。后续获得独立、可追溯且含父关系的真实结构 SVG 后，才运行正式分布距离与 bootstrap 区间。

结果入口：

- 参照资格裁决：`artifacts/paper_a_chapter4_v1/rq4/reference_manifest_adjudicated.csv`
- 真实结构逐例指标：`artifacts/paper_a_chapter4_v1/rq4/real_reference_raw.csv`
- 真实与生成描述统计：`artifacts/paper_a_chapter4_v1/rq4/summary.csv`
- 指标可比性：`artifacts/paper_a_chapter4_v1/rq4/metric_comparability.csv`
- 图9状态：`artifacts/paper_a_chapter4_v1/rq4/figure_data.csv`
- 8 个真实 SVG 预览：`artifacts/paper_a_chapter4_v1/rq4/reference_previews/`

### 8.2 人工评价材料

人工评价材料已按冻结设计生成：30 个 Matrix-C 上下文，每个上下文包含 `FixedSlot`、`LocalGreedy` 和 `Ours` 三张盲化图。A/B/C 显示位置采用循环平衡，避免方法与固定位置绑定。

材料规模为：

- 90 张盲化刺激图；
- 270 条盲码映射；
- 30 名参与者 × 每人 15 个三图任务，共 450 条任务分配；
- 每张刺激预计获得 15 次评分，A/B/C 三个位置各出现 5 次；
- 3 个评分维度 × 450 个任务，共 1350 条评分记录。

三个冻结评分维度为 `structural_coherence_1_5`、`visual_balance_1_5` 和 `vine_scroll_structural_plausibility_1_5`。Codex 不替参与者判断“更美”或“更像传统纹样”。

结果入口：

- 盲图：`artifacts/paper_a_chapter4_v1/rq4/human_evaluation/blind_images/`
- 盲码密钥：`artifacts/paper_a_chapter4_v1/rq4/human_evaluation/blind_key.csv`
- 参与者任务分配：`artifacts/paper_a_chapter4_v1/rq4/human_evaluation/participant_assignments.csv`
- 评分说明：`artifacts/paper_a_chapter4_v1/rq4/human_evaluation/rating_codebook.csv`
- 待填写评分表：`artifacts/paper_a_chapter4_v1/rq4/human_evaluation/ratings_raw.csv`
- 参与者背景表：`artifacts/paper_a_chapter4_v1/rq4/human_evaluation/participant_background_template.csv`
- 平衡检查：`artifacts/paper_a_chapter4_v1/rq4/human_evaluation/assignment_balance.csv`

评分回填后执行：

```powershell
python experiments\branch_unit\paper_a_evaluation\summarize_human_study.py
```

当前空评分表执行该脚本会明确返回 `PENDING: ratings_raw.csv contains no participant scores`，不会生成伪造的统计结果。

## 9. 最短结果查阅路径

如果只需核对论文第4章，按下列顺序读取：

1. `artifacts/paper_a_chapter4_v1/protocol/protocol.json`：确认方法、矩阵和失败保留规则。
2. `artifacts/paper_a_chapter4_v1/rq1/summary.csv`：填写总体成功率、机械合法率和结构规模。
3. `artifacts/paper_a_chapter4_v1/rq2/summary.csv`：填写四方法消融和配对区间。
4. `artifacts/paper_a_chapter4_v1/rq3/summary.csv`：填写控制单调性和种子结构距离。
5. `artifacts/paper_a_chapter4_v1/rq4/reference_manifest_adjudicated.csv`：限定真实参照的论证边界。
6. `artifacts/paper_a_chapter4_v1/rq4/human_evaluation/rating_codebook.csv`：核对人工评价维度。
7. 各 RQ 的 `figure_examples.csv` 和 `examples_*` 目录：组装图6、图7和图8。

## 10. 后续仅剩的外部输入

第4章尚缺两项外部数据：

1. 一组没有参与方法校准、来源可追溯、最好带显式父子关系的真实结构 SVG，用于 RQ4 正式分布比较和图9。
2. 人工评价的真实回收评分，用于参与者层面的统计汇总。

这两项补齐前，RQ1、RQ2、RQ3 可进入论文写作；RQ4 只能报告描述性真实结构统计、盲评设计和待完成状态。
