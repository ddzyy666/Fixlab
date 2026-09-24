# 导入本地 Git 仓库任务

导入器从指定提交的 Git 对象导出代码，不切换分支、不修改原仓库、不包含工作区中未提交的更改。它创建现有 evaluate/compare 可用的任务格式，不会自动挑选 bug、生成可信验收或安装依赖。

## 准备

1. 一个本地已克隆的 Python Git 仓库和存在缺陷的提交 ID。
2. issue.txt：公开问题描述、复现方法及行为要求，不含参考修复答案。
3. public/：至少一个 test_public_*.py 文件，提供模型可见的 unittest 回归测试。
4. hidden/：至少一个 test_hidden_*.py 文件，提供独立隐藏 unittest 验收。

当前仅支持从仓库根目录用 unittest 发现测试。测试文件要求平铺；pytest-only、需要服务或复杂安装流程的仓库需先适配测试和 Docker 镜像。导入完成不表示任务已具备可执行环境。建议选择体积小、依赖简单的仓库。

## 导入和评测

以下路径为示例，替换为真实路径和提交 ID：

```powershell
python -m fixlab import-task "D:\repos\example" `
  --commit "完整提交ID" `
  --description-file "D:\cases\example\issue.txt" `
  --public-tests "D:\cases\example\public" `
  --hidden-tests "D:\cases\example\hidden" `
  --output ".fixlab/real-tasks/example-bug"

python -m fixlab evaluate .fixlab/real-tasks --task-id example-bug --backend docker --self-check off --max-steps 12
python -m fixlab compare .fixlab/real-tasks --task-id example-bug --backend docker --repeats 3 --max-steps 12
```

导入不需要 API Key，也不会调用模型。导入后的 task.json 保存源提交 ID、仓库名称、文件哈希及排除路径；repo/ 中是历史版本与公开测试，hidden/ 中是独立验收。compare 冻结任务时保留源版本信息。

## 边界

- 输出目录必须不存在且位于源仓库外。已有同名测试不会被覆盖。
- 不复制 .git、.env、.env.*、本地 FixLab 密钥配置、虚拟环境、字节码和 .pem/.key 文件。此规则不等于全面秘密扫描；发布前仍应检查源码中的硬编码凭据。
- 拒绝软链接、子模块、大小写冲突及不兼容的路径；最大 2 MB/文件、20 MB 源快照。Git LFS 指针不自动下载或展开。
- Git 中的可执行权限不恢复，只适合 Python 源码测试；依赖必须预装在测试镜像中。
- 导入不会运行代码。基线失败可能来自环境缺失，需检查错误日志，不能把环境问题当作模型修复题。
- 重新分发第三方源码前确认其许可证，保留许可证文件和出处。默认输出在被 Git 忽略的 .fixlab 目录中。
