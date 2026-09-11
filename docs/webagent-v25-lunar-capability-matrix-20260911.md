# WebAgent V2.5 扩展与 Lunar 迁移矩阵

审查对象：WebAgent `origin/famou-v2.5/base`，固定提交
`f6ad20caf8963d105fe26c96b6a30ef4dfd34859`；关键架构切换提交为
`1e5a2ce9b5a14e699fab933f5a3c0826ad94275f`。

## 结论先行

WebAgent V2.5 没有修改 OpenCode 核心源码。它利用 OpenCode 1.3.10 的官方插件接口，
把工具、审批、事件和 worker 生命周期集中到一个实例级插件，再用 agent/skill/command
文件改变编排，并通过 `famou-ctl` 把深度演化交给远端 famou-v2。

因此 Lunar 不应复制 WebAgent 的 OpenCode 兼容层，也不应引入远端 FamouClient。Lunar
真正需要吸收的是可移植的状态和边界契约：副作用审批、worker 结算、unknown 语义、
崩溃恢复、可复核 evaluator receipt、候选 lineage，以及本地演化的持久状态。

## V2.5 做了什么，为什么做

| 扩展 | WebAgent 的实现与动机 | Lunar 判断 |
|---|---|---|
| 插件入口与工具注册 | `opencode/tools/famou/index.ts` 由一个工厂创建实例级 state；`tools/index.ts` 汇总所有工具。工具不放在 OpenCode 自动扫描的保留目录，避免 `PluginOptions` 丢失、门禁漏包和工具被重复注册。 | **不照搬实现。** Lunar 已有显式 registry/controller。保留“实例级隔离、启动自检、唯一注册”的原则。 |
| Approval gate | `approval/gate.ts`、`store.ts`、`tool-executor.ts`、`block-while-pending.ts` 将审批写入 `.famou/approvals.json` 和日志，支持 approved/failed/timed_out/abandoned/not_confirmed，待审批时阻断同会话工具，并拦截直接 `famou-ctl`。动机是原生 Permission.ask 只在内存中挂起，不能可靠恢复，也容易绕过 evolve 工具。 | **P0 借鉴。** Lunar 已有 policy、event ledger、recovery，但要统一副作用动作的审批状态机、超时/放弃/未知终态和 bypass 防护。 |
| Multiagent 生命周期 | `agent/agent_send/list/wait/cancel` 加 `WorkerRegistry`、event hook、父子级联、resume、background notification、崩溃 reconcile。`agent_wait` 超时表示“等待未完成”，不等于 worker 失败。动机是把 worker 状态从 master session 解耦，并能在进程重启后重建。 | **P0/P1。** Lunar 已有 AgentLoopRuntime、checkpoint、transcript、event sink 和 staged Master→Build；应补齐可持久 worker 状态、idle/error/abort 结算、resume/cancel 语义。无需复制 OpenCode tool API。 |
| Evolve 控制面 | 七个 `evolve_*` 工具通过 `FamouClient` 调外部 `famou-ctl`；create/status/list/continue/update/sync/cancel 使用 opaque experiment ID。副作用调用一次完成；超时或无 ID 为 unknown，先 status 对账，不自动 create。动机是远端实验是独立控制面，不能冒充本地 worker。 | **远端部分不需要。** 用户已确定本地路线。只借鉴 lifecycle 状态机和“不确定不重试”的原则；Feature 084 的 remote protocol 保持 opt-in，不进入默认构造。 |
| 演化物料与 admission | 提交前准备 `init.py`、`evaluator.py`、`prompt.md`、`config.yaml` 和数据，做静态/初始可执行检查；远端重新评估 seed。动机是普通求解结果不能直接当作可演化种群，且外部分数不能成为本地权威。 | **P0。** 这是 Lunar 当前最大缺口。实现 verified seed bundle、source/dependency/contract fingerprint、exact-harness receipt、初始 population admission 和 lineage。Feature 084 已定义边界。 |
| GPU / sandbox / transfer | `remote_bash/upload/download`、sandbox acquire/release ledger、压缩后 payload 计量和非 JSON 错误处理，解决远端 GPU 与大文件传输中的资源泄漏和错误误判。 | **当前不迁移。** Lunar 没有远端 GPU 需求。可抽取 acquire/release ledger 和资源终态审计模式，服务本地 host execution。 |
| Project attribution / relay | `project_list`、`project_attribution` 和 relay 重试协议解决 WebAgent session 到服务端项目的归属、默认项目和外部 URL。 | **不需要。** Lunar 是本地 run/workspace/SQLite 模型，没有对应的项目服务。 |
| Memory cards | `memory-cards.ts` 提供跨任务用户事实的 upsert/search，并带 request ID、abort-aware HTTP 和脱敏日志。动机是 WebAgent 的产品级跨任务记忆。 | **已有大部分等价物。** Lunar 的 `MemoryStore`、run-scoped memory、transcript、SQLite 已覆盖核心；后续只检查用户级/run 级边界、secret redaction 和审计。 |
| Model trace | `model-http-trace.ts` 通过 provider fetch hook 记录真实 request/response，默认关闭并脱敏，解决只看 SSE 看不到 prompt 的调试缺口。 | **可选 P2。** Lunar 可增加 request trace/redaction，但不应迁移 OpenCode 1.3.10 的 provider hook workaround。 |
| Skills/agents/commands | V2.5 用 `famou-master/build/evaluate/evolve-analyst` 和 skills 重写编排，普通 Build 先交付，深度演化显式 opt-in。动机是把求解交付与实验控制解耦。 | **P0 设计原则。** Lunar 保持 staged Master→Build；五轮演化应是独立、可恢复的 local population run，而不是 Build 失败重试。 |

## 对 Lunar 的实现优先级

### P0：必须补齐

1. **Verified seed handoff**：从 Build 结果生成只读 bundle；固定 source、依赖、合同、环境和 evaluator 指纹。
2. **Admission gate**：每个 seed 先过本地 exact harness，只有带新鲜 receipt 且 `validity == 1` 的候选进入 population；全失败时在 generator 和 population mutation 前 fail closed。
3. **本地正式演化状态**：为五轮演化持久化 run/generation/candidate/parent/iteration、checkpoint 和 archive，支持 resume，区分 candidate failure、timeout、unknown 和 run failure。
4. **副作用状态机**：对 approval、cancel、host acquire/release 等动作提供可恢复的 pending/approved/failed/timed_out/abandoned/unknown 语义。
5. **Worker 结算与恢复**：记录 started/running/idle/completed/failed/cancelled/unknown，父子关系和重启 reconcile；等待超时不能直接改写 worker 终态。

### P1：已有基础，按需增强

- candidate lineage 和 archive 的结构化 analyst artifact；
- 阶段摘要、终态报告，且分析只读，不修改 evaluator 或分数；
- 本地 model request trace（默认关闭、脱敏、可审计）；
- 资源 acquire/release ledger 的统一接口。

### 当前明确不做

- `FamouClient`、`famou-ctl`、远端 experiment service；
- 远端 GPU sandbox、project relay、WebAgent 前端 approval marker；
- 为兼容 OpenCode 1.3.10 而复制 `tool.definition` 或特定 hook workaround；
- 把远端 `combined_score` 直接写入 Lunar leaderboard。

## 与现有 Lunar 工作的关系

- `src/famou/evolution.py` 已有本地 `loop`、`population` 和 OpenEvolve subprocess adapter，但 OpenEvolve 目前只是外部命令适配器，不等于完整的 famou-v2 风格本地控制面。
- `src/famou/agent_evolution.py` 已有候选生成、独立 evaluator、bounded evidence 和 lineage 辅助数据，可复用为 admission/evaluation 层。
- `src/famou/store.py`、`recovery.py`、`agent_loop.py` 已提供事件账本、transcript、checkpoint 和恢复基础；缺口是把它们统一到 evolution run/candidate/receipt 状态。
- Feature 084 应继续作为实现入口，但需要兑现其 admission、receipt、resume fingerprint 和“不推进失败迭代”的约束；不能把当前 `PopulationStrategy` 宣称为已等价 famou-v2。

## 最终建议

Lunar 的路线应是“本地 Agent runtime + 本地 verified population evolution”。先完成 seed admission、exact receipt、持久演化状态和 worker/副作用恢复，再决定是否把 OpenEvolve 作为一个候选生成后端。WebAgent V2.5 的远端控制面只作为协议参考，不作为 Lunar 的运行时依赖。

本审查为只读代码审查，没有启动 WebAgent、模型、远端服务或公司评测平台。
