# 动态 BranchUnit R v2：当前代码机制审计

## 结论

当前代码已经具备 StrictP0 隔离、确定性 L1 beam solver、完整候选库存、冲突图和可重放 digest，但新冻结合同指出的核心区域语义尚未成立。旧 `[R0/R1/R2 PASS]` 只对应旧 v1 合同，不能转移为 R v2 的通过证据。

## 冻结问题逐项审计

### 1. 当前区域是否只是探针形成的可挂接区间

是，分两类：

- `prototype_analysis._space_probes` 与 `_l1_mount_regions` 形成主藤两侧的可挂接弧长区间；
- `derive_loop_growth_region` 围绕花位做径向探针，形成 role-neutral 花缘可用深度。

它们都不是冻结规范所要求的 role-aware完整生长通道。

### 2. 区域是否只决定根节点，没有影响完整路径

普通 L1 是。`_ordinary_candidates` 用候选区间选择 `root_s`，随后路径由固定的长度、radial scale、切向符号和 Hermite 规则构造，区域不约束完整路径。

旧 R2 的 wrap 会消费 guide centerline，但该 guide 是在已有 support lane 之后生成，且不具备独立主藤入口。

### 3. 是否存在先生成曲线、再补区域元数据

存在。`attach_loop_growth_guide(lane, analysis, guide_contract)` 明确接受已生成的 selected `terminal_flower_support` lane：

- support guide 直接复制 `lane["centerline"]`；
- 随后调用 `derive_loop_growth_region`；
- 再把 `loop_growth_region`、`guide_channel` 和 `flower_wrap_channel` 附加回 lane。

这违反 R2B 的“区域计划先于任何 branch geometry”与“branch geometry 不得作为区域输入”。

### 4. 是否存在固定 waypoint、固定半径或固定角度模板

存在：

- SW1 support 使用固定 `sw1_waypoint_rx_fraction`、水平/垂直 margin；
- SW3 remote support 枚举固定 remote mount distances 与 waypoint rx/margin 组合；
- wrap 使用固定 `wrap_span_deg` 以及围绕花位的角度步进；
- `proto_sw_1_3` 的 `_fixed_warp_candidates` 直接读取 seed 对应的 fixed prior cubics。

这些机制必须被角色区域和通道消费取代，不能通过继续微调参数解决。

### 5. support、wrap 是否被错误处理为父子关系

是。`_compile_guide_following_child_curve` 输出 `level="L2"` 且 `parent_curve_id=parent_curve["curve_id"]`。`_build_candidate` 对 `TerminalSupport-Wrap` 将该 child 标为 `flower_wrap`。

冻结拓扑要求 SW1 support 与 wrap 均为独立 L1，直接挂主藤且服务同一花位。

### 6. SW3 是否被错误强制生成 wrap

基础 Stage3B 的 SW3 只创建 `terminal_flower_support`，但旧 `run_R2_support_wrap.py` 对固定 `proto_sw_3_1/4101/support_1` 附加 `flower_wrap_channel` 并编译 `TerminalSupport-Wrap`。因此旧 R2 验证路径确实强制了 SW3 wrap，不能沿用到 R2D。

### 7. Stage 5 是否找到第一组合法解就停止

是。`select_global_units.search` 在覆盖最后一个 lane 时立即返回 `True`，上层第一次递归成功后立即结束；solver trace 明确记录：

```text
stopped_at_first_complete_legal_assignment = true
composite_visual_score_used = false
```

### 8. 验收是否由实现代码自己生成并自己判定

部分是。旧 R runner 会同时生成实现输出、metrics 与 acceptance；其中已有若干基于采样几何的独立测量，但仍读取实现产出的 role、intrinsic `valid`、guide 标记与 score。R v2 验收必须从几何、parent graph、主藤挂接、花位关系、通道覆盖、切线、交叉、边界和周期拼接独立重算，不能只信这些标签。

## 已有可复用能力

- StrictP0 与 digest chain；
- Stage2 主藤/花位/保护区/空间探针；
- 确定性采样与多候选库存；
- Stage3B beam set compatibility solve；
- Stage4 parent graph、曲线采样与几何诊断；
- Stage5 conflict graph；
- SVG/PNG/三重复渲染器；
- 旧 R0/R1 runner 中的独立几何 digest、切线、横向推进、边界与交叉测量。

## 不可复用为正确机制的部分

- role-neutral radial loop region；
- post-hoc `attach_loop_growth_guide`；
- fixed waypoint、fixed span、seed fixed prior cubics；
- support -> wrap L2；
- SW3 TerminalSupport-Wrap；
- Stage5 first-complete assignment；
- 由实现标签直接推导通过的旧验收分支。
