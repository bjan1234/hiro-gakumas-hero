# 引擎数据

考试引擎 `gakumas_exam` 和培育层公式 `gakumas_produce` 读的数据。

## 主数据（master）

来源：社区提取的 master 数据 [vertesan/gakumasu-diff](https://github.com/vertesan/gakumasu-diff)，固定到某个提交，不自动追随 main。不声称官方提供，也不保证和本机客户端逐表一致。

- `master/<提交>/source-files.json`：这个提交要下载的 YAML 清单（随仓库提交）。
- `master/<提交>/raw/*.yaml.gz`、`manifest.json`、`catalog.sqlite`：下载和构建产物，不进仓库。`catalog.sqlite` 是运行时查询用的索引，每条原始记录以 JSON+zlib 保存，卡牌另有名称 / ID / 强化等级索引。
- `master/current.json`：当前用哪个快照，以及数据库和 manifest 的 SHA256（构建时写，不进仓库）。

下载并构建（setup 脚本会做；构建要 PyYAML，运行时只用标准库）：

```bash
python vendor/gakumas-player/scripts/fetch_master.py [提交]
```

默认提交写在 `scripts/fetch_master.py` 的 `DEFAULT_COMMIT`。升级快照就新建一个提交目录，重跑上面的命令，再跑全量测试。

卡牌主键是 `(id, upgradeCount)`；`ProduceCard.order` 是图鉴显示顺序，不能当运行时牌堆的排序键。定制表同一 ID 可能对应多个 `customizeCount`，评分表同一 ID 对应多个属性节点；单行查询遇到歧义会拒绝，要拿完整组用 `Catalog.by_id()`。

## 其余数据（随仓库提交）

- `schedules/hif.json`：H.I.F 日历（选拔 20 步、本战 9 步）、可选行动、训练 master 引用和数据来源。逐日行动来自[社区 H.I.F 观察表](https://seesaawiki.jp/gakumasu/d/H.I.F)，不是 `ProduceStepTransition`。
- `community/hif-wiki-tables.json`：社区 wiki 原始表格单元格，包含合并行列信息。
- `community/hif-community-20261030.json`：社区攻略核对快照（`gakumas_produce.community_rules` 的数值来源）。
- `openings/campus-20261019/{r1,r2}-opening.json`：实机考试开局快照，`hiro.sim` 合成考试开局的模板。
- `multiplier-observations.json`：实机倍率观测（`gakumas_produce.multiplier` 校验用）。
