# 动态 BranchUnit R v2：已知反捷径风险

## 已在当前实现中发现

1. **POSTHOC_REGION_FIT**
   - `attach_loop_growth_guide` 接受已经生成的 lane，support guide 直接复制 lane centerline，再附加 region。
   - R2B 前必须拆除此数据依赖。

2. **FIXED_WAYPOINT_TEMPLATE**
   - SW1/SW3 support 使用固定 waypoint fraction、margin 与固定 remote mount distances。
   - 必须由入口、guide、width、target、exit 的区域计划替代。

3. **FIXED_CIRCLE_OR_ANGLE_TEMPLATE**
   - 旧 wrap 以固定 span 角度绕花位采样。
   - 新区域不得由固定圆弧、半径或起止角决定。

4. **SEED_FIXED_GEOMETRY_PRIOR**
   - `_fixed_warp_candidates` 对 `proto_sw_1_3` 读取 seed 对应 cubics。
   - R 线不得把该 prior 当作生成模板。

5. **WRAP_AS_SUPPORT_L2**
   - `TerminalSupport-Wrap` 将 wrap 编译为 support child L2。
   - R2A 必须停用核心错误拓扑。

6. **FORCED_SW3_WRAP**
   - 旧 R2 固定 SW3 support 并附加 wrap。
   - R2D 必须只生成 remote_support L1。

7. **FIRST_COMPLETE_STAGE5**
   - Stage5 DFS 在第一组完整合法 assignment 处停止。
   - R6 必须完成最优合法组合搜索。

8. **IMPLEMENTATION_LABEL_AS_EVIDENCE**
   - Stage4/5 依赖 `intrinsic_diagnostics.valid`、role、status 和 score。
   - R 验收必须独立从几何和 parent graph 重算。

## 执行中持续扫描

- 冻结文件或阈值变更；
- seed/prototype 专用坐标；
- 扩大随机重试；
- 删除失败曲线；
- 先曲线后区域；
- 扩大区域包住曲线；
- Stage5 替 Stage3B 删除错误 L1；
- R5 前的叶、芽、卷头或装饰末端；
- 连续只调半径、角度、权重而不改变错误机制。

任一风险命中即使数字指标为绿，阶段也不得 `PASSED`。
