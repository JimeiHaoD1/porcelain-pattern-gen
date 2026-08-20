# Paper A 程序化结构生成系统交接

## 1. 状态与边界

- 工程基线：`ds@eb795b2`。
- Paper A 工作分支：`paper-a-method`。
- 当前论文方法状态：`METHOD_AUDIT_MISMATCH_PENDING_DECISION`。
- 程序只生成周期结构骨架：主干、花位、承花枝、一级枝、少量二级枝和周期边界。
- 叶片、花瓣、枝叶膨大、纹理、色彩和大模型渲染不属于本生成器。

`ds@eb795b2` 保存 2026-08-16 已确认的生成行为。Paper A 分支上的交接修复不得改变该版本的主干、花位、分支几何或选择结果。

## 2. 唯一批量生产入口

```powershell
Set-Location 'D:\sdxl\chanzhi_sw_clean_oldmain_opt'
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\run_batch_generation.py `
  --cases-per-prototype 100 --workers 8 --slim --render both `
  --output-dir .\artifacts\runs\dynamic_branch_batch_v1
```

生产链实际执行：

```text
production_seed 四域拆分
→ 主干变体
→ 花位与承花枝生成并冻结
→ 普通 L1 公共候选池
→ L1 硬约束过滤与冲突图
→ 兼容 L1 整组选择
→ BranchUnit 候选展开
→ 完整 Unit 冲突图
→ L1 基线上的稀疏 L2 升级
→ 单周期/三周期渲染与角色 SVG 导出
```

Stage3B V2 是唯一生产 L1 路径。历史 V1 和早期固定槽位脚本只用于追溯，不得作为 Paper A 方法入口。

## 3. 正式产物

| 产物 | 本地路径 | 用途 |
|---|---|---|
| 500 案例运行目录 | `artifacts/runs/dynamic_branch_batch_v1` | 案例 JSON、正式选择、机械检查和渲染 |
| 500 三周期 PNG | `artifacts/dynamic_branch_batch_500_triple` | 视觉检查与人评材料来源 |
| 500 角色 SVG | `artifacts/dynamic_branch_batch_500_svg` | Paper A 结构输出与下游接口 |
| 当前失败表 | `artifacts/runs/dynamic_branch_batch_v1/failures.json` | 当前批次失败记录 |
| 历史失败表 | `artifacts/runs/dynamic_branch_batch_v1/failures_history.json` | 首轮 14 个失败案例及修复追溯 |

这些目录是生成产物，不纳入 Git 工作树。交接以生成命令、聚合 manifest、案例 JSON 和本文路径索引为准，不使用文件哈希证明结果正确。

500 个角色 SVG 已于 2026-08-20 使用交接版导出器重新生成。SVG root 记录
prototype、production seed、四域 seed、主干变体、density 与来源；三周期实例记录
repeat ID、平移量和唯一 instance ID。canonical curve/unit/parent ID 保持不变，
导出过程不重新生成或重选结构几何。

## 4. 已确认事实

- 聚合 manifest 记录 500 个成功案例和 0 个当前失败案例。
- 批次覆盖 5 个原型、3 个主干变体和 3 个密度档。
- 聚合机械结果记录正式选择曲线相交 0、近距违规 0。
- 这些记录支持工程稳定性，不替代独立评测、视觉判断或真实纹样合理性评价。

## 5. 论文方法必须据实描述的机制

1. 系统包含两级冲突关系：上游 L1 冲突图和下游完整 Unit 冲突图。
2. 上游求解器在收集到的可行整组中择优；它不声明全局最优。
3. 正式 5E 先建立全 L1 基线，再按 `unit_seed` 尝试少量 L2 升级。
4. 当前密度档从几何可行基数中选择 `min/center/max`。它属于基数条件化控制，尚未实现偏好式密度目标。
5. 承花枝在普通 BranchUnit inventory 之前生成并冻结。普通 BranchUnit 不应被描述为同时生成所有花枝角色。

## 6. Paper A 证据缺口

- RQ1：需要统一评测器独立重算相交、净空、花位侵入、接缝和层级合法性。
- RQ2：需要共享候选池和约束的 IndependentCurve、LocalGreedy、FixedSlot 与当前方法对照。
- RQ3：需要汇总控制量对 L1 数量、根位、长度、曲率、占据率和拓扑的真实响应。
- RQ4：需要整理真实结构标注、来源、角色语义和同指标比较。

旧 `paper_experiment` 的 run57 指标、消融、图表和人评刺激不代表当前动态 BranchUnit 方法。
