# 动态 BranchUnit 回环区域优化线 R：冻结验收合同 v2

> 本合同为只读验收依据。  
> Codex 无权修改本文件、阈值、指标定义和原型角色拓扑。  
> 若合同定义存在错误，任务必须标记为 `BLOCKED`，由用户发布新版本；不得在当前任务中自行修改。

---

# 一、冻结的原型角色拓扑

## SW1：波谷填补型

适用：

```text
proto_sw_1_1
proto_sw_1_3
```

必需角色：

```text
flower_support L1，parent=backbone
flower_wrap L1，parent=backbone
balance L1，parent=backbone
```

硬约束：

```text
support.parent_curve_id == null
wrap.parent_curve_id == null
support.root_s != wrap.root_s
support.service_flower_id == wrap.service_flower_id
wrap_must_not_be_child_of_support == true
```

## SW2：轴穿型

适用：

```text
proto_sw_2_3
```

硬约束：

```text
do_not_force_SW1_support_wrap_topology == true
do_not_force_SW3_remote_support_topology == true
```

## SW3：远端承花型

适用：

```text
proto_sw_3_1
proto_sw_3_2
```

必需角色：

```text
remote_flower_support L1，parent=backbone
balance L1，parent=backbone
```

硬约束：

```text
remote_support_required == true
flower_wrap_required == false
forced_wrap_generation == false
wrap_as_support_child == false
```

---

# 二、统一指标

## 根部切线误差

```text
root_tangent_error_deg
=
min(
  angle(curve first derivative, parent forward tangent),
  angle(curve first derivative, parent reverse tangent)
)
```

第一导数使用第一段贝塞尔 `p1-p0`。

## 水平推进率

```text
horizontal_progress_ratio
=
abs(unwrapped_x_end - unwrapped_x_root)
/
curve_arc_length
```

## 越界长度

```text
out_of_bounds_length
out_of_bounds_ratio
```

按路径弧长计算。

## 通道覆盖率

```text
channel_coverage
=
curve length inside role region
/
curve total length
```

## 方向一致性

```text
mean_guide_alignment
p10_guide_alignment
```

## 花缘关系

```text
rho =
sqrt(
  ((x-cx)/rx)^2
  +
  ((y-cy)/ry)^2
)
```

记录：

```text
wrap_span_deg
minimum_rho
mean_rho
rho_cv
```

## 交叉

```text
unit_self_crossing_count
L1_L1_crossing_count
cross_unit_crossing_count
periodic_crossing_count
backbone_crossing_count
```

---

# 三、R0 验收

```text
case_count == 15
missing_case_count == 0
required_metric_missing_count == 0
unresolved_failure_reference_count == 0
baseline_geometry_changed == false
baseline_selection_changed == false
geometry_digest_run1 == geometry_digest_run2
selection_digest_run1 == selection_digest_run2
```

---

# 四、R1 验收

范围：

```text
五种原型 × 4101、4102、4103
只生成 L1
```

全部 L1：

```text
root_tangent_error_deg <= 15°
maximum_tangent_error_to_selected_flow_first_15pct <= 20°
backbone_clearance_at_25pct >= 0.012
out_of_bounds_length == 0
non_root_backbone_crossing_count == 0
L1_L1_crossing_count == 0
periodic_L1_crossing_count == 0
```

普通 L1：

```text
horizontal_progress_ratio >= 0.30
```

承花类 L1：

```text
horizontal_progress_ratio >= 0.20
```

任意长度 0.10 的主藤窗口：

```text
L1_root_count <= 2
```

`proto_sw_3_2`：

```text
vertical_long_lane_count == 0
```

禁止：

```text
L2_count > 0
L3_count > 0
```

---

# 五、R2A 验收

SW1：

```text
support_role_slot_exists == true
wrap_role_slot_exists == true
support.level == L1
wrap.level == L1
support.parent == backbone
wrap.parent == backbone
support_and_wrap_are_siblings == true
wrap_as_support_child == false
```

SW3：

```text
remote_support_role_slot_exists == true
remote_support.level == L1
remote_support.parent == backbone
forced_wrap_slot_exists == false
```

SW2：

```text
forced_SW1_topology == false
forced_SW3_topology == false
```

通用：

```text
topology_contract_digest_matches_frozen == true
unsupported_role_topology_count == 0
```

---

# 六、R2B 验收：回环角色区域

固定：

```text
proto_sw_1_1
seed 4101
一个目标花位
```

本阶段：

```text
new_branch_curve_count == 0
```

必需区域：

```text
support_region_count == 1
wrap_region_count == 1
balance_region_count == 1
flower_forbidden_region_count == 1
backbone_protection_region_count >= 1
```

每个角色区域：

```text
boundary_is_closed == true
boundary_self_crossing_count == 0
guide_centerline_exists == true
guide_centerline_sample_count >= 12
guide_tangent_sample_count == guide_centerline_sample_count
width_profile_sample_count >= 5
entry_s_range_exists == true
exit_direction_exists == true
capacity_exists == true
service_flower_id_exists == true
region_plan_digest_exists == true
```

生成顺序：

```text
region_plan_created_before_branch_geometry == true
branch_geometry_used_as_region_input == false
selected_candidate_used_as_region_input == false
stage5_selection_used_as_region_input == false
```

区域区别：

```text
support.region_id != wrap.region_id
support.entry_s_range != wrap.entry_s_range
support.guide_centerline_digest != wrap.guide_centerline_digest
support.service_flower_id == wrap.service_flower_id
```

禁止替代：

```text
axis_aligned_rectangle_region_count == 0
sector_region_count == 0
independent_ellipse_substitute_count == 0
fixed_circle_template_used == false
seed_specific_control_points_used == false
```

回环关系：

```text
support_wrap_boundary_interlock_count >= 1
support_wrap_guide_direction_difference_deg >= 25°
horizontal_guide_progress_ratio_support >= 0.20
horizontal_guide_progress_ratio_wrap >= 0.20
region_plan_digest_run1 == region_plan_digest_run2
```

---

# 七、R2C 验收：SW1 独立承花—包花枝

拓扑：

```text
support.level == L1
wrap.level == L1
support.parent_curve_id == null
wrap.parent_curve_id == null
support.root_s != wrap.root_s
support.service_flower_id == wrap.service_flower_id
support.region_id != wrap.region_id
```

区域依赖：

```text
support.source_region_plan_digest == frozen_R2B_region_plan_digest
wrap.source_region_plan_digest == frozen_R2B_region_plan_digest
region_plan_regenerated_after_curve_generation == false
```

承花：

```text
support_channel_coverage >= 0.85
support_mean_guide_alignment >= 0.70
support_p10_guide_alignment >= 0.35
support_contact_error <= 0.01
abs(contact_x - flower_cx) / rx <= 0.15
abs(contact_y - (flower_cy + ry)) / ry <= 0.10
```

包花：

```text
wrap_channel_coverage >= 0.85
wrap_mean_guide_alignment >= 0.70
wrap_p10_guide_alignment >= 0.35
wrap_span_deg >= 90°
wrap_span_deg <= 180°
minimum_rho >= 1.00
mean_rho >= 1.05
mean_rho <= 1.45
rho_cv <= 0.20
```

候选多样性：

```text
candidate_count_per_region >= 3
unique_geometry_digest_count_per_region >= 2
source_region_plan_digest_unique_count == 1
```

合法性：

```text
unit_self_crossing_count == 0
support_wrap_crossing_count == 0
flower_core_intrusion_count == 0
backbone_crossing_count == 0
out_of_bounds_length == 0
```

禁止：

```text
wrap.level == L2
wrap.parent_curve_id == support.curve_id
posthoc_region_fit_detected == true
```

---

# 八、R2D 验收：SW3 远端承花

```text
remote_support.level == L1
remote_support.parent_curve_id == null
wrap_curve_count == 0
L2_count == 0
L3_count == 0
remote_mount_arc_distance >= 0.30
remote_mount_arc_distance <= 0.48
below_flower_waypoint_margin >= 0.035
support_contact_error <= 0.01
support_channel_coverage >= 0.85
mean_guide_alignment >= 0.70
root_tangent_error_deg <= 15°
horizontal_progress_ratio >= 0.20
unit_self_crossing_count == 0
flower_core_intrusion_count == 0
backbone_crossing_count == 0
out_of_bounds_length == 0
```

---

# 九、R3 验收

SW1：

```text
support_count == 1
wrap_count == 1
balance_count == 1
support_wrap_parent_child_relation == false
ordinary_count_inside_flower_group == 0
balance_length / max(support_length, wrap_length) >= 0.50
balance_length / max(support_length, wrap_length) <= 0.75
balance_target_in_largest_remaining_sector == true
balance_channel_coverage >= 0.80
balance_mean_guide_alignment >= 0.65
balance_horizontal_progress_ratio >= 0.30
```

SW3：

```text
remote_support_count == 1
balance_count == 1
forced_wrap_count == 0
```

通用：

```text
unassigned_short_branch_count == 0
minimum_unrelated_root_gap >= 0.06
crossing_count == 0
flower_intrusion_count == 0
out_of_bounds_length == 0
geometry_role_classifier_accuracy == 100%
```

分类器不得读取角色标签。

---

# 十、R4 验收

```text
L1_crossing_count == 0
periodic_L1_crossing_count == 0
backbone_crossing_count == 0
minimum_root_gap >= max(0.05, 0.60 × median_root_gap)
maximum_root_gap <= 2.20 × median_root_gap
任意长度 0.15 的周期窗口 root_count <= 2
near_backbone_length_ratio_after_root <= 0.15
family_required_core_group_complete == true
additional_branch_count_within_group_envelope <= configured_capacity
maximum_empty_horizontal_bin_run <= 1
maximum_overloaded_bin_count <= 1
terminal_direction_alignment_with_seam >= 0.75
settle_out_of_bounds_length == 0
undeclared_endpoint_inside_seam_guard == 0
stage5_required_deletion_count == 0
```

无单侧强调原型：

```text
upper_curve_length / lower_curve_length >= 0.60
upper_curve_length / lower_curve_length <= 1.67
```

---

# 十一、R5 验收

每条 ordinary 和 balance lane：

```text
valid_L1_only_candidate_count >= 1
valid_single_L2_candidate_count >= 1
```

所有 lane：

```text
lanes_with_only_Y2C_feasible == 0
feasible_candidate_count >= 2
```

核心角色：

```text
support_core_role_level == L1
wrap_core_role_level == L1
core_role_replaced_by_L2_count == 0
```

L2：

```text
L2_length / L1_length >= 0.25
L2_length / L1_length <= 0.45
mount_fraction >= 0.35
mount_fraction <= 0.80
root_tangent_error_deg <= 15°
```

L3：

```text
L3_without_functional_reason == 0
L3_without_level3_capacity == 0
```

允许的子枝功能：

```text
balance_fill
frontier_extension
settle_subordinate
local_echo
tertiary_echo_with_space_evidence
```

禁止：

```text
secondary_flower_wrap_used_as_core_wrap == true
unassigned_descendant_count > 0
```

合法性：

```text
unit_self_crossing_count == 0
flower_intrusion_count == 0
backbone_crossing_count == 0
out_of_bounds_length == 0
```

---

# 十二、R6 验收

硬约束：

```text
crossing_count == 0
periodic_crossing_count == 0
flower_core_intrusion_count == 0
backbone_intrusion_count == 0
out_of_bounds_length == 0
root_tangent_failure_count == 0
family_topology_failure_count == 0
region_path_failure_count == 0
seam_conflict_count == 0
```

求解器：

```text
stopped_at_first_complete_legal_assignment == false
composite_visual_score_used == true
best_legal_assignment_search_completed == true
```

评分拆分：

```text
role_completeness_score
region_path_score
hierarchy_score
density_balance_score
horizontal_rhythm_score
flower_group_score
settle_continuity_score
```

最优性：

```text
proto_sw_3_1 / seed 4101:
optimized_best_score == exhaustive_best_score
```

Y-2C：

```text
selected_Y2C_count <= max(1, floor(ordinary_unit_count × 0.15))
core_flower_group_Y2C_count == 0
```

原型顺序：

```text
1. proto_sw_3_1
2. proto_sw_1_1
3. proto_sw_3_2
4. proto_sw_2_3
5. proto_sw_1_3
```

三 seed：

```text
hard_constraint_pass_rate == 100%
family_role_topology_consistent == true
geometry_digest_unique_count >= 2
```

确定性：

```text
selection_digest_run1 == selection_digest_run2
score_breakdown_run1 == score_breakdown_run2
geometry_digest_run1 == geometry_digest_run2
```

---

# 十三、阶段通过逻辑

任何阶段必须同时满足：

```text
hard_failure_count == 0
semantic_topology_pass == true
numeric_acceptance_pass == true
anti_shortcut_audit_pass == true
reproducibility_pass == true
required_artifact_missing_count == 0
frozen_contract_unchanged == true
```

实现代码自身生成的 `role`、`valid`、`pass`、`score`、`status` 不能作为唯一验收依据。

验收必须根据：

```text
几何
拓扑
父子关系
挂接位置
花位关系
区域依赖
路径采样
```

独立重算。
