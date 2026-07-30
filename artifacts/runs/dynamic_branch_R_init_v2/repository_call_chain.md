# 动态 BranchUnit R v2：真实仓库调用链

## 总览

当前主链不是单文件生成器，而是带摘要链与人工门的分阶段流水线：

```text
skeleton_profile.json
  -> strict_p0_v2.load_strict_p0_v2
  -> run_stage1_inputs
  -> strict_p0_v2.json
  -> run_stage2_analysis
  -> prototype_analysis.analyze_prototype
  -> prototype_analysis.json
  -> run_stage3b_l1_flow
  -> global_l1_flow.generate_global_l1_flow_plan
  -> global_l1_flow_plan.json + candidate inventory
  -> run_stage4_unit_candidates
  -> branch_unit_grammar_v1.generate_unit_candidate_inventory
  -> complete BranchUnit candidates
  -> run_stage5_global_selection
  -> stage5_global_unit_selection.select_global_units
  -> SVG / PNG / JSON / diagnostics
```

## 1. StrictP0

- 文件：`experiments/branch_unit/dynamic/strict_p0_v2.py`
- 入口：`load_strict_p0_v2`、`load_materialized_strict_p0_v2`
- 调用者：`run_stage1_inputs.py`、`run_stage2_analysis.py`
- 输入：五种原型的 `skeleton_profile.json`
- 白名单数据：repeat local frame、主藤弧长采样及切线、花位椭圆、结构保护区
- 输出：`artifacts/runs/dynamic_branch_stage1_inputs_v1/<prototype>/strict_p0_v2.json`
- 当前职责：隔离旧 branch/growth-region/region-graph 字段，建立规范化输入与 digest。
- R 线计划：不修改 StrictP0；区域计划继续只从这条受控几何链读取主藤、花位、保护区与 seam。

## 2. prototype_analysis

- 文件：`experiments/branch_unit/dynamic/prototype_analysis.py`
- 入口：`analyze_prototype`
- 调用者：`run_stage2_analysis.run`
- 输入：materialized StrictP0
- 输出：主藤峰谷、空间探针、连续空白/拥挤区、L1 可挂接区间、花位关系、禁入区、seam 分析及 `analysis_digest`
- 当前区域机制：
  - `_space_probes` 沿主藤两侧探测 clearance；
  - `_l1_mount_regions` 将连续探针折算为可挂接弧长区间；
  - `derive_loop_growth_region` 围绕花位按角度做径向探测，输出 role-neutral 花缘空间、入口距离范围和宽度样本。
- 当前局限：没有 support/wrap/balance/settle 的独立入口、完整引导路径、退出方向、容量与相互嵌合。
- R 线计划：R2B 在现有分析数据流内部生成 role-aware soft corridors；禁止独立 CLI，禁止读取候选曲线或 Stage 5。

## 3. global_l1_flow / Stage 3B

- 文件：`experiments/branch_unit/dynamic/global_l1_flow.py`
- 入口：`generate_global_l1_flow_plan`
- 调用者：`run_stage3b_l1_flow.run`
- 输入：StrictP0、PrototypeAnalysis、morphology profile、fixed visual prior、Stage3B contract、seed
- 输出：`global_l1_flow_plan.json`、完整 L1 candidate inventory、SVG/PNG/三重复调试图
- 当前分支生成：
  - `_make_slots` 先生成 SW1 `flower_support` 或 SW3 `terminal_flower_support`，其余为 generic ordinary/balance/frontier；
  - `_ordinary_candidates` 从 Stage 2 可挂接区间选择根节点，再用长度、法向量和切向符号构造目标与 Hermite 段；
  - `_sw1_support_candidates` 使用波谷加固定 offset，并使用固定花下 waypoint；
  - `_sw3_support_candidates` 使用固定远端弧长距离组合和固定 waypoint 组合；
  - `_fixed_warp_candidates` 对 `proto_sw_1_3` 读取 seed 对应的固定 prior cubics；
  - `_candidate_rejections` 后验拒绝；
  - `_solve` 使用确定性 beam set solver，在完整 L1 状态中按 individual、pair 和 global score选取最佳保留状态。
- 当前区域接入：`attach_loop_growth_guide` 接受已经存在的 `terminal_flower_support` lane；support guide 直接复制该 lane centerline，再由 role-neutral 径向区域构造 `flower_wrap_channel`。
- R 线计划：
  - R1 复验并只在新合同不足时修复 L1 基础运动；
  - R2A 引入冻结 family topology；
  - R2B 先冻结 role region plan；
  - R2C/R2D 让独立 L1 候选完整消费区域；
  - R3/R4 在同一 Stage3B 求解链中增加核心枝组、剩余容量、balance、ordinary 与 settle。

## 4. branch_unit_grammar / Stage 4

- 文件：`experiments/branch_unit/dynamic/branch_unit_grammar_v1.py`
- 入口：`generate_unit_candidate_inventory`
- 调用者：`run_stage4_unit_candidates.run`
- 输入：已批准 Stage3B plan、PrototypeAnalysis、fixed visual prior、grammar contract
- 输出：每条 L1 lane 的完整候选 BranchUnit、parent graph、intrinsic diagnostics、candidate digest
- 当前职责：
  - `_candidate_strata` 为 ordinary/balance 默认枚举 `Y-C` 与 `Y-2C`；
  - `_l1_curve` 固化 Stage3B L1；
  - `_build_candidate` 编译 L2/L3；
  - `_compile_guide_following_child_curve` 将 flower wrap 明确编译为 `level=L2`、`parent_curve_id=<support L1>`。
- 当前错误拓扑：旧 R2 的 `TerminalSupport-Wrap` 把包花作为 SW3 support 的 L2；SW1 的 `flower_support` 也默认把 child semantic role 写为 `flower_wrap`。
- R 线计划：R2A 停用核心 wrap-as-L2；R5 才恢复具有功能理由的普通 L2/L3。

## 5. stage5_global_unit_selection

- 文件：`experiments/branch_unit/dynamic/stage5_global_unit_selection.py`
- 入口：`build_conflict_graph`、`select_global_units`
- 调用者：`run_stage5_global_selection.run`
- 输入：Stage4 candidate inventory、conflict graph、Stage5 contract
- 输出：每 lane 一个候选的全局组合、选择 digest、PNG/三重复 PNG 和 solver trace
- 当前职责：读取 intrinsic `valid` 过滤候选，按 role stratum priority 排序，深度优先回溯。
- 当前停止条件：递归搜索在第一组完整合法 assignment 返回 `True`，`stopped_at_first_complete_legal_assignment` 被写为 `true`，没有 composite visual score。
- R 线计划：R6 搜索全部合法组合或具有最优性保证的等价空间，记录七项拆分分数，并在固定小案例与 exhaustive best 对齐。

## 6. 输出与诊断

- Stage2：`prototype_analysis.json/svg/png`
- Stage3B：L1 plan、candidate inventory、single/debug/three-repeat SVG/PNG
- Stage4：candidate inventory、role grammar atlas、诊断
- Stage5：conflict graph、selection JSON、single/triple previews
- R v2：在不建立平行生成系统的前提下，为每阶段增加独立重算指标、失败图、anti-shortcut audit、digest 与冻结验收报告。
