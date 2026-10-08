# 任务资源预算与费用估算

`run`、`evaluate`、`compare` 和 `resume` 支持以下参数，默认不设置额外限制：

| 参数 | 含义 |
|---|---|
| `--max-tokens` | 每个任务累计的已报告总 Token 上限，正整数 |
| `--max-seconds` | 每个任务累计 Agent 执行时间上限，正数 |
| `--input-price` | 每百万输入 Token 单价，非负 |
| `--output-price` | 每百万输出 Token 单价，非负 |
| `--currency` | 用户指定的币种标签，提供单价时必填 |

```powershell
python -m fixlab evaluate benchmarks --task-id addition --backend docker --max-steps 12 --max-tokens 50000 --max-seconds 300
python -m fixlab resume .fixlab/evals/<批次ID>/addition/state.sqlite --max-tokens 100000 --max-seconds 600
```

预算按任务计算；批量或对照评测中的每个任务各自拥有额度，并非整个批次共享。续跑默认继承保存的限制，Token 与 Agent 耗时跨续跑累计；显式传入新值会更新对应上限，未传入的项继续保留。`resume --inspect` 显示保存的预算。旧任务没有预算配置时保持原行为。

## 停止与恢复语义

这是协作式上限：在模型请求（含重试）、工具操作和完成检查之间检查预算，不中断正在执行的文件写入、测试或网络请求。当前操作可能让实际用量超出上限；Token 限制依据服务返回的 usage，不提前估算输入或截断输出，因此不保证硬性费用封顶。请求仍有 90 秒超时，测试仍有 30 秒超时。

计时范围与 `execution_seconds` 一致，为 Agent 循环运行时间，包括模型、工具及循环中的完成检查。不包括启动前的 Docker 检查、基线验收、循环结束后的最终验收及报告写入，也不包括两次续跑之间的等待时间；不是严格的整个进程墙钟时限。达到限制后仍执行最终验收并保存报告。

返回 `agent_status=budget_exhausted`，`budget_stop_reason` 分别为 `max_steps`、`max_tokens`、`max_seconds` 或 `token_usage_unknown`。预算停止不代表补丁已成功：`repair_success` 仍要求 Agent 正常完成及验收通过。已保存但尚未执行的工具请求可在提高预算后继续执行；已经完成的工具不会重放。

启用 Token 限制时，如果某次请求缺少总 Token 用量或曾发生失败请求（可能计费但用量未知），停止后续请求，原因是 `token_usage_unknown`。提高数字不能消除用量未知的事实。默认停止；如明确接受统计不完整，可用 `--unknown-usage allow` 续跑。本模块不清除历史记录。

## 费用字段

同时提供两项单价与币种后，报告中的 `cost.estimated_amount` 为已知输入和输出 Token 的估算费用。`cost.complete=false` 表示缺失用量、请求重试或执行异常；不能将它视为实际总账单。未指定单价时 `cost=null`。币种不做汇率转换，缓存命中价、阶梯价格、折扣和其他计费项目未计算，实际费用以服务端账单为准。单价由用户填写，项目不内置供应商价格。

例如：`--input-price 1 --output-price 2 --currency CNY` 仅演示参数格式，**不是任何模型的实际报价**。

本模块的离线测试覆盖耗尽前拦截写文件、累计续跑、时间耗尽、未知用量、失败请求、费用标记及 CLI 参数传递，不调用付费模型。


## 断连后的显式恢复

`--unknown-usage stop` 是新任务默认策略；`--unknown-usage allow` 允许存在失败请求或缺失 usage 时继续。策略保存在任务预算中，后续续跑继承，可显式切回 stop。状态库的 usage_policy 事件记录策略变更。

allow 不清除失败请求、不补造 Token 数，也不重置累计额度。已知 Token 上限、时间和步数限制仍生效；真实费用可能超过已报告用量对应的估算。每次模型调用仍最多尝试 3 次，沿用 1、2 秒退避，不无限重试。

```powershell
python -m fixlab resume .fixlab/evals/<批次ID>/<任务ID>/state.sqlite --unknown-usage allow --max-steps 30 --max-tokens 200000 --max-seconds 900
```

新增 api_request 事件记录请求开始 UTC 时间、请求体字节数、消息条数、90 秒超时设置，以及结束后的耗时和成功/异常类型；不记录密钥、请求正文或原始异常文本。旧请求不能补录诊断字段。发生进程强制终止时可能只有 started 事件。
