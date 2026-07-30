# 动态 BranchUnit 回环区域优化线 R：Codex 总 Goal v2

> 本文件定义执行任务、阶段顺序、允许修改范围和自动执行规则。  
> 所有验收阈值与原型角色拓扑以同目录下的  
> `动态_BranchUnit_回环区域优化线_R_冻结验收合同_v2.md` 为唯一依据。

---

## 0. 执行前置条件

开始任务前，仓库必须已经由用户完成以下操作：

1. 将本 Goal 与冻结验收合同提交到仓库：
   ```text
   docs/branchunit_R/
   ├── 动态_BranchUnit_回环区域优化线_R_总Goal_v2.md
   └── 动态_BranchUnit_回环区域优化线_R_冻结验收合同_v2.md
   ```
2. 创建并推送不可移动的基线标签：
   ```bash
   git tag -a branchunit-r-contract-v2 -m "Freeze BranchUnit R v2 goal and acceptance contract"
   git push origin branchunit-r-contract-v2
   ```
3. Codex 必须在新分支工作：
   ```text
   work/dynamic-branchunit-region-R-v2
   ```

若标签 `branchunit-r-contract-v2` 不存在，任务状态必须设为 `BLOCKED`。  
Codex 不得自行创建、移动、删除或重打该标签。

---

# 一、总任务

继续改造现有流程：

```text
prototype_analysis
→ global_l1_flow
→ branch_unit_grammar
→ stage5_selection
```

按顺序完成：

```text
R0  基线与验收证据冻结
R1  一级枝基础运动
R2A 原型角色拓扑接入
R2B 回环角色区域生成
R2C SW1 独立承花—包花枝消费区域
R2D SW3 远端承花验证
R3  花位核心枝组
R4  单元级全局布局与收束
R5  L2/L3 层级语法
R6  Stage 5 最优选择与五原型覆盖
```

每个阶段执行：

```text
读取冻结合同
→ 记录阶段起点 commit
→ 声明拟修改文件
→ 检查白名单
→ 实现最小必要改动
→ 运行目标案例
→ 执行冻结验收
→ 执行反捷径审计
→ 失败则留在当前阶段继续修复
→ 通过则提交阶段 checkpoint
→ 自动进入下一阶段
```

任何硬约束不通过，禁止进入下一阶段。

---

# 二、最高优先级规则

发生冲突时按以下顺序执行：

1. `branchunit-r-contract-v2` 标签中的冻结验收合同；
2. 冻结的原型角色拓扑；
3. 冻结指标定义与阈值；
4. 当前阶段任务；
5. 现有代码；
6. 当前输出结果。

现有代码和当前结果不得反向修改结构语义与验收标准。

---

# 三、绝对禁止事项

禁止：

1. 修改本 Goal。
2. 修改冻结验收合同。
3. 修改、替换或重打基线标签。
4. 修改验收阈值、指标定义、原型拓扑和阶段通过条件。
5. 删除失败指标。
6. 将硬约束改成软目标。
7. 根据当前输出重新设置正常范围。
8. 使用 seed 专用坐标、原型专用固定控制点或单图补丁。
9. 扩大随机重试次数获得偶然合格结果。
10. 删除不合格曲线获得合法图。
11. 扩大区域包住已有曲线。
12. 先生成曲线，再从曲线反推区域。
13. 将区域实现为仅存在于 JSON 中、但不参与候选生成的标签。
14. 用矩形、扇形、四个独立椭圆或固定圆弧模板代替回环区域。
15. 把 SW1 的承花枝和包花枝设置成父子关系。
16. 在 SW3 中强制生成包花枝。
17. 用 L2 代替核心组织枝。
18. 在 R5 之前生成叶片、芽头、卷头或风格化末端。
19. 为通过阶段修改冻结测试、基线数据或验收程序。
20. 跳过失败阶段。

---

# 四、冻结合同完整性检查

每次阶段开始、验收前和提交前运行：

```bash
git diff --exit-code branchunit-r-contract-v2 --   docs/branchunit_R/动态_BranchUnit_回环区域优化线_R_总Goal_v2.md   docs/branchunit_R/动态_BranchUnit_回环区域优化线_R_冻结验收合同_v2.md
```

若发现差异：

```text
stage_status = FAILED
failure_code = FROZEN_CONTRACT_MUTATED
```

立即恢复冻结文件，本轮不得继续宣布通过。

---

# 五、阶段文件白名单

每个阶段开始前生成：

```text
artifacts/runs/dynamic_branch_R_current/stage_change_plan.json
```

格式：

```json
{
  "stage": "R1",
  "stage_start_commit": "",
  "files_to_modify": [],
  "reason_by_file": {},
  "expected_metrics_to_improve": [],
  "protected_metrics": []
}
```

需要修改白名单外文件时，状态设为 `BLOCKED`，不得自行扩大范围。

## R0 白名单

```text
experiments/branch_unit/dynamic/diagnostics/**
experiments/branch_unit/dynamic/reporting/**
tests/branch_unit_R/test_R0_*
artifacts/runs/dynamic_branch_R0_*
```

禁止修改生成逻辑。

## R1 白名单

```text
experiments/branch_unit/dynamic/global_l1_flow.py
experiments/branch_unit/dynamic/contracts/runtime/global_l1_flow_*.json
experiments/branch_unit/dynamic/diagnostics/l1_*
tests/branch_unit_R/test_R1_*
artifacts/runs/dynamic_branch_R1_*
```

## R2A 白名单

```text
experiments/branch_unit/dynamic/global_l1_flow.py
experiments/branch_unit/dynamic/branch_unit_grammar_v1.py
experiments/branch_unit/dynamic/topology_contract_loader.py
tests/branch_unit_R/test_R2A_*
artifacts/runs/dynamic_branch_R2A_*
```

## R2B 白名单

```text
experiments/branch_unit/dynamic/prototype_analysis.py
experiments/branch_unit/dynamic/global_l1_flow.py
experiments/branch_unit/dynamic/role_region_plan.py
experiments/branch_unit/dynamic/diagnostics/region_*
tests/branch_unit_R/test_R2B_*
artifacts/runs/dynamic_branch_R2B_*
```

`role_region_plan.py` 只能作为现有流程内部的数据层，不得拥有独立生成入口或独立 CLI。

## R2C 白名单

```text
experiments/branch_unit/dynamic/global_l1_flow.py
experiments/branch_unit/dynamic/branch_unit_grammar_v1.py
experiments/branch_unit/dynamic/role_region_plan.py
experiments/branch_unit/dynamic/diagnostics/region_*
tests/branch_unit_R/test_R2C_*
artifacts/runs/dynamic_branch_R2C_*
```

## R2D 白名单

```text
experiments/branch_unit/dynamic/global_l1_flow.py
experiments/branch_unit/dynamic/role_region_plan.py
experiments/branch_unit/dynamic/diagnostics/region_*
tests/branch_unit_R/test_R2D_*
artifacts/runs/dynamic_branch_R2D_*
```

## R3 白名单

```text
experiments/branch_unit/dynamic/global_l1_flow.py
experiments/branch_unit/dynamic/role_region_plan.py
experiments/branch_unit/dynamic/diagnostics/group_*
tests/branch_unit_R/test_R3_*
artifacts/runs/dynamic_branch_R3_*
```

## R4 白名单

```text
experiments/branch_unit/dynamic/global_l1_flow.py
experiments/branch_unit/dynamic/role_region_plan.py
experiments/branch_unit/dynamic/diagnostics/global_*
tests/branch_unit_R/test_R4_*
artifacts/runs/dynamic_branch_R4_*
```

## R5 白名单

```text
experiments/branch_unit/dynamic/branch_unit_grammar_v1.py
experiments/branch_unit/dynamic/contracts/runtime/branch_unit_grammar_*.json
experiments/branch_unit/dynamic/diagnostics/hierarchy_*
tests/branch_unit_R/test_R5_*
artifacts/runs/dynamic_branch_R5_*
```

## R6 白名单

```text
experiments/branch_unit/dynamic/stage5_global_unit_selection.py
experiments/branch_unit/dynamic/contracts/runtime/stage5_selection_*.json
experiments/branch_unit/dynamic/diagnostics/selection_*
tests/branch_unit_R/test_R6_*
artifacts/runs/dynamic_branch_R6_*
artifacts/runs/dynamic_branch_R_complete_*
```

---

# 六、反捷径审计

每次验收后生成 `anti_shortcut_audit.json`：

```json
{
  "frozen_contract_unchanged": true,
  "stage_file_scope_pass": true,
  "thresholds_unchanged": true,
  "metric_definitions_unchanged": true,
  "prototype_topology_unchanged": true,
  "seed_specific_patch_detected": false,
  "fixed_coordinate_template_detected": false,
  "posthoc_region_fit_detected": false,
  "branch_geometry_used_as_region_input": false,
  "random_retry_count_increased": false,
  "automatic_curve_deletion_used": false,
  "role_label_used_as_geometry_evidence": false
}
```

任一项失败：

```text
stage_status = FAILED_RETRYING
```

---

# 七、失败处理

验收失败后先写 `failure_hypothesis.json`：

```json
{
  "stage": "",
  "iteration": 0,
  "failure_codes": [],
  "root_cause_layer": "topology | region | layout | geometry | hierarchy | selection | validator",
  "root_cause": "",
  "proposed_change": "",
  "files_to_modify": [],
  "metrics_expected_to_improve": [],
  "metrics_that_must_not_regress": [],
  "forbidden_shortcuts": []
}
```

连续三轮未改善同一指标：

1. 回滚到阶段起点；
2. 停止同类参数微调；
3. 重新审计调用链；
4. 提出新的机制级根因；
5. 再开始下一轮。

---

# 八、阶段状态与提交

阶段状态：

```text
IN_PROGRESS
FAILED_RETRYING
PASSED
BLOCKED
```

阶段通过必须同时满足：

```text
semantic_topology_pass == true
numeric_acceptance_pass == true
anti_shortcut_audit_pass == true
reproducibility_pass == true
required_artifacts_complete == true
```

提交格式：

```text
[R0 PASS] freeze baseline and evidence
[R1 PASS] establish tangent-led L1 motion
[R2A PASS] integrate frozen prototype topology
[R2B PASS] establish looped role regions
[R2C PASS] drive SW1 support-wrap L1 by frozen regions
[R2D PASS] validate SW3 remote support
[R3 PASS] establish family-aware flower groups
[R4 PASS] establish global unit layout and settle flow
[R5 PASS] rebuild role-aware L2/L3 hierarchy
[R6 PASS] optimize five-prototype global selection
```

---

# 九、阶段任务

## R0：基线与验收证据冻结

不改变任何图形、几何、候选和选择结果。

覆盖五种原型 × 三个 seed：

```text
proto_sw_1_1
proto_sw_1_3
proto_sw_2_3
proto_sw_3_1
proto_sw_3_2

4101
4102
4103
```

输出统一指标、失败定位、对照图和 digest。

通过条件：执行冻结合同 R0。

---

## R1：一级枝基础运动

将 L1 改为：

```text
沿主藤切线起步
→ 延迟转向
→ 进入目标空间
→ 保持横向运动
→ 在构图包络内收束
```

禁用 L2/L3。

同时修改候选生成、拒绝规则、评分、路径边界检查和调试输出。

通过条件：执行冻结合同 R1。

---

## R2A：原型角色拓扑接入

接入冻结拓扑：

```text
SW1：
独立 L1 承花枝
独立 L1 包花枝
同一花位、不同根节点、无父子关系

SW3：
独立 L1 远端承花枝
不强制包花

SW2：
不强套 SW1 或 SW3 拓扑
```

本阶段只验证角色槽位与拓扑，不优化曲线。

通过条件：执行冻结合同 R2A。

---

## R2B：回环角色区域生成

固定：

```text
proto_sw_1_1
seed 4101
一个目标花位
```

只生成区域，不生成新增分支曲线。

生成：

```text
support_region
wrap_region
balance_region
flower_forbidden_region
backbone_protection_region
```

角色区域必须包含：

```text
region_id
role
service_flower_id
entry_s_range
guide_centerline
guide_tangents
width_profile
target_relation
exit_direction
capacity
source_geometry
region_plan_digest
```

区域输入只允许：

```text
主藤
花位
空间探针
禁入区
原型角色拓扑
重复接缝
```

禁止使用任何候选曲线或选择结果。

通过条件：执行冻结合同 R2B。  
区域不通过，禁止进入 R2C。

---

## R2C：SW1 独立承花—包花枝消费区域

固定：

```text
proto_sw_1_1
seed 4101
与 R2B 相同花位
```

只生成：

```text
一根独立 L1 承花枝
一根独立 L1 包花枝
```

两根枝分别消费不同角色区域，区域 digest 必须在曲线生成前冻结。

同一冻结区域生成多个候选，证明区域是软通道，不是固定曲线模板。

通过条件：执行冻结合同 R2C。

---

## R2D：SW3 远端承花

固定：

```text
proto_sw_3_1
seed 4101
support_1
```

只生成一根独立 L1 远端承花枝。

禁止包花、L2、L3。

通过条件：执行冻结合同 R2D。

---

## R3：花位核心枝组

按家族建立枝组：

```text
SW1：
support L1 + wrap L1 + balance L1

SW3：
remote_support L1 + balance L1
wrap 不作为必需角色

SW2：
按冻结拓扑执行
```

角色生成顺序：

```text
核心服务枝
→ 已占用区域
→ 剩余视觉容量
→ 平衡枝
```

通过条件：执行冻结合同 R3。

---

## R4：单元级全局布局与收束

在 Stage 3B 建立：

```text
核心枝组
→ 剩余空白
→ 平衡枝
→ 必要普通枝
→ 单元末端收束
```

全局评分包括：

```text
根节点节奏
区域容量
花位角色完整度
上下视觉重量
横向覆盖
路径通道符合度
曲线包络重叠
收束与接缝方向连续性
```

Stage 3B 自身解决 L1 冲突，不依赖 Stage 5 删除。

通过条件：执行冻结合同 R4。

---

## R5：L2/L3 层级语法

建立：

```text
L1-only
L1 + 单个功能 L2
少量双 L2
条件满足时的单个 L3
```

核心承花枝和包花枝始终保持独立 L1。  
L2 不得代替核心角色。  
Y-2C 不再是默认结构。  
不生成叶片、芽头和卷头。

通过条件：执行冻结合同 R5。

---

## R6：Stage 5 最优选择与五原型覆盖

将 Stage 5 从：

```text
找到第一组合法解即停止
```

改为：

```text
在合法组合中选择综合构图得分最高的组合
```

推进顺序：

```text
1. proto_sw_3_1
2. proto_sw_1_1
3. proto_sw_3_2
4. proto_sw_2_3
5. proto_sw_1_3
```

每个原型先跑 4101，通过后再跑 4102、4103。

通过条件：执行冻结合同 R6。

---

# 十、统一阶段产物

```text
artifacts/runs/dynamic_branch_R{stage}_v2/
├── acceptance_report.json
├── anti_shortcut_audit.json
├── stage_change_plan.json
├── failure_hypothesis.json
├── iteration_history.json
├── metrics.json
├── failures.json
├── before_after_contact_sheet.png
├── debug_overlay.svg
├── run_manifest.json
└── stage_summary.md
```

---

# 十一、最终交付

```text
artifacts/runs/dynamic_branch_R_complete_v2/
├── final_acceptance_report.json
├── final_anti_shortcut_audit.json
├── stage_status_summary.json
├── all_stage_iteration_history.json
├── five_prototype_three_seed_contact_sheet.png
├── final_metrics.csv
├── final_metrics.json
├── region_plan_contact_sheet.png
├── failure_resolution_log.md
├── architecture_change_summary.md
├── reproduction_commands.md
└── final_report.md
```

完成条件：

```text
overall_status == PASSED
frozen_contract_unchanged == true
anti_shortcut_audit_pass == true
all_required_artifacts_exist == true
all_regression_tests_pass == true
working_tree_clean == true
```
