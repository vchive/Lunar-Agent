# Lunar Evolution 与 WebAgent + reference-engine-v2 能力对照

本文分析外部参考项目；“参考引擎”、插件、角色、分支和 benchmark 的中性名称仅作描述，
不是 Lunar Evolution 的组件名称，也不是声称上游已改名的实际路径。原始名称、源码路径
及引用保留在[历史归档](history-archive.md)指向的固定迁移前版本；外部代码归属及其适用
许可仍属于原作者。本次名称整理没有重新运行外部项目或模型测量。

创建日期：2026-09-20；2026-09-21 更新包含 142 Phase C 本机夹具验证和已完成本地验收的 143 修复，142 Phase A/B 历史基线为 `65d9ae2`。

本文将迁移前功能基线中的本地源码、离线验证和 Feature 139 的唯一真实多文件运行，与本地审计过的
WebAgent v2.5 和 reference-engine-v2 引擎做能力对照。这里的“覆盖”指 Lunar 具备对应的本地
数据链或协议；它不等于已经在真实模型上取得相同成功率，也不等于复刻了对方的服务实现。

## 结论

Lunar 已经覆盖 WebAgent/reference-engine-v2 最重要的本地求解与程序演化链：任务合同、工具循环、
角色/DAG、候选生成、种群搜索、独立执行、独立评测、有效性优先选优、lineage、checkpoint、
seed admission、证据收据和父任务交付。

Feature 142 Phase A/B 已完成前台共享活动墙钟、父任务编排、父子取消、实际进程登记与清理。
Phase B 定向回归 146 项通过；其迁移前双阶段回归为 `8636 passed, 1 skipped, 24 deselected`、
冻结 Feature 123 阶段 `24 passed`；原始记录见[历史归档](history-archive.md)。这些计数不代替
Feature 145 当前命名空间的独立回归。
Phase C 自动后台执行现已实现，solve/resume/answer 的真实本机子进程与回环 HTTP 夹具已通过，
覆盖前后台交付、等待输入退出、取消、恢复和执行权争用；当前完整三阶段回归已通过。
新的真实模型验收只有计划，尚无新登记或运行；Feature 139 的真实闭环结果仍为 `0/1`。

Lunar 没有覆盖 WebAgent 的 OpenCode 产品层和 reference-engine-v2 的远程实验控制面：插件注册、持久
审批门、完整 WorkerRegistry 语义、外部实验服务客户端/外部服务 CLI、远程 GPU sandbox、project relay、
SSE replay 和多租户服务。这些不是当前本地路线的默认依赖。

Feature 143 已修复本地 worker 的并发取消、活性恢复和排队取消缺陷，补上独立执行工厂、
精确 attempt 进程清理及消息原子消费，共享回归 260 项通过。T009 实际 delegation consumer
尚未接入；本地 API 验收不代表模型已能使用 worker 工具，该接线不是 Feature 142 的依赖。
最终验证记录见 [143 validation](../specs/143-local-worker-lifecycle/validation.md)。

## 能力矩阵

状态含义：**已覆盖** = 有本地实现和协议；**部分覆盖** = 有相近实现但生命周期或语义不同；
**未覆盖** = 当前没有对应能力，或按本地路线明确不迁移。

| 能力域 | Lunar 当前状态 | 与参考仓库的关系 |
| --- | --- | --- |
| Agent 工具循环、模型适配、请求/工具/token 预算、transcript、取消 | **已覆盖**。`AgentLoopRuntime`、runtime adapters、usage ledger 和事件/会话记录均在本地。 | 对应 WebAgent 的普通 agent 执行层；不依赖 OpenCode。 |
| 普通任务合同、计划、依赖 DAG、角色路由、验收和交付 | **已覆盖**。默认链路为 `data_discovery → formulate → solve → verify`，并支持显式 role DAG。 | 覆盖 WebAgent 的 Master/Build 的主要数据流；角色 prompt 和动态 specialist 派发不是原样复制。 |
| 本地持久状态和基础恢复 | **已覆盖**。SQLite/WAL 保存 run/task/attempt/event/artifact/计划版本，普通任务支持恢复、取消和进程组登记；自动多文件前后台共享预算、父编排和本地取消清理。 | 覆盖持久化和基础 crash recovery；后台新增所有权交接与显式恢复已通过本机夹具，完整回归已通过。 |
| Memory cards / 跨任务记忆核心 | **已覆盖**。`MemoryStore`、global/run scope、显式 recall/remember 和 transcript 已存在。 | 对应 WebAgent memory cards 的核心数据能力；没有 WebAgent 的远端产品级 user/project 服务。 |
| Select → Generate → Evaluate → Judge 的演化抽象 | **已覆盖（本地等价链）**。`PopulationStrategy` 有 generation、parent lineage、archive、island、migration 和 checkpoint/resume。 | 覆盖 reference-engine-v2 的核心演化思想，但不是其具体 `adaptive_cluster`、feature-vector clustering、`LLMJudge` 实现。 |
| 候选生成和严格协议 | **已覆盖**。多文件候选必须通过严格 JSON/source-map 解析，Markdown fence、说明文字和字段类型错误会拒绝。 | 结果边界比“模型返回了代码”更严格；Feature 139 的真实响应证明拒绝逻辑实际生效。 |
| 多文件候选隔离执行 | **已覆盖**。源码、输入、命令、依赖、环境、输出限制和执行身份先准入，再在独立 workspace/进程组执行。 | 覆盖 reference-engine-v2 的候选执行层；不是远程容器或 GPU sandbox。 |
| 独立 evaluator、exact receipt、validity-first 选优 | **已覆盖**。冻结 evaluator/auditor/profile，重新核验 launch-intent、result/completed、inode、digest 和输出快照，再进入 archive。 | 这是 Lunar 的主要强项；外部 producer 自报分数不能替代本地权威评测。 |
| Seed admission、lineage、外部候选重验 | **已覆盖（本地化）**。OpenEvolve/Shinka/generic producer 材料带 fingerprint、source digest、依赖/环境身份，并重新走本地 evaluator。 | 对应 reference-engine-v2 的 initial-program feasibility gate；没有接入其远程 experiment service。 |
| OpenEvolve / Shinka | **部分覆盖**。handoff、seed manifest 和本地重新准入协议存在；原生自动多文件入口尚未直接启动外部 producer，真实框架效果也未验收。 | 能接“已完成候选材料”，还不是完整 producer 调度平台。 |
| 失败分类、unknown、checkpoint/resume | **部分覆盖**。候选失败、timeout、unknown、run failure 和 preparation failure 有固定记录。 | 与 reference-engine-v2 的 retry queue/正式 iteration 语义不同；不能宣称恢复语义完全相同。 |
| 全链路 wall-clock、父子取消、后台自动多文件 | **已覆盖（本地活动执行）**。Feature 142 统一一次活动执行的共享墙钟、父编排、父子取消与进程清理；Phase C 已接通后台入口，前后台一致性等本机夹具通过，完整回归已通过。 | 不累计人工等待和多次显式续跑的时间；本地清理不证明远端 provider 已停止计算，也不是远程实验控制面。 |
| WebAgent 持久 approval gate | **部分覆盖**。Lunar 有 policy、event ledger、recovery 和 cancel，但没有完整的 `pending/approved/failed/timed_out/abandoned/not_confirmed` 状态机、同会话阻断和 bypass 防护。 | 应吸收状态机和未知终态原则，不必复制 OpenCode hook。 |
| WebAgent WorkerRegistry | **部分覆盖**。Feature 143 已有持久 Worker/WorkerAttempt、`dispatch/send/list/wait/resume/cancel`、owner/depth 校验和结果投递 API；已补独立执行、活性锁、精确进程清理和排队取消修复，T009 consumer 尚未接入。 | 不能宣称完整产品集成等价或真实效果持平；T009 接线不阻塞 Feature 142。 |
| WebAgent `evolve_*` / 外部实验服务客户端 / 外部服务 CLI | **未覆盖，且当前不迁移**。Lunar 默认使用本地 population 和本地 Store。 | 对方是远程实验控制面；Lunar 只保留 transport-neutral 的协议边界。 |
| 远程 GPU、sandbox、upload/download、project relay | **未覆盖**。Lunar 当前是本地受控子进程和本地 workspace。 | 属于 WebAgent/reference-engine-v2 服务部署能力，当前产品没有这个运行前提。 |
| Provider HTTP trace、SSE stall replay、OpenCode plugin compatibility | **未覆盖等价实现**。Lunar 有 transcript、usage 和事件诊断，但没有 provider fetch hook 或 OpenCode 1.3.10 插件兼容层。 | 只能吸收脱敏、可审计和 unknown 不自动重试的原则。 |

## 真实证据边界

当前代码和离线夹具已经能走完“准备 → 生成 → 解析 → 隔离执行 → 独立评分 → 选择 → 父任务
交付”的完整数据链，但 Feature 139 的唯一 50 分钟真实槽没有产出有效候选：

- preparation：`1/1`；
- 17 次请求均 HTTP 200，已知用量 `135344 tokens`；
- 候选生成回执：`worker_failed`、`malformed_candidate`；
- completed/evaluated/valid candidates：`0`；
- primary/joint：`0/1`；
- 没有候选执行、独立评分、选择、父任务交付或 holdout；
- native/process exit 为 `1`，cleanup 通过。

因此可以说 Lunar 已覆盖主要实现能力和证据边界，不能据此说它在真实模型效果上已经与
WebAgent 持平，也不能把 Feature 139 描述为端到端成功。

[Feature 142 前台真实验收计划](../specs/142-automatic-solve-lifecycle/real-acceptance-plan.md)
定义了新的 50 分钟独立验收，但尚未形成具体登记或运行结果，不能计为新增通过样本。

## 产品判断

如果目标是“本地可验证的 Agent + 程序演化系统”，Lunar 已经覆盖参考仓库最值得迁移的核心，
并在 evaluator receipt、候选身份和交付证据上走得更严格。下一步的高价值工作是新的真实
闭环验收、Feature 142 Phase C 完整回归与当前平台验证，以及提高严格最终响应协议在真实模型下产出
可执行候选的成功率。Feature 143 本地生命周期已补修复，下一步验证实际 consumer 接线。
历史版本 `8e1e089` 的 Linux/Python 3.11、3.12、3.13 完整双阶段测试和静态检查均通过；
这不表示当前 Phase C 改动已通过 Linux。具体见[系统评估](system-readiness-20260916.md)。
真实模型完整交付仍待新验收。

如果目标是“兼容 WebAgent 的线上产品形态”，还需要另行建设 OpenCode 插件/审批、完整多
worker 编排、远程 外部实验服务客户端、队列、GPU sandbox、项目归属、SSE/HTTP trace 和多租户服务；这些
不应被当前 Lunar 的本地能力表述为已经完成。

参考审计：

- [WebAgent v2.5 迁移矩阵](webagent-v25-lunar-capability-matrix-20260911.md)
- [reference-engine-v2 引擎审查](reference-engine-v2-review-20260911.md)
- [当前架构快照](current-architecture-20260920.md)
- [Feature 139 真实运行报告](history-archive.md)
