# 动态 BranchUnit 回环区域角色与划分规范 v2

> 本文件是“动态 BranchUnit 回环区域优化线 R”的冻结语义规范。  
> 它定义区域是什么、各区域承担什么结构角色、如何从主藤与花位关系中划分，以及哪些实现不算完成区域规划。  
> Codex 只能读取本文件，不得在执行阶段修改、放宽或重新解释。

---

# 一、核心定义

## 1. 区域不是整张画布的硬分区

本任务中的“区域划分”不是把 unit 画布切成互不相交的矩形、多边形、扇形或 Voronoi 区块。

区域应理解为：

```text
围绕主藤、花位与剩余空间生成的角色化软生长通道
```

每个区域同时规定：

- 分支从哪里进入；
- 分支服务哪个对象；
- 分支沿什么方向推进；
- 分支在哪个范围内弯曲；
- 分支在哪里退出或收束；
- 该区域最多容纳多少枝条；
- 与相邻区域如何嵌合；
- 哪些位置绝对禁止进入。

允许存在未分配空间。禁止为了“分满画布”而生成无功能区域。

---

## 2. 回环区域的含义

“类似太极阴阳鱼”指空间组织关系，不是复制太极图形。

必须体现：

- 相邻区域具有内凹与外凸；
- 一个区域的外凸部分进入另一个区域的内凹空间；
- 区域围绕花位形成托、抱、绕、回收关系；
- 区域整体仍服从二方连续纹样的横向推进；
- 区域边界与引导线均为连续曲线；
- 区域形态由主藤、花位、禁入区和剩余容量共同决定。

禁止把“回环”简化为：

- 一个固定圆；
- 一个固定椭圆环；
- 四个互不相干的椭圆；
- 一组直线或折线分区；
- 在已有曲线外面补画一条带状背景。

---

# 二、区域分为两大类

## A. 硬约束区域

硬约束区域用于禁止或限制进入，不直接生成角色枝。

包括：

1. `flower_forbidden_region`
2. `backbone_protection_region`
3. `seam_guard_region`
4. 现有结构保护区

## B. 角色生长区域

角色生长区域用于组织枝条。

包括：

1. `support_region`
2. `wrap_region`
3. `remote_support_region`
4. `balance_region`
5. `settle_region`
6. `ordinary_fill_region`
7. SW2 家族使用的 `axis_flow_region`

角色区域不必全部出现在每个原型中。具体启用方式由冻结的原型角色拓扑决定。

---

# 三、硬约束区域语义

## 1. flower_forbidden_region：花心禁入区

### 作用

保护花位主体，禁止普通枝、平衡枝和收束枝穿入花心。

### 几何来源

由花位椭圆扩张得到：

```text
flower center
flower rx / ry
protection padding
```

### 允许关系

- 承花枝只能接近花位下侧目标扇区；
- 包花枝只能沿禁入区外围运行；
- 任何曲线不得穿过禁入区内部；
- 禁止通过缩小禁入区让不合格曲线通过。

---

## 2. backbone_protection_region：主藤保护带

### 作用

防止分支在离开根部后再次穿越主藤，或长距离贴着主藤并行滑行。

### 允许关系

- 分支根部前段可从保护带中离开；
- 离开后不得重新进入；
- 仅允许在明确的合法连接点接触主藤；
- 不得把保护带当作普通生长通道。

---

## 3. seam_guard_region：拼缝保护区

### 作用

保证二方连续拼接方向与入口空间。

### 允许关系

- 只有声明为 seam/frontier/settle 的结构可以进入；
- 普通枝不得在拼缝处被裁断；
- 收束枝进入时必须服从下一重复单元的连续方向。

---

# 四、角色生长区域语义

# 4.1 support_region：承花/托花区域

## 结构角色

承花区负责建立“主藤—花位下侧”的支撑关系。

它应让花位看起来由枝条托起，而不是悬浮在枝条上方。

## 适用范围

主要用于 SW1。

SW3 使用独立的 `remote_support_region`，不直接套用普通 support 区。

## 空间关系

```text
主藤波谷或波谷侧翼入口
→ 花位下方绕行空间
→ 花位下侧连接扇区
```

## 入口

- 根节点位于目标花位附近的主藤波谷或波谷侧翼；
- 入口不是离花位最近的随意点；
- 根部先继承主藤切线；
- support 与 wrap 必须拥有不同的入口区间。

## 引导中心线

应包含三个阶段：

```text
root：沿主藤切线离开
bend：向花位下方转入
settle：在花位下侧减缓并接近目标
```

## 目标

目标为花位下侧连接扇区，不是花心，也不是花位任意最近点。

## 宽度变化

```text
根部较窄
→ 中段适度展开
→ 花下绕行段保持可弯曲空间
→ 接点附近收窄
```

## 容量

```text
maximum_l1_count = 1
```

核心承花角色必须由独立 L1 承担。

## 禁止形态

- 从花旁短距离临时长出；
- 根部直接垂直上冲；
- 直线连接根节点与花位；
- 贴着主藤长距离滑行；
- 由另一根枝的 L2 代替核心承花；
- 穿过花心。

---

# 4.2 wrap_region：包花/围合区域

## 结构角色

包花区负责形成花位外围的环抱、围合和回护关系。

它不是“避开花位”，而是沿花位外围有组织地运行。

## 适用范围

主要用于 SW1。

SW3 不强制生成 wrap 区。

## 拓扑

包花枝是独立 L1：

```text
parent = backbone
parent_curve_id = null
```

它与承花枝服务同一花位，但不是承花枝的子枝。

## 空间关系

```text
主藤独立入口
→ 花位侧下方进入
→ 沿花位外缘运行 1/4–1/2 周长
→ 向外摆出或向主藤方向回收
```

## 入口

- 位于花位侧方或侧下方对应的主藤区间；
- 与 support 的入口分离；
- 入口方向先服从主藤切线；
- 禁止直接从花位附近向外画固定圆弧。

## 引导中心线

引导线必须同时受以下因素影响：

- 主藤入口位置；
- 花位椭圆形状；
- 花位与主藤的相对位置；
- support 区已占用空间；
- 外侧剩余容量；
- 退出方向。

## 花缘关系

包花引导线应围绕花位外缘运行，但保持安全距离：

```text
不侵入花心
不紧贴花缘形成机械描边
不远离花位失去围合关系
```

## 宽度变化

```text
入口较窄
→ 围合中段保持稳定宽度
→ 出口逐渐收窄
```

## 容量

```text
maximum_l1_count = 1
```

## 禁止形态

- 作为 support 的 L2；
- 用固定半径、固定角度的圆弧模板；
- 只在终点靠近花位；
- 只做碰撞避让；
- 穿过花位；
- 与 support 完全镜像；
- 与 support 使用同一根节点。

---

# 4.3 remote_support_region：远端承花区域

## 结构角色

远端承花区用于 SW3，从远离花位最近点的主藤位置出发，经过花位下方，最终连接花位下侧。

## 适用范围

```text
proto_sw_3_1
proto_sw_3_2
```

## 空间关系

```text
远端主藤入口
→ 横向扫动
→ 花下绕行
→ 花位下侧接入
```

## 特征

- 根节点与花位最近主藤点之间保持较大弧长距离；
- 横向运动是主要特征；
- 花下 waypoint 只是引导信息的一部分，不得成为固定控制点模板；
- 不强制同时生成包花枝；
- 区域应给出有宽度的远端通道，而不是一条固定路径。

## 容量

```text
maximum_l1_count = 1
```

## 禁止形态

- 从花位最近点直接连接；
- 在 SW3 强制增加 wrap；
- 把远端承花退化为一条两段固定 Hermite 模板；
- 竖直上冲。

---

# 4.4 balance_region：平衡区域

## 结构角色

平衡区用于补偿承花、包花或远端承花形成的视觉重量，填补剩余空白。

它不服务花位连接，不形成新的中心。

## 生成顺序

balance 区必须在核心服务区域确定后生成：

```text
support / wrap / remote_support 已占用空间
→ 计算剩余空白
→ 选择最大且可用的剩余扇区
→ 生成 balance_region
```

禁止提前固定 balance 区后再放置核心枝。

## 空间关系

- 位于核心枝组视觉重量的相对侧；
- 与核心区域存在嵌合，但不能遮盖核心通道；
- 保持横向展开；
- 不做完全对称镜像。

## 长度与容量

```text
maximum_l1_count = 1
length_target = main_service_branch_length × 0.50–0.75
```

## 禁止形态

- 完全竖直；
- 与 support 或 wrap 等长等权；
- 指向花心；
- 形成新的花位中心；
- 默认生成 Y 叉；
- 与核心区域完全重合。

---

# 4.5 settle_region：收束区域

## 结构角色

收束区负责 unit 末端的方向回归和重复拼接准备。

它不负责填满剩余空间，也不负责生成卷头。

## 空间关系

```text
单元后段剩余入口
→ 逐渐降低曲率与密度
→ 回到主藤或重复接缝连续方向
→ 为下一单元留出入口空间
```

## 适用位置

- 靠近 unit 末端或 seam；
- 避开花位核心枝组；
- 在普通填充完成前确定其保留空间。

## 容量

```text
maximum_l1_count = 0 or 1
```

## 禁止形态

- 冲出上下边界；
- 形成大圆形卷头；
- 在接缝处突然折断；
- 与下一重复单元入口冲突；
- 为了填空白而生成多根枝。

---

# 4.6 ordinary_fill_region：普通填充区域

## 结构角色

普通填充区只处理核心枝组、平衡区和收束区确定后的残余空间。

## 生成顺序

```text
核心区域
→ balance
→ settle 保留空间
→ 剩余空间仍超过容量阈值时
→ ordinary_fill_region
```

## 约束

- 可以不存在；
- 数量由剩余空间决定；
- 不得服务花位核心关系；
- 不得形成新的视觉中心；
- 不得侵入 support、wrap、remote_support 和 settle 的主要通道。

---

# 4.7 axis_flow_region：SW2 轴向主运动区域

## 结构角色

用于 SW2 轴穿型原型，保持原型已有的轴向穿行或主运动关系。

## 适用范围

```text
proto_sw_2_3
```

## 规则

- 不强制套用 SW1 的 support + wrap；
- 不强制套用 SW3 的 remote support；
- 入口、方向和目标由 SW2 的参考 morphology、主藤轴向关系与空白证据共同确定；
- 花位主要作为结构关系和禁入边界参与，不自动成为承花目标；
- 必须保持横向主运动，禁止形成上下失衡的长竖枝。

在完成 SW2 参考形态审计前，不得通过猜测硬编码其区域模板。

---

# 五、区域划分的统一算法顺序

区域必须按以下顺序生成。

## Step 1：建立局部坐标系

对目标花位或 unit 建立：

```text
t：主藤局部切线方向
n：主藤局部法线方向
flower local center
unit periodic x range
```

局部横轴沿主藤推进方向，不直接等同于画布全局 x 轴。

---

## Step 2：先生成硬约束区

生成：

```text
flower_forbidden_region
backbone_protection_region
seam_guard_region
existing structure protection zones
```

后续角色区域只能在硬约束剩余空间中生成。

---

## Step 3：确定角色入口区间

入口区间来自：

- 主藤弧长 `s`；
- 当前 family 的角色拓扑；
- 花位与主藤关系；
- 空间探针；
- 根节点最小间距；
- 已占用入口。

禁止直接选择离目标最近的点。

---

## Step 4：生成角色引导中心线

每个角色先生成 `guide_centerline`，再扩张为区域。

引导线只规定主导流向，不等于最终分支曲线。

每条引导线必须包含：

```text
entry
root flow
main bend
service segment
exit or settle
```

---

## Step 5：根据 width_profile 扩张为软通道

沿引导线法线方向构造左右边界。

`width_profile` 至少包含：

```text
u = 0.00
u = 0.25
u = 0.50
u = 0.75
u = 1.00
```

宽度应随角色变化，禁止全程固定宽度。

---

## Step 6：形成回环嵌合关系

### SW1

优先关系：

```text
support_region 先确定花下托举通道
→ wrap_region 从侧方绕入并贴合 support 外侧
→ 二者形成一处内凹—外凸嵌合
→ balance_region 使用剩余空间
```

要求：

- support 和 wrap 不平行；
- support 和 wrap 不镜像；
- 二者 guide 方向存在明显差异；
- 至少一个区域边界出现面向另一区域的内凹；
- 不要求两区域完全无重叠；
- 允许小范围软重叠，但主通道不能重合。

### SW3

```text
remote_support_region 形成远端横向扫动
→ balance_region 填补相对侧
```

不强制 wrap。

---

## Step 7：裁剪与容量分配

角色区域必须：

- 裁剪到有效 unit 构图包络；
- 从硬禁入区中扣除；
- 保留接缝入口；
- 记录面积、宽度和最大枝条容量；
- 容量不足时允许该可选角色不存在，禁止缩小安全距离硬塞入。

---

## Step 8：冻结区域计划

在生成任何分支候选前输出：

```text
role_region_plan.json
role_region_overlay.svg
region_plan_digest
```

后续曲线必须引用：

```text
source_region_plan_digest
region_id
```

禁止在曲线生成后重新调整区域。

---

# 六、区域优先级与重叠规则

优先级：

```text
硬禁入区
>
核心服务区（support / wrap / remote_support / axis_flow）
>
balance
>
settle 保留空间
>
ordinary_fill
```

规则：

1. 硬禁入区与角色区域不得重叠；
2. 核心角色区域之间允许小范围软重叠；
3. guide_centerline 不得重合；
4. balance 不得覆盖核心服务通道；
5. ordinary_fill 只能使用最终剩余空间；
6. settle 的接缝出口空间不得被普通区域占用；
7. 不要求所有区域面积之和覆盖整个 unit。

---

# 七、区域数据结构

每个角色区域至少输出：

```json
{
  "region_id": "",
  "unit_id": "",
  "role": "",
  "service_flower_id": "",
  "family_id": "",

  "entry_s_range": [0.0, 0.0],
  "entry_direction_range_deg": [0.0, 0.0],

  "guide_centerline": [],
  "guide_tangents": [],
  "width_profile": [],
  "boundary": [],

  "target_relation": "",
  "target_sector": "",
  "exit_direction": [0.0, 0.0],

  "capacity": {
    "maximum_l1_count": 0,
    "maximum_l2_count": 0
  },

  "priority": 0,
  "soft_overlap_allowed_with": [],
  "forbidden_overlap_ids": [],

  "source_geometry": {
    "backbone_s_ranges": [],
    "space_probe_ids": [],
    "protection_zone_ids": [],
    "topology_contract_digest": ""
  },

  "created_before_branch_geometry": true,
  "region_plan_digest": ""
}
```

---

# 八、Codex 理解检查点

在修改区域代码前，Codex 必须先输出：

```text
artifacts/runs/dynamic_branch_R2B_v2/region_semantics_review.md
artifacts/runs/dynamic_branch_R2B_v2/resolved_region_role_table.json
```

`region_semantics_review.md` 必须逐项说明：

1. 每个区域服务什么结构关系；
2. 每个区域从哪里进入；
3. 每个区域经过哪里；
4. 每个区域在哪里退出；
5. 每个区域与花位、主藤和相邻区域的关系；
6. 哪些原型启用该区域；
7. 哪些做法被明确禁止。

`resolved_region_role_table.json` 必须与本冻结规范逐项匹配。

该检查点不通过时，禁止编写区域生成代码。

---

# 九、R2B 视觉验收图必须表达的内容

区域图只显示：

- 主藤；
- 花位；
- 花心禁入区；
- 主藤保护带；
- support / wrap / balance 区域；
- guide_centerline；
- 入口区间；
- 退出方向；
- 区域 ID；
- unit 边界与 seam。

禁止显示新增枝条。

合格区域图应能直接读出：

```text
哪一块负责托花
哪一块负责包花
哪一块负责平衡
它们如何围绕同一花位互相嵌合
分支未来应从哪里进入并向哪里退出
```

若隐藏文字标签后，区域形态完全无法区分角色，则 R2B 视觉验收不通过。

---

# 十、自动验收补充条款

## 1. 角色区分

```text
support.guide_centerline_digest != wrap.guide_centerline_digest
support.entry_s_range != wrap.entry_s_range
support.target_relation != wrap.target_relation
support.service_flower_id == wrap.service_flower_id
```

## 2. 区域先于曲线

```text
new_branch_curve_count == 0 during R2B
branch_geometry_used_as_region_input == false
selected_candidate_used_as_region_input == false
region_plan_created_before_branch_geometry == true
```

## 3. 非模板化

```text
fixed_circle_template_used == false
fixed_ellipse_template_used == false
axis_aligned_rectangle_region_count == 0
sector_region_count == 0
seed_specific_control_points_used == false
```

## 4. 软通道真实性

在 R2C 中，同一冻结区域至少生成三个候选：

```text
candidate_count_per_region >= 3
unique_geometry_digest_count_per_region >= 2
source_region_plan_digest_unique_count == 1
```

## 5. 角色几何可读性

验收器不能读取 role 标签，必须根据区域几何判断：

- support 指向花位下侧；
- wrap 沿花位外围运行；
- balance 指向剩余空白；
- settle 指向接缝连续方向。

---

# 十一、与总 Goal 的关系

总 Goal 必须将本文件加入冻结检查：

```text
docs/branchunit_R/动态_BranchUnit_回环区域角色与划分规范_v2.md
```

Codex 每阶段开始、验收前和提交前必须确认：

```text
region_semantics_contract_unchanged == true
```

本文件发生任何修改时：

```text
stage_status = FAILED
failure_code = FROZEN_REGION_SEMANTICS_MUTATED
```

