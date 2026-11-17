# 初 / N.I.A 机制说明

这篇讲初（定期公演『初』）和 N.I.A（NEXT IDOL AUDITION）培育的规则和数值。写决策、写模拟器时查这里。打法放在 [hajime-playbook.md](hajime-playbook.md) 和 [nia-playbook.md](nia-playbook.md)。

每条后面标了出处，代号是：

- 〔主〕：主数据。快照是 gakumasu-diff `d31baf6`，读取方式是 `vendor/gakumas-player` 的 `Catalog`。
- 〔社〕：社区攻略，后面跟原文代号（例如 g8-PRO、ww-初M），原文摘录和链接见文末。
- 〔GK〕：GKMSProject（yuzeis）的实测。他们是对着服务器录到的整局数据核出来的，文件是 `GakumasCLI/produce/nia_produce.py`、`nia_route.py`。
- 〔实〕：我们自己在 Mac 账号 2 上跑出来的（篠澤広 Campus mode!!，2026-11-17）。
- 〔推〕：推断，还没核对，用的时候要小心。

模拟器是 `vendor/gakumas-player/gakumas_produce/hajime_nia.py`，测试是 `tests/test_hajime_nia_sim.py`。下文提到的函数都在这个模块里。

## 1. 模式总表

| produce | 模式 | 周数 | AP | 属性上限 | 考试 | 过关名次 | 设置 |
|---|---|---|---|---|---|---|---|
| produce-001 | 初 レギュラー | 13 | 15 | 1000 | 中間 + 最終 | 前 3 | p_setting-1 |
| produce-002 | 初 プロ | 16 | 20 | 1500 | 中間 + 最終 | 前 3 | p_setting-2 |
| produce-003 | 初 マスター | 18 | 20 | 1800 | 中間 + 最終 | 前 3 | p_setting-3 |
| produce-006 | 初 レジェンド | 18 | 20 | 3000 | 中間 + 最終 | 前 3 | p_setting-6 |
| produce-004 | N.I.A プロ | 27 | 20 | 2000 | 1 次 / 2 次 / 最終オーディション | 第 1 | p_setting-4 |
| produce-005 | N.I.A マスター | 26 | 20 | 2600 | 同上 | 第 1 | p_setting-5 |

以上全部来自〔主〕：`Produce`、`ProduceStepAuditionDifficulty.rankThreshold`、`Produce.idolCardParameterGrowthLimit`。

初的四档共用评价组 `produce_group-001`，N.I.A 用 `produce_group-002`。家族靠 produce id 区分，因为 `Produce.name` 里初和 N.I.A 都叫「プロ」「マスター」，从名字分不出来。这个映射写在 `hiro.state.modes`。

## 2. 培育设置（ProduceSetting）

| 字段 | 初（p_setting-1） | N.I.A（p_setting-4 / -5） | 含义 |
|---|---|---|---|
| refreshStaminaRecoveryPermil | 700 | 700 | 休息回最大体力的 70%，向下取整（最大 23 回 16，和 g8-休 一致） |
| beforeAuditionRefreshStaminaRecoveryPermil | 700 | 500 | 试镜前一周休息的回复比例；N.I.A 只有 50%〔GK〕 |
| stepSkipStaminaRecoveryPermil | 250 | 250 | 跳过一周回 25% |
| produceDrinkPossessLimit / MaxLimit | 3 / 4 | 3 / 4 | 饮料能拿 3 瓶，有道具时最多 4 瓶 |
| continueCount | 3 | 3 | 每场考试最多再挑戦 3 次 |
| customizeProduceCardCount | 1 | 1 / 2 | 一次特別指導能定制几张；MASTER 是 2 张，和 ww-NIAM 一致 |
| produceAuditionTrendAssessmentPermilUpper/Lower | 200 | 200 / 110 | 审查基准的上下浮动，含义〔推〕 |

## 3. 评价

### 3.1 初

```
评价 = floor(属性和 × 2.3) + 名次分 + 最終試験分数的分段折算
```

- 拿第 1 名时，每项属性先 +30，然后再算属性和〔社 ww-初M〕。属性和不会超过各项的上限。
- 名次分：第 1 名 1700〔社 + 核对〕。第 2 名 900、第 3 名 500 是〔推〕，还没对过。
- 分数折算的斜率按分段算：0–5000 段 0.30，5000–1 万段 0.15，1–2 万段 0.08，2–3 万段 0.04，3–4 万段 0.02，4 万以上 0.01。
- 核对方法：拿 ww-初M 的分数线表（属性和 3010 / 3410 时 A+、S、S+ 各要多少分）代进去算，各档都落在 11500 / 13000 / 14500 上，误差不超过 1 分。测试是 `test_hajime_evaluation_matches_wiki_table`。
- 档位阈值〔主 ProduceGrade〕：A 10000、A+ 11500、S 13000、S+ 14500、SS 16000、SS+ 18000、SSS 20000、SSS+ 23000、SSSS 26000。
- 实现：`hajime_evaluation(params, final_score, rank, cap)`。

### 3.2 N.I.A

```
评价 = floor(属性和 × 2.3) + floor(票数 × m + c)
```

票数对应的 (m, c) 按区间取〔GK，出处是学マスwiki「最終プロデュース評価」；GKMSProject 拿 9 局录到的结算逐分核对过〕：

| 票数 | PRO m / c | MASTER m / c |
|---|---|---|
| ≤ 2 万 | 0.100 / 0 | 同 |
| ≤ 4 万 | 0.085 / 300 | 同 |
| ≤ 6 万 | 0.070 / 900 | 同 |
| ≤ 8 万 | 0.065 / 1200 | 同 |
| ≤ 10 万 | 0.060 / 1600 | 同 |
| > 10 万 | 0.055 / 2100 | ≤ 12 万 0.050 / 2600，≤ 14 万 0.040 / 3800，再往上 0.030 / 5200 |

- 属性按上限截断：PRO 2000，MASTER 2600。
- 实现：`nia_evaluation(params, votes, produce_id, cap)`。
- 〔实〕我们 N.I.A PRO 那局的评价是 A 11,475，但结算页的属性和票数没截图，所以这局还不能拿来核对公式。下一局要截结算页。

## 4. 初的课程

### 4.1 每节课的回合数、过关线、满分线

数据来自 `ProduceStepLesson` → `ProduceStepLessonLevel`〔主〕。字段对应关系：`limitTurn` 是回合数，`successThreshold` 是过关线，`resultTargetValueLimit` 是满分线，也就是这节课属性收益的上限。

主数据有三种写法：

- REGULAR / PRO：按角色和属性写，例如 `p_step_lesson_level-001-shro-sp-da-002`。最后的序号表示这是第几次上这种课。
- MASTER：只有追い込み，按考试流派写，例如 `p_step_lesson-produce-003-exam_card_play_aggressive_01-hard-01`。这份快照里**没有 MASTER 通常课和 SP 课的行**（缺口）。
- LEGEND：按流派写，三项属性共用，例如 `p_step_lesson-produce_006-card_play_aggressive-sp-03`。

篠澤広属于 plan2、やる気流派（aggressive），下表是她的课程，格式为「回合 / 过关线 / 满分线」：

| 模式 | 通常（第 1、2、3…次） | SP | 追い込み |
|---|---|---|---|
| REGULAR | 6/25/50、6/25/50、7/40/80、7/40/80 | 6/40/80、7/70/140、7/70/140 | 9/75/300、9/100/400 |
| PRO | 6/30/60、6/30/60、7/55/110、7/60/120、7/75/150 | 6/45/90、7/85/170、7/100/200、7/110/220 | 9/90/360、11/165/600 |
| MASTER | （快照里没有） | （没有） | 9/90/360、11/165/600 |
| LEGEND | 8 回合，满分 120/160/240/380/630 | 8 回合，满分 160/210/310/460/710 | — |

- 通常课和 SP 课，plan2（含 aggressive）比 plan1 多 1 回合，过关线和满分线一样；追い込み两者相同〔主〕。
- REGULAR 一共能上通常课 4 次、SP 课 3 次、追い込み 2 次。PRO 是 5 / 4 / 2 次。SP 课是在通常课那一周按概率替换出来的〔社 g8-SP〕。
- PRO 有「追加レッスン」：授業有时会派生出一节课，7 回合，过关 45、满分 90〔主 school-event〕。

### 4.2 收益

- 属性收益 = 基础值 + floor(基础值 × 加成)〔推，套用 GK 的 N.I.A 自主课公式〕。基础值是这节课打到的分数，最多到满分线。加成按画面读数的写法记，1472 表示 +47.2%。实现是 `grow()`，〔实〕还没逐节核对过。
- 打满（パーフェクト）以后课就结束了，剩下几回合，每回合回 2 体力〔社 g8-レッスン〕。
- 追い込み：达到目标以后进入「追い込みボーナス」，这段时间多涨的属性在下课时平分到三项〔社 g8-レッスン〕。模拟器用 `oikomi_extra` 参数表示这部分。
- 体力消耗取决于怎么出牌，主数据里没有。模拟器的 `stamina_used` 必须由调用方给。

### 4.3 考试（初）

| 模式 | 中間 基础分 / 封顶 | 最終 基础分 | 名次 |
|---|---|---|---|
| REGULAR | 600 / 900 | 2450 | 前 3 |
| PRO | 1150 / 1700 | 6950 | 前 3 |
| MASTER | 1380 / 不封顶 | 8340 | 前 3 |

以上是篠澤広的数据，来自 `ProduceStepAuditionDifficulty`〔主〕。中間打到封顶分就直接结束。〔实〕REGULAR 中間打了 900 分，第 1 名。

## 5. N.I.A 的周行动

### 5.1 自主レッスン（不打牌）

| 阶段 | 通常 体力 / 属性 | SP 体力 / 属性 | P 点 |
|---|---|---|---|
| 1 次试镜前 | 6 / 80 | 8 / 100 | +20 |
| 2 次试镜前 | 6 / 100 | 8 / 120 | +25 |
| 最终试镜前 | 6 / 120 | 8 / 150 | +30 |

- 体力和属性〔主 ProduceStepSelfLesson〕。主数据只有 produce_004 的这 6 行，MASTER 共用。P 点〔社 ww-NIA〕。
- 属性收益 = 基础值 + floor(基础值 × 加成)〔GK，7 节课里 7 节对上〕。
- 体力门槛：g8-NIA 原文是「体力が消費体力以下だとレッスンが行えません」，按字面，体力等于消耗时也不能上；g8-NIAM 写的是「営業後の体力が 8 以上」。两种说法对不上，模拟器按严格的读法（体力 ≤ 消耗就不能上）。〔实〕待核对。

### 5.2 営業

| 场所（颜色） | 主数据 id 里的写法 | 投票（1 次前 / 2 次前 / 最终前） | 附带 |
|---|---|---|---|
| 商業施設（紫） | produce_card | 2400 / 3200 / 4000 | 技能卡已强化 |
| 企業イベント（青） | produce_drink | 同上 | 饮料 |
| 自治体イベント（黄） | produce_point | 同上 | P 点 +50 |
| リゾート施設（绿） | stamina | PRO 1700 / 2200 / 2800，MASTER 2200 / 2900 / 3700 | 体力 +10 |

- 投票数〔主 ProduceStepEventDetail〕。大成功用 `-ex` 那一行，正好是 1.3 倍（例如 3120 / 4160 / 5200）。〔实〕画面上看到的「大成功ボーナス」+720、+960，就是多出来的那 30%。
- 选项涨的属性：PRO 60 / 80 / 100，MASTER 80 / 110 / 130，**不吃加成**〔主 ProduceStepEventSuggestion；GK〕。三个选项分别涨 Vo、Da、Vi，选哪个就涨哪项。
- 实际到手的投票 = 票数 × (1000 + 支援卡营业投票加成‰) / 1000〔GK〕。
- 体力：多数选项扣 5〔GK，实录 business_list〕，主数据里这个字段是 0。ww-NIA 说企業不扣体力，GK 说「多数」扣 5，两边都还没核对。
- 大成功的概率看属性合计：1 次前合计 ≥ 798、2 次前合计 ≥ 1468 时是 100%〔社 ww-NIA，PRO〕。最终段原文说概率曲线有 bug，没给数字。
- 〔实〕这一页认场所靠图标和颜色，不靠文字；用户定的规矩是「场所没读出来不重要，重点是匹配图标和对应的属性」。

### 5.3 オーディション（选档）

篠澤広 PRO〔主〕，格式为「要先攒到的票数 / 基础分」：

| 场次 | 第 1 档 | 第 2 档 | 第 3 档 | 第 4 档 |
|---|---|---|---|---|
| 1 次 | 0 / 1000 | 4000 / 1600 | 9000 / 2150 | — |
| 2 次 | 0 / 6400 | 14000 / 10300 | 25000 / 19500 | — |
| 最終 | 0 / 12800 | 28000 / 20400 | 40000 / 32550（亲爱度 14） | 57000 / 58150（亲爱度 17） |

MASTER：1 次 0 / 11000 / 13000 票，2 次 0 / 31000 / 38000 票，最終 0 / 51000 / 55000 / 62000 票〔主〕。

- 每档都要拿第 1 名才算过。
- 档名用的是中文补丁的叫法〔GK〕：1 次 Music Order / Harmony To Night / 节奏Bang！；2 次 MELODY Journey / POP Fair / GAL★AXY音乐；最终 Single Cut / IDOL Big Up！ / QUARTET / FINALE。
- 〔实〕我们那局：1 次选了 ToNight（第 2 档），2 次选了 POP Fair（第 2 档），最终选了第 2 档（IDOL Big up!，门槛 28,000，我们当时 36,036 票），三场都是第 1 名。
- 试镜奖励（票数、属性）随得分变化：属性按审查基准排名封顶（PRO 1 次 92 / 75 / 62，2 次 119 / 98 / 80，最终 172 / 145 / 116），票数是一条按得分取对数的单调曲线〔GK，拟合的录制点〕。模拟器不推算这两项，由调用方填结算画面上的数字。
- 衰减线：最终试镜的分数超过 PRO 约 20 万、MASTER 约 65 万以后，投票数大幅减少〔社 g8-NIAM〕。
- 試験后的 P 道具三选一：见 [nia-playbook.md](nia-playbook.md)。

### 5.4 其它周

| 行动 | 效果 | 出处 |
|---|---|---|
| 休む | 回最大体力 70%，试镜前一周 50%；最多 4 次 | 〔主〕〔社 g8-NIA〕 |
| お出かけ | 回体力，带删卡、强化或换卡选项；三个选项的内容几篇攻略说法不一 | 〔社〕 |
| 差し入れ | 和以前的活動支給差不多，给不给 P 点看概率 | 〔社 g8-NIA〕 |
| 特別指導 | 定制技能卡（カスタマイズ），PRO 一次 1 张、MASTER 2 张 | 〔主〕〔社〕 |
| 相談（商店） | 买卡、买饮料、删卡、强化；N.I.A 价格原文没写 | 〔社〕 |

## 6. 初的周行动

| 行动 | 效果 | 出处 |
|---|---|---|
| 授業 | 扣体力，涨的属性和数值随机（20 / 30 / 40 / 55 / 80 / 110）；PRO 起可以选「トラブル追加」，往牌堆塞一张眠気，换这个授業的最高值 | 〔社 g8-授業〕 |
| 活動支給 | 给 P 点、饮料或卡；MASTER 有几周强制踩 | 〔社〕 |
| お出かけ | 花 P 点回体力，带饮料或卡。例：100P 回 40%，50P 回 20%，0P 回 30% | 〔社 g8-外出〕 |
| 相談 | 删卡、强化：PRO 第 1 次 100P、第 2 次 125P | 〔社 g8-PRO〕 |
| 休む | 回最大体力 70%，体力满的时候不能选 | 〔主〕〔社 g8-休〕 |

## 7. 周表

主数据里没有周表，日程是服务器下发的。现在已知的情况记在 `vendor/gakumas-player/data/schedules/hajime_nia.json`：

- **初 MASTER**：完整。三种周表随机抽一种，第 3、4、6、9、10、12 周三种不一样；第 7 周追い込み、第 8 周中間、第 17 周追い込み、第 18 周最終〔社 ww-初M〕。`calendar("produce-003", pattern)` 能取到。
- **初 REGULAR**：不完整。已知 13 周、通常课 4 次、SP 3 次、追い込み 2 次〔主〕；g8 推荐第 4、7、11 周外出，SP 可能出现在第 1、3、9、10 周〔社，原文没标难度〕。用实机 trace 补全的工作正在做。
- **初 PRO**：不完整。g8 说 PRO 的周表每个偶像不一样，原文是图片。
- **N.I.A PRO**：不完整。第 9、18、27 周是试镜〔社 g8-NIA〕。ww-NIA支 给了各种行动的次数：自主课 8、営業 7、お出かけ 5、特別指導 4，加 3 场试镜正好 27 周。〔实〕每周固定一种主行动，休む 一直可选，例如「休む + 三属性自主课」「休む + 営業」「休む + 特別指導」「休む + お出かけ / 相談 / 差し入れ」。
- **N.I.A MASTER**：不完整。比 PRO 少一周，去掉的是 PRO 第 16 周的自主课〔社 ww-NIAM〕。

`calendar()` 只给 complete=true 的模式（目前只有初 MASTER）。其它模式会抛 `Unsupported`，不会拿猜出来的周表冒充完整的。

## 8. 模拟器能做什么、不能做什么

能做：

- `rules(produce_id, idol_card_id)`：读出这个偶像卡在这个模式下的全部主数据规则，包括课程、自主课、营业、考试档位、评价阈值和培育设置。
- `Sim`：一周一周推进状态（体力、P 点、三项属性、票数、上课次数、休息次数），规则不允许时抛 `Unsupported`。会拦下的情况有：体力不够、试镜档位票数不够、满体力休息、超出周数、N.I.A 里调用初的动作等。
- `evaluation()`：按 3.1 / 3.2 的公式算最终评价和档位。

不做（必须由调用方给，或者交给别的模块）：

- 打牌：考试和初的课程分数用 `gakumas_exam` 或 UINet 去打，或者用实机读数。
- 随机结果：授業涨什么、SP 课出不出、事件、支援卡和 P 道具的触发、营业会不会大成功。
- 试镜结算的票数和属性奖励（见 5.3）。
- 卡组和饮料的增减。

## 9. 缺口

1. 初 REGULAR、PRO 和 N.I.A 两档的逐周表。要从实机 trace 补，或者截游戏里的日程页。
2. 初 MASTER 通常课和 SP 课的主数据行（这份快照里没有）。
3. 初第 2、3 名的名次分（900 / 500 是推的）。
4. N.I.A 营业的体力消耗（5 是 GK 的实测，企業扣不扣体力两边说法不一）、最终段的大成功概率。
5. N.I.A 自主课的体力门槛，「体力等于消耗」时能不能上。
6. N.I.A 试镜结算的票数和属性曲线，只有 GK 用录制点拟合的结果，我们自己还没有数据。
7. 初课程收益公式没有逐节核对（N.I.A 自主课 GK 核过）。

## 出处

- 社区原文摘录：`~/github/digital-hiro/.temp/plans-20261112/初与NIA-攻略摘录.md`（16 篇，game8 和 wikiwiki，各条都标了原文代号）。原文文本在同目录的 `hajime-nia-sources/`。
  - g8-PRO <https://game8.jp/gakuen-idolmaster/610357>、g8-NIA <https://game8.jp/gakuen-idolmaster/661665>、g8-NIAM <https://game8.jp/gakuen-idolmaster/688368>
  - ww-初M <https://wikiwiki.jp/gakumas/初_マスター育成>、ww-NIA <https://wikiwiki.jp/gakumas/N.I.A立ち回り>、ww-NIAM <https://wikiwiki.jp/gakumas/N.I.Aマスター/基本>
- GKMSProject：`~/github/digital-hiro-research/ext/GKMSProject/GakumasCLI/produce/nia_produce.py`、`nia_route.py`、`scenario/nia.py`（41c8778）
- 实机：`~/github/digital-hiro/.temp/nia-mac/`、`~/github/digital-hiro/.temp/hajime-mac/`，trace 在集成 worktree 的 `traces/20261117-*`
