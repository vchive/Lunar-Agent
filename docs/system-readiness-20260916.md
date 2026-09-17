# Lunar-Agent 当前能力、剩余工作与终态验收

评估创建于 2026-09-16，2026-09-17 更新至 Feature 122。最初盘点基于 `af4f8d8`（Feature 107）；
随后已完成多文件独立评测、原生 population、Agent 生成、普通 solve 自动准备和父任务交付。
首批 `c977eb4` 真实验收已完成：两例均在合同编译失败，尚未形成有效多文件交付。
随后 114 隔离合同编译并补齐 schema，115 新验收仍为 0/2：一例合同通过后 evaluator
请求超时，另一例合同请求超时。尚无真实多文件交付。
116 已区分依赖等待与用户待答，并为自动准备增加可查询失败记录及显式恢复提示；
这是离线验证的状态/恢复修复，不改变真实验收结果。
117 随后独立登记 600 秒单调用/3600 秒每题预算，结果仍为 0/2：一例 evaluator 请求
超时，另一例合同返回 Markdown JSON 代码块被拒绝。116 的失败状态/诊断已真实生效，
但没有冻结 evaluator 或交付，完整链路效果仍未验收。
118 已离线修复完整 JSON 代码块的入口兼容，并引入显式约束验证范围。生成 evaluator
在请求前拒绝尚无独立检查能力的 source/execution 要求，保留合同并给出具体诊断；
这不是新增源码/执行行为验证器，113/115/117 的真实结果不变。
119 随后接入精确的最少 Python 源码文件数检查，独立源码证据参与评测、选优与父任务
交付；不支持的行为要求仍提前说明。自动离线流程已拒绝单文件高分候选并交付合规双文件
结果，当前版本真实多文件有效交付仍未验收。

## Feature 120 真实验收结果

Feature 120 在已推送登记 `f3b575c` 上按支持范围运行两题，结果 **0/2**。两题合同编译分别耗时约44秒和118秒，随后 evaluator preparation 请求都在600秒 `open_response` 超时；无 evaluator、候选、交付或 holdout，已知用量16,161 tokens，超时消费/费用未知。详见 [120 report](../specs/120-supported-scope-acceptance/postrun/report.md)。

Feature 121 随后离线补齐 evaluator compiler/auditor 的完整响应/报告格式、源码限制和
合成测试数据规则；新增51项测试通过，最终全仓 **6049 passed, 1 skipped**，保持解析、
调用与恢复协议。原120请求从冻结源码
重建且哈希匹配，没有重复历史/合同。请求大小不证明超时原因，121没有真实模型结果，
不能据此更新多文件有效率。见 [121 validation](../specs/121-evaluator-prompt-protocol/validation.md)。

Feature 122 为有界 HTTP 请求补充最后本地里程碑、第几次 HTTP 交换和经过毫秒数，
分别记录进入连接、连接返回、请求写入调用返回和响应头返回（含中间重定向）等已观察点，
不保证失败时仍处于该阶段。
连接仍合并 DNS/TCP/代理隧道/TLS，写入返回不证明远端接收或模型执行。新详细失败使用
subject schema5，历史1–4和粗 phase/status 保留；请求参数和时限不变。新增151项测试和
445项相关回归通过，最终全仓 **6200 passed, 1 skipped**；恢复与历史字节复验通过。
这为下一次独立登记的小型 evaluator 准备诊断提供工具，没有新的真实模型测量，
113/115/117/120仍各自0/2。见 [122 validation](../specs/122-transport-milestone-observation/validation.md)。

## 当前判断

Lunar 已有可运行的本地 Agent 和完整的单文件 population 演化链路。多文件链路也已接通
生成、独立执行与评分、Candidate/receipt/archive、下一代选择、terminal resume 和完整
源码/已评分输出交付。用户可通过 `evolve-bundle` 或普通 `solve --evolve --bundle-profile`
运行这条路径，也可用 `solve --evolve --multi-file` 自动编译、审查、冻结 evaluator/profile。
普通入口支持父任务交付、澄清回答和终态恢复。自动准备保留原输入格式和探针容量限制；
运行中取消编排及当前版本真实任务稳定性、演化收益仍待完成或验收。

Feature 111 的最终基线为 **5277 passed, 1 skipped**；Feature 112 的最新验证见
[112 validation](../specs/112-automatic-bundle-evaluator/validation.md)。测试通过证明
覆盖的实现行为，不代表有效解率或相对 WebAgent 的效果。完成度按下述闭环验收判断。
Feature 114 修复后的全仓结果为 **5517 passed, 1 skipped**，详见
[114 validation](../specs/114-isolated-contract-intake/validation.md)；之后 115 已独立测量，
结果见下方真实证据。116 的产品修复验证见
[116 validation](../specs/116-preparation-recovery-state/validation.md)：最终全仓
**5636 passed, 1 skipped**，新增 69 项状态/恢复测试及本地完整交付验证通过。
118 新增 134 项格式/能力/CLI 测试，最终全仓 **5818 passed, 1 skipped**；详见
[118 validation](../specs/118-contract-protocol-capabilities/validation.md)。
119 新增 94 项源码检查、便携证据和恢复测试，最终全仓 **5912 passed, 1 skipped**；见
[119 validation](../specs/119-source-file-verification/validation.md)。

| 能力 | 实际状态 | 验证层次 |
| --- | --- | --- |
| 本地 Agent / Controller | 工具循环、任务调度、预算、SQLite、恢复、验收和交付已有实现与接线 | 自动化测试；较早普通流程有真实有效解 |
| 单文件 population | 生成、独立评估、receipt、archive/选择/迁移、checkpoint/resume 与交付已集成 | 代码和离线 fixture；当前版本收益仍待实测 |
| 多文件候选 | command/Agent/native runtime 生成 → bundle → 执行/独立评测 → receipt/archive/population → 父任务交付/terminal resume 已完成 | 普通 intake、完整父代上下文、helper-only 改进、有效性选优、迁移、失败保留、完整交付与不重跑 fixture |
| 自动 evaluator/profile | 多文件 solve 复用 compiler、独立 auditor、输出探针和冻结恢复；硬源码文件数另做确定性检查；其余 source/execution 提前报不支持 | 本地 fixture；检查只证明声明文件数，真实任务仍需验收 |
| OpenEvolve | 显式 subprocess adapter、Lunar 本地重评及结果接入已有实现 | 本地 fixture；尚无真实 OpenEvolve 搜索效果验证 |
| ShinkaEvolve | SQLite 结果导出和 CLI population warm-start 已实现 | 本地 fixture；尚无 Shinka launcher/调度实现 |
| 固定条件比较 | task、comparison plan、result、evidence binding 已实现 | 协议测试；尚无这些新协议下的真实框架对照 |
| 远端演化 | lifecycle 协议和 completed material bridge 已实现 | 无内置真实 transport/client；默认本地路线不依赖它 |

代码接点：`src/famou/controller.py`、`evolution.py`、`producer_handoff.py`、
`candidate_execution_evidence.py`、`candidate_evaluation.py`、`bundle_evolution.py`、`agent_bundle_generation.py`、
`bundle_delivery.py`、`solve_bundle.py`、`automatic_solve_bundle.py`、`bundle_parent_delivery.py`、`remote_evolution.py`。

## 版本闭环的四个里程碑

| 顺序 | 工作 | 验收条件 |
| --- | --- | --- |
| 1 | 多文件 exact evaluator 与输出契约：已完成本地实现与验证 | evaluator 实现与契约固定，成功 execution record 关联评测时输出快照；坏输出直接无效，失败进程拒绝；评测不重跑候选 |
| 2 | 多文件进入演化与最终交付：原生本地闭环已完成，外部 producer 接线待补 | Candidate/receipt/archive/lineage 已表达 bundle；command generator 和 controller 已接通；helper 模块任务完成生成、评分、下一代选择与可复核交付；OpenEvolve/Shinka 通用 material 仍为单文件 |
| 3 | 统一用户入口与恢复：已有普通 solve 自动 evaluator/profile 准备、父任务交付及 terminal resume | parent 输入/profile 绑定与 publication journal 已接通；支持范围内无需手写 profile/harness；运行中取消编排与更大输入格式/探针容量后续按需求处理 |
| 4 | 当前版本真实验收 | 使用明确模型、输入、预算和 evaluator，分别验证 normal、原生 population、多文件与至少一个真实外部 producer 路径；保留失败分母，报告有效解率、分数、耗时和已知用量 |

第 4 项应先用小规模端到端样例贯穿开发，再在实现冻结后形成正式测量。不能等到所有
可选框架接完才验证产品效果。沿用已有 WebAgent 历史材料；不重跑 WebAgent、不重开旧
失败槽、不改写历史分数。新的真实测量使用独立登记与固定条件。

## 下一项实现需要解决的具体问题

自动准备 → 双文件生成 → 执行 → 独立评测 → 选优 → 交付现已通过本地进程样例。
首批真实验收停在合同编译，已确认的入口接线问题由 114 修复，应以新登记继续验证。

1. 113、115、117 各自两例 GLM-5.2 验收均为 0/2。117 已延长时限，仍发生 evaluator
   超时；另一例原始合同响应含代码块标记，内部 schema 在离线诊断中通过。118 已实现
   精确包装兼容和显式验证范围预检，119 已把最低源码文件数接入独立检查、评分和交付，
   接下来登记支持范围内的新真实验收。超时没有响应，具体服务端原因仍未知，
   不继续补槽或盲目加时。尚没有真实有效率提高或评测器质量的证据。
2. 父任务交付、artifact 预算和 output journal 恢复已接通；自动模式恢复只需完整任务
   workspace/Store，不需外部 profile 路径。显式 profile 模式仍须提供匹配资源。运行中取消
   和全链路总时长编排继续待补，未知现场不自动重跑，终态恢复不增加候选或交付副本。
3. 扩展通用 producer material/SeedManifest 的多文件接线，使 OpenEvolve/Shinka 输出也
   进入同一完整源码路径，再用独立登记的小规模任务验证当前模型和真实 producer 效果。

Feature 108 的快照明确是评测时观察：107 completion 仍不包含执行退出时输出。inspect
可以在原 workspace 改动后复验保留快照；它检查本地一致性。Feature 109 的 archive 登记
还复验完整源码、执行与 evaluator 关联，交付使用已评分的保留输出快照，不重跑选中候选。
远端调度、通用 repository/workflow 和训练系统仍为后置扩展。

## 真实效果证据

- [069 普通/分阶段测量](../specs/069-webagent-normal-workflow/postrun/results.md)：普通流程
  GLM-5.2 的两例均有效，钣金 `0.999999`、邮政 `1.0185`。每例仅一次，产品源码固定
  `80f5af1`；它证明这两个任务上的交付能力，不是当前 HEAD 的效果或整体 parity。
- [082 分阶段测量](../specs/082-http-deadline-measurement/postrun/results.md)：两例均通过
  Master 计划并进入 Build，最终有效 `0/2`，没有完成的 subject/harness 回执。后续基础
  设施修复不能代替新的真实验收。
- [113 当前版本验收](../specs/113-real-multifile-acceptance/postrun/report.md)：`c977eb4`
  的两例 GLM-5.2 自动多文件入口均在合同编译失败，有效 **0/2**，质量 null，已知用量
  15958 tokens。没有进入 evaluator/候选生成，不构成这些后续阶段的效果证据。
- [115 修复后验收](../specs/115-isolated-intake-acceptance/postrun/report.md)：`5e2568f`
  完成 0/2，一例合同编译成功后 evaluator 请求超时，另一例合同请求超时。已知用量小计
  8625 tokens，超时消费未知；没有交付或可审计的冻结 evaluator。
- [117 延长时限验收](../specs/117-extended-deadline-acceptance/postrun/report.md)：`9a26a73`
  完成 0/2，evaluator 请求在 600 秒超时，另一题合同原始响应含 Markdown 代码块而被
  拒绝。三请求、两响应，已知用量小计 11309 tokens，超时消费未知；没有 evaluator/交付。
- Feature 084–112 的融合与证据工作主要由本地 fixture 验证。尚无当前多文件链路或真实
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
