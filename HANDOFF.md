# Lunar-Agent 交接记录

更新时间：2026-09-06  
当前仓库：`/Users/liminghan/Documents/lunar_agent`  
当前分支：`main`  
远端：`git@github.com:vchive/Lunar-Agent.git`  
提交身份：`vchive <vchive@users.noreply.github.com>`

## 1. 当前状态

本次续接从干净且与 `origin/main` 同步的 `4a61044` 开始。续接开始时的最近提交：

```text
4a61044 test: cover nested candidate manifest traversal
46d576d docs: update handoff for failure statistics
32561c9 feat: report deep evolution failure statistics
558f510 docs: record continuation findings
f633dde fix: allow candidate interpreter startup before timeout
b3df70e docs: add lunar agent handoff
edaa4a6 feat: add controlled deep evolution feedback
```

本次变更修复普通/深度效果试验的记录权威和深度 round receipt 完整性，更新 Feature
048/051/052 文档，并补齐官方 FM-Eval AgentServer normal-mode comparator。收口后应提交、
推送并保持
`main == origin/main`。

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

- Feature 048：导入 FM-Eval 历史结果，比较单 case 的 Lunar best 与 WebAgent historical best，
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

### P0：补齐 comparator 边界并运行真实 `2 logical runs × 5 rounds`

官方 publication kit 和 AgentServer normal-mode historical comparator 已就绪，不需要手填
历史分数：

```text
suite:    .lunar/famou-kit-real-001/suite.json
projection: .lunar/famou-kit-real-001/baseline.json
raw:      .lunar/famou-kit-real-001/fm-eval-results.json
case:     supply_chain_inventory
model:    gpt-5.6-sol
adapter:  agentserver (deep_evolution=false)
```

关键摘要：

```text
suite SHA-256:    1701995e8f65d9bd2ba73e840b870c9427fce27107e14048cffb34d594a04e46
baseline SHA-256: 355a8f1dee33532e720711a9c72988e83f61b4f9af8e4187e51ed3e859579440
raw SHA-256:      fa41c138ed3c73a50dd17e9e99704b41a079aef15ab45b1a6bdd65c3897c889d
```

`provenance.json` 保存只读查询、模型观测和来源实验状态；
`publication-identity-verification.json` 保存发布期 FM-Eval SDK commit
`b17023d3f849f3312f8fc79f366b0c18495ee726` 的复算证据。该 projection 是在 WebAgent adapter
guard 加入前用当时的 converter 生成；重复转换结果与落盘文件逐字节相同。这只证明旧结构转换
可重复，不能改变 comparator 类型；当前 converter 会按预期拒绝这份 AgentServer raw export。

这个 export 不能闭合 Feature 048 的 WebAgent-specific comparator 要求。若目标是严格比较
WebAgent，仍需取得相同 publication、CaseRevision 和 harness 身份下 `adapter=webagent` 的
machine-readable export，再单独生成 baseline。当前 effect protocol 的机器字段固定为
`webagent_historical_best`，因此不得把这份 AgentServer projection 直接传给
`effect-trial`/`effect-deep-trial`；否则机器可读报告会错误标注 comparator。
`effect-baseline` 现在会在写文件前拒绝该 export 的显式 `agentserver` evidence，并拒绝互相
冲突的 adapter evidence；缺少 adapter metadata 的 legacy export 继续兼容，但必须另外保留
WebAgent 来源证明。

真实试验尚未运行。除上述 WebAgent-specific export 外，当前还缺显式的执行配置：shell 中没有
`FAMOU_MODEL_ENDPOINT`、
`FAMOU_API_KEY`、`FAMOU_MODEL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`、
`ANTHROPIC_MODEL`、`OPENAI_API_KEY`、`OPENAI_BASE_URL` 或 `ANTHROPIC_API_KEY`，项目 venv 也
没有 `anyio` 和 `claude_agent_sdk`。来源实验的 extractor 冻结为 Anthropic API、模型
`glm-5.2`，发布期 FM-Eval harness 锁定 `claude-agent-sdk==0.1.81`；exact extractor 必须使用
包含对应依赖、与冻结身份相符且获授权的运行环境，并显式设置
`ANTHROPIC_MODEL=glm-5.2`。密钥只通过显式环境传递，不能写入仓库、request、receipt 或
report，也不能用 Codex/Claude 的本机登录态冒充 extractor 配置。

执行步骤：

1. 先补 `adapter=webagent` export，用 `effect-baseline` 生成新的 WebAgent baseline；当前可访问
   的 117 条 FM-Eval 实验列表全部是 AgentServer，其中覆盖该 case 的 36 条也没有 WebAgent。
2. 提供可调用 `gpt-5.6-sol` 的 subject endpoint/model 配置，以及 exact extractor 所需的
   Anthropic 配置、`glm-5.2` 模型值和发布期依赖环境。
3. 用下面的冻结 suite/baseline 跑 1 case、2 runs、5 rounds。
4. 确认十次 private harness 都真实执行，检查每轮 `solution.json`、RoundFeedback、模型身份、
   failure statistics 和恢复记录，再计算相对 historical best `0.3496` 的 descriptive delta。
5. 完成单 case 证据后，再决定是否扩展到第二个 case 或更多 runs。

运行深度试验的模板：

```bash
export ANTHROPIC_MODEL=glm-5.2
uv run lunar-agent effect-deep-trial .lunar/famou-kit-real-001/suite.json \
  /absolute/path/to/verified-webagent-baseline.json \
  --case-source supply_chain_inventory=.lunar/famou-kit-real-001/cases/supply_chain_inventory \
  --subject-command "/Users/liminghan/Documents/lunar_agent/.venv/bin/lunar-agent effect-subject --model WEBAGENT_BASELINE_MODEL --max-steps 100" \
  --subject-env FAMOU_MODEL_ENDPOINT --subject-env FAMOU_API_KEY \
  --harness-command "/Users/liminghan/Documents/lunar_agent/.venv/bin/lunar-agent effect-harness --case-root /Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-bench/03_assignment/supply_chain_inventory --python /absolute/path/to/python-with-anyio-and-claude-agent-sdk-0.1.81 --extractor-env ANTHROPIC_AUTH_TOKEN --extractor-env ANTHROPIC_BASE_URL --extractor-env ANTHROPIC_MODEL" \
  --harness-env ANTHROPIC_AUTH_TOKEN --harness-env ANTHROPIC_BASE_URL \
  --harness-env ANTHROPIC_MODEL \
  --requested-model WEBAGENT_BASELINE_MODEL --runs-per-case 2 --outer-rounds 5 \
  --stagnation-rounds 2 --workspace .lunar/deep-effect-trial-real-001 --json
```

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

从知识库评测看，深度演化模型需要同时看质量、时延、token 和格式失败率。后续可增加：

- `model profile`（model、thinking/budget、max steps、timeout）；
- 每轮 token/cost 预算；
- parse failure 子类、per-round error code/timeout breakdown；
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
specs/051-deep-evolution-effect-trial
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

接着先复核 `.lunar/famou-kit-real-001/` 的 baseline/provenance 摘要和显式 subject/extractor
执行配置。当前 `baseline.json` 是 AgentServer projection，不能传给现有 WebAgent-specific
effect protocol。只有另行取得匹配的 `adapter=webagent` export 并生成新 baseline，exact private
harness 实际完成新的 `2 × 5` 试验后，才可报告该冻结 case 上的 descriptive
delta/breakthrough；它仍不构成 WebAgent parity、suite parity 或 statistical superiority。历史
comparator 已就绪本身不代表 Lunar 新结果。

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
