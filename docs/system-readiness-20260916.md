# Lunar-Agent 当前能力、剩余工作与终态验收

评估日期：2026-09-16。产品代码基线：`af4f8d8`（Feature 107）。本次为代码与已有证据
审查，没有新增模型调用、框架运行、真实测量或产品代码。Feature 108 尚未实现。

## 当前判断

Lunar 已有可运行的本地 Agent 和完整的单文件 population 演化链路。多文件链路已完成
声明、物化、输入 staging、有界执行和持久执行证据，尚未连接独立评分、Candidate、
archive、搜索循环和恢复交付。当前版本的真实任务稳定性及演化收益仍待验收。

最后全仓回归为 **4707 passed, 1 skipped**，证明当前测试覆盖的实现行为；它不代表
有效解率或相对 WebAgent 的效果。完成度应按下述闭环验收判断，不按 Feature 或测试数折算。

| 能力 | 实际状态 | 验证层次 |
| --- | --- | --- |
| 本地 Agent / Controller | 工具循环、任务调度、预算、SQLite、恢复、验收和交付已有实现与接线 | 自动化测试；较早普通流程有真实有效解 |
| 单文件 population | 生成、独立评估、receipt、archive/选择/迁移、checkpoint/resume 与交付已集成 | 代码和离线 fixture；当前版本收益仍待实测 |
| 多文件候选 | bundle → workspace → admission → input staging → runner → execution record 已完成 | 本地真实进程、崩溃、并发和文件边界 fixture |
| OpenEvolve | 显式 subprocess adapter、Lunar 本地重评及结果接入已有实现 | 本地 fixture；尚无真实 OpenEvolve 搜索效果验证 |
| ShinkaEvolve | SQLite 结果导出和 CLI population warm-start 已实现 | 本地 fixture；尚无 Shinka launcher/调度实现 |
| 固定条件比较 | task、comparison plan、result、evidence binding 已实现 | 协议测试；尚无这些新协议下的真实框架对照 |
| 远端演化 | lifecycle 协议和 completed material bridge 已实现 | 无内置真实 transport/client；默认本地路线不依赖它 |

代码接点：`src/famou/controller.py`、`evolution.py`、`producer_handoff.py`、
`candidate_execution_evidence.py`、`remote_evolution.py`。

## 必须完成的四个里程碑

| 顺序 | 工作 | 验收条件 |
| --- | --- | --- |
| 1 | 多文件 exact evaluator 与输出契约 | 固定 evaluator 实现与契约，消费完整 execution record，绑定实际评测的输出字节；坏输出、失败进程不能因 harness 返回高分而通过；评测无需重跑候选 |
| 2 | 多文件进入演化与最终交付 | Candidate/receipt/archive/lineage 能表达 bundle；接 population generator、producer material 和 controller；一个包含 helper 模块的任务能完成生成、评测、下一代选择和最终可复核交付 |
| 3 | 统一用户入口与恢复 | 用户通过正常任务入口完成全链路；中断后能复验已提交结果、保留未知现场、不重复执行或登记；预算、取消与恢复覆盖新链路；无需手工拼接多条底层 candidate-bundle 命令 |
| 4 | 当前版本真实验收 | 使用明确模型、输入、预算和 evaluator，分别验证 normal、原生 population、多文件与至少一个真实外部 producer 路径；保留失败分母，报告有效解率、分数、耗时和已知用量 |

第 4 项应先用小规模端到端样例贯穿开发，再在实现冻结后形成正式测量。不能等到所有
可选框架接完才验证产品效果。沿用已有 WebAgent 历史材料；不重跑 WebAgent、不重开旧
失败槽、不改写历史分数。新的真实测量使用独立登记与固定条件。

## 下一项实现需要解决的具体问题

1. Feature 107 的 completion 绑定进程 telemetry，不含输出 artifact 快照。评测阶段必须
   明确所评分输出的字节身份；若需要证明它们来自执行结束时，需在新的执行完成路径捕获
   输出，不能事后从旧 107 记录推导。也必须核对传入 workspace/input 与 intent 的身份。
2. 复用 `OutputSpec` / `EvaluationReport` 的语义；新的 evaluator 身份应绑定实际 harness
   字节、命令和配置。当前 admission 中的 opaque pin 本身不会执行或验证 evaluator。
3. 旧 `ExecutionAwareCandidateEvaluator` 会调用 runner，不能直接用于已 recorded attempt。
   旧 command evaluator 的输出采集方式也不适合照搬；新的报告读取必须完整、有界且严格解析。
4. `CandidateDraft` 和通用 producer material 当前仍面向单文件。多文件接入需明确模型兼容
   和迁移边界，不能只把 bundle 的 entrypoint 当作整个候选。

这四项是实现约束，不额外扩张为远端调度、通用 repository/workflow 或训练系统。

## 真实效果证据

- [069 普通/分阶段测量](../specs/069-webagent-normal-workflow/postrun/results.md)：普通流程
  GLM-5.2 的两例均有效，钣金 `0.999999`、邮政 `1.0185`。每例仅一次，产品源码固定
  `80f5af1`；它证明这两个任务上的交付能力，不是当前 HEAD 的效果或整体 parity。
- [082 分阶段测量](../specs/082-http-deadline-measurement/postrun/results.md)：两例均通过
  Master 计划并进入 Build，最终有效 `0/2`，没有完成的 subject/harness 回执。后续基础
  设施修复不能代替新的真实验收。
- Feature 084–107 的融合与证据工作主要由本地 fixture 验证。尚无当前多文件链路或真实
  OpenEvolve/Shinka 搜索带来的增益结论。

普通任务交付继续作为默认使用路径；分阶段编排和演化的稳定性、收益分别验证。

## 最终应交付的系统

一个独立、本地、可由用户或其他 Agent 调用的算法任务系统。用户给出目标、数据和预算，
默认普通求解，按需启动本地演化；原生 population 与外部 producer 共用候选执行、独立
评分、receipt、archive、恢复和交付流程。单文件和多文件候选都能交付可重现代码、结构化
输出、独立评测报告、来源及预算记录，失败和未知状态也能解释与复验。

```text
目标 / 数据 / 预算
        ↓
普通求解；按需启用原生 population 或外部 producer
        ↓
单文件 / 多文件候选 → 有界执行 → 输出绑定与独立 exact evaluator
                                      ↓
                                receipt / archive
                                      ↓
                          下一代选择或最终可验证交付
```

预算、取消、持久状态和恢复贯穿全链路。完成标准是上述四项验收通过，且使用者无需
理解底层 digest、inode 或逐条组装执行流程。

远端服务/GPU、DGM repository 候选、ADAS/EvoAgentX workflow graph、训练/RL 候选和更多
算法移植是后续可选扩展，不是这一版本完成的前提。本地 bounded runner 仍不是通用沙箱；
依赖/环境真实性及更强资源隔离需在扩大运行范围前按实际需求处理。
