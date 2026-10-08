# 批量续跑与并发保护

`resume-batch` 处理一个评测批次，不重复调用已经正常完成的任务。它串行续跑，保持原模型、自检开关、Docker 镜像及累计用量。

```powershell
# 先检查，不调用模型
python -m fixlab resume-batch .fixlab/evals/<批次ID> --inspect

# 续跑未完成任务
python -m fixlab resume-batch .fixlab/evals/<批次ID>

# 增加每个任务的累计上限，已用额度不会清零
python -m fixlab resume-batch .fixlab/evals/<批次ID> --max-steps 20 --max-tokens 100000 --max-seconds 600
```

密钥、服务地址来自当前 `fixlab.local.toml`，也可用 `--config` 指定；请使用原供应商。`--inspect` 不加载配置或发送请求。

## 哪些任务会执行

- `skip_completed`：状态数据库已记录正常完成，跳过模型调用。即使隐藏验收失败也不重复运行已完成的 Agent；需要另开评测处理这类失败。
- `resume`：恢复已有状态的任务，包括断网、超时和预算耗尽。步数不足时先提高上限。
- `start`：从新批次保存的 `batch-plan.json` 启动尚未创建工作副本的任务。计划保存代码、公开/隐藏测试快照、来源哈希以及非敏感模型设置，不保存 API 密钥。原套件改动不会影响此次恢复。
- `blocked`：工具结果不明、状态缺失、部分工作副本已存在、锁被占用或无剩余步数，需要检查；不会自动覆盖已有工作副本或重放不确定的工具。

一个任务失败或被阻止不会终止其余任务；Ctrl+C 会停止整个续跑，保留已经完成的记录。Token 用量未知默认遵循保守停止规则，提高数值不能补回未知用量；显式使用 `--unknown-usage allow` 可接受统计不完整并有限续跑，历史未知用量标记仍保留。

旧批次没有冻结计划时，扫描直接子目录中的状态文件，包括尚未写进原汇总的中断任务；无法重建从未开始、没有状态记录的任务。`unrecoverable_unstarted` 给出数量，需要从原套件另建评测。部分初始化失败、只有工作副本但没有有效状态的任务不会自动重置。

## 报告与实验记录

每个完成续跑的任务会更新原 `summary.json`；恢复前的汇总仍保存到 `resume-history`。当前报告和缺失汇总条目会重新对齐，但任务 SQLite 不因跳过而改变。每次批量续跑另存 `resume-history/batch-<ID>.json`，记录逐项处理结果：

- `finished`：本次处理结束，不表示所有补丁验收成功；查看 `repair_success`。
- `finished_with_pending`：仍有被阻止、执行错误、预算耗尽或无法恢复的任务。
- `interrupted`：用户中断或进程内异常退出，已处理项目保留。强制杀进程时可能停留在上一次持久化状态。

可以针对对照实验的单个 `repeat-*-on/off` 子批次执行本命令。原 `comparison.json` 不重写，会产生 `resume-notice.json`，避免将追加预算的结果混进原对照。暂不自动恢复整个多轮对照调度器。

## 锁的范围

`evaluate`、`run`、`resume`、`resume-batch` 的评测路径使用非阻塞操作系统文件锁：同一批次只允许一个写入流程，同一状态文件或工作副本不允许同时执行多个 Agent。发生竞争时立即报告 busy，不等待或重复调用模型。不同批次和不同工作副本可以由不同进程运行；本命令本身不提供并行调度。

锁文件放在目标旁边，名称类似 `.state.sqlite.fixlab-task.lock`。Windows 使用字节范围锁，Linux 使用 flock；进程退出或崩溃后系统释放锁。锁文件保留是正常现象，**不要删除正在使用的锁文件**，文件存在不代表仍被占用。它们已加入 Git 忽略规则。

这保护通过这些入口发起的本机进程，不阻止手动编辑、旧版本 FixLab、其他工具或网络共享上的写入；`demo`、`deliver` 不属于此执行锁协议。只读报告页面仍可打开，但运行中的记录可能尚未完整。
