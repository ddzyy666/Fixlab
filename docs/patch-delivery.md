# 补丁审核与独立分支交付

`deliver` 将一次完整成功的修复交给开发者审核。它不会提交、合并或推送 Git，也不会修改源仓库当前分支的工作文件。

## 审核清单

```powershell
python -m fixlab deliver .fixlab/evals/<批次>/<任务>/state.sqlite "D:\repos\example" --commit <原始提交ID>
```

默认仅读取：显示源版本、变更文件和 changes.diff 路径。请先查看 diff 和 report.json；预览不会执行测试，也不保证此刻的代码仍通过，应用时会重新验收。

## 应用到独立 worktree

```powershell
python -m fixlab deliver .fixlab/evals/<批次>/<任务>/state.sqlite "D:\repos\example" `
  --commit <原始提交ID> `
  --branch fixlab/review-bug `
  --output "D:\reviews\example-bug" `
  --apply
```

前置条件：报告 repair_success 为 true；原仓库工作区干净；HEAD 等于指定提交；提交中的业务文件匹配初始快照；新分支与输出目录不存在。测试文件和受保护路径的改动会被拒绝。源仓库已前进时不会自动合并或 cherry-pick，需重新评测匹配的版本。

应用时先在原执行后端重新验收候选代码，通过后创建分支和 worktree，仅复制业务文件变更（包括新增和删除），再对交付结果运行原始公开与隐藏验收。生成 delivery-<ID>.json 记录。交付 worktree 不包含临时导入的公开测试或隐藏测试源码，它们由验收器在临时环境加载。

你可以在新 worktree 中运行 `git diff`、审核并自行提交。验证失败或用户中断后，已经创建的 worktree 保留供检查，delivery 报告记录失败；不会递归删除目录或自动回滚可能被人工修改的内容。

当前限制：适合小型 Python 源码仓库；不支持软链接、子模块、文件权限变更；不自动生成 GitHub PR。不支持并发操作同一源仓库。worktree 是同一 Git 仓库的新检出目录，原分支的文件不变，但 Git 会新增分支与 worktree 元数据。
