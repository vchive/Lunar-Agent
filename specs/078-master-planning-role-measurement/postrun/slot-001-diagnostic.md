# Feature 078 Slot 001：钣金套料只读失败诊断

本槽已终止。Master计划通过原生校验并进入Build，最终失败诊断为model/timeout。Subject耗时5280.390秒、退出码2；外层和worker退出码0只表示失败结果已保存。

已保存16条模型响应、21条工具结果；计数与原生v1诊断一致。未产生最终Build响应、checkpoint、续跑、_agent_summary.md、subject receipt或harness；分数、完整失败usage与cost仍为null。

| 阶段 | 模型响应 | 工具结果 | 最终文本响应 |
| --- | ---: | ---: | ---: |
| Master | 8 | 10 | 1 |
| Build | 8 | 11 | 0 |

工作流仅持久化Master结束快照：8 rounds、10 tools、93219 tokens。它不包含完整Build及失败请求，不能当作完整用量；精确独立Master耗时仍为null。

终局文件元数据如下；未打开候选文件、计算候选哈希、执行候选或采用本地工具分数。

| 路径 | 类型 | 字节 |
| --- | --- | ---: |
| analyze.py | file | 1403 |

无HTTP状态或原始异常，无法进一步确定provider、网络或具体请求内部原因。文件存在和计划交接不等于有效解；subject总耗时不等于Build独立耗时。进程终止检查另见root保存的final-process-check.json。

独立最终审计已接受登记的原生链条；本诊断复核30项证据SHA、request与failure副本、worker→outcome→report/record→control记录链及源码绑定。输入证据和工作区元数据在保存前后保持一致。完整证据路径、SHA及限制见同名JSON。
