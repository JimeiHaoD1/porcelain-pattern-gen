# Inkscape v3 标注模板使用说明

模板文件：`data/annotation_templates/chanzhi_annotation_v3_template.svg`

静态预览：`data/annotation_templates/chanzhi_annotation_v3_template_preview.png`

它用于 SW 二方连续缠枝纹的结构中心线标注。模板没有嵌入任何真实候选图；顶部灰色区域保存了两类末端语法的示例对象，下方虚线框是底图工作区。

## 第一次打开先看什么

- `00 底图（锁定）` 默认锁定，避免描线时误拖图片。
- 顶部彩色对象均带 `data-example="true"`，只用于查看颜色、线宽和属性写法。
- 正式标注完成后，必须删除全部 `data-example="true"` 示例对象，再交给解析器或质检程序。
- 彩色路径描的是结构中心线，不是纹样轮廓。

## 标准操作流程

1. 复制模板，以候选图片文件名保存，例如 `review_001_ann_v3.svg`，不要覆盖模板。
2. 在 Inkscape 的“图层与对象”面板中解锁 `00 底图（锁定）`。
3. 删除下方的占位框和三行占位文字；保留白色页面背景、顶部示例带与页脚。
4. 用“文件 → 导入”放入候选图片，选择嵌入或链接均可；保持原始宽高比，不要横向或纵向拉伸。
5. 将图片移动到 `00 底图（锁定）`，置于下方工作区，重新锁定该层。
6. 在对应图层用贝塞尔工具描中心线。路径使用无填充、圆端点、圆连接。
7. 为每个新对象设置唯一 `id`，并在 XML 编辑器中补充 `data-role`、`data-generation`、`data-parent-id`、`data-terminal-family` 等字段。
8. 完成后删除顶部所有带 `data-example="true"` 的示例对象，保存 SVG，再运行质检。

## 图层、颜色与必要属性

| 图层 | 颜色 | 用途与必要属性 |
|---|---|---|
| Unit boundary | `#000000` 黑色虚线 | `data-role="unit_boundary"`；左右各一条 |
| Backbone | `#0000FF` 蓝色 | `data-role="backbone"`；从左重复边界连续到右重复边界 |
| Secondary backbone | `#FF00FF` 粉色 | `data-role="secondary_backbone"`；仅 DI 双主藤样本使用 |
| Primary branch | `#FF9900` 橙色 | 细枝型用 `primary_branch`，粗枝型用 `scroll_branch`；`data-generation="1"` |
| Secondary branch | `#00B7C7` 青色 | `data-role="scroll_branch"`、`data-generation="2"`，父对象必须是一级枝 |
| Tertiary branch | `#7A3DB8` 紫色 | `data-role="scroll_branch"`、`data-generation="3"`，父对象必须是二级枝 |
| Leaf guide | `#00FF00` 浅绿色 | `data-role="leaf_guide"`，只用于独立叶片方向并绑定细枝型一级枝 |
| Flower support | `#007800` 深绿色 | `data-role="flower_support"`，必须绑定花位 `target_flower_id` |
| Wrap flower | `#FFFF00` 黄色 | `data-role="wrap_flower"`，必须绑定花位 `target_flower_id` |
| Flower anchor | `#FF0000` 红色 | `data-role="flower_anchor"`；圆或椭圆覆盖花朵主体约 80%–90% |

颜色必须使用表中的精确十六进制值。不要新用旧版 `#FF7800`、`#66CC66`、`#FFCC00`。

## 两种分支语法不要混用

### Profile A：细枝着叶型 `leaf_bearing`

- 橙色一级细枝：`data-role="primary_branch"`、`data-generation="1"`、`data-terminal-family="leaf_bearing"`。
- 浅绿色短线只表达独立叶片或叶簇的生长方向：`data-role="leaf_guide"`。
- 每条浅绿色短线都要用 `data-parent-id` 指向对应橙色一级枝。
- 不要用浅绿色路径描完整叶片轮廓。

### Profile B：粗枝卷叶型 `scroll_swollen`

- 橙色一级枝、青色二级枝、紫色三级枝统一使用 `data-role="scroll_branch"`。
- 分别设置 `data-generation="1"`、`"2"`、`"3"`。
- 二级枝的 `data-parent-id` 指向一级枝；三级枝指向二级枝。
- 卷曲膨大末端不另画一种颜色，也不额外描末端范围；末级路径的位置和切线就是生成依据。

## ID 与父子关系示例

```xml
<path id="primary_scroll_017"
      data-role="scroll_branch"
      data-generation="1"
      data-parent-id="backbone_001"
      data-terminal-family="scroll_swollen" />

<path id="secondary_scroll_017_01"
      data-role="scroll_branch"
      data-generation="2"
      data-parent-id="primary_scroll_017"
      data-terminal-family="scroll_swollen" />
```

同一张图中 `id` 不得重复。更改父对象的 `id` 后，应同步更新全部子对象的 `data-parent-id`。

## 提交前最低检查

- 左右重复边界是否各一条，主藤是否真正跨越两条边界。
- 所有路径是否画在正确图层，颜色是否完全匹配 v3。
- 每条二级、三级枝是否存在且绑定正确父枝，没有悬空起点。
- 每条叶片方向线是否绑定细枝型一级枝，没有被误当成二级枝。
- 承花枝、包花枝是否指向真实存在的红色花位。
- 是否仍有 `data-example="true"` 对象；若有，删除后再提交。
- 是否保留了原图宽高比，且没有把照片或浮雕中的不确定连接关系“猜成”结构。

原始颜色规范位于：`D:\sdxl\chanzhi_annotation_color_spec_v3.txt`。
