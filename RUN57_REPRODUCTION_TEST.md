# run57 迁移与复现测试

日期：2026-07-03

## 结论

迁移成功。历史 run57 的**最终视觉结果可以复现**：5 个原型的 `terminal_lineart.svg` 和 `terminal_lineart_preview.png` 均与冻结 run57 快照 SHA-256 完全一致。

严格 JSON 字节比较为 2/5 完全一致；另外 3 个 JSON 只在诊断字段 `composition_candidate_count` 上不同，最终 motifs、叶片数、coverage、SVG 和 PNG 均一致。

## 实际迁移

- 5 个 baseline SVG：`data/baselines/sw/`
- 8 个当前核心源码：`src/chanzhi_sw/`
- 40 个 run28→run56→run57 回归快照：`tests/fixtures/reference_only/run57_snapshot/`
- 6 个历史 Python 3.11 字节码：`legacy/run57_exact/runtime/`
- 合计：59 个迁移资产，约 4.97 MiB。

## 测试一：当前源码完整四阶段运行

输入仅为迁移后的 5 个 baseline SVG，没有读取冻结 run JSON。

- 5 个原型的 skeleton profile、region graph、branch layout、branch geometry 共 20 项，在归一化绝对路径后与历史 run28/run56 快照全部一致。
- 当前 `src/chanzhi_sw/chanzhi_terminal_renderer.py` 对 `proto_sw_1_1` 生成 `valid=true`，但结果不同：motifs `25 vs 17`、leaves `42 vs 43`、coverage `0.756952 vs 0.847104`。
- 因首例已否定“当前源码等于历史 run57”，停止其余长时间终端搜索。

结论：漂移只在终端 renderer；当前 6 月 17 日源码不是生成历史 run57 的精确版本。

## 测试二：历史 run57 Python 3.11 字节码

使用迁移后的历史 `chanzhi_terminal_renderer.pyc`，输入为测试一重新生成的 profile/layout/geometry。

| 原型 | SVG SHA-256 | PNG SHA-256 | SVG/PNG 一致 | JSON 情况 |
|---|---|---|---|---|
| `proto_sw_1_1` | `e59aa4f640e0375774f6c6d55a8691525c23d966f2f1968e56b1a6f1d4bd2738` | `741b42d8c9e63661040ba0468ad43bdfba4b9a2c6f00ab49aeb756541b8f3245` | 是 | 字节一致 |
| `proto_sw_1_3` | `ea1c09b77e1d9a985935e650cabfd52eb29c1aa4bef54548545bfd45401f3ffd` | `9e3953baaf7f7d1d4d37fbe5f2ea95679abd4e1eebb195c0e179c471ca30ca21` | 是 | 仅 candidate count `460 vs 463` |
| `proto_sw_2_3` | `e4485c995587f91c1e82349ea23662406a5ed3209927daa40414a3d490959ec7` | `210d8be000a7ed1b664751c6f41351815ff860910bc1e355037da83cdfce2edd` | 是 | 仅 candidate count `292 vs 293` |
| `proto_sw_3_1` | `0cbcd73b91357c0666c4501f399bfd67aeeb4e137f7412450fcccdbc8be31474` | `0915973db2d19413df5d50deaa588096968f312db93dad3074d6036d0794cd59` | 是 | 字节一致 |
| `proto_sw_3_2` | `b02fd88736546b48d98c8e5158c058080ad9a5221dc0ee553d0302e43fa441aa` | `3bb15ce410bbdfa929f3397930690779931a811ec7e7a788b60ecd4dcc7ec38f` | 是 | 仅 candidate count `761 vs 770` |

所有测试进程退出，stderr 均为空。

## 后续优化边界

1. `legacy/run57_exact/runtime/*.pyc` 是取证基线，不是可维护主代码。
2. 下一步应恢复/重建历史终端 renderer 的可读源码，并以 5 个 SVG/PNG 哈希作为 golden regression gate。
3. 优化从该可读源码分支开始；每次变化必须明确是“预期改进”，不得静默覆盖 run57 baseline。
4. `run57_adapter.py` 不参与该复现链，也不得进入主代码。
