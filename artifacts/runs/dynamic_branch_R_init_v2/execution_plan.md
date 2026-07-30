# 动态 BranchUnit R v2：执行计划

## 每阶段固定循环

1. 完整复读三份冻结文件并重算 SHA256。
2. 记录阶段起点 commit。
3. 写 `stage_change_plan.json`，只列冻结白名单内文件。
4. 生成修改前案例、指标、图和 digest。
5. 实施当前阶段最小机制修改。
6. 运行目标矩阵并生成 metrics、failures、overlay 和 contact sheet。
7. 用独立几何/拓扑测量器执行冻结验收。
8. 执行 anti-shortcut audit。
9. 失败先写 `failure_hypothesis.json`，留在本阶段修复。
10. 通过后再次复验冻结 SHA、提交 checkpoint 并自动进入下一阶段。

## R0

- 复用旧 runner 的只读测量思想，但输出到 `dynamic_branch_R0_v2`。
- 覆盖五原型 × 三 seed，连续运行两次。
- 冻结 Stage2、Stage3B、Stage4、Stage5 当前结果和失败索引。
- 不修改生成逻辑。

## R1

- 先用新冻结合同重验现有 `tangent_led_v1`。
- 若任一指标失败，仅在 `global_l1_flow.py`、runtime contract、诊断和 R1 测试内修复。
- 同时验证控制点、起始导数、完整路径边界、交叉、根密度和 `proto_sw_3_2` 竖直长廊。

## R2A

- 加载冻结 family topology。
- SW1 创建 support/wrap/balance 独立 L1 槽；SW3 创建 remote_support/balance 且无 forced wrap；SW2 保持 axis family。
- 停用核心 wrap-as-L2，但不删除普通 L2 能力。

## R2B

- 固定 `proto_sw_1_1/4101/一个花位`。
- 在现有 `prototype_analysis -> global_l1_flow` 数据链内，先构造局部 frame、硬禁入区、入口、guide、tangents、width、boundary、interlock、capacity 和 digest。
- 只输出区域，不生成新增 branch curve。
- 区域视觉图不过不得进入 R2C。

## R2C

- 读取并冻结 R2B plan。
- 每个 support/wrap region 至少生成三候选、至少两种 geometry digest。
- 两根曲线均为独立 L1，分别完整消费 entry/guide/tangents/width/target/exit/capacity。

## R2D

- 固定 `proto_sw_3_1/4101/support_1`。
- 只生成一根独立 remote_support L1；无 wrap/L2/L3/balance/ordinary/terminal。

## R3

- 按 family 顺序规划核心服务区、已占用空间、剩余容量和 balance。
- SW2 只走 axis family。

## R4

- 将核心枝组、balance、必要 ordinary 和 settle 纳入 Stage3B 单元级兼容性与全局评分。
- Stage3B 自己解决 L1 冲突、密度、上下重量、空白、末端和 seam；Stage5 deletion count 必须为零。

## R5

- 恢复 role-aware L2/L3。
- ordinary/balance 至少有 L1-only 和 single-L2；Y-2C 不再默认。
- 每个 descendant 具有允许的 functional reason 与空间容量证据。

## R6

- 按冻结原型顺序逐一推进，每个先 4101，再 4102/4103。
- 搜索最高 composite score 的合法组合。
- 对 `proto_sw_3_1/4101` 与 exhaustive best 对齐。

## 最终

- 生成完整最终目录、CSV/JSON、五原型三 seed contact sheets、区域 contact sheet、复现命令与架构变更说明。
- 运行完整回归和冻结哈希复验。
- 只有所有阶段、反捷径、产物、回归与工作树条件同时满足才宣布 `overall_status=PASSED`。
