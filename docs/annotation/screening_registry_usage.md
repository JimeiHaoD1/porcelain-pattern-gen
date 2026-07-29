# 人工筛选结果登记工具

实现文件：`src/chanzhi_sw/chanzhi_dataset_registry.py`

该工具只读取审查目录。缺失的候选图片被解释为人工删除，存在的图片被解释为保留；工具不会移动、恢复、重命名或删除图片。

## 筛选过程中只读检查

在项目根目录执行：

```powershell
$env:PYTHONPATH = "D:\sdxl\chanzhi_sw_clean\src"
python -m chanzhi_sw.chanzhi_dataset_registry `
  --review-dir "D:\sdxl\chanzhi_sw_clean\data\review_candidates_all_20260715" `
  --dry-run
```

## 筛选完成后生成正式登记文件

```powershell
$env:PYTHONPATH = "D:\sdxl\chanzhi_sw_clean\src"
python -m chanzhi_sw.chanzhi_dataset_registry `
  --review-dir "D:\sdxl\chanzhi_sw_clean\data\review_candidates_all_20260715" `
  --additions-manifest "D:\sdxl\chanzhi_sw_clean\data\dataset_registry\review_additions.csv" `
  --output-dir "D:\sdxl\chanzhi_sw_clean\data\dataset_registry\screening_final"
```

输出包括：

- `screening_summary.json`：数量、来源分布、异常和完整明细；
- `kept_candidates.csv`：人工保留图片；
- `deleted_candidates.csv`：人工删除图片。

工具会区分四种状态：`kept_original`（原样保留）、`kept_modified`（已修改）、`added`（用户新增）和 `deleted`（人工删除）。新增图片会进入保留清单，但在补齐来源字段前标记为 `provenance_status=pending`。人工删除和内容修改本身不是错误；使用 `--strict` 时，仍有新增图片未补来源才会返回非零退出码。

新增图片的来源补录表使用 `review_file,sample_origin,source_reference,source_parent_id,notes` 五列。`sample_origin` 推荐填写 `real_lineart` 或 `structure_preserving_remake`；`source_reference` 填网页、论文、原图路径或其他可追溯来源。

默认情况下，只要新增图片仍缺来源，工具就拒绝写出“最终”登记文件。确需保存中间快照时可显式增加 `--allow-incomplete`；该选项不得用于论文训练数据冻结。
