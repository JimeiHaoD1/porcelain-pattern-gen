# 缠枝纹 v3 标注基础设施

本目录汇总人工筛选结束后进入20张试标所需的工具和规范。

## 已完成组件

### 1. Inkscape 标注模板

- 模板：`../../data/annotation_templates/chanzhi_annotation_v3_template.svg`
- 静态预览：`../../data/annotation_templates/chanzhi_annotation_v3_template_preview.png`
- 操作说明：`Inkscape_v3_标注模板使用说明.md`

模板顶部对象只用于示范颜色、线宽和属性，带有 `data-example="true"`。复制模板、导入底图、完成正式标注后必须删除这些示例对象。

### 2. v3 SVG解析器

- 实现：`../../src/chanzhi_sw/chanzhi_svg_skeleton_io.py`
- 测试：`../../tests/test_svg_skeleton_io_v3.py`

支持 v3 颜色、元数据优先级、父子层级字段、组样式继承、常用 Inkscape 仿射变换，以及 `M/L/H/V/C/Q/S/T/Z` 路径命令。`A/a` 椭圆弧命令会明确报错，当前正式模板不使用该命令。带 `data-example=true` 的模板示例默认不进入结构解析。

### 3. 自动质检

- 实现：`../../src/chanzhi_sw/chanzhi_annotation_qa.py`
- 测试：`../../tests/test_annotation_qa.py`
- 模板示例验收报告：`../../artifacts/annotation_qa/template_examples_qa.json`

运行方式：

```powershell
$env:PYTHONPATH = "D:\sdxl\chanzhi_sw_clean\src"
python -m chanzhi_sw.chanzhi_annotation_qa "标注文件.svg" -o "质检报告.json"
```

正式标注默认忽略 `data-example=true`。只在检查模板示例时增加 `--include-examples`。

### 4. 筛选结果登记

- 实现：`../../src/chanzhi_sw/chanzhi_dataset_registry.py`
- 使用说明：`screening_registry_usage.md`
- 新增图片来源补录模板：`../../data/dataset_registry/review_additions_template.csv`

登记器只读审查目录，区分原样保留、人工修改、用户新增和人工删除。用户宣布筛选完成前，只运行 `--dry-run`，不得生成最终冻结清单。

### 5. 结构保真重制规范

- 规范：`structure_preserving_remake_protocol_v1.md`

只允许在人工可确认的骨架上清线、去材质和展平，不允许生成模型改写拓扑。

### 6. 20张试标目录

- 目录：`../../data/annotations/pilot_20/`
- 登记模板：`../../data/annotations/pilot_20/manifest_template.csv`

筛选完成后再选择20张来源互异、结构最清楚的图片复制到试标目录。试标阶段不直接训练HierBranchNet，先验证标注一致性、解析和质检闭环。

## 当前验证结果

- 全部自动测试：32项通过；
- 模板XML和Inkscape读取正常；
- 模板解析：12条路径、1个花位；
- 模板示例质检：0错误、0警告；
- 5份旧SW baseline继续正常解析；
- Python编译检查通过。

## 下一检查点

用户完成图片筛选后：

1. 只读扫描最终剩余图片；
2. 补齐新增图片来源；
3. 冻结筛选清单；
4. 选择20张试标图片；
5. 用Inkscape模板完成第一张；
6. 解析并质检第一张，人工确认标注粒度后再扩展到20张。
