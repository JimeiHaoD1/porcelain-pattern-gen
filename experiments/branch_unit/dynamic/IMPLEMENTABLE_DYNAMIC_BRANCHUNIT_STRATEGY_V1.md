# 可实现的动态 BranchUnit 生成策略 V2

> **LEGACY / 历史规划快照。** 本文是实施前方案，其中固定数量、槽位化 L1 等内容
> 已被 V2 公共候选池生产链替代。当前唯一生产入口与真实链路见 `README.md` 和
> `PAPER_A_ENGINEERING_HANDOFF_V1.md`，不得重新启用本文的旧规划作为正式方法。

本版替代原 V1。优先级依次为：正式主链可接入、形变效果可控、能够分阶段生成真实结果、再扩大随机性。不恢复 R 区域规划，不重写现有 L1/BranchUnit 求解器。

## 1. 目标与成功条件

同一原型在不同 seed 下能够产生：

1. 同一形态家族内的平滑主干变体；
2. 随主干保持局部关系的花位；
3. 由变体实际挂接容量约束的不同 L1 数量；
4. 与数量匹配的非等距根位节奏；
5. 不同的 L1-only、单 L2、双 L2 配比和落位。

成功不是多出一组 JSON 或预览图，而是最终 BranchUnit 候选、全局选择和正式渲染都消费同一份变体主干及其分析结果。

## 2. 唯一生产主链

正式数据流固定为：

`基准 StrictP0 -> 主干/花位变体 -> analyze_prototype -> 动态数量 -> 根位节奏 -> L1 候选与单次全局求解 -> BranchUnit 候选 -> Stage 5 选择 -> 正式渲染`

每个任务目录必须携带并传递：

- `strict_p0_variant.json`；
- `prototype_analysis_variant.json`；
- `global_l1_flow_plan.json`；
- 后续 BranchUnit inventory 和 selection。

`run_edit_feedback_branch_units_v2.py` 必须从任务 manifest 加载该任务自己的 `prototype_analysis_variant.json`，不得再按 `prototype_id` 从固定 Stage 2 目录重新加载旧 analysis。渲染器、BranchUnit grammar 和冲突选择器必须收到同一对象。

形态分类和编辑器曲率先验仍按基准 `prototype_id` 复用。主干变体只允许留在原形态家族内，因此第一版不重新训练或重新分类 morphology。

## 3. D0：受控主干变体

### 3.1 周期局部标架

当前 P0 已有 81 个 `arc_samples`，不反推 Bézier 控制点。实现时：

1. 去掉与首点重复的末端样本；
2. 给首尾建立 `x ± 1` 的周期邻居；
3. 用周期中心差分重算切线 `T(s)`；
4. 由 `N(s) = (-T_y, T_x)` 得到周期法向；
5. 形变和重采样后，再复制首点并加 `(1, 0)` 形成末端。

这样端点位置天然连续，首尾使用同一周期邻域，不依赖原输入端点切线恰好一致。基准原型已有的 seam 切线差不作为拒绝基准原型的理由。

### 3.2 只使用三个低维形变模式

不再让纵向缩放、一次谐波和二次谐波各自独立取满。原始位移场为：

`Delta_raw(s) = wa * V_amplitude(s) + wb * V_bend(s) + wc * V_asymmetry(s)`

其中：

- `V_amplitude`：相对主干周期中线轻微增强或减弱原有起伏；
- `V_bend = sin(2πs + phi) * N(s)`：改变一周期内的整体偏转；
- `V_asymmetry = 0.35 * sin(4πs + 2phi + delta) * N(s)`：只提供弱不对称，不建立新的高频波形。

`wa/wb/wc` 由 `backbone_seed` 产生，但先归一化到单位能量，再统一乘以形变强度。二次模式不能独立超过一次模式，避免规则曲线退化成机械波纹。

### 3.3 总位移预算

所有模式合成后统一缩放：

`Delta(s) = scale_to_budget(Delta_raw, Dmax)`

`Dmax` 从当前几何余量推导，不使用原型专用常数：

`Dmax = max(0, min(0.025, 0.45 * available_margin))`

`available_margin` 是主干和花位保护椭圆距离上下画布边界的最小余量，再扣除 `0.035` 的视觉安全边。最大位移因此通常不超过约 6.4 个源像素；画布余量较小的原型自动得到更弱形变。

生产 seed 使用连续强度 `rho in [0.35, 1.0]`，最终预算为 `rho * Dmax`。若 `Dmax` 为零，明确返回 `backbone_variation_unavailable_for_margin`；不重试，不强行制造主干变化，后续仍可由 `branch_seed` 提供分支变化。

### 3.4 花位跟随

花位先连续投影到基准主干折线，而不是取最近离散采样点。记录：

- `anchor_s`；
- `period_offset`；
- 局部切向偏移 `offset_t`；
- 局部法向偏移 `offset_n`；
- 原来的法向侧别。

变体花心为：

`C_variant = P_variant(anchor_s) + offset_t * T_variant(anchor_s) + offset_n * N_variant(anchor_s)`

第一版保持花朵 `rx/ry` 不变。当前五个原型没有额外 structure protection zone；以后若出现 ellipse zone，可与所属花位使用同一局部变换，polygon zone 必须显式声明锚点后才能移动。

### 3.5 每个变体重新分析

变体生成后立即构造新的 `StrictP0V2`，并调用现有 `analyze_prototype()` 重建：

- 主干采样、切线、弧长参数；
- extrema、turns 和 long slopes；
- 花位最近主干关系；
- blank/crowded/prohibited space；
- `candidate_l1_attachment_regions`；
- seam analysis。

所有后续阶段只消费该变体 analysis。基准主干的旧 analysis 不能混入同一任务。

## 4. D1：动态 L1 数量

### 4.1 主干容量

先合并变体 analysis 中所有 `candidate_l1_attachment_regions[].s_ranges`，得到周期挂接区间并集。使用正式 solver 的根位最小间距计算：

`root_capacity = periodic_max_separated_point_count(merged_ranges, minimum_root_spacing)`

这里只判断一维根位容量，不建立二维区域，也不预测枝条形状。

### 4.2 数量候选

编辑反馈中的 `preferred_l1_count` 继续作为中心值，不再作为固定值：

`raw_counts = {preferred - 1, preferred, preferred + 1}`

`feasible_counts = {n | 5 <= n <= 9 and n <= root_capacity}`

由 `prototype_id + branch_seed` 生成一个 `density_u`，在可行数量中一次选择最终 `N`。随后只运行一次正式 L1 求解；不尝试多个数量，不在失败后自动减枝。

若集合为空或正式求解不可行，分别返回：

- `dynamic_l1_count_infeasible`；
- `dynamic_l1_layout_infeasible`。

## 5. D2：非等距根位节奏

### 5.1 可立即使用的数据来源

第一版不等待五个原型全部补齐专属根位标注。根位 gap 的数据来源按以下顺序选择：

1. 若当前原型已有编辑案例导出的 L1 周期 gap 样本，使用原型级样本；
2. 否则使用现有 fixed visual prior 中的 `consecutive_mount_gap.samples`；
3. 禁止退回完全等距根位。

### 5.2 从 gap 样本生成 N 个槽位

1. 对 gap 样本排序；
2. 用 `branch_seed` 决定低差异量化序列的相位；
3. 从经验分布取出 N 个 gap；
4. 施加正式最小根位间距下限；
5. 归一化，使周期 gap 总和为 1；
6. 累计得到 N 个 `preferred_s`；
7. 用 seed 旋转整个节奏，不改变 gap 顺序关系。

这是一组槽位偏好，不是固定坐标。最终根位仍由变体挂接区、候选硬过滤和现有全局求解器确定。

### 5.3 候选采样随 N 扩展

当前每个挂接区固定取五个候选根位，数量增大后容易拥挤。修改 `_region_s_values()`：

- 总候选根位数至少为 `max(10, 2 * N)`；
- 按各挂接区的 `s_span` 分配样本数；
- 每个非空区间至少保留两个内部样本；
- 不在边界端点直接挂根。

该变化只增加同一合法挂接区内的候选密度，不扩大区域，不改变硬约束，也不引入随机重试。

## 6. D3：层级随数量变化

继续复用 Stage 5 的最大余数法，把编辑器学习到的比例换算成整数：

- L1-only：`0.276`；
- 单 L2：`0.398`；
- 双 L2：`0.326`。

对任意最终数量 `N`，三类整数和必须等于 `N`。`branch_seed` 只旋转层级类别访问顺序和同类参数访问顺序，不能改变相交、净空或 sibling spacing 硬约束。

## 7. Seed 分工

正式接口接受非负 32 位整数 seed，并拆成两个独立域：

- `backbone_seed`：主干模式权重、相位和安全预算内强度；
- `branch_seed`：数量档、根位节奏相位、现有 L1 几何 latent 和层级落位。

允许固定其中一个 seed，只观察另一层变化：

- 固定主干、改变分支；
- 固定分支 seed、改变主干；
- 两者同时改变用于正式批量生成。

4101–4103 只保留为人工对照，不再是生产接口的唯一输入。

## 8. 实现顺序

### D0A：主干变体核心与真实预览

新增 `backbone_variation_v1.py`：

- 构造周期切线/法向；
- 生成受总预算约束的三模式形变；
- 连续锚定并移动花位；
- 输出新的 `StrictP0V2`；
- 直接调用 `analyze_prototype()`。

一次输出五个原型的基准、低、中、高形变量对照图。该图只用于尽早判断主干和花位关系，状态为 `VISUAL_REVIEW_PENDING`；D0A 不声称已经完成正式主链接入。

### D0B：接入当前固定数量的完整 BranchUnit 主链

修改：

- `run_stage3b_l1_flow.py`
  - 每个任务先生成变体 P0 和 analysis；
  - manifest 指向任务自己的变体文件；
  - L1 生成与渲染消费变体 analysis。
- `run_edit_feedback_branch_units_v2.py`
  - 从 task manifest 加载变体 analysis；
  - BranchUnit inventory、冲突图、选择和渲染沿用该对象。
- `global_l1_flow.py`
  - 允许独立 `backbone_seed/branch_seed`；
  - 暂时保持当前固定 L1 数量，先隔离验证主干变化的视觉影响。

D0B 完成后只做一次反事实：同一 `branch_seed` 下将主干强度从 0 改为中档，正式 L1 根点、候选几何和最终 BranchUnit 渲染必须发生可解释变化。该检查确认主链消费后即停止。

### D1：动态数量

- 新增周期根位容量计算；
- `preferred_l1_count` 改为中心值；
- 移除固定 seed choices；
- 同一任务只选择一次数量并求解一次。

### D2：动态根位节奏

- 从经验 gap 样本重采样 N 个非等距 gap；
- `_make_slots()` 消费新节奏；
- `_region_s_values()` 按 N 和区间长度提供足够候选。

### D3：动态层级落位

- 保留现有最大余数整数配比；
- 用 `branch_seed` 旋转层级和同类候选访问相位；
- 输出完整 BranchUnit 批次供视觉验收。

## 9. 最小验证与视觉门槛

自动检查只保留：

- 主干 seam 位置连续；
- 主干无自交；
- 正式 Unit 内及相邻周期无分支相交；
- D0B 的一次主链反事实。

不增加 SHA-256、digest 对比、冗余验收 JSON、历史全量回归或自动审美评分。

视觉检查按生成阶段进行，不长期停留在前期审核：

1. D0A：看主干是否仍属于原家族、花位是否仍自然；
2. D0B：看当前已认可枝条规律在变体主干上是否仍协调；
3. D1/D2：看数量与根位疏密是否自然；
4. D3：看完整层级、空白和周期连续构图。

未得到用户明确认可时，视觉状态只能是 `VISUAL_REVIEW_PENDING` 或 `VISUAL_REJECTED`。

## 10. 明确不做

- 不恢复 R 区域规划或二维 occupancy mask；
- 不建立平行生成系统；
- 不对主干采样点独立加噪；
- 不随机改变主干拓扑或波峰波谷顺序；
- 不使用原型专用形变坐标和固定曲线模板；
- 不在主干变化后固定花位绝对坐标；
- 不让下游重新加载基准 analysis；
- 不给槽位增加 `SKIP` 并重写大型联合求解器；
- 不尝试多个数量后择优；
- 不扩大随机重试；
- 不增加机器学习模型或自动审美评分。

## 11. V2 的可推进边界

V2 不是无限制随机生成。它优先保证：

- 主干变化可见但受统一预算控制；
- 花位关系随主干稳定迁移；
- 所有变化进入当前唯一生产主链；
- 数量、根位和层级分别可控、可复现；
- 任一阶段出现视觉问题时能够只回退该层机制，不推翻已经稳定的曲线生成器和编辑器先验。

实施从 D0A 直接进入生成，D0B 随后接通完整 BranchUnit；不再增加新的前置审计阶段。
