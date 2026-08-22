# Paper A 第4章正式结果全量视觉审阅索引

- 实际找到正式案例：500 例。
- Matrix A：450 例。
- Matrix B seed variation：50 例。
- 三周期联系表：84 页，每页最多 6 例，布局为 3 列 x 2 行。
- 单周期联系表：84 页，每页最多 6 例，布局为 3 列 x 2 行。
- 三周期单 tile 画布：1900 x 1085 px；其中原图实际显示尺寸：[(1900, 935)]。
- 单周期单 tile 画布：1900 x 2345 px；其中图像实际显示尺寸：[(1852, 2200)]。
- 冻结源 PNG、SVG、CSV、JSON、manifest 和 evaluation 文件均未修改；检查方式为整理前后逐文件比较文件大小与纳秒级修改时间。
- 500 个冻结案例目录中没有 `formal_single.svg`。单周期审阅图由现有 `formal_triple.svg` 的中央一周期视窗栅格化得到，没有调用生成器。栅格化工具为 PyMuPDF，长边 2200 px，联系表以 lossless PNG 保存。
- 第二轮明细包只能显式传入 case ID：`python experiments/branch_unit/paper_a_evaluation/make_visual_review_pack.py --cases A014,A029,A183,B021 --output artifacts/paper_a_chapter4_v1/visual_review_shortlist_v1`。
