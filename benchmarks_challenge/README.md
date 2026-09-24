# 业务组合条件任务集

本组扩展跨模块、状态变化和组合条件覆盖，用于继续研究自检的成本与收益。是否比原任务集更难，应由真实模型评测决定，不能仅凭题目描述断言。

| 任务 | 公开复现 | 隐藏验收范围 | 总验收用例数 |
|---|---|---|---:|
| config_layers | worker=0 被忽略 | 多层嵌套优先级、None 继承、显式空值、类型替换、输入不变与深拷贝、重复调用隔离 | 8 |
| tenant_cache | 同用户 ID 跨租户串数据 | 过期边界、零 TTL、不滑动过期、空字典缓存、深拷贝、加载失败不缓存 | 9 |
| refund_ledger | 部分退款未累计 | 全额状态转换、重复请求幂等、请求冲突、超额退款、金额类型校验、失败原子性、返回值隔离 | 9 |

所有期望行为写入 task.json；隐藏测试只隐藏具体测试用例，不增加未公开的需求。每题 repo/ 是模型工作区来源，hidden/ 不进入模型上下文。tests/fixtures/challenge_references.json 中保存正确和不完整参考修复，仅供任务集质量测试；不会复制进 Agent 工作区。

每题都验证了：有 bug 的初始代码不能通过公开测试；不完整修复可以通过公开测试却不能通过隐藏验收；参考正确实现可通过全部测试。没有外部服务、真实支付或真实客户数据，时间由注入的时钟控制。Docker 验收也已验证上述正反样本。

先选一题做小规模自检对照：

```powershell
python -m fixlab compare benchmarks_challenge --task-id refund_ledger --backend docker --repeats 1 --max-steps 12
```

全组重复对照（18 次修复，会调用模型）：

```powershell
python -m fixlab compare benchmarks_challenge --backend docker --repeats 3 --max-steps 12
```

保持两组相同步数。若两组经常耗尽预算，可另开一个更高预算的实验；不要只给一组加预算。结果输出到 .fixlab/comparisons/。本组目前尚未完成真实模型实验；参考补丁通过率不是模型成功率。
