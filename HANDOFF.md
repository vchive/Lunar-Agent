# Lunar-Agent 交接记录

更新时间：2026-09-05  
当前仓库：`/Users/liminghan/Documents/lunar_agent`  
当前分支：`main`  
远端：`git@github.com:vchive/Lunar-Agent.git`  
提交身份：`vchive <vchive@users.noreply.github.com>`

## 1. 当前状态

工作区在本次交接开始时干净，`main` 与 `origin/main` 同步。最近提交：

```text
f633dde fix: allow candidate interpreter startup before timeout
edaa4a6 feat: add controlled deep evolution feedback
22c4e10 chore: close deep trial SDD checklist
79f1012 feat: add matched deep evolution effect trials
05c7740 feat: build content-addressed effect kits
b404671 feat: add executable famou bench adapters
0d114a5 feat: measure frozen benchmark breakthroughs
```

本文件和 Feature 052 的 checklist 更新属于交接收口改动，完成后应再提交、推送，并保持
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

### P0：真实深度演化效果闭环

当前还没有使用真实 FM case + 真实模型完成 `2 logical runs × 5 rounds` 的效果试验。原因是
本地目前找到的是 Famou-Bench case 和 reference metrics，没有发现已授权的 FM-Eval historical
results export。不能手工填一个 WebAgent 分数，否则会破坏比较可信度。

需要：

1. 从 FM-Eval 导出一个与选定 case、release、harness 完全匹配的历史结果 JSON。
2. 用 `effect-kit` 冻结 1 个 case（最多 2 个），再用 `effect-baseline` 转换结果。
3. 确认 subject endpoint/model 和 extractor 所需的环境变量；密钥只通过显式环境传递，不写
   入仓库、request、receipt 或 report。
4. 先跑 1 case、2 runs、5 rounds；检查每轮是否真正改善 `solution.json`、每轮 harness 是否
   执行、RoundFeedback 指令是否合理、是否超过同 case historical best。
5. 再考虑扩大到第二个 case或更多 runs。

准备 kit 的模板：

```bash
cd /Users/liminghan/Documents/lunar_agent
uv run lunar-agent effect-kit .lunar/famou-kit \
  --case supply_chain_inventory=/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-bench/03_assignment/supply_chain_inventory \
  --owner-attested-content-equivalence --json
```

准备 baseline 的模板：

```bash
uv run lunar-agent effect-baseline /absolute/path/fm-eval-results.json \
  .lunar/famou-kit/suite.json .lunar/famou-kit/baseline.json \
  --experiment-id <exact-export-id> \
  --requested-model <historical-requested-model> \
  --effective-model <historical-effective-model> \
  --model-evidence provider_observed --json
```

运行深度试验的模板：

```bash
uv run lunar-agent effect-deep-trial .lunar/famou-kit/suite.json \
  .lunar/famou-kit/baseline.json \
  --case-source supply_chain_inventory=/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-bench/03_assignment/supply_chain_inventory \
  --subject-command "/absolute/path/lunar-agent effect-subject --model <model> --max-steps 100" \
  --subject-env FAMOU_MODEL_ENDPOINT --subject-env FAMOU_API_KEY \
  --harness-command "/absolute/path/lunar-agent effect-harness --case-root /absolute/path/private-case" \
  --harness-env ANTHROPIC_AUTH_TOKEN --harness-env ANTHROPIC_BASE_URL \
  --requested-model <model> --runs-per-case 2 --outer-rounds 5 \
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
- parse failure、timeout、invalid candidate 的按轮统计；
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
specs/052-deep-evolution-feedback-contract
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
uv run pytest -q tests/test_deep_feedback.py tests/test_deep_effect_trial.py
```

接着优先寻找/生成经过授权的 FM-Eval historical results export；在没有真实 baseline 前，
不要宣称 Lunar 已经打平或超过 WebAgent。

## 10. 本次续接记录（2026-09-05）

已检查本地 FM-Eval 源码、文档、Git refs 及 Famou-Bench 文件，未发现可作为 WebAgent
historical baseline 的 machine-readable 授权导出。开发 canary 报告、token 账单和 case
`reference_metrics.json` 均不满足该比较边界，因此真实 2×5 深度试验仍等待导出文件。

同时修复了候选物化的极短超时可靠性：`CommandCandidateRunner` 为进程创建和解释器启动保留
50ms 下限，避免正常候选在启动阶段被误判超时；较长超时预算保持原值。全套测试与构建检查均已通过。
