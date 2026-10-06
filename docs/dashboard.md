# 本地只读报告页面

在项目目录运行：

```powershell
python -m fixlab dashboard .fixlab/evals
Start-Process .fixlab/reports/index.html
```

`dashboard` 生成单个离线 HTML 文件，不启动服务器，不调用模型，也不读取模型配置。第二条命令使用系统默认浏览器打开文件。

默认输出为 `.fixlab/reports/index.html`，可以通过 `--output` 指定其他 HTML 路径。再次执行会更新 FixLab 生成的文件；已有的其他 HTML 文件不会被覆盖。

```powershell
# 汇集 runs、evals 和 comparisons 下的状态文件
python -m fixlab dashboard

# 只查看一个批次
python -m fixlab dashboard .fixlab/evals/<批次ID>

# 只查看一个任务，另存报告
python -m fixlab dashboard .fixlab/evals/<批次ID>/<任务ID>/state.sqlite --output .fixlab/reports/task.html
```

## 页面内容

- 按任务路径、任务描述或模型名搜索；筛选成功、未成功及状态未知的任务。
- 展开任务查看执行状态、补丁状态、自检状态、停止原因、预算和费用估算。
- 查看原始测试、最终验收与模型生成的自检结果。
- 查看新增/删除行高亮的代码差异及按事件序号排列的模型、工具调用轨迹。

每个状态数据库是一条任务记录，不会把旧汇总或 resume-history 重复计为新任务。成功数以保存报告的 `repair_success` 为准；记录缺失或报告损坏显示状态未知。任务正在运行时，报告和事件可能来自不同时间，需等运行结束后重新生成。页面不实时刷新，也不提供运行、续跑或交付操作。

读取 SQLite 使用只读连接；代码、模型文本及工具返回内容全部转义为文本展示，不执行其中的 HTML。报告不加载网络资源。仅访问同目录的固定报告与 diff 路径，不跟随报告里的路径字段。

最多展示 500 个任务、每个任务前 500 条事件；单条事件与 diff 上限 200,000 字符，单个 JSON 报告上限 2,000,000 字符。达到上限时会显示提示，可缩小输入目录查看。符号链接目录和工作副本中的数据库不参与目录扫描。

HTML 包含代码、提示词、工具输出和本地路径，未自动脱敏；适合本地检查，分享前请审核内容。
