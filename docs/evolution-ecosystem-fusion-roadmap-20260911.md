# Evolution ecosystem fusion roadmap（2026-09-11）

当前整体现状与版本完成标准见 [2026-09-16 系统评估](system-readiness-20260916.md)。
主线收敛为多文件评测、演化/交付接线、统一入口/恢复、当前版本真实验收四项；
Feature 108/109 已完成多文件评测、原生 population 选优和显式本地交付；下一步聚焦
普通任务入口、Agent 多文件生成和恢复编排，外部 producer 的多文件接线仍未完成；
下文按日期保留实现过程，旧条目中的“下一步”以该评估和最新 HANDOFF 为准。

本文记录 Lunar-Agent 与公开 evolution/program-search 项目的融合边界和优先级。公开项目
信息核对于 2026-09-11；没有执行外部框架、模型、provider、远端服务、候选评测或真实
campaign。当前 Feature 084/085 建立 verified seed、population-first 和协议边界，Feature
086 又把已完成的远端 material observation 接到同一 exact-harness admission；仓库同时具备
OpenEvolve 的有界本地 subprocess producer 接线、ShinkaEvolve 的只读离线结果 exporter，以及
可供这些 producer 复用的 transport-free `ProducerResultEnvelope` → `SeedManifest` adapter。
这些接线只由离线 fixture 验证，不能据此声称真实框架已运行或任何项目的公开效果已由 Lunar
复现。

## 2026-09-16：多文件原生 population 与完整交付

Feature 109 已通过 `MultiFileCandidatePipeline` 复用原生 population/archive：完整源码 map
经过 103–108 的物化、执行和独立评测，再发布 v2 receipt；旧 v1 数据与摘要保持兼容。
本地 command producer 可以读取完整 parent 源码并只修改 helper。谱系、代数、island、迁移、
有效性优先选优和 checkpoint 沿用已有搜索循环；同一 execution/evaluation 不能冒充多个候选。
失败/未知尝试保留原目录，terminal resume 只复验，不追加执行。

`evolve-bundle` 提供一条显式入口完成生成、评分、选优及可选交付。Controller 校验 Store
绑定的选择结果后，交付完整源码、已评分输出快照、输入与 evaluator 材料，独立 byte manifest
支持复制后的只读检查。原 107/108 inode-bound 证据保留原位。可运行样例见
[109 quickstart](../specs/109-bundle-population-integration/quickstart.md)。

这完成了本地多文件闭环；普通任务自动路由、Agent 自动生成多文件与 harness、parent-run
交付/统一恢复以及 OpenEvolve/Shinka 的多文件 seed 导入继续后置接线。本轮没有新真实模型
或外部框架运行，不能把 fixture 分数视为当前版本效果提升。

## 2026-09-14：CLI 热启动入口

Feature 096 已把现有离线 adapter 接到用户入口：`export-shinka-result` 导出静态 Shinka
结果；`evolve --producer-result ROOT --producer-fingerprint SHA` 将兼容 envelope 交给
Lunar population 的同一 exact-harness seed admission。新共享 API
`prepare_producer_seed_manifest` 只做只读校验与内存 manifest 构造，准备阶段不评测、
不创建 Candidate 或 receipt。CLI 支持固定 producer pin、可选名称 pin、正常 resume
fresh revalidation 和 detached 参数传递。使用方法见
[096 quickstart](../specs/096-producer-cli-warm-start/quickstart.md)。

该入口已用 SQLite + 本地 generator/evaluator fixture 验证，未启动真实 Shinka、模型或
远端服务；不构成框架效果比较。下一层仍是 SkyDiscover/LLM4AD benchmark/task envelope
与固定条件下的独立测量，多文件/repository/workflow candidate 另立契约。

## 2026-09-14：benchmark/task envelope

Feature 097 adds the offline `lunar-benchmark-task-v1` envelope and static
`benchmark-task validate` command. It binds task, contract, input bytes, model/evaluator identities
and physical budget for future SkyDiscover/LLM4AD comparisons. Admission is read-only and external
scores or generation IDs never become Lunar scores or iterations. No external framework or model is
launched; comparisons still require fixed conditions and a new pre-registered measurement.

## 2026-09-15：fixed-condition comparison plan

Feature 098 adds `BenchmarkComparisonPlan` above the task envelope. It freezes common workload,
contract, model, evaluator, candidate and physical budget across two or more arms, then performs
read-only input/pin admission. This is preparation for later SkyDiscover/LLM4AD comparisons; no
framework execution or effectiveness claim is included.

## 2026-09-16：多文件候选 bounded runner

Feature 108 已补上独立评测入口：成功的 execution record 经身份和字节复验后，把声明
输入/输出复制到新 evaluation 目录；固定指纹的 harness 仅读取快照，返回严格评测报告。
输出格式不合格时直接给出无效零分，不启动 harness。保存原始报告和绑定快照的 manifest，
`inspect-evaluation` 只读复验，不重跑候选。输出观察明确发生于评测时，不冒充执行退出时
的输出证明。双文件本地样例和边界 fixture 已通过；尚未接入 Candidate/receipt/archive、
population/controller 与恢复交付，没有新增真实模型或外部框架效果结论。

Feature 107 已在 runner 之上完成独立执行证据层：`candidate-bundle run-recorded` 先独占
新 attempt 目录并同步 launch intent，再执行一次 Feature 106，最后绑定 result/completed
文件的 SHA-256、size 和 inode。`inspect-execution` 只读复验原 plan/admission 与记录；
缺完成记录或保留临时文件时返回 uncertain，同一 attempt 不自动重跑。真实双进程争用与
五个 os._exit 崩溃阶段已有本地 fixture 覆盖。该层不复用旧单文件 Store 状态机，不登记
Candidate、不评分、不提供 attestation 或 resume。下一项优先把完整多文件执行记录与
exact evaluator 的输出契约关联，再进入 receipt/archive；真实固定条件效果测量仍未完成。

Feature 106 consumes the verified workspace plan, execution admission and staged input directory
with a single bounded local process invocation. It revalidates immutable declarations and mutable
bytes immediately before launch, rejects symlinked or overlapping roots, uses explicit argv plus the
bundle entrypoint, and bounds stdout/stderr while terminating the process group on timeout or output
overflow. The static `candidate-bundle run` command is dispatched before normal Store/home setup.

This is an execution boundary only. It accepts `max_processes == 1` as the current admission subset,
does not monitor candidate-created forks, and does not produce durable execution evidence, invoke an
exact evaluator, create Candidates, or resume interrupted work. A zero exit code cannot be used as a
Lunar score or as evidence of OpenEvolve/WebAgent parity. Those concerns require a later launch-intent,
evidence and evaluator feature; no external framework, model, provider or campaign was run here.

## 2026-09-15：comparison result receipt

Feature 099 adds a bounded result envelope for future fixed-condition measurements. It binds each
per-arm summary to the 098 plan and preserves only evidence digests and finite summary metrics;
parsing is read-only and does not run or score any external framework.

## 2026-09-15：comparison evidence binding

Feature 100 optionally adds a relative evidence path and byte size to each 099 arm result. When an
operator supplies an evidence root, Lunar verifies confined non-symlink regular-file bytes,
stable device/inode, exact size and SHA-256 before accepting the receipt. Digest-only 099 results
remain compatible without an evidence root. This binds a receipt to observed local bytes but does
not certify the producer, evaluator or framework, and does not create a benchmark effectiveness
claim.

The Feature 100 follow-up replaces separate path checks/opens with bounded descriptor-relative
reads for result JSON and evidence. It also rejects observed file or directory replacement,
same-size rewrites, malformed scalar fields and null explicit binding roots. Legacy digest-only
receipt identities remain compatible; result/evidence paths now share the strict no-symlink boundary.

## 2026-09-15：exact comparison plan binding

Feature 101 adds a complete canonical plan pin to new result receipts. It rejects reuse after a
same-named arm changes benchmark release/publication or swaps its envelope with another arm. The
explicit caller pin can require that binding; legacy receipts remain readable with `plan_bound:
false`. Plan/task DTO replay and bounded descriptor reads cover the static admission path. This is
measurement preparation, not a live experiment or evidence that external frameworks improved results.

## 2026-09-15：多文件候选源码包

Feature 102 新增独立 `CandidateSourceBundle` 和静态 `candidate-bundle validate` 命令，
为多文件候选建立 contract、entrypoint、每文件路径/大小/摘要以及完整 bundle digest。
只读验证有界 UTF-8 源码，拒绝路径冲突、symlink 和观察到的文件变化；显式 bundle pin
可以固定整个声明。此阶段只覆盖声明的源码文件，不等同 repository 快照、依赖/环境
认证或执行回执，也不转换现有 Candidate、SeedManifest 或 producer envelope。

后续仍需定义独立 workspace 中的多文件执行、输入/依赖/环境契约、exact evaluator、
receipt/archive/resume 关联，之后才可接 DGM 等 repository producer。ADAS/EvoAgentX
的 workflow graph 也需要独立候选契约。真实框架对照测量仍未完成，本功能无效果结论。

## 2026-09-15：候选源码 workspace 物化

Feature 103 新增 `candidate-bundle materialize` 和独立 workspace plan。它把 Feature 102
已验证的声明文件复制到新建私有目录，逐文件重新校验并在失败时清理半成品；plan 绑定
bundle/contract、entrypoint、文件表摘要、显式 runner、超时、输出上限和环境摘要。命令不
执行 entrypoint、不初始化 Store/home，也不产生 Candidate、receipt 或 archive。多文件执行、
exact evaluator、依赖/环境真实性和恢复关联仍需后续 Feature。

## 2026-09-16：Feature 104 candidate execution admission（已完成静态 admission 边界）

已冻结草案位于 [specs/104-candidate-execution-admission](../specs/104-candidate-execution-admission/)。
它承接 Feature 103 的 path-free workspace plan，现已实现 immutable DTO、canonical admission
digest、完整 plan/bundle/contract 与 caller pin 校验，以及可选的 bounded no-follow 输入字节
复核。声明绑定逻辑输入文件的目标/大小/SHA-256、dependency/environment identity、exact
evaluator pin、output-contract pin 和有界 process budget；输入 root 不提供时仍可执行纯内存
结构 admission。所有 pin 在输入文件 IO 前校验，输出只含身份、计数、限制和摘要。

该层只产生静态、可重放的 admission digest，不启动命令、不 import 候选、不安装依赖、不
调用 evaluator、不初始化 Store/home，也不写 Candidate、receipt、archive、resume 或
materialization ledger。Feature 104 focused suite 当前为 **195 passed**（含 installed CLI fixture）；
全仓回归为 **4471 passed, 1 skipped**；这些是离线协议验证，不构成任何框架效果结论。

静态 `candidate-bundle admit-execution` CLI 已在普通配置/Store 初始化之前分派，并覆盖
installed-CLI 的 no-home/no-execution、pin mismatch 和输入字节校验。后续仍需独立 Feature
处理真实 runner、exact evaluator、execution evidence 与恢复协议；input staging 由下述
Feature 105 实现。

## 2026-09-16：Feature 105 candidate input staging

新增 `stage_candidate_execution_inputs` API 和静态 `candidate-bundle stage-inputs` CLI。
它先重验完整 admission、plan 和 caller pins，再将声明的输入复制到新的 `.candidate-inputs-*`
私有目录。输入支持二进制、嵌套目标和空文件；源/目标根按实际目录身份检查，目标逐个重读
size/SHA-256。失败或中断时只清理本次创建且身份仍匹配的内容，清理无法安全完成时返回固定
错误。输入使用新建目录，不合并到源码文件表，也不复制未声明文件。

返回元数据只含摘要、计数和大小；本地 `input_path` 单独提供给调用方。重复调用生成不同
目录，没有自动复用、恢复或执行回执。Feature 105 的 **96** 项测试、installed CLI 及可运行
示例均通过；全仓 **4568 passed, 1 skipped**。详见
[Feature 105 验证记录](../specs/105-candidate-input-staging/validation.md)。

下一步仍需实现消费源码 workspace、staged inputs 和 admission 的真实 runner，再接 exact
evaluator、execution evidence 和恢复协议。本功能没有运行真实模型或框架，不产生效果结论。

## AlphaEvolve 与 OpenEvolve 的关系

[AlphaEvolve](https://deepmind.google/discover/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)
是 Google DeepMind 公布的系统。[官方结果仓库](https://github.com/google-deepmind/alphaevolve_results)
明确说明它不包含运行 AlphaEvolve 的代码；DeepMind 另行公开了
[问题仓库](https://github.com/google-deepmind/alphaevolve_repository_of_problems)。因此不能把任何
第三方仓库描述为 DeepMind 官方实现或完整、逐行复刻。

[OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) 的仓库描述是
“Open-source implementation of AlphaEvolve”。它是 Apache-2.0 的第三方开源实现，采用
LLM 生成、MAP-Elites、quality-diversity、多岛迁移、外部 evaluator 和 checkpoint 等思路。
它与 AlphaEvolve 方向一致，适合作为 Lunar 的首个本地 subprocess producer，但其分数、
数据库和 checkpoint 都不自动成为 Lunar 的权威状态。

ShinkaEvolve 的 native 结果可通过 `src/famou/shinka_handoff.py` 导出到同一 envelope。该
exporter 只读查询 `programs` 表中固定的 `id`、`code`、`language`、`parent_id`、`generation`、
`combined_score`、`correct` 字段，并显式兼容 `programs.sqlite` 与旧的 `evolution_db.sqlite`
文件名；有 live `-wal`/`-shm`/rollback-journal sidecar 的数据库会被拒绝，避免只读打开产生
副作用。调用方可按顺序指定 `program_ids`，此时省略 `top_k`；不指定时，`top_k` 默认一条，
只选择 `correct = 1` 的 convenience rows，并按 producer score、generation、ID 确定性排序。
导出目标要求是不存在的新 leaf，已有 parent 必须是无任意 symlink 组件的目录。源文件优先是
`gen_<generation>/main.<ext>`，仅在该文件缺失时回退到 `best/main.<ext>`，且必须和数据库
`code` 的 UTF-8 字节完全一致。导出后的 envelope 仍须经过 `admit_producer_result` 和
Lunar exact evaluator；Shinka 的 score、correct、metrics、generation 与 SQLite 元数据只归一化
为 digest-only external evidence，parent IDs 只作有界 lineage，不获得 Lunar 的 score、rank
或交付权限。当前只用离线 fixture 验证，未运行真实 Shinka、模型、网络或 Slurm。

Feature 086 的 `remote_material_handoff` 复用这条边界处理 Feature 084 的
`RemoteExperimentState`：只有经过可选 previous-state reconciliation、身份 pin 匹配、状态为
`completed` 且带有 `candidate_source` 的 observation 才能在内存中转换为 producer envelope。
本地 material root 仍由 descriptor-based regular-file、大小、UTF-8、路径 confinement 和
SHA-256 检查保护，随后统一调用注入的 exact evaluator。远端 ID、时间戳、attempt 和任何
score-like evidence 只保留摘要；bridge 不含网络、subprocess、scheduler 或 backend 调用。

## 项目映射

| 项目 | 公开定位 | 对 Lunar 的合适接法 | 优先级 |
|---|---|---|---|
| [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) | AlphaEvolve 风格的程序演化，Apache-2.0 | 先做隔离 subprocess material producer；也可选择性移植 MAP-Elites、双重选择和多岛机制 | P0 |
| [ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve) | 面向开放式、样本高效程序演化，Apache-2.0；有 runner、CLI、并行评测和 Slurm 路径 | 以独立进程或远端作业产出程序与 lineage，再走同一 seed admission | P0 |
| [EoH](https://github.com/FeiLiu36/EoH) | Evolution of Heuristics，MIT | 将 selection/reflection/heuristic mutation 抽成 Lunar 原生策略模块 | P1 |
| [ReEvo](https://github.com/ai4co/reevo) | reflective evolution hyper-heuristic，MIT | 借鉴 reflection 与候选改写策略，评分仍使用 Lunar evaluator | P1 |
| [FunSearch](https://github.com/google-deepmind/funsearch) | LLM 程序搜索示例，Apache-2.0 | 借鉴程序库、采样和 evaluator 驱动的搜索；不作为 AlphaEvolve 后端 | P1 |
| [GEPA](https://github.com/gepa-ai/gepa) | reflective prompt/code optimization，MIT | 注册为文本、prompt 或代码 mutation 策略；需要显式候选类型 | P1 |
| [LLM4AD](https://github.com/Optima-CityU/LLM4AD) / [LLM4AD Next](https://github.com/Optima-CityU/LLM4AD_Next) | 自动算法设计平台，BSD-2-Clause / BSD-3-Clause | 优先作为算法比较和 benchmark 适配层，选定模块再原生化 | P1 |
| [SkyDiscover](https://github.com/skydiscover-ai/skydiscover) | 优化、合成与统一 benchmark，Apache-2.0；仓库内含 AdaEvolve/EvoX 并支持比较多个框架 | 先接 benchmark/task envelope；AdaEvolve 没有独立官方仓库，不能假设单独 adapter | P1 |
| [Darwin Gödel Machine](https://github.com/jennyzzt/dgm) | 开放式自改进 coding agent，Apache-2.0 | 等 Lunar 定义多文件 repository candidate 和隔离执行后再接 | P2 |
| [ADAS](https://github.com/ShengranHu/ADAS) | 自动设计 agentic systems，Apache-2.0 | 需要 agent graph/workflow candidate、运行回执和结构化 diff 后再接 | P2 |
| [EvoAgentX](https://github.com/ANative-Lab/EvoAgentX) | 构建、评估并演化 Agent/workflow，MIT | 作为上游 workflow producer；不能压成单个 Python candidate | P2 |
| [MLEvolve](https://github.com/InternScience/MLEvolve) | 端到端机器学习算法发现，Apache-2.0 | 先以完整实验后端导出 material；训练数据、环境和成本身份需单独契约 | P2 |
| [ThetaEvolve](https://github.com/ypwang61/ThetaEvolve) | 面向 test-time learning/RL 的 AlphaEvolve 扩展，Apache-2.0 | RL checkpoint、训练环境和资源账本成熟后再接 | P3 |

优先级表示接口适配顺序，不表示算法效果排名。仓库自述的 benchmark、SOTA 或可复现性
不能替代 Lunar 在固定 contract、预算、模型、输入和 exact harness 下的对照测量。

## 三层融合方式

### 1. Material producer adapter

`src/famou/producer_handoff.py` 提供通用的 `ProducerResultEnvelope`、`ProducerMaterial`、
`admit_producer_envelope` 和文件入口 `admit_producer_result`；它为有稳定 CLI/runner 的框架定义一个共享 material 边界，不要为每个
框架增加一套 Lunar strategy 状态。请求只包含固定 contract digest、bounded budget、run-scoped
output root 和 producer identity；结果只允许包含 terminal/unknown 状态、opaque producer run ID、
候选 material `{path, size, sha256}`、lineage 和 bounded external evidence。所有外部 evidence
与 record metadata 在进入 Lunar canonical state 前统一变成
`{present, score_present, payload_sha256}`，不保存原始分数或 prose。

producer 产物统一转换为 Feature 084 `SeedManifest`。Lunar 在自身 workspace 内重验候选源
路径与字节摘要、声明的依赖/环境身份和 evaluator fingerprint，然后调用本地
`exact_harness`。`material_refs` 只是带规范化列表摘要的 opaque 引用；除非具体 adapter
另行取回并校验相应物料，不能把该列表摘要描述成物料字节验证。只有生成匹配
receipt 且 `validity == 1` 的 material 才能成为 `Candidate`、进入 archive/population、参与
rank 或最终交付。外部 score 只保存为 provenance；producer 不得直接构造 Lunar
`EvaluationReport`。

这层适合 OpenEvolve 和 ShinkaEvolve，也是其他 CLI 兼容框架的默认接入方式。每个具体
adapter 至少要满足：版本/配置可生成稳定 fingerprint、候选可导出并校验摘要、输出有界、
timeout/cancel 受控、未知结果可区分，而且集成不需要信任其 score。

### 2. Lunar-native algorithm modules

对只需要算法思想的项目，移植 selection、mutation、crossover、reflection、MAP-Elites、
island/migration、novelty 或 retry 机制。模块输入输出使用 Lunar 的 `Candidate`、
`GenerationRequest` 和 `EvaluationReport`，继续由 Lunar 管理 budget ledger、archive、
checkpoint、resume 和 evaluator authority。这条路径适合 EoH、ReEvo、FunSearch、GEPA，
以及 OpenEvolve/SkyDiscover 中经独立基准证明有价值的局部机制。

算法移植必须保留正式 iteration 的语义：至少一个 offspring 完成生成和评估才推进；失败、
timeout、unknown 与无效候选分开记录。不能把外部框架的 retry 次数、generation 或数据库
序号直接映射为 Lunar iteration。

### 3. Remote backend/control plane

长时、集群或服务化框架使用 Feature 084 的 `RemoteEvolutionBackend` 生命周期：
`submit`、`status`、`sync`、`continue_experiment` 和 `cancel`。请求绑定 bundle、预算、producer
和幂等身份；超时、断连或缺少实验 ID 时保持 `unknown`，先 reconcile，禁止盲目重建。
`sync` 只带回 material 和外部 evidence，随后仍回到第一层的本地 exact-harness admission。

Feature 086 的 bridge 是这一回路的离线最后一跳：它只接受 caller 已经取得并 reconciled 的
completed state 和本地同步文件，不执行 `sync`，也不把 completed 生命周期状态解释成
`EvaluationReport`。因此 remote backend 的未知、失败或取消状态仍然只能停在生命周期层。

famou-v2/WebAgent 风格控制面、Slurm ShinkaEvolve、MLEvolve 或其他远端实验适合这一层。
默认 population 构造不能自动联网、发现服务或实例化 remote backend。

## 两种 OpenEvolve 用法必须分开

- `--strategy openevolve` 表示本次搜索由 OpenEvolve producer 执行；最终 Lunar candidate 和
  result 保留 `openevolve` 策略身份，但仍需本地 receipt 才能交付。
- OpenEvolve 结果也可以通过 seed manifest 成为本地 population warm start；此时 candidate
  的策略身份是 `population`，`producer_id=openevolve`、producer fingerprint 和 run ID 留在
  provenance 中。

两条路径可以共用 material、receipt 和 admission 组件，但不能把 population placement
字段硬编码进通用 producer 结果，也不能把 OpenEvolve 的外部分数作为快速通道。

## 实施顺序

1. 完成 Feature 084 的原子 mixed-batch admission、receipt 持久化、fresh revalidation 和
   resume fingerprint 校验；完成 Feature 085 的 population-first 默认及历史 loop 只读边界。
2. 把现有 OpenEvolve one-shot wrapper 收敛为首个 `EvolutionMaterialProducer`，补 producer
   fingerprint、lineage、bounded output、timeout/cancel 和同一 exact-harness receipt；当前
   wrapper 与通用 envelope 均已由离线 fixture 验证。
3. 已用固定离线 fixture 验证 ShinkaEvolve 的显式 best/program exporter、OpenEvolve producer
   输出和 completed remote material observation 能进入同一 `lunar-producer-result-v1` admission；
   不启动真实模型或外部框架。
4. 为 SkyDiscover/LLM4AD 增加 benchmark/task envelope，使用相同 contract、输入、模型、
   evaluator 和物理尝试预算进行比较。
5. 只移植经上述对照有收益的原生算法模块。多文件、Agent/workflow、训练型候选和远端服务
   各自进入后续冻结 Feature，不扩张单文件 seed schema。

完成这些边界只证明互操作和评分权威一致，不证明任何框架提高 Lunar 的有效解率。效果结论
需要新的预注册真实测量；历史 Feature 051/074/076/078/082 的 protocol、manifest、receipt
和统计保持原字节。普通 offspring/candidate 的完整 receipt、contract/evaluator/dependency/
environment fingerprint 后来已由独立 Feature 087 完成，未混入 Feature 086 的 archive
schema。
