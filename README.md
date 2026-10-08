# FixLab

可恢复、可评测的代码修复 Agent Harness，支持 Docker 测试隔离、API 重试、需求自检和独立隐藏验收。

## 安装与配置

```powershell
conda create -n fixlab python=3.11 -y
conda activate fixlab
python -m pip install -e .
Copy-Item fixlab.example.toml fixlab.local.toml
```

在本地配置中填写 API Key、接口地址和模型 ID。不要提交 `fixlab.local.toml`。无需密钥即可运行 `python -m fixlab demo`。

## 重试与完成检查

模型 API 遇到断连、连接错误、超时，以及 HTTP 408/429/500/502/503/504 时，每轮最多请求 3 次，重试前分别等待 1、2 秒。401 等非临时 HTTP 错误直接失败。重试只重新请求模型，不重放已执行的工具；失败请求可能已被服务商计费。报告记录 `api_retry_events` 和 `usage_may_be_incomplete`，批次汇总相应将 `token_usage_complete` 标记为 false。模型调用轮数上限不等于 HTTP 请求次数上限。

`run` 和 `evaluate` 在模型给出最终文本时检查：业务代码相对初始快照是否变化，以及原始公开测试是否通过。未通过就把公开检查结果反馈给模型继续修复，仍受累计 `--max-steps` 限制。隐藏测试不参与该反馈，只用于最终验收。报告的 `completion_rejections` 记录结束请求被拒绝的次数。

已有 `completed` 任务不会自动重新打开。比较机制改动效果，请使用 `evaluate` 创建全新批次；旧报告保持原样。该检查要求实际代码变更，因此没有缺陷或没有公开测试的任务不适合当前修复流程。

## 进阶任务与隐藏验收

```powershell
python -m fixlab evaluate benchmarks_advanced --backend docker --max-steps 12
```

新增 pagination（分页及参数校验）、inventory（库存扣减与失败原子性）、money（Decimal 金额及舍入）三个跨文件任务。原来的 `benchmarks` 五题保持不变，便于比较历史结果。

每个任务的 `repo/` 是模型可见代码与公开测试，旁边的 `hidden/test_hidden_*.py` 仅由验收器加载。隐藏测试不复制进模型工作区，不进入模型消息或测试工具反馈；最终临时验收目录加入原始公开测试和隐藏测试。任务说明公开全部行为要求，隐藏的是具体测试用例。

报告的 `public_acceptance` 是原始公开测试结果，`acceptance` 是公开加隐藏测试结果，`has_hidden_tests` 标识是否启用。成功判定以综合验收为准。任务内容指纹包含隐藏测试；续跑使用初次保存的隐藏测试快照，拒绝更换测试。

此处“隐藏”表示运行时对 Agent 工具不可见，不表示测试源码未发布或能抵御恶意代码。使用 Docker 后端避免本机执行突破目录边界；验收报告可供开发者阅读，但不会自动回传模型。这组开发任务不能当作独立盲测或生产能力指标。

## Docker 执行后端

启动 Docker Desktop 并选择 Linux containers，首次准备镜像：

```powershell
docker pull python:3.11-slim
python -m fixlab evaluate benchmarks --backend docker --max-steps 12
```

单任务同样支持 `--backend docker`，可用 `--image` 选择已准备好依赖的 Python 镜像。默认仍为 `local`，仅适合可信代码。Docker 模式下模型 API 请求仍由宿主机发出；Agent 的测试工具、基线验收和最终验收均在容器内执行。文件编辑仍由 Harness 在目标工作区完成。

容器断网、1 CPU、256 MiB 内存及交换总额度、64 个进程限制，使用非 root 用户、只读根文件系统、128 MiB 临时目录。经过过滤的代码副本只读挂载，再复制到容器内临时目录执行；不挂载密钥配置、Git 元数据或 Docker socket。测试超时为 30 秒，结束或超时后按唯一容器名强制删除，清理失败会报错。Docker 不可用时不自动退回本机。依赖需预装进镜像，测试期间不联网安装。

续跑必须使用相同后端和镜像；报告记录后端与镜像标签。镜像标签可变，严谨复现实验应通过 `--image` 使用固定 digest。容器降低执行风险，但不应将此 MVP 当作面向敌对代码的完整安全平台。

可恢复、可评测的代码修复 Agent Harness。当前为 Python 标准库实现的本地 MVP，面向可信仓库。

## 快速演示

```powershell
python -m fixlab demo
python -m fixlab report .fixlab/demo/state.sqlite
python -m unittest discover -s tests -v
```

演示先执行失败测试，再通过预设工具调用修复加法函数，最后重新验收。生成 `.fixlab/demo/report.json` 与 SQLite 执行记录。演示使用确定性脚本，不调用模型，不代表模型修复能力。重复演示请指定新的 `--output` 目录。

## 连接模型

直接编辑项目中的 `fixlab.local.toml`，填写 `api_key`、`api_base` 和 `model`。此文件已加入 Git 忽略规则；新克隆的项目可从 `fixlab.example.toml` 复制。默认从当前工作目录读取，也可以用 `--config` 指定路径。

配置优先级：命令行 `--model` > 环境变量 `FIXLAB_MODEL` / `FIXLAB_API_KEY` / `FIXLAB_API_BASE` > 本地文件。配置好文件后可省略 `--model`。API 地址是 Chat Completions 兼容基础地址，程序追加 `/chat/completions`。

```powershell
python -m fixlab run ./trusted-repo --task "修复具体问题" --model YOUR_MODEL --state .fixlab/task1.sqlite --max-steps 12
```

相同命令恢复相同任务。达到步数上限后，可提高 `--max-steps` 继续；这是整个任务累计的模型调用上限。状态文件必须放在被修复仓库外。省略 `--state` 时，每次创建 `.fixlab/runs/<任务ID>/state.sqlite`，命令开始时打印路径。

## 批量评测

先验证一个真实模型任务：

```powershell
python -m fixlab evaluate benchmarks --task-id addition --max-steps 6
```

运行全部 5 个任务：

```powershell
python -m fixlab evaluate benchmarks --max-steps 12
```

使用本地模型配置，会产生模型 API 用量。默认输出到 `.fixlab/evals/<批次ID>/`；可用 `--output` 指定一个尚不存在的目录。每个任务目录包括 `workspace/` 副本、任务说明及源内容 SHA256、`state.sqlite` 和 `state-artifacts/`。原始 `benchmarks/` 不受修改。批次根目录的 `summary.json` 在每个任务结束后更新，包含成功率、每个任务结果和已报告 token 总数；`token_usage_complete=false` 表示 token 数据不完整，不能把已知总数当作完整用量。

任务格式为 `benchmarks/<任务名>/task.json`（含字符串 `task`）和 `repo/`。目前顺序执行，任务出错后继续，错误按执行异常、步数耗尽、验收失败、基线已通过分类。批次中断后可读取已保存的 summary；批次本身不自动续跑，单任务可用已有 state 通过 `run` 恢复，恢复后不会自动刷新批次汇总。

这 5 个公开的小任务用于开发回归，不是独立隐藏评测集，也不代表通用代码修复能力。真实模型评测与脚本模型测试应分别报告。

## 单任务报告内容

`run` 会在首次模型调用前保存文件快照、执行基线验收，并在运行后生成与状态文件同目录的 `<状态文件名>-artifacts/`：

- `baseline.json`：初始文件内容及基线验收结果，续跑时保持不变。
- `changes.diff`：相对初始快照的文本差异，二进制变更仅列出文件名。
- `report.json`：模型状态、基线与最终验收、变更文件、token 用量及累计执行耗时。

验收在临时目录中执行，组合当前代码与初始测试。初始 `test*.py` 和 `tests/` 目录里的文件作为测试基准，新增测试不参与验收；支持 unittest 标准发现规则。零测试或全部跳过不算通过。`repair_success` 要求模型完成、最终验收通过且基线未通过；它只代表这组原始测试的结论，不证明所有行为正确。首次快照前已完成的旧任务不能追溯原始代码，需要使用新的状态文件和有 bug 的初始仓库。

这是可信代码的回归验收，不是恶意代码安全沙箱，也不是隐藏测试平台。项目依赖须已安装在当前 Python 环境；软链接、虚拟环境、Git 元数据和本地密钥配置不复制。快照会保存其他项目文件，适用于小型演示仓库。耗时统计包含模型/工具循环，不含基线及最终验收；没有返回 usage 的模型显示 null，费用暂不计算。

## 结构

- `fixlab/core.py`：工具协议、模型适配、事件存储、执行循环。
- `fixlab/cli.py`：运行、演示和事件报告入口。
- `tests/test_core.py`：恢复、预算、路径边界和任务身份验证。

模型响应 → SQLite 持久化 → 工具开始记录 → 工具执行 → 工具结果持久化 → 下一次模型调用。

已保存但尚未开始的工具调用可以继续执行；已开始却没有持久化结果的调用会阻止自动恢复，要求人工检查工作区并创建新任务。这避免盲目重放有副作用的操作，不承诺 exactly-once。模型响应完成前断线可能造成重复请求及费用。

## 当前能力与边界

- 支持文件列表、读取、完整文件写入、unittest 测试执行。
- 工具文件路径检查阻止越界和部分受保护路径访问，不是安全沙箱。
- 测试执行具有 30 秒超时和返回日志长度限制，但不保证终止测试生成的全部子进程。
- 默认本地测试以当前用户权限运行，仅适合可信代码；可显式启用 Docker 隔离和资源限制。
- 记录 API 返回的 token usage；尚未实现费用和 token 总预算。
- `completed` 仅表示模型结束执行；请同时查看自动报告中的 `acceptance` 和 `repair_success`。
- 真实任务验收使用初始测试，模型修改测试会列在 `changed_test_files`，不会作为新的验收标准。
- API 适配器已通过硅基流动模型联调并支持有限重试；尚无上下文摘要或并发调度。
- 事件日志包含提示词、代码和工具输出，请使用不含敏感信息的演示仓库。

## 后续里程碑

1. 扩展任务集、重复实验和自检策略对照。
2. 批次恢复与汇总更新。
3. 上下文整理与预算策略，在固定任务集上做对照实验。
4. FastAPI 与执行轨迹页面，发布可复现的评测报告和演示视频。

求职展示应区分框架能力、脚本演示结果和真实模型评测结果。

## 需求自检与边界测试

真实 API 模型运行时增加 `self_check` 工具，输入需求清单 `requirements` 和 unittest 源码 `test_code`。模型需按公开任务要求检查正常、非法、空输入、边界和条件组合。测试在临时副本执行，使用选定的 local/Docker 后端，不写入原始测试文件；结果回传模型用于修复。

真实模型在结束前必须调用自检，并通过最新代码上的自检重跑以及原始公开测试。零测试、全部跳过和失败都会阻止完成；继续执行仍受累计步数上限约束。脚本 demo 不强制此流程。报告增加 `self_check_calls` 与 `self_check_final`，执行轨迹保留需求清单、测试源码和结果。模型可修改自己生成的测试，这些测试不作为独立成功评分依据；隐藏测试不会反馈给模型。

新机制可直接用原命令运行。若遇到步数不足，可提高 `--max-steps`，但对照实验应保持预算一致。已经标记 completed 的历史任务保持不变，比较效果请创建新评测批次。

```powershell
python -m fixlab evaluate benchmarks_advanced --backend docker --max-steps 12
```

## 自检开关与重复对照评测

比较自检策略时，其他机制（API 重试、步数限制、公开完成检查、隐藏验收）保持一致。

```powershell
# 单独运行关闭自检的一组
python -m fixlab evaluate benchmarks_advanced --backend docker --self-check off --max-steps 12

# 两组各重复 3 次：3 个任务 × 2 组 × 3 次 = 18 个修复任务
python -m fixlab compare benchmarks_advanced --backend docker --repeats 3 --max-steps 12

# 先进行较小规模的对照
python -m fixlab compare benchmarks_advanced --task-id money --backend docker --repeats 1 --max-steps 12
```

`run` / `evaluate` 的 `--self-check` 默认 `on`；关闭时移除自检工具、额外提示和自检结束门槛。恢复任务不能切换模式。脚本 demo 不作为真实模型实验。

`compare` 默认输出到 `.fixlab/comparisons/<ID>/`，包含：

- `suite/`：本轮实验冻结的代码、公开和隐藏测试。
- `repeat-01-off/`、`repeat-01-on/` 等：各次独立工作区与完整评测报告。
- `comparison.json`：逐任务配对结果、成功率、执行异常数量、token 和耗时统计。
- `comparison.md`：可直接阅读的汇总表。

每次运行从同一冻结任务集开始，每轮交替 on/off 顺序；记录任务内容和 Harness 源码指纹、模型名称、步数限制及后端。模型服务与模型保持相同，采样参数沿用服务默认值，不能保证模型回复确定性。固定镜像 digest 可进一步稳定容器环境。等步数不等于等 token 或等费用。

`tokens_per_success` 是包含失败尝试在内的总 token 除以成功次数，不是仅成功任务的平均 token。发生失败请求或用量缺失时，平均 token 和成功单位 token 显示 unknown/null，而非零。部分运行报告的成功率只覆盖已完成任务，须同时检查完成数量；中断时保留已完成批次汇总，当前不支持自动续跑整个对照实验。

这项命令会真实调用模型，18 个任务通常比单轮评测消耗更多。建议先做小规模验证。开发任务上的小样本差异不等于统计显著结论；重复相同任务也不等于增加独立任务数量。

## 业务组合条件任务集

新增 `benchmarks_challenge`：配置分层合并、多租户缓存、退款幂等与原子性，共 3 个跨文件任务、26 个公开及隐藏验收用例。完整说明见 [任务集文档](benchmarks_challenge/README.md)。原来的基础与进阶任务保持不变。

```powershell
python -m fixlab compare benchmarks_challenge --task-id refund_ledger --backend docker --repeats 1 --max-steps 12
```

任务集质量检查验证了初始失败、正确实现通过，以及不完整实现公开通过但隐藏失败；这些是离线验收验证，不是模型评测结果。

## 实验结论与真实仓库接入

- [自检策略对照报告](docs/self-check-experiments.md)：两组开发任务、36 次修复的结果与局限，附脱敏实验数据。
- [本地 Git 仓库任务导入](docs/importing-repositories.md)：使用 `import-task` 从固定提交创建任务，保留版本与文件哈希，不修改原仓库。

## 一键续跑与状态说明

```powershell
# 仅读取恢复参数，不调用模型
python -m fixlab resume .fixlab/evals/<批次ID>/<任务ID>/state.sqlite --inspect

# 沿用原任务、模型名、Docker 后端及自检开关
python -m fixlab resume .fixlab/evals/<批次ID>/<任务ID>/state.sqlite

# 需要额外预算时显式提高累计步数上限
python -m fixlab resume .fixlab/evals/<批次ID>/<任务ID>/state.sqlite --max-steps 20
```

API 密钥和服务地址仍从当前本地配置读取，可通过 `--config` 指定原服务配置；请使用与原运行相同的服务。模型名优先取保存记录，不会使用配置里另一个模型。已完成任务直接返回原报告。工具执行结果不明时拒绝自动重放；恢复不是从头运行。

报告现在分开记录 `patch_status`（passed/failed）、`execution_status`（completed/interrupted/budget_exhausted）、`self_check_status`（disabled/passed/incomplete）及 `error_type`。`incomplete` 表示本轮尚未确认自检完成；具体失败用例仍查看 `self_check_final`。补丁通过而 API 断连时，补丁可显示 passed，执行显示 interrupted，整体 repair_success 仍为 false。

resume 保留原单任务报告及批次汇总到 resume-history，再更新包含该任务的 summary.json。token 和耗时累计，不删除历史重试记录，缺失用量不会因恢复成功被标为完整。如果任务属于对照实验，保留原 comparison.json 并写入 resume-notice.json，避免把额外预算的续跑混入原实验；需新建配对实验作正式比较。同一任务、工作副本或批次的并发写入现由操作系统锁保护，发生竞争会报告 busy。

## 补丁交付、CI 与进度提示

- [补丁交付说明](docs/patch-delivery.md)：`deliver` 默认预览，`--apply` 新建独立分支和 worktree，交付前后重新验收，不自动提交或推送。
- `.github/workflows/tests.yml` 在 push / pull request 时进行 Windows、Linux 和 Python 3.11、3.13 的安装与单元测试；不使用 API Key 或调用模型。此工作流需要推送后才会在 GitHub 实际执行。
- 模型请求显示尝试次数和 90 秒超时，临时失败显示退避重试，工具执行显示名称；输出在 stderr，不打印密钥或请求正文。
- Ctrl+C 以退出码 130 友好退出。现有 finally 路径保存状态并执行容器清理；中断的工具仍可能结果不明，续跑前应先 `resume --inspect`。

## 资源预算

支持累计 Token 上限、Agent 协作式运行时限及用户单价费用估算，续跑继承已用额度。

```powershell
python -m fixlab evaluate benchmarks --backend docker --max-tokens 50000 --max-seconds 300
```

限制按每个任务计算，在操作之间检查，可能超出当前请求或工具的消耗；并非硬性费用或进程墙钟封顶。详情见 [资源预算说明](docs/resource-budgets.md)。

## 本地报告页面

```powershell
python -m fixlab dashboard .fixlab/evals
Start-Process .fixlab/reports/index.html
```

离线查看任务列表、状态、预算、测试结果、执行轨迹与代码差异；支持搜索和结果筛选。重新生成可更新快照，不调用模型或修改任务记录。详细用法及读取上限见 [报告页面说明](docs/dashboard.md)。

## 批量续跑与并发保护

```powershell
python -m fixlab resume-batch .fixlab/evals/<批次ID> --inspect
python -m fixlab resume-batch .fixlab/evals/<批次ID> --max-steps 20
```

跳过已完成任务，续跑中断任务，新批次可从冻结计划启动尚未开始的任务。旧批次只恢复有状态记录的任务。每次操作保留逐项日志并更新汇总；同一任务、工作副本及批次使用进程锁避免重复执行。详见 [批量续跑说明](docs/batch-resume.md)。

## 上下文构建

通过 `--context-max-tokens 16000` 显式启用请求上下文压缩；保留完整 SQLite 轨迹、任务要求及完整工具配对。摘要核对测试对应的文件指纹，避免把旧结果视为当前有效。参数是含工具定义和输出预留的估算预算，默认关闭，详见 [上下文说明](docs/context.md)。
