# Evolution ecosystem fusion roadmap（2026-09-11）

本文记录 Lunar-Agent 与公开 evolution/program-search 项目的融合边界和优先级。公开项目
信息核对于 2026-09-11；没有执行外部框架、模型、provider、远端服务、候选评测或真实
campaign。当前 Feature 084/085 建立 verified seed、population-first 和协议边界，并实现
OpenEvolve 的有界本地 subprocess producer 接线、ShinkaEvolve 的只读离线结果 exporter，以及
可供 OpenEvolve、ShinkaEvolve 等复用的 transport-free `ProducerResultEnvelope` →
`SeedManifest` adapter；这些接线只由离线 fixture 验证，不能据此声称真实框架已运行或任何
项目的公开效果已由 Lunar 复现。

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

`src/famou/producer_handoff.py` 提供通用的 `ProducerResultEnvelope`、`ProducerMaterial` 和
`admit_producer_result`；它为有稳定 CLI/runner 的框架定义一个共享 material 边界，不要为每个
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
3. 继续用固定离线 fixture 验证 ShinkaEvolve 的显式 best/program exporter 与 OpenEvolve
   producer 输出能进入同一 `lunar-producer-result-v1` admission；不启动真实模型或外部框架。
4. 为 SkyDiscover/LLM4AD 增加 benchmark/task envelope，使用相同 contract、输入、模型、
   evaluator 和物理尝试预算进行比较。
5. 只移植经上述对照有收益的原生算法模块。多文件、Agent/workflow、训练型候选和远端服务
   各自进入后续冻结 Feature，不扩张单文件 seed schema。

完成这些边界只证明互操作和评分权威一致，不证明任何框架提高 Lunar 的有效解率。效果结论
需要新的预注册真实测量；历史 Feature 051/074/076/078/082 的 protocol、manifest、receipt
和统计保持原字节。
