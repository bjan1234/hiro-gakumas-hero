# 初星助手 token 用量与花费统计（参考 ccusage）

2026-11-25 · 状态：待用户确认

## 为什么做

初星助手在三处调用大模型：对局里规则拿不准时的决策（`hiro.brain.*`）、认不出画面时的兜底（`hiro.loop.rescue`）、界面右侧的对话助手（Go，`app/agent.go`）。使用者自己出 API Key（缺省 DeepSeek），钱从他们账户里扣，但现在**完全看不到花了多少**：

- Python 侧每次调用其实已经算好用量（`hiro.brain.llm.LLMResult` 有输入 / 输出 / 缓存读 / 缓存写、`claude -p` 还给 `total_cost_usd`），只是散在各局 trace 的 `decision.llm` 里，没人汇总；兜底的用量连 trace 都没进。
- Go 对话助手解析回复时直接丢掉了 `usage`。
- 11-25 账号 3 打初星課題时发现：命令行确认的任务拿不到界面设置里的模型，悄悄退回 `claude:sonnet`（走本机 `claude -p`）。用户以为在用 DeepSeek，实际用的是 Claude。

用户要的（11-25 原话）：**每局花了多少钱最想看**，月度 / 日度汇总也要。

## 目标

1. **每局花费**：每个对局任务（hif / hajime / nia / tower）结束时，任务报告里写「本局调用模型 N 次、token 多少、约多少钱」，界面在报告卡上显示；`hiro run report <job>` 也给出同样的数。
2. **开局前心里有数**：开局确认卡上显示「同模式最近几局平均每局约多少钱」（有历史时）。
3. **汇总**（ccusage 的 daily / monthly / session）：`hiro usage daily | monthly | job | chat`，可按日期范围过滤、按模型拆分、`--json` 输出；设置页显示今天 / 本月的 token 和花费、按模型拆。
4. **模型来源一致**：命令行确认的任务和界面开的任务用同一个模型配置（修上面那个悄悄退回 claude 的问题）。

## 非目标

- 不扫 `~/.claude` / `~/.codex` 的会话日志（那是 ccusage 本身的做法；我们的 DeepSeek 调用在那里没有记录，自己记账更全）。
- 不做 ccusage 的 5 小时计费窗口（blocks）、实时监控、statusline。
- 不回填历史：这个功能上线之前的局不补算（旧 trace 里 `decision.llm` 有部分数据，但兜底和对话没有，补出来的数是残缺的，宁可不给）。
- 不做预算上限 / 超额停机（以后可以在流水账上加，这次不做）。

## 反目标（做了就是失败）

- 显示一个看起来准确、其实是猜的金额：价格表里没有的模型，花费显示「—」而不是 0 或估一个价。
- 统计本身影响对局：写流水失败只打日志，绝不抛出、不拖慢出牌（每次调用多一次文件追加）。
- 把 API Key、提示词、回复内容写进流水账。

## 设计

### 1. 一本流水账（所有调用写同一种格式）

位置：`HIRO_HOME/usage/YYYY-MM.jsonl`（按月分文件，追加写）。每次模型调用一行：

```json
{"v": 1, "id": "…", "ts": "2026-11-25T07:03:33.562+08:00",
 "source": "decision | rescue | chat",
 "job": "20261125-062938-df2d" | null, "thread": "t-1a20…" | null,
 "provider": "deepseek | claude-cli | codex-cli | openai-compatible",
 "model": "deepseek-flash",
 "input": 1234, "output": 56, "cache_read": 0, "cache_write": 0,
 "cost": 0.0021 | null, "currency": "CNY | USD" | null, "cost_source": "reported | priced | null",
 "ok": true}
```

- **id**：每次调用生成（uuid4）；Go / Python 各自生成。汇总时按 id 去重（ccusage 按 message id + request id 去重，同一思路：同一行被重复写也只算一次）。
- **job**：对局任务的子进程从环境变量 `HIRO_JOB_ID` 取（`Job.child_env` 新增注入任务 id）；对话助手里的调用 job 为空、thread 为对话 id。
- **token 字段口径**（沿用 `LLMResult` 已有口径）：input = 不含缓存命中的输入；cache_read = 命中缓存读进来的输入；cache_write = 写进缓存的输入（OpenAI 兼容服务没有这项，记 0）；output = 输出。四项相加 = 总 token。
- 失败的调用（超时、报错）也记一行，`ok: false`，有 usage 就记 usage（服务商对失败调用可能也计费）。
- 拿不到用量的调用（codex exec、不返回 `usage` 的 OpenAI 兼容端点）也记一行，四个 token 字段为 `null`；计入调用次数，汇总里写「N 次没有用量数据」。

写入方：

| 调用方 | 改动 |
|---|---|
| Python 适配器（`ClaudeCLI` / `CodexCLI` / `OpenAICompatible` 的 `ask_json` / `ask_json_image`） | 每次返回 `LLMResult` 前调用 `hiro.usage.record(result, source=…)`。source 由调用方传：决策层 `decision`、`rescue.py` 传 `rescue`。放在适配器层而不是各调用点，保证不会漏记。 |
| Go 对话助手（`OpenAICompat.Chat`，以及 `CLIAgent.Ask` 的 claude / codex 那条路，都在范围内） | 解析回复里的 `usage`（`prompt_tokens`、`completion_tokens`、`prompt_tokens_details.cached_tokens`）追加同格式的一行；claude 那条路改用 `--output-format json` 拿 `usage` 与 `total_cost_usd`（回复正文从 JSON 的 `result` 取）；codex 没有用量，记 token 为 null 的一行。`source: "chat"`；`thread` 为当前对话 id（`Ask` 要加参数把 thread id 传进去）。 |

并发：任务子进程、service、Go 主进程可能同时追加同一文件。每行用一次 `write` 追加（Python `open(..., "a")` 单次写完整一行；Go `O_APPEND`），单行远小于 PIPE_BUF，POSIX 下不会交错；Windows 上用文件锁（`hiro.cli.lock` 已有的锁）包住追加。

### 2. 花费怎么算（ccusage 的 auto 模式）

流水账里只存**用量**和**调用结果自带的费用**；按价格表算的钱一律在汇总时算（Go 读不到 Python 的价格表，两边各放一份又要同步，所以都不在写入时算）：

- 调用结果自带费用（`claude -p` 的 `total_cost_usd`）→ 写进行里 `cost` / `currency: "USD"`，`cost_source: "reported"`。
- 其余行写入时 `cost: null`；汇总时按价格表算：`input × 输入单价 + cache_read × 缓存命中单价 + cache_write × 缓存写单价 + output × 输出单价`。
- 价格表里没有 → 花费「—」，汇总里列出「N 次调用没有价格」。
- 价格表：`src/hiro/usage/prices.json`，**按 (provider, model) 查**（同名模型不同服务商不同价）；每项写每百万 token 单价、币种、官方价格页 URL、核对日期。不联网拉（ccusage 默认拉 LiteLLM；我们离线、可审计）。价格变了会影响旧账的估算，报告里写「按 <核对日期> 价格估算」。
- provider：Go 的 preset id（deepseek / kimi / qwen / glm / openai / openrouter / custom / claude / codex）原样写；Python 侧由 `OPENAI_BASE_URL` 的域名反推同一套 id（反推不出 → `openai-compatible`，必然没价格）。
- model：记**请求时用的模型名**，查价前按 Go `legacyDeepSeek` 同样的别名表归一（`deepseek-chat` / `deepseek-reasoner` → `deepseek-flash`）。

**Claude / Codex 订阅**：`claude -p` 的 `total_cost_usd` 是 API 等价价，订阅用户并不按它付钱。这类行在报告里单独写「Claude 订阅（不另收费，折合 API 约 $x）」，**不并进「花了多少钱」的合计**；codex 没有用量数据，只计次数。

币种：DeepSeek 国内站按人民币，其他多按美元。**不做汇率换算**；合计按币种分开显示，例如「¥0.42 + $0.03」。

### 3. 汇总（ccusage 的报表）

新模块 `hiro.usage`：读 `usage/*.jsonl` → 去重 → 按维度分组。

命令（进 `hiro tools` 清单，对话助手也能调）：

```
hiro usage daily   [--since YYYY-MM-DD] [--until …] [--breakdown] [--json]
hiro usage monthly [同上]
hiro usage job <job-id>          # 一局：按来源（决策 / 兜底）和模型拆
hiro usage chat [<thread-id>]    # 对话助手：按对话
```

每行：调用次数、input / output / cache_read / cache_write / 合计 token、花费（按币种）、没价格的调用数。`--breakdown` 再按模型展开（ccusage 同名选项）。

### 4. 每局花费（用户最想看的）

- 任务结束时 `hiro.cli.report.summarize` 增加 `usage` 段：`{calls, tokens: {...}, cost: {"CNY": 0.42}, unpriced_calls, by_source: {decision: …, rescue: …}, by_model: {…}}`（从流水账按 job id 取）。
- 任务的 `report` 事件带上这一段，**没有考试成绩的局也发**（现在 `service._exited` 只在有成绩行时发，要改成总是发）；界面报告卡（游戏运行现状 / 对话里的结束卡）加一行：**「本局模型：12 次 · 3.4 万 token · 约 ¥0.42」**；没有调用时写「本局没有调用模型」。
- 任务结束时把这一局的 `usage` 段写进任务目录 `usage.json`（之后不再变）；`hiro run status` 的最近任务列表直接读它带上 `cost`（不在每次轮询时扫流水账）。
- 开局确认卡：同 kind + 同实际难度（params 里的 difficulty，空则取该 kind 的缺省难度）最近 5 局有 `usage.json` 时，加一行「最近 5 局平均每局约 ¥0.38」；没有历史不显示。

### 5. 设置页

设置页（`app/plugins/settings`）加「用量」一节：今天、本月各一行（调用次数、token、花费），下面按模型拆（模型名、次数、token、花费），底部一行「花费按价格表估算，以服务商账单为准」。

### 6. 修：命令行确认的任务也用界面设置的模型

现状：`cmd_run` 只从确认那个进程的环境变量里取 `HIRO_LLM` 等（`LLM_VARS`），界面会注入，命令行确认（`hiro confirm`）不会 → 任务退回 `claude:sonnet`。

改：`Job.child_env` 里，`_llm_env` 为空且没有显式关模型时，按 `HIRO_HOME/settings.json`（provider / model）+ `HIRO_HOME/model-keys.json`（Key，已有，权限 600）推出同样的环境变量（与 Go `assistant.go` 的 `LLMEnv` 规则一致：deepseek → `HIRO_LLM=openai:<model>` + `OPENAI_BASE_URL` + `OPENAI_API_KEY`；claude → `claude:sonnet`；codex → `codex`；none → `off`）。Python 侧复制 Go `LLMEnv` 的**整张** preset 表（含 kimi / qwen / glm / openai / openrouter / custom 的 base_url）。用例写成一份共享 JSON（`app/testdata/llm_env_cases.json` 之类），Go 和 Python 的测试都读它，保证两边规则一致。`settings.json` 不存在（纯命令行用户）时保持现在的行为（退回 `claude:sonnet`）。

## 交给实现的部分

- `hiro.usage` 的模块划分、函数名、表格的具体排版。
- Go 侧追加行用的小工具放哪个包。
- 价格表初始收哪些模型：至少 `deepseek-flash`、`deepseek-v4-pro`（缺省 / 设置页可选的两个）、Claude 当前几款、OpenAI 兼容常见几款；单价以实现当天官方价格页为准。
- 界面文字的细节（遵循 `app/DESIGN.md`）。

## 验收

1. 实机打一局（DeepSeek，有兜底调用）：结束卡显示本局次数 / token / 约多少钱，与 `hiro usage job <id>` 一致；与 DeepSeek 控制台当天用量对得上量级。
2. 对话助手聊几句：`hiro usage chat` 有记录，设置页今天的数增加。
3. 命令行 `hiro run start hajime … && hiro confirm …` 开的任务，用的是设置页的模型（任务日志 / 流水账里 provider 是 deepseek）。
4. 写流水的目录不可写时，对局照常进行，只有一条警告日志。
5. 价格表没有的模型：显示「—」，汇总里列出未定价调用数。

## 我的判断（用户可推翻）

- 按价格表算的钱都在汇总时算（Go 不放第二份价格表）；价格变了旧账估算跟着变，报告写明按哪天的价格。
- 价格按 (provider, model) 查；model 记请求名、按别名表归一；Python 由 base_url 反推 provider。
- Claude / Codex 订阅的调用不并进「花了多少钱」，单独写「订阅，折合 API 约 $x」。
- 拿不到用量的调用照记一行（token 为空），计次数。
- 对话助手的 CLI 路径（claude / codex）也在范围内；claude 改用 JSON 输出拿用量。
- 每局用量在结束时写进任务目录 `usage.json`，任务列表和「最近 5 局平均」读它，不每次扫流水账。
- 没有考试成绩的局也发报告（带用量）。
- 第 6 节 Python 复制 Go 整张 preset 表，两边共用一份用例；没有 settings.json 时保持退回 claude。

- 自己记流水账，不读 `~/.claude` 日志；不回填上线前的旧局。
- 价格表内置、离线，不联网拉 LiteLLM。
- 不做汇率换算，按币种分开显示。
- 每局花费放在任务报告 / 结束卡；开局确认卡显示最近 5 局平均。
- 第 6 节（命令行确认也用界面模型）一起做，因为不修它「每局花费」会把 Claude 订阅的调用算进来、让用户误以为在用 DeepSeek。

## 来源

- 11-25 设计审阅（builder check，sonnet 子代理）提出的 7 个问题都已按上面「我的判断」写进各节。

- 本对话 11-25：用户要求「逻辑参考 ccusage」「每局花了多少钱最想看，日 / 月汇总也要」。
- 11-25 账号 3 实测：本会话 Claude Code 自身约 2.65 亿 token；初星助手的 6 次兜底调用实际走了 `claude -p`（Sonnet），合计约 2.3 万 token，DeepSeek 0 次 —— 第 6 节的来由。
