# Paper A 第4章结果导航

本目录保存 Paper A 第4章的冻结协议、正式原始结果、统计汇总、论文案例和人工评价材料。实验方法与案例在 `ds` 分支冻结，正式结果提交为 [`2c15c9e`](https://github.com/JimeiHaoD1/porcelain-pattern-gen/commit/2c15c9e4416f1468e3968f05a2791283e4e81ea0)。

完整的执行过程、指标解释与结果边界见 [实验操作总结与结果指引](https://github.com/JimeiHaoD1/porcelain-pattern-gen/blob/ds/experiments/branch_unit/paper_a_evaluation/CHAPTER4_EXPERIMENT_OPERATION_SUMMARY_AND_RESULTS_GUIDE_V1.md)。实验代码位于 [paper_a_evaluation](https://github.com/JimeiHaoD1/porcelain-pattern-gen/tree/ds/experiments/branch_unit/paper_a_evaluation)。

## 最短查阅路径

| 研究问题 | 首选结果 | 辅助材料 |
|---|---|---|
| 冻结协议 | [protocol.json](./protocol/protocol.json) | [frozen_cases.csv](./protocol/frozen_cases.csv)、[metric_parameters.csv](./protocol/metric_parameters.csv) |
| RQ1 总体合法性与稳定性 | [summary.csv](./rq1/summary.csv) | [raw_results.csv](./rq1/raw_results.csv)、[failure_cases.csv](./rq1/failure_cases.csv)、[成功案例](./rq1/examples_success)、[失败案例](./rq1/examples_failure) |
| RQ2 核心机制消融 | [summary.csv](./rq2/summary.csv) | [paired_case_metrics.csv](./rq2/paired_case_metrics.csv)、[computational_overhead.csv](./rq2/computational_overhead.csv)、[failure_cases.csv](./rq2/failure_cases.csv)、[图7案例](./rq2/examples_success) |
| RQ3 可控性与多样性 | [summary.csv](./rq3/summary.csv) | [raw_results.csv](./rq3/raw_results.csv)、[figure_data.csv](./rq3/figure_data.csv)、[图8案例](./rq3/examples_control) |
| RQ4 真实结构参照 | [reference_manifest_adjudicated.csv](./rq4/reference_manifest_adjudicated.csv) | [summary.csv](./rq4/summary.csv)、[metric_comparability.csv](./rq4/metric_comparability.csv)、[图9状态](./rq4/figure_data.csv)、[真实样本预览](./rq4/reference_previews) |
| RQ4 人工评价 | [human_evaluation](./rq4/human_evaluation) | [rating_codebook.csv](./rq4/human_evaluation/rating_codebook.csv)、[participant_assignments.csv](./rq4/human_evaluation/participant_assignments.csv)、[ratings_raw.csv](./rq4/human_evaluation/ratings_raw.csv)、[盲评图](./rq4/human_evaluation/blind_images) |

## 论文图素材

- 图6：[`rq1/examples_success`](./rq1/examples_success)，案例索引为 [`rq1/figure_examples.csv`](./rq1/figure_examples.csv)。
- 图7：[`rq2/examples_success`](./rq2/examples_success)，案例索引为 [`rq2/figure_examples.csv`](./rq2/figure_examples.csv)。
- 图8：[`rq3/examples_control`](./rq3/examples_control)，案例索引为 [`rq3/figure_examples.csv`](./rq3/figure_examples.csv)。
- 图9：当前状态记录在 [`rq4/figure_data.csv`](./rq4/figure_data.csv)。由于独立真实参照数为 0，正式分布检验未运行。

## 完整原始证据

- `Ours` 的 500 个正式案例：[rq1_rq3/formal_ours/raw_cases](./rq1_rq3/formal_ours/raw_cases)。
- 四方法的 90 个共享消融上下文：[rq2/matrix_c_four_methods/raw_cases](./rq2/matrix_c_four_methods/raw_cases)。
- Matrix-C 运行记录：[rq2/matrix_c_four_methods/raw_results.csv](./rq2/matrix_c_four_methods/raw_results.csv)。

原始证据目录包含大量 JSON、PNG 和 SVG。论文写作应先读取各 RQ 的 `summary.csv` 与 `figure_examples.csv`，只有核对具体案例或选择过程时才进入 `raw_cases`。

## 当前边界

RQ1、RQ2 和 RQ3 已完成正式运行。RQ4 已完成描述性真实结构统计与盲评材料准备，仍需两项外部输入：独立且可追溯的真实结构 SVG，以及参与者实际评分。空白评分表不是实验结果。
