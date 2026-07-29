# 缠枝纹分支规则直接编辑器（M0–M6）

这是基于真实 `record_4101.json`、`record_4102.json`、`record_4103.json` 与 `skeleton_profile.json` 的本地 SVG 结构编辑器。它直接修改矢量分支及其合法域，不使用参数滑块，也不在 PNG 上放置假控制点。

主干、花位和 repeat 骨架锁定。分支根点、枝尖、Bézier 控制柄、合法区顶点和包络边界均在 SVG 中直接操作；父枝变化时，后代按挂载处局部切向/法向框架递归跟随。

## 启动

```powershell
Set-Location 'D:\sdxl\chanzhi_sw_clean'
D:\Anaconda3\python.exe .\experiments\branch_unit\direct_editor\app.py --seed 4101
```

服务仅绑定 `127.0.0.1:5127`。若只启动服务、不自动打开浏览器，追加 `--no-browser`。

## M0–M6 操作

- **M0–M2 直接曲线编辑**：选择分支后，拖动根点、枝尖、`p1/p2` 控制柄和两段 cubic 的公共连接点；两段连接侧保持 G1 方向，父枝变化会递归传播到后代。
- **M3 合法域**：用“根点范围”直接在父枝上拖出允许挂载的弧长区间；用“枝尖合法区”在画布自由圈定 polygon，随后可继续拖动 polygon 顶点。
- **M4 曲线包络与禁区**：用“曲线包络”直接拖两条 Bézier 边界；系统实时重建包络 polygon，并计算长度、方向、弓高、最大偏移与边界相交警告。用“禁区”圈定 global、Unit、parent 或 level 作用域的 forbidden polygon，顶点可再次拖动。
- **M5 分支与数量语义**：用“新增枝”从主干或 L1/L2 父枝直接拖出新枝；支持删除整棵子树，并把枝设为 required、optional 或 forbidden。Unit 面板实时给出 minimum、maximum、禁用数和总槽位。
- **M6 多 seed 与 target**：在 4101/4102/4103 三个真实记录之间切换；每个 seed 的未保存状态在本次页面会话中独立保留。可切换上下文、整图、`2× repeat`、Unit 视图，并对已有保存会话做结构对比。

## 保存与兼容

“保存结构”写入：

- `artifacts/editor_sessions/<session_id>/session.json`
- `artifacts/editor_sessions/<session_id>/edited.svg`

保存时 Python 后端会重新投影并校验根点、父子关系、层级、约束类型、禁区作用域和包络分析；使用临时目录原子提交，失败不会留下半成品。源 record 永不覆盖。

旧 M2 `direct_branch_rule_editor_session_v1` 会话可直接载入，载入本身不会重写旧文件；再次保存时会生成新的完整 M0–M6 会话。

## 测试

```powershell
Set-Location 'D:\sdxl\chanzhi_sw_clean'
D:\Anaconda3\python.exe -m pytest -q .\tests\test_direct_branch_editor_core.py
D:\Anaconda3\python.exe -m pytest -q
```

自动测试验证数据与交互约束；视觉质量仍需在实际 SVG 画布中人工检查枝流连贯性、层级关系、花枝关系和 repeat 衔接。
