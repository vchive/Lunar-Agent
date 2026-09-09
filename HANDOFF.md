# Lunar-Agent 交接记录

更新时间：2026-09-09
当前仓库：`/Users/liminghan/Documents/lunar_agent`  
当前分支：`main`  
远端：`git@github.com:vchive/Lunar-Agent.git`  
提交身份：`vchive <vchive@users.noreply.github.com>`

## 1. 当前状态

Feature 058 已提交并推送于 `1ae1893`，新增只读预检及公司平台 baseline 来源记录。
Feature 059 已完成普通求解和 isolated compiler/audit 调用的模型预算、超时边界修复。
Feature 059 已提交于 `503fe0a`。Feature 060 已提交并推送于 `f4b7ba9`，修复结构化输出验收
绕过，统一普通/委派 Solver、候选程序执行和最终产物生成的独立输出校验。
用户再次确认现有实验数据已足够；不运行 WebAgent，不再要求补 WebAgent 数据。
2026-09-08 用户进一步要求推进真实 Lunar 评测：当前优先级已切换为运行首个真实 trial，
不再以新功能开发作为前置条件。下文旧轮次的“本轮不启动真实 trial”仅是历史记录。
已通过用户授权的 CC Switch 接通模型，完成 `supply_chain_inventory` 的首个真实 1 run ×
1 round：有效性 `1.0`、得分 `0.2079`，历史最佳 `0.3496`。独立的 2 runs × 5 rounds
试验已结束，但两个 run 均在首轮 subject 退出、未进入评分；最新证据与待修复项见第 16 节。
用户随后要求改用 WebAgent 已有记录中的较弱求解模型：已选定并实际验证 `glm-5.1`，
后续不再启动 `gpt-5.6-sol` 求解。Feature 061 已补齐此前失败暴露的安全诊断缺口；
GLM 独立单 case 实评已执行，在 900 秒预算内未产出候选、没有进入评分，安全诊断为
model timeout。当前模型选择、结果与证据边界见第 17–18 节。

以下保留 2026-09-06 续接时的历史提交记录：

```text
4a61044 test: cover nested candidate manifest traversal
46d576d docs: update handoff for failure statistics
32561c9 feat: report deep evolution failure statistics
558f510 docs: record continuation findings
f633dde fix: allow candidate interpreter startup before timeout
b3df70e docs: add lunar agent handoff
edaa4a6 feat: add controlled deep evolution feedback
```

此前收口已修复普通/深度效果试验的记录权威和深度 round receipt 完整性，更新 Feature
048/051/052 文档，并补齐官方 FM-Eval AgentServer normal-mode comparator。变更已按指定身份
提交并推送；完成时保持 `main == origin/main`。

## 2. 产品目标和设计边界

Lunar-Agent 的目标是一个独立、本地、可被其他 Agent 调用的算法问题 Agent：

- 用户可以直接运行；Codex、Hermes、OpenClaw 等也可以把它当作 CLI 子进程调用。
- 不要求用户机器预装 Hermes、OpenCode、Codex 或某个全局配置目录。
- 内部自带 Agent runtime 骨架，同时允许显式接入 OpenAI-compatible endpoint、subprocess
  或 mock runtime。
- 解决算法/组合优化问题，输出结构化文件、数据和可验证报告，而不只是对话文本。
- 借鉴 WebAgent 的 clarify/build/evolve、fresh loop、评估、恢复和证据边界，但不复制其
  服务化、队列、计费、远端 workspace 架构。
- 同时保留三类搜索入口：`loop`、`population`、显式 `OpenEvolve` adapter。
- 所有评分必须由独立 evaluator/harness 给出，Agent 不能自报分数。

当前总体架构可看：

- [架构文档](/Users/liminghan/Documents/lunar_agent/docs/architecture.md)
- [项目 README](/Users/liminghan/Documents/lunar_agent/README.md)

核心链路：

```text
CLI / parent Agent
        ↓
LocalController + DomainRouter + MasterPolicy
        ↓
AlgorithmProblemContract / plan / output contract
        ↓
Runtime Adapter
  mock | subprocess | OpenAI-compatible | AgentLoopRuntime
        ↓
loop | population | openevolve adapter
        ↓
candidate archive → execution/evaluator → verified artifacts/data/report
```

深度效果评测另有独立边界：

```text
fresh subject round
        ↓
exact private extractor/evaluator harness
        ↓
bounded RoundFeedback
        ↓
fresh subject round + shared candidate workspace
```

## 3. 已完成工作

### Feature 001–011：独立 Agent 基础和恢复

已完成 standalone local Agent、CLI/TUI 基础、Hermes-inspired bounded tool loop、模型 runtime
adapter、交互恢复、transcript、Master Policy、plan contract、DAG 调度、artifact acceptance、
evidence-guided recovery、隔离 worker pool、retry feedback。

对应目录：

```text
specs/001-standalone-local-agent
specs/002-webagent-effect-parity
specs/003-hermes-inspired-local-agent
specs/004-interactive-session-recovery
specs/005-session-transcript-recovery
specs/006-master-policy-plan-contract
specs/007-domain-routing-solver-evaluator
specs/008-artifact-acceptance-contracts
specs/009-evidence-guided-recovery
specs/010-local-isolated-worker-pool
specs/011-verified-retry-feedback
```

### Feature 012–026：算法任务、Agent adapter 和演化运行时

已完成算法问题契约、loop/population/OpenEvolve 入口、Agent delegation、Agent-backed
generator/evaluator、portfolio、evaluator ensemble、runtime-backed evolution、执行验证、
对话式算法任务、role DAG、evolution agent loop、结果 handoff、provenance、verified feedback。

### Feature 027–036：benchmark、运行 profile 和结构化输出

已完成 evolution benchmark、unified benchmark、runtime profile benchmark、Agent evidence、
structured algorithm outputs、input staging、role evidence、runtime artifact envelope、
conversational evolution handoff、evolved output materialization。

### Feature 037–047：执行闭环、评估器安全和搜索增强

已完成 execution-grounded evolution/refinement、objective harness handoff、frozen evaluator
bundle、private data profile、adversarial evaluator audit、solver scoring contract、verified
experiment memory、adaptive search orchestration、contract-driven algorithm playbooks、
quality-diversity population。

对应重点目录：

```text
specs/037-execution-grounded-evolution
specs/039-execution-grounded-refinement
specs/040-frozen-evaluator-bundle
specs/041-private-data-profiling
specs/042-adversarial-evaluator-audit
specs/043-solver-scoring-contract
specs/044-verified-experiment-memory
specs/045-adaptive-search-orchestration
specs/046-contract-driven-algorithm-playbooks
specs/047-quality-diversity-population
```

### Feature 048–050：Famou-Bench 效果层

- Feature 048：导入历史结果，比较单 case 的 Lunar best 与通用 baseline historical best，
  只允许独立 harness 提供分数。
- Feature 049：加入可执行的 subject/harness adapter，支持 public projection、private
  extractor/evaluator、receipt 和环境隔离边界。
- Feature 050：生成 content-addressed effect kit，冻结 suite、case digest、public file ledger、
  evaluator/extractor digest，避免 benchmark 内容漂移。

本地已准备好经过官方 publication 身份校验的 `supply_chain_inventory` kit 和历史 comparator：

```text
.lunar/famou-kit-real-001/
```

该目录被 `.gitignore` 忽略。baseline 来自 FM-Eval 只读 Query 的实验
`fmexp-1fae1f63-b54a-400b-9ca4-118a4c6387f9`，三次历史分数为
`0.3496 / 0.3496 / 0.2415`，historical best 为 `0.3496`。选中 case 的三条结果都满足
FM-Eval conclusion eligibility；整个来源实验本身仍保留 `failed/partially_valid` 状态，不能把
case slice 的可比较性扩张成整个实验成功。该实验的 adapter 是 `agentserver` 且
`deep_evolution=false`，所以它是官方 FM-Eval AgentServer normal-mode comparator，不能称为
WebAgent historical baseline；严格的 WebAgent 比较仍需同 publication/case 的
`adapter=webagent` export。

### Feature 051：五轮深度演化效果试验

目录：

```text
specs/051-deep-evolution-effect-trial/
src/famou/deep_effect_trial.py
tests/test_deep_effect_trial.py
```

命令：

```bash
lunar-agent effect-deep-trial ...
```

行为：默认 5 个 outer rounds；每轮启动新的无记忆 subject 进程；共享 attempt workspace；
每轮执行 exact private harness；每轮原子保存 logical-run record；`--resume` 校验 suite、
baseline、case、receipt、harness 和配置身份；报告 round curve、best、P50/P90、gain 和
milestone。

本次进一步加固了效果试验的恢复和评分权威：

- built-in deep subject receipt 用 `request_sha256` 绑定 canonical request；旧的已完成
  receipt/record 仍可读取，但未登记 subject round 没有绑定摘要就不能复用；
- 恢复时逐项复核 subject 的模型、evidence、turns、usage，以及 harness 的 extraction、
  validity、overall、quality、detail metrics 和已记录的 harness request 摘要；
- 已有 request-bound subject receipt 且 harness 目录安全时，未写入 durable round 的 harness
  目录会删除并由 private harness 重评分；harness 早于 subject receipt 或路径不安全会 fail
  closed。未在 state 中登记摘要的普通/深度 `record.json` 也不能自动成为权威记录；
- 只有 `incomplete_rounds` 可继续原 attempt；进程或边界失败在下一次恢复时创建新 attempt，
  并保留旧目录作为证据；
- control、state、record、attempt 路径检查完整祖先 symlink 链；subject 不能预建同级
  harness workspace；
- `record.previous.json` journal 覆盖 `record.json` 已替换而 `state.json` 尚未登记新摘要的
  中断窗口，只允许回滚到与 state 摘要精确匹配的上一版本。

### Feature 052：受控 RoundFeedback 契约

目录：

```text
specs/052-deep-evolution-feedback-contract/
src/famou/deep_feedback.py
tests/test_deep_feedback.py
```

当前反馈不再是裸的 validity/quality/overall 三个分数，而是严格、有限的 projection：

- finite scores、score delta、best round；
- 通用 allowlisted detail metrics；
- 候选文件的相对路径、大小、SHA-256，不传文件内容；
- `invalid_candidate`、`evaluation_failed` 等有限失败类别；
- `repair_validity`、`repair_evaluation`、`change_search_strategy`、`refine_best`、
  `preserve_best_and_probe` 指令；
- 停滞窗口默认 2，可由 `--stagnation-rounds` 配置并冻结进 state identity。

subject receipt 仍然不允许携带分数；分数只能来自 private harness。

### Feature 053：深度试验失败统计

目录：

```text
specs/053-deep-effect-failure-statistics
```

深度试验的每个 case 报告现在包含有界 `failure_statistics` 投影：逻辑 run 错误码、round
反馈类别、已记录/已完成 round 数、超时计数，以及覆盖每个配置 round（含空 round）的固定
明细。该投影只从已验证的持久记录派生，不创建分数，也不改变 private harness 的评分权威。
本次还修复了候选物化的极短超时可靠性：候选解释器启动保留 50ms 下限，避免正常候选在
启动阶段被误判超时；较长预算保持原值。

### Feature 054–055：模型 profile、成本控制与 runtime 集成

目录：

```text
specs/054-model-profiles-cost-control/
specs/055-runtime-model-profile-integration/
src/famou/profiles.py
src/famou/model_profile.py
```

`ModelProfile` 提供无凭据的模型身份、thinking budget、步数/超时、token 和 micro-USD 成本
上限；`UsageLedger` 对每轮规范化用量做整数计费并在超限前拒绝。`AgentLoopRuntime` 可选接入
profile，使用 profile 的默认 timeout 和 step 上限，在每轮模型响应进入工具动作前校验 token/cost
预算，并在成功结果中报告 profile 名称和可用的 `cost_micros`。没有 profile 的既有调用保持原有
行为；同一 runtime 复用时账本按 invocation 重置。

### Feature 056：CLI runtime profile provenance

目录：

```text
specs/056-cli-runtime-model-profile-provenance/
```

普通 `run`、`solve`、`resume`、`answer` 和 `plan` 的 `--agent-loop` 现在可通过
`--model-profile PATH` 加载有界 JSON `ModelProfile`。profile 必须是非 symlink 的普通 UTF-8
JSON 文件，内容经 `ModelProfile.from_dict` 校验；它可提供默认 model，并把 timeout、步数、
token 和成本限制传入 `HermesSessionRuntime`。没有 `--agent-loop` 时显式 profile 会在运行前
拒绝。detached 子进程只传播 profile 路径，API key 仍通过环境变量传递。solve 的 compiler
fingerprint 包含 profile 的 canonical SHA-256，profile 变更会拒绝 conversational resume。
one-shot runtime、`run_isolated`、effect adapter 和 evolution/benchmark 专用 runtime 参数
仍未接入该 CLI profile，后续应单独设计。

## 4. 本地知识库索引

知识库根目录：

```text
/Users/liminghan/Documents/fm/ku-offline-D15p9TZGvN/
```

正文通常在 `raw/content/<docGuid>.json`，同步日志在 `archive.log`，离线渲染页面在
`docs/<docGuid>/index.html`。

重点文档：

| 文档 | docGuid | 作用 |
|---|---|---|
| 深度演化 PRD | `sqWURJ5cTnE_Z7` | Session/Experiment 生命周期、Top 5、可恢复和用户可见演化图谱 |
| v2.5 深度演化工具集设计 | `7bveCuILHL_BnP` | evolve_create/update/continue/cancel/list/status/sync 七工具和窄控制面 |
| web agent 与 famou-v2 深度演化打通链路梳理 | `y0gVkzefWknA6h` | Console → AgentServer → AgentRunner、异步进度回调 |
| 深度演化阶段 webagent loop vs famou-v2 evolve | `qx9kRYpa6zTQmP` | 同模型 loop 与 population/pipeline 对比、reward hacking 证据 |
| 基于 famou-bench-v2 的深度演化阶段模型评测报告 | `YfEcoKAjskbg3P` | 100 轮模型对比、token/时长/成本、格式失败影响 |
| webagent benchmark 测评工程方案（二期） | `xOvDqBtdcHUO16` | fm-eval workload、评测服务化和 benchmark 接入方案 |
| famou-v2 Island & Population Ablation | `jncZRh92LHwYV0` | population/island 消融证据，后续比较 population 时查阅 |

面试/架构辅助文档：

```text
/Users/liminghan/Documents/fm/面经/合集/伐谋agent架构细节面试小抄.md
/Users/liminghan/Documents/fm/面经/合集/项目二-伐谋WebAgent与Workspace.md
/Users/liminghan/Documents/fm/面经/合集/webagent-架构图.svg
```

## 5. 可查阅代码仓库

### Lunar-Agent

```text
本地：/Users/liminghan/Documents/lunar_agent
远端：git@github.com:vchive/Lunar-Agent.git
分支：main
```

### WebAgent

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/webagent
远端：https://liminghan01@icode.baidu.com/baidu/acg-fm/webagent
```

已知分支：

```text
origin/master
origin/famou-v2.5/base
origin/famou-v2.5/evolve_tool
origin/famou-v2.5/master-agent
origin/multi-round
origin/memory_card
origin/famou/memory
origin/feature/or-agent
```

重点代码检索词：`evolve`、`loop`、`population`、`workspace`、`agentic loop`、`master agent`、
`analyst`、`executor`、`callback`。

### Famou-Bench

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-bench
远端：https://liminghan01@icode.baidu.com/baidu/acg-fm/famou-bench
当前本地分支：agentco-bench-lite
```

真实 case 示例：

```text
/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-bench/03_assignment/supply_chain_inventory
```

该 case 已包含 `instruction.md`、`data/`、`tests/extractor_agent.py`、`tests/evaluator.py`、
`tests/baseline/reference_metrics.json`，但 `reference_metrics.json` 不是 FM-Eval historical
run export，不能直接冒充 WebAgent baseline。

### FM-Eval

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/fm-eval
远端：https://liminghan01@icode.baidu.com/baidu/acg-fm/fm-eval
```

重点：`container_runtime/harness/`、`tests/test_harness_equivalence.py`、
`tests/golden/harness_equiv/`、`tools/release/`、`service/`。

### Famou-v2

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-v2
远端：https://liminghan01@icode.baidu.com/baidu/acg-fm/famou-v2
```

### 外部参考

```text
OpenEvolve: https://github.com/algorithmicsuperintelligence/openevolve
DeepSeek Harness: https://github.com/deepseek-ai/deepseek-harness
Lunar-Agent remote: https://github.com/vchive/Lunar-Agent
```

OpenEvolve 在 Lunar 里是 adapter，不是必须依赖；Hermes/OpenCode/OpenClaw 同样是可选外部
调用方或显式 runtime，不是 Lunar 的部署前置条件。

## 6. 下一步任务（按优先级）

### P0：结合历史数据解释 GLM 结果，冻结后续测量方案

官方 publication kit 和 AgentServer normal-mode historical comparator 已就绪，不需要手填
历史分数：

```text
suite:    .lunar/famou-kit-real-001/suite.json
projection: .lunar/famou-kit-real-001/baseline-agentserver.json
raw:      .lunar/famou-kit-real-001/fm-eval-results.json
case:     supply_chain_inventory
baseline model (historical): gpt-5.6-sol
current Lunar solver:        glm-5.1
adapter:  agentserver (deep_evolution=false)
```

关键摘要：

```text
suite SHA-256:    1701995e8f65d9bd2ba73e840b870c9427fce27107e14048cffb34d594a04e46
baseline SHA-256: 17e308b4eca5cdc1ebf334daf9c8956fe8871230c1ddcd38872d56f66466a34b
raw SHA-256:      fa41c138ed3c73a50dd17e9e99704b41a079aef15ab45b1a6bdd65c3897c889d
```

`provenance.json` 保存只读查询、模型观测和来源实验状态；
`publication-identity-verification.json` 保存发布期 FM-Eval SDK commit
`b17023d3f849f3312f8fc79f366b0c18495ee726` 的复算证据。旧 `baseline.json` 没有内嵌 adapter
provenance，保留作历史审计，SHA-256 为
`355a8f1dee33532e720711a9c72988e83f61b4f9af8e4187e51ed3e859579440`。Feature 058 从同一 raw
export 离线生成 `baseline-agentserver.json`，明确保存 `source=company-platform` 和
`adapter=agentserver`；除来源字段外，模型、case 身份和全部 per-run 值与旧 projection 一致。
`baseline-agentserver-provenance.json` 记录本次输入/输出摘要和一致性复核。

当前任务复用冻结 suite/harness，已有 AgentServer baseline 仅保留审计；不补跑 WebAgent 或搜集新的 WebAgent export。
用户最新模型要求优先：已有单 case baseline 的模型是 GPT，与新选 GLM 不同；旧 baseline
保留作历史证据，不传入 GLM 的同模型比较、不改写模型标签。离线 WebAgent 报告足以确认
GLM 求解模型选择，但其中跨 case 聚合值不能伪造成此 case 的 per-run baseline。
effect protocol 的规范机器字段是 `baseline_historical_best`；显式 WebAgent provenance 或
旧 `fm-eval` 无 provenance 的兼容路径还会输出 `webagent_historical_best` 别名。因此当前
示例使用带明确来源的新 projection。只有将来另行要求 WebAgent-specific 比较时，才需要
取得相同 publication、CaseRevision 和 harness 身份下 `adapter=webagent` 的 export。
`effect-baseline` 在默认 `webagent` 模式下会拒绝该 export 的显式 `agentserver` evidence；使用
`--adapter-kind agentserver --baseline-source company-platform` 可离线生成带明确来源的
`baseline-agentserver.json`。冲突的 adapter evidence 仍会被拒绝；缺少 adapter metadata 的
legacy export 继续兼容，但必须另外保留来源证明。

2026-09-08 初次检查时，普通 shell 中没有
`FAMOU_MODEL_ENDPOINT`、
`FAMOU_API_KEY`、`FAMOU_MODEL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`、
`ANTHROPIC_MODEL`、`OPENAI_API_KEY`、`OPENAI_BASE_URL` 或 `ANTHROPIC_API_KEY`。本轮已另行创建
专用 `.lunar/harness-venv-sdk-0.1.81/` 并安装、验证评分依赖，见第 15 节；无需在项目 venv 中
重复安装。来源实验的 extractor 冻结为 Anthropic API、模型
`glm-5.2`，发布期 FM-Eval harness 锁定 `claude-agent-sdk==0.1.81`；exact extractor 必须使用
包含对应依赖、与冻结身份相符且获授权的运行环境，并显式设置
`ANTHROPIC_MODEL=glm-5.2`。密钥只通过显式环境传递，不能写入仓库、request、receipt 或
report，也不能用 Codex/Claude 的本机登录态冒充 extractor 配置。随后用户明确授权复用
CC Switch 当前 provider 的 API 配置；第 16 节记录了只读接入、显式环境注入及首轮真实结果。
普通 shell 中没有这些变量已不再是启动阻塞。

当前执行步骤：

1. 先读第 17 节，检查 `.lunar/real-eval-glm-5.1-20260908/started.json`、`report.json`
   和 `attempt-001/diagnostics/`，保留已运行 attempts；不要重复启动已消费的实验目录。
2. 当前 solver 只用 `glm-5.1`，extractor 保持 `glm-5.2` 与 SDK `0.1.81`，继续通过
   已授权的 CC Switch 只读加载连接环境，不再运行旧 GPT 脚本。
3. 单 case 实评由本机 `run_single.py` 调用已有 subject/exact harness adapters，预先验证
   冻结输入，成功后检查实际 receipt 与模型身份。只有 private harness 的实际结果可评分。
4. 本次没有 GLM per-run baseline，仅报告独立分数、用时与可观测用量；不计算匹配模型的
   delta/breakthrough，不用跨 case 聚合分代替单 case 历史结果。
5. 这两个冻结 slot 已完成；按第 20 节汇总失败与分母。未来新的 baseline-free 批量测量
   必须单独冻结 manifest 和 SDD，不放宽现有 comparative runner 的模型一致性 guard。

### P1：修复真实 case 适配差距

真实 Famou-Bench 的 extractor 使用 `claude_agent_sdk`，并可能需要 case-specific 的数据
语义。执行真实试验后，若 Lunar 写出的文件不能被 extractor 识别，优先补充：

- case-specific output contract / `OutputSpec`；
- subject prompt 的目标文件提示；
- solution artifact materialization；
- harness detail metrics 的安全 allowlist；
- 不改变 evaluator authority 的 repair loop。

不要把 extractor 改成“帮 Agent 重新求解”，也不要将 private `gt.json`、`information.md`、
`tests/` 内容注入 subject。

### P1：统一 native loop / population / OpenEvolve 的反馈抽象

当前 Feature 052 只覆盖 effect-deep-trial 外层 loop。后续可以把 `RoundFeedback`、native
`ExecutionAwareRefinement`、population 的 best/novelty summary、OpenEvolve result envelope
统一到一个 runtime-neutral `EvolutionFeedback` 接口，但必须先有真实效果数据再抽象。

### P2：模型 profile 和成本控制

从知识库评测看，深度演化模型需要同时看质量、时延、token 和格式失败率。现有进度：

- Feature 054–057 已提供 `ModelProfile`、max steps/timeout、每次调用的 token/cost 预算和
  telemetry；深度试验的每个 fresh subject round 分别应用预算。
- Feature 059 补齐 missing usage、isolated 调用、显式 timeout 和精确预算耗尽时的行为。
- Feature 053 已提供 per-round error code/timeout breakdown；更细 parse failure 分类待需要时扩展。
- 跨所有 outer rounds 的总预算仍是后续工作；`thinking_budget` 当前只保存配置，未映射到
  provider 请求参数，不应声称它已经限制了推理 token。
- 后续支持新版 workload-based export 时，把权威 `experiment.request.workload_ref.kind` 纳入
  baseline adapter guard，并明确它与 `adapter_request.kind` 的优先级；
- best-of-run、best-of-round、suite average 的明确区分。

## 7. 6Astra 模型切换注意事项

截至交接时，仓库代码没有 `6Astra` 的硬编码限制。Lunar 的 OpenAI-compatible runtime 接受
任意非空模型字符串，入口包括：

```bash
--model 6Astra
--agent-runtime-model 6Astra
export FAMOU_MODEL=6Astra
```

但模型必须真实存在于所配置的 endpoint/provider，并且 provider 返回的 `model` 字段如果存在
必须满足身份校验。Codex Desktop 项目顶部的“当前模型”属于宿主应用的模型目录/权限选择，
不是 Lunar 仓库代码控制的配置；仓库无法把一个未被宿主暴露或未被 endpoint 支持的模型强行
加入 Codex 的模型切换列表。

后续接手者应区分两件事：

1. **Lunar CLI 调模型**：检查 `FAMOU_MODEL_ENDPOINT`、`FAMOU_MODEL` 或对应 CLI 参数，确认
   endpoint 的路由文档中确实使用 `6Astra` 这个精确 ID。
2. **Codex 项目本身切换模型**：检查 Codex Desktop 的宿主模型权限、项目策略和当前 host 的
   model catalog；这不由 Lunar 项目文件解决。

此问题在本次交接前尚未完成宿主侧诊断，不能把它误判成 Lunar runtime bug。

## 8. SDD 工作规范

当前 `.specify/feature.json` 指向：

```text
specs/061-subject-failure-diagnostics
```

后续新功能必须：

1. 新建 `spec.md`、`plan.md`、`tasks.md`，必要时补 `research.md`、`data-model.md`、
   `quickstart.md`、`contracts/`。
2. 先写失败测试，再实现。
3. 运行：

```bash
uv run pytest -q
uv run ruff check src tests
uv run python -m compileall -q src
uv build
SPECIFY_FEATURE_DIRECTORY=/Users/liminghan/Documents/lunar_agent/specs/<feature> \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

4. 代码提交使用：`vchive <vchive@users.noreply.github.com>`。
5. 默认直接在 `main` 开发并推送；不要擅自切换到工作树或新分支。

## 9. 接手第一步

新 Agent 应先阅读本文件、`README.md`、`docs/architecture.md`、Feature 051/052 的 SDD 文档，
然后执行：

```bash
cd /Users/liminghan/Documents/lunar_agent
git status --short --branch
git log --oneline -5
uv run pytest -q tests/test_effect_trial.py tests/test_deep_feedback.py tests/test_deep_effect_trial.py
```

接着阅读第 17 节并检查 GLM 实验的 started/report/diagnostics；当前 solver 是 `glm-5.1`。
复用冻结 suite 与 exact private harness，已有 GPT baseline 和第 15–16 节的 GPT 脚本仅用于
历史审计。不要重复运行 WebAgent、要求补数据或把 GLM 实评伪装成匹配模型的历史对照。
只有 exact harness 实际完成后才能报告新的独立分数；没有同模型 per-run baseline 时不计算
breakthrough，也不声称 WebAgent parity、suite parity 或 statistical superiority。

## 10. 本次续接记录（2026-09-06）

已通过 FM-Eval 官方只读 Query 取得 machine-readable 历史结果、case catalog 和 publication
身份，完成 `supply_chain_inventory` 的 official-publication kit、AgentServer normal-mode
baseline、provenance 和发布期 SDK 身份复算。历史三次分数为
`0.3496 / 0.3496 / 0.2415`；requested/effective model 都是 `gpt-5.6-sol`，evidence 为
`runtime_observed`，authority 为 `descriptive`，所选 case slice 的 conclusion eligibility 为
`eligible`。来源 adapter 是 `agentserver` 且 `deep_evolution=false`，因此不能把它标成 WebAgent
baseline。严格的 WebAgent comparison 仍缺同身份 `adapter=webagent` export。这些产物位于被
`.gitignore` 忽略的 `.lunar/famou-kit-real-001/`，不包含凭据。

本次还修复了普通/深度效果试验对未登记 record 的自动采信、深度 receipt/request 绑定、完整
telemetry/metric 恢复校验、未登记 harness 重评分、失败 attempt 复用边界、subject 越界创建
harness workspace、祖先 symlink、record/state 提交窗口，以及非 WebAgent baseline export 的
误接收。`record.previous.json` 只在摘要与 state 当前授权版本精确匹配时用于恢复；伪造或摘要
不匹配的 journal 会 fail closed。旧的已完成 schema 继续兼容读取，但不能追溯获得新摘要提供
的完整性保证；需要新证据时必须重新评分。

针对性及全仓测试、Ruff、compileall、构建、Feature 048/051 Specify 前置检查和
`git diff --check` 已通过。真实 `2 × 5` 深度试验尚未运行：当前环境缺少显式 subject endpoint/
model 凭据、extractor 的 `glm-5.2` 配置和包含 `anyio`、发布期 `claude_agent_sdk` 的运行环境。
不得把 AgentServer historical baseline 的准备完成误报为 WebAgent baseline 或新的 Lunar
效果结论。

Feature 054/055 已完成并通过全量 pytest、Ruff、compileall、构建、Specify prerequisites 和
`git diff --check`。Feature 056 已完成并通过全量 pytest、Ruff、compileall、构建、Specify
prerequisites 和 `git diff --check`，提交于 `8c00edd`。

## 11. Feature 057（2026-09-07）

Feature 057 已完成实现：`effect-subject` 支持受限 `ModelProfile`，并在不暴露凭据或分数的
前提下输出 profile digest、token usage 和 cost telemetry。普通/深度 effect trial 的请求、
receipt、logical record、report 和 resume identity 均绑定 profile digest；profile 文件被修改、
缺失或与请求模型不一致时 fail closed。无 profile 的旧请求和历史 record 继续兼容读取。

已通过全量 pytest、Ruff、compileall、`uv build`、Feature 057 Specify prerequisites 和
`git diff --check`，提交于 `9e08129`。真实效果试验仍未运行，subject endpoint/model 凭据及
exact extractor 运行环境待配置；不得据此声称 WebAgent parity 或新的效果结论。

## 12. Feature 058（2026-09-08）

Feature 058 已完成实现：新增只读 `effect-preflight`，在不启动 subject、exact harness 或
模型请求的情况下，复核冻结 suite/baseline、public case、命令可执行文件、显式环境变量、
model profile digest，以及 exact harness Python 的 import/distribution 能力。预检报告只保留
身份、哈希、版本和环境变量名称，不写入凭据、私有路径、命令原文、分数或 extractor/evaluator
输出；可选 JSON 文件使用新路径原子写入并拒绝 symlink/覆盖。

Feature 058 的聚焦测试和全量 pytest、Ruff、compileall、`uv build`、Feature 058 Specify
prerequisites 以及 `git diff --check` 均已通过。已从本地 raw export 生成带 `agentserver` 来源的
`baseline-agentserver.json`，历史最佳仍为 `0.3496`，仅用于所选 case 的描述性历史对照。
本轮没有运行 WebAgent 或真实 Lunar trial。未来真实试验需要显式 subject endpoint/model
凭据，以及包含 `anyio` 和发布期 `claude_agent_sdk==0.1.81`、并配置 `ANTHROPIC_MODEL=glm-5.2`
的 exact harness 环境。预检通过也不构成新的 Lunar 效果结论。

## 13. Feature 059（2026-09-08）

Feature 059 统一 `AgentLoopRuntime.run` 和 `run_isolated` 的模型执行约束。有 token/cost
上限时，每个返回的响应必须具备合法 usage；缺失、格式错误或超限会在执行工具、保存成功
响应或生成 subject completed receipt 前失败。用量刚好达到上限的最终文本可成功；同样
用量的工具请求会在副作用发生前停止，不再发起下一次模型调用。

显式 timeout 只能收紧 profile 上限。模型返回和各工具执行前后检查剩余时间，过期响应
不得成为成功结果或触发下一步。账本改为每次调用独立；isolated 仍只有 system/user 输入、
空工具集，不读写 transcript/memory，无 profile 的旧路径保持兼容。

先验证 69 项新增 runtime 回归中 42 项失败、27 项通过，及 4 项 subject adapter 回归全部
失败，再实现修复；实现后 126 项聚焦测试通过。费用依据响应后 usage 计算，不能撤销已计费
请求或保证单次请求绝不超支；运行中的模型/工具仍负责自身取消。跨整个深度试验的总预算
尚未实现，当前预算粒度是一轮 fresh subject invocation。

全仓 532 项 pytest、Ruff、compileall、`uv build`、Feature 059 Specify prerequisites 和
`git diff --check` 均通过；独立审查未发现阻塞问题。

继续使用已有 `baseline-agentserver.json`，不重新运行 WebAgent，也不要求新的平台实验数据。
后续优先按实际需求完善求解产物和演化流程；不在没有真实效果证据时抽象统一反馈接口。

## 14. Feature 060（2026-09-08）

已修复自定义 acceptance 的 `any` 分支可以绕过必需 OutputSpec 的问题。此前，缺少字段的
CSV 可能因为另一条文字条件通过而被提升并交付；现在声明输出始终与 base evaluator、task
acceptance 共同作为必过条件。删除了仅因 output_valid 出现在规则树中就跳过校验的优化。

`evaluate_output_contract` 复用既有格式、字段、大小与安全路径检查，独立处理最多 32 个
OutputSpec，并保留 `output_valid` 叶子诊断用于重试反馈。可选输出只有真正缺省才跳过；
已存在的目录、直接/断开/循环软链接、软链接祖先和非目录祖先都不能被当作缺省。
普通/委派 Solver、ContractCandidateRunner、最终 materialization 均使用该函数。

先确认 controller 17 项新增回归中 9 项失败、8 项通过，候选/最终产物的 4 项路径阻塞回归
全部失败；实现后 93 项聚焦测试通过。测试覆盖缺字段后重试修复、只提升正确产物并校验
交付摘要。旧 materialization 恢复证据无需迁移，但本次不会追溯重新评价已完成的历史 run。

现有通用 acceptance 语法仍保留自身 32-rule 上限；独立输出检查不消耗该表达式的规则额度。
本轮没有改变 CSV/JSON 内容格式规则、promotion 事务或 evaluator 评分权威。继续使用既有
实验数据，没有运行 WebAgent、真实 Lunar trial、平台查询或新的模型调用。

全仓 566 项 pytest、Ruff、compileall、`uv build`、Feature 060 Specify prerequisites 和
`git diff --check` 均通过；独立审查未发现阻塞问题。

## 15. 首次真实评测准备（2026-09-08）

用户要求继续并追问何时真实评测 Lunar。当前优先执行真实试验；无需等待下一项 feature，
也不再寻找 WebAgent 基线。首轮为 `supply_chain_inventory` 的 1 run × 1 round，通过后在
新 workspace 扩展为 2 runs × 5 rounds。沿用既有 company-platform/AgentServer baseline，
历史最佳 `0.3496`，保持单 case 描述性对照的证据边界。

本机准备产物（全部位于忽略目录，无凭据）：

```text
.lunar/real-eval-20260908/README.md
.lunar/real-eval-20260908/run.sh
.lunar/real-eval-20260908/input-checks.json
.lunar/real-eval-20260908/harness-environment.json
.lunar/real-eval-20260908/harness-requirements.lock
.lunar/real-eval-20260908/sdk-wheel-verification.json
.lunar/real-eval-20260908/readiness.json
.lunar/harness-venv-sdk-0.1.81/
```

准备结果：

- suite、baseline、raw export、完整 private case、extractor、evaluator 和公开文件摘要均
  已复核，baseline 的 benchmark/evaluation profile 与 suite 一致。
- 专用 Python `3.13.12` 使用 `venv --copies` 创建，可执行文件非 symlink。已安装
  `claude-agent-sdk==0.1.81`、`anyio==4.15.1`、`mcp==2.2.0`；extractor 所需 SDK 符号实际
  import 和 `pip check` 均通过。发布期仅锁定 SDK，传递依赖没有完整历史锁；本次实际版本
  单独记录，不能声称重建了发布期的完整依赖环境。
- PyPI 直连下载较慢，改用清华镜像获取 macOS arm64 SDK wheel，并核对官方 PyPI SHA-256：
  `e4bc8797cc2bc882031cf6b287a550ae2bb38a3822aa081e9ffc81bb4bed51da`。
- 启动脚本固定 subject `gpt-5.6-sol`、extractor `glm-5.2`，分别显式传递环境。每次先预检，
  通过后才启动 trial；拒绝缺失或空的四个连接变量。Bash 3.2 语法检查及缺省/空值退出检查
  通过，未创建 smoke/deep trial 目录。

本节准备阶段的启动阻塞曾是缺少以下连接配置，现已通过第 16 节的用户授权 CC Switch 接入解决：

```text
FAMOU_MODEL_ENDPOINT
FAMOU_API_KEY
ANTHROPIC_BASE_URL
ANTHROPIC_AUTH_TOKEN
```

已向用户请求现有环境配置文件路径或本机环境注入，不要求在聊天中发送密钥。不要搜索其他
应用的登录态来代替配置。配置到位后在同一进程环境中执行：

```bash
bash /Users/liminghan/Documents/lunar_agent/.lunar/real-eval-20260908/run.sh smoke
# 首轮真实链路完成并核对后：
bash /Users/liminghan/Documents/lunar_agent/.lunar/real-eval-20260908/run.sh deep
```

`run.sh` 每次都会重新预检；`smoke --resume` 或 `deep --resume` 只恢复各自冻结的配置。
当时 `readiness.json` 是缺配置状态记录，没有模型调用、私有 harness 执行或新的 Lunar 分数；
该文件现已更新为第 16 节的实际运行状态。本次准备仅更新交接文档和本地实验文件，没有修改产品实现，未重跑
已通过的 566 项全仓测试。

## 16. CC Switch 接入与首轮真实结果（2026-09-08）

用户明确授权使用本机 CC Switch，若不能接入再提供 key。已只读接入 CC Switch `3.19.2`
的当前 Codex/Claude provider；没有修改 app 设置或开启代理。辅助脚本
`.lunar/real-eval-20260908/ccswitch.py` 只读 settings 与 SQLite，将 API 配置仅通过进程环境
交给现有 `run.sh`，不输出或复制密钥。CC Switch 当前 Codex 默认模型虽然是 `gpt-6-astra`，
本次实验仍固定为 `gpt-5.6-sol`，未改变历史比较的模型名。

实际连接证据：

- 两组当前接口的模型列表都包含 `gpt-5.6-sol` 和 `glm-5.2`。
- 现有 Lunar Chat Completions runtime 的最小工具往返通过，两次响应均报告
  `gpt-5.6-sol`，探测共 205 tokens；没有执行本地工具。
- SDK `0.1.81` 在隔离临时目录用 `glm-5.2` 完成一轮无工具 query，报告模型相符。
- 完整 `effect-preflight` 通过，见 `ccswitch-preflight.json`。

首轮真实结果位于 `.lunar/real-eval-20260908/smoke/`：

| 项目 | 结果 |
| --- | --- |
| case / 配置 | supply_chain_inventory / 1 run × 1 round |
| 模式 | deep_evolution / loop 的第一轮 |
| overall / quality | 0.2079 |
| validity | 1.0 |
| 历史最佳 / 差值 | 0.3496 / −0.1417 |
| 用时 | 351.715 秒 |
| Lunar 模型交互 | 15 次 |
| Lunar 输入 / 输出 / 总 token | 95,723 / 4,383 / 100,106 |
| 实际响应模型 | gpt-5.6-sol，provider_observed |

首轮真实求解、原始私有 extractor/evaluator 和 receipt 链已完成；没有超越历史最佳。
独立只读审计 16 项证据一致性通过，包括 state 授权 record 摘要、request/receipt、公开输入、
solution manifest、实际 private case 和评分脚本摘要。`smoke --resume` 快速完成且返回报告
与原报告完全相同，没有新建 attempt。

这些用量仅属于 Lunar subject，不包括 extractor；harness receipt 未保存实评 extractor
的返回模型、usage 或完整成本。归一化中间文件和 SDK transcript 仍是临时产物，因此保留
证据支持 receipt 一致性审计，不能仅凭该目录离线重算评分。比较仍仅为本 case 的描述性
对照，baseline 的模型身份仅有 `runtime_observed`，不能升级为两侧 provider 证明。

后续独立 `deep/` workspace 的 2 runs × 5 rounds 已实际执行并结束，运行命令为：

```bash
uv run python .lunar/real-eval-20260908/ccswitch.py deep
```

两次逻辑 run 都在首轮 subject 以 `process_nonzero_exit` 退出，分别耗时 495.668 秒和
75.177 秒；没有 subject receipt/harness workspace，没有完成评分的 round，`lunar_best`
为 null。不能将这两次失败解释为质量分 0 或零模型消耗。首轮 smoke 的独立结果仍有效，
但本次没有得到演化提升证据。

事后纯本地复核发现 run 1 的原始公开文件未变，但新增了 `subject/case/solve.py`，违反
冻结 public projection 的文件集合；run 2 的同项检查通过。新增文件若走后验校验必被拒绝，
但由于检查在 `agent.run()` 返回后，无法仅凭当前文件断言它就是历史退出的直接原因。
失败后再次极小模型请求成功，响应仍为 `gpt-5.6-sol`；这只证明当前连接可用，不能排除
历史瞬时接口故障。独立只读审查确认以上证据边界。

当前诊断缺口已由真实失败暴露：`effect_trial._default_executor` 将 stdout/stderr 送入
DEVNULL，`_invoke` 统一记录 `process_nonzero_exit`，`run_subject_adapter` 又将 runtime
异常压成类型名。下一项 SDD 应补充 score-free、有界、白名单字段的 subject 失败诊断，
保存失败阶段/安全错误类别/退出状态；不要直接保存可能包含凭据的原始 stdout/stderr。
同时明确整个 `case/` 目录不可新增文件，求解代码和产物写在 attempt 根目录或其他允许目录。
先用本地回归区分 public projection 与 runtime/模型失败，再修复并恢复真实试验；保留原始
失败 attempts，不盲目重复消耗调用。此轮没有修改产品实现，仍以 `790c086` 对应实现开展
试验；新增内容仅是本机接入/状态脚本、结果记录和本文档。

汇总说明位于 `.lunar/real-eval-20260908/results.md`。每次新启动/恢复会读取届时 CC Switch
的当前 provider；已经运行的进程环境不受之后全局切换影响。新结果只从实际登记的 round
及最终 report 派生，不改基线、不手填分数、不向 subject 提供私有评分内容。

## 17. WebAgent 记录模型与 GLM 实评（2026-09-08）

用户明确要求“别用这么好的模型，用 WebAgent 已有记录的模型”。选择 `glm-5.1`：离线
报告 `qx9kRYpa6zTQmP` 的 C/E 组明确记载 `webagent loop / glm-5.1`。报告属于 20 case、
12 小时、每组 3 次的聚合实验，不能作为当前单 case 的同模型 baseline。无需再运行 WebAgent、
索取新实验数据或修改已有 GPT baseline。旧 `ccswitch.py smoke/deep` 与 `run.sh` 固定 GPT，
保留供审计，后续不得误用它们启动新的求解。

经用户授权继续只读使用本机 CC Switch。虽然当前 provider 的模型列表没有列出 `glm-5.1`，
实际文本调用与两轮 function-call probe 都成功，响应模型均为 `glm-5.1`；工具探测共 403
tokens。冻结 extractor 仍为 `glm-5.2`，SDK 仍为 `claude-agent-sdk==0.1.81`。

本机忽略目录 `.lunar/real-eval-glm-5.1-20260908/` 保存连接证据、模型选择、profile、冻结
suite、单 case 请求和 `run_single.py`。该脚本只导入旧 CC Switch 脚本的环境加载函数，
不会调用旧 GPT 启动入口。新求解预算为 40 个工具 steps、900 秒、200,000 tokens；无已核实单价，
不编造美元成本或设置虚假的费用估计。Profile canonical SHA-256：
`b2589138335badc4b9ff0fbb27f20f4235b397844e65e122b54b9150d9e587fc`。

现有 `EffectTrialRunner` 要求 requested model 与 baseline model 一致，本次保留该 guard。
独立实评调用现有 `effect-subject` 与 exact `effect-harness`，报告标注
`kind=lunar_single_case_evaluation`、`comparisons_disabled=true`、
`same_model_baseline_available=false`；不是普通/深度 comparative trial 的替代 schema。
subject 成功后才运行原始私有 extractor/evaluator，分数只取自其实际 receipt。

实际 GLM 运行已结束：subject 耗时 900.333 秒、退出码 2，总用时 900.334 秒。
规范诊断为 `stage=model`、`code=timeout`、`http_status=null`，记录到 12 次模型响应事件、
13 次工具结果事件。工具计数包含失败结果的可能性，不能说 13 次工具操作均成功。
没有候选文件、成功 subject receipt 或 harness 目录，0 次评分；质量分未知，不能记为 0。
失败调用用量与返回模型链不完整；连接探测确认同名模型，但不能据此补造本次运行的
provider_observed 成功回执、token 数或费用。

事后复核 request/public projection、sidecar 与采集副本、启动时所有产品 Python 源文件
SHA 均一致，原 GPT baseline 未改动。工具执行已开启，最小环境中的 `python3` 可正常
启动；没有证据断言具体工具错误、provider 断线或某次读取导致了超时。过程不保存原始
模型/工具正文，因此不能重建前 13 次工具操作。结果与本地核验分别在 `results.md`、
`report.json`、`postmortem-checks.json`；`started.json` 拒绝对已启动目录重复执行。

2026-09-09 用户纠正了此前“先取得正常解”的优先级：未产生正常解可能是合理的测量结果，
应结合已有真实评测数据判断。当前目标改为在明确、冻结的预算下测量 Lunar 的完成率、
有效解比例和质量，允许失败成为正式样本；不以取得成功为停止条件。下一批应预先冻结
配置与尝试次数，同时保留全部成功/失败；把进程完成、extractor 完成、evaluator validity、
质量分与用量分别统计。变更 prompt、工具能力或预算时，另立明确的变体和假设，不把“不断
重跑直到成功”的 best result 代替总体表现。只对确定性复现的缺陷做修复；早落盘、预算提示
和更长 timeout 目前都只是待验证假设。本轮已完成两次预先冻结的新 attempt，结果见第 20 节。

## 19. 按真实历史数据解释无解（2026-09-09）

重新复核已有离线报告 `qx9kRYpa6zTQmP`，其中 `webagent loop / glm-5.1` 的 C 组有效解
比例为 57.9%，E 组为 93.0%；表中平均分分别为 0.478、0.854。这个数据证明 WebAgent
也并非始终取得有效解。报告没有提供该指标的超时、运行错误或格式错误细分，不能把有效解
比例的补数称作超时率，也不能推断当前 `supply_chain_inventory` 的失败概率或历史结果。

两组均为 20 case、每组 3 次取平均、12 小时演化，并从 agent build 产物开始；E 组还在
演化期间使用真值评估器。单解“评估”上限为 10800 秒，不等同于 subject 求解预算。
Lunar 本次是从公开输入冷启动的 normal subject，整轮预算为 900 秒，harness 尚未运行。
因此既不能拿 57.9%/93.0% 作为当前单 case 的匹配成功率，也不能通过简单时长比例推定
Lunar 应有表现；尤其不能为了贴近 E 组而把私有评估器内容交给 subject。

本次应记为一个在指定预算内未完成的真实样本，尚无证据表明它是实现缺陷、模型不可用或
框架劣势。无解不写成成功，也不当成质量零分或代码 bug。结构化复核在本机
`.lunar/real-eval-glm-5.1-20260908/historical-context.json`。

## 20. 两槽固定预算测量结果（2026-09-09）

为避免“重跑到成功”，新建了独立 campaign
`.lunar/real-eval-glm-5.1-20260909/`，预先冻结两个 normal slot：同一
`glm-5.1`、profile、公开 case、prompt/adapter、40 tool steps、900 秒和 200,000 token ceiling。
2026-09-08 的单次 exploratory pilot 不进入这两个 slot 的分母。两个 slot 并行执行，使用同一
授权 provider 配置；并发限制已写入 summary，不能把它们解释为完全独立的时序重复。

两个 slot 均在 subject 阶段退出码 2，耗时分别约 310.289 秒和 250.987 秒；Feature 061
诊断均为 `stage=runtime`、`code=budget_exceeded`，各观察到 14 次模型响应事件和 15 次工具
结果事件。这个诊断不说明具体是哪次工具、是否为 provider 故障或是否触发 token ceiling。
两个 slot 都没有 subject receipt、候选文件、harness 目录或评分。

固定分母汇总为：planned 2、terminated 2、process success 0、subject receipt 0、harness
started 0、scored 0、valid 0、failed 2、unresolved 0；`valid_solution_rate=0/2` 是完成率
统计，不是质量分 0。overall/quality 的 `n=0` 且值为 null，usage known 为 0，不能声称
token 消耗或费用为零。结构化汇总为
`.lunar/real-eval-glm-5.1-20260909/summary.json`。

这批结果仍不能证明 Lunar 框架劣势：样本只有两个、subject 是冷启动、历史 WebAgent
实验条件不同，而且本次没有进入 evaluator。后续若继续，应先重新冻结新的变体和样本数；
不能在同一 campaign 中改 prompt、预算、工具后补位，也不能把成功样本挑出来替代失败样本。

## 18. Feature 061 安全失败诊断（2026-09-08）

新增 4096 字节上限的严格 score-free sidecar，绑定执行前 request SHA、normal/deep 模式、
run/round，保留固定阶段/错误码、有限模型/工具计数和可选 HTTP 整数。normal/deep runner
只在 subject 失败时验证并采集到 attempt 的 `diagnostics/`；缺失、伪造、超大、陈旧、
symlink/FIFO/其他不安全文件均不改变原 process 错误。分类或发布自身失败也保留原异常。
没有保存原始 stdout/stderr、异常正文、模型/工具内容或密钥；评分、成功 receipt、记录与
resume schema 保持兼容。两种 subject prompt 明确整个 `case/` 树不可新增、修改或删除。

原始 HEAD 上新增 9 项回归全部先失败；最终全仓 634 项测试、Ruff、compileall、build、
Feature 061 Specify prerequisites、diff 检查通过。独立代码审查无阻塞问题；真实 GLM
超时也成功生成并采集规范诊断。诊断不保存完整失败用量，计数只代表可观测事件。
