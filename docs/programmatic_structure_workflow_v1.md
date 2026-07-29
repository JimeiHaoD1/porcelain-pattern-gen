# SW 程序化结构生成与结构表达优化工作流

## 一、目标与冻结决策

现有证据已经排除“继续调单条曲线和搜索参数”：

- `formal_v5` 50/50 几何合规，但人工视觉失败。
- `run15` 已有 BranchUnit 和 beam search，仍然 0/6 通过，说明瓶颈是枝组词汇，不是搜索强度。

本轮冻结以下决策：

- 程序化层交付“可被模型消费的结构包”，不承担最终成熟纹样绘制。
- 使用参数化 BranchUnit 词汇：主扫线、动态子枝节奏、花位关系、收梢行为和留白包络。
- 采用两阶段闸门，局部词汇不通过便停止扩展，不进入全局调参。
- JSON 结构包是运行时唯一真值；SVG 是人工编辑入口和可视化输出。
- 商业模型测试纳入工作流，以 GPT Image 2 作能力上界，再寻找最低充分能力层级。
- v1 只覆盖五个 SW 原型：`proto_sw_1_1`、`proto_sw_1_3`、`proto_sw_2_3`、`proto_sw_3_1`、`proto_sw_3_2`。
- 正式实现位于 `D:\sdxl\chanzhi_sw_clean`。run57、run15、formal_v5、formal_v6 和 ordered-lineart 全部冻结为回归或失败证据，禁止作为运行时输入。

## 二、结构包与核心接口

建立 `canonical_structure_package_v1`，最少包含：

- `meta`：包、原型、生成器版本、配置摘要、输入哈希和来源链。
- `frame`：画布、viewBox、归一化变换、重复轴、周期、单元边界和接缝配对。
- `graph`：节点、花位、交叠关系及路径；路径必须保存 `parent_id`、`generation`、`role`、`unit_id`、`mount_fraction`、`target_flower_id`、`terminal_family` 和权威 cubic 几何。
- `branch_units`：枝组类型、局部挂载坐标、主扫线、可变数量子枝、花位关系、包络、参数、seed、候选编号、约束结果和拒绝原因。
- `derived`：region graph 等可删除重建的数据，并记录源结构摘要。
- `render_adapters`：控制图、掩膜、坐标变换、通道语义和源结构哈希。
- `qa`：分别保存 `structural_status`、`visual_status`、`consumer_status` 和 `publishable`。
- `artifacts`：所有文件的相对路径、类型、哈希、生产者和输入摘要。

兼容规则：

- SVG 通过 `data-role`、`data-generation`、`data-parent-id`、`data-unit-id`、`data-terminal-family`、`data-target-flower-id` 表达语义；颜色推断只保留给旧文件导入。
- 每次人工修改 SVG 都生成新的 JSON 包及哈希，禁止 SVG、JSON 同时作为可修改真值。
- region graph、采样 polyline、索引和 Spec Card 均是派生数据。
- 每个结构包固定导出：`structure.svg`、`control_lineart.png`、`role_map.png`、`structure_lock_mask.png`、`detail_allowed_mask.png`、`background_preserve_mask.png`、`adapter_manifest.json` 和 `qa.json`。

模型允许补充叶片轮廓、花瓣细节、内部装饰线和青花材质；不得改变主干拓扑、枝条挂接、花位数量与中心、重复接缝、层级关系和主要留白。

## 三、程序化生成工作流

| 阶段 | 工作内容 | 通过条件 |
|---|---|---|
| 0. 清理运行边界 | 从 clean baseline SVG 重新分析；修正默认输入输出到 `data/baselines/sw` 和 `artifacts/runs/<run_id>`；旧输出只读 | 运行时不读取 run28/56/57 或 newpipe 输出；五个 baseline 均有固定哈希 |
| 1. 编译结构包 | 实现 SVG → canonical JSON → SVG/控制资产；region graph 改为派生缓存 | 同一输入与配置产生相同摘要；父子、代次、花位、接缝可验证；往返编译不丢语义 |
| 2. 局部 BranchUnit 闸门 | 在 `proto_sw_1_3` 提取普通挂载、花位 support/wrap、开放空隙三种真实语境；每种生成 8 个完整枝组 | 24 个候选至少 6 个 `unit_success`，三种语境各至少 1 个；通过项无直杆、硬折、须状簇、悬浮子枝；盲比至少 70% 优于旧独立曲线 |
| 3. 全局构图 | 从 region graph 和密度场产生真实挂载位；以完整枝组为候选单位，使用 beam 与有限回溯替换整个 unit | 主路线 25/25 结构有效；视觉批准至少 20/25，且每个原型至少 3/5；相对旧路线盲比胜率至少 70% |
| 4. 结构表达导出 | Branch-only 通过后再加入收梢方向、叶链占位、花位包络和模型控制掩膜 | 掩膜极性、尺寸变换、覆盖率、接缝及结构哈希全部一致；人工确认结构包表达清晰 |
| 5. 商业模型消费 | 先黑白线稿细化，再做青花风格；所有输入、参数、输出和漂移报告绑定在同一 manifest | 满足下述能力资格测试后才认定模型能消费结构 |

BranchUnit 的固定词汇包括：

- 沿真实父路径切线建立局部坐标系。
- 主扫线支持前伸、回卷、承托和绕花，不使用固定 waypoint。
- 子枝数量由可用弧长、层级和留白决定，可为 0、1 或多个；禁止固定两个子枝或固定槽位。
- 花位关系限定为 `support`、`wrap`、`approach`、`bypass`、`reserve_only`。
- 收梢限定为 C 卷、S 卷、芽状收束和叶柄接口，可参数化变形，不使用完整枝组模板。
- 硬约束只负责过滤非法候选；视觉排序负责整体流向、层级、长短节奏、负空间和枝花关系。

局部闸门最多进行两轮词汇修订。两轮仍不通过，则冻结程序化装饰枝生成，保留结构编译、主骨架和掩膜能力，不进入全局搜索。

全局搜索使用冻结初值：每个挂载位尝试 24 个候选、保留 12 个、beam width 32、最多回退替换两个 BranchUnit。未通过局部闸门前不得优化这些搜索参数。验证顺序为：

1. `proto_sw_3_2`，一个 seed。
2. 五原型，各一个 seed。
3. `proto_sw_1_3`，五个 seeds。
4. 五原型 × 五 seeds × `constraints_only/rule_ranked` 两策略。

两策略必须共享候选池；`constraints_only` 只作为消融，不参与默认结果晋升。

## 四、最低模型能力阶梯

先用 GPT Image 2 验证结构包存在可消费上界。上界失败时停止测试更低能力模型，返回结构表达或适配器阶段。

随后建立至少三个非旗舰商业候选的能力登记表。候选按图像编辑能力、参考图遵循度、mask/局部编辑能力和跨次稳定性排序；价格、参数量和品牌等级不参与判定。

每个候选执行：

- 三个代表原型：`proto_sw_1_3`、`proto_sw_2_3`、`proto_sw_3_2`。
- 两种适配方式：control-only、control + lock/detail/background。
- 两次固定重复，共 12 张黑白线稿。
- 固定结构包、提示词、分辨率和编辑强度，禁止 best-of 挑图。
- 黑白资格通过后才测试青花材质。

最低能力资格条件：

- mask-assisted 的 6/6 输出全部通过结构硬闸门。
- 主干、父子挂接、花数和重复接缝零语义变化。
- 花位中心漂移不超过宽度 1%、高度 2%。
- 锁定边缘召回率不低于 0.97，P95 漂移不超过条带高度 0.75%。
- 保护区外新增墨迹不超过背景面积 1%。
- 至少 4/6 获得人工确认的自然度提升，且每个原型至少有一次提升。
- mask-assisted 相对 control-only 至少 4/6 获得配对偏好，结构指标不得退化。
- 首次通过后，再以每原型一个未见重复进行确认；三张均须通过硬闸门，至少两张通过视觉闸门。

第一个满足资格与确认测试的候选即为“最低充分能力配置”。如果只有 GPT Image 2 通过，结论应如实记录为能力下界尚未下降，不用单张好图宣称成功。

失败反馈固定映射为：

- 两种适配在同一位置失败：返回 BranchUnit 或结构表达。
- control-only 失败、mask-assisted 通过：保留模型，优化适配器。
- 锁定区漂移：检查坐标、mask 极性和编辑强度。
- 结构忠实但枝花仍难看：返回程序化枝组，不让模型重写结构。
- 跨重复结果不稳定：判定模型能力不足。
- 留白被擅自填满：收紧 detail/background 掩膜，不依赖提示词补救。

## 五、测试、验收与退出条件

- 快速测试：SVG 语义解析、JSON schema、哈希确定性、父子关系、cubic 连续性、挂载切线、重复接缝、候选精确重放。
- 集成测试：五原型从 baseline 到结构包、SVG、控制图和掩膜的完整生成；验证所有派生物的源摘要一致。
- 视觉测试：统一输出局部、全局、重复、细节和 debug 对照表；AI 可做预检，但用户是最终视觉批准者。
- 消费测试：每次模型运行保存 provider/model/version、prompt、重复标识、尺寸变换、编辑参数、原始输出、漂移 overlay、自动指标和人工结论。
- 状态机强制为 `structural_valid → visual_approved → consumer_approved → publishable`，后级不得覆盖前级失败。
- 将快速契约测试与慢速渲染/视觉测试分开；当前相关测试只能确认可收集，不能把未完整跑完的测试写成已通过。
- AC、DI、深度模型训练、数据标注和最终青花风格评价不进入 v1；仅在 SW 黑白结构与模型消费闭环通过后另行扩展。
