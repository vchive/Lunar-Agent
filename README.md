# Lunar-Agent

Lunar-Agent is a standalone, local-first agent for conversational problem solving **and concrete
data production**. It is inspired by Hermes' continuous sessions, practical tools, and long-running
memory, but keeps the durable task ledger, artifacts, optional memory, and algorithm outputs in a
run-scoped local directory. It does **not** require a machine-wide Hermes, OpenCode, or Codex
installation. A natural-language answer is only the audit trail; an algorithm mission is complete
only when its declared output files pass independent checks and are delivered as hashed artifacts.

The project is being developed with Spec-Driven Development (SDD). The current solver-visible
scoring contract is captured in
[`specs/043-solver-scoring-contract/`](specs/043-solver-scoring-contract/), building on the
adversarial evaluator-audit boundary in
[`specs/042-adversarial-evaluator-audit/`](specs/042-adversarial-evaluator-audit/), the
private-data profiling boundary in
[`specs/041-private-data-profiling/`](specs/041-private-data-profiling/) and the frozen evaluator
bundle in
[`specs/040-frozen-evaluator-bundle/`](specs/040-frozen-evaluator-bundle/), which builds on the
execution-grounded refinement loop in
[`specs/039-execution-grounded-refinement/`](specs/039-execution-grounded-refinement/) and the
optional exact scorer in
[`specs/038-objective-harness-handoff/`](specs/038-objective-harness-handoff/), which adds an
optional exact local objective scorer to the execution-grounded search in
[`specs/037-execution-grounded-evolution/`](specs/037-execution-grounded-evolution/), building on
the evolved-output materialization boundary in
[`specs/036-evolved-output-materialization/`](specs/036-evolved-output-materialization/), building
on the conversational evolution handoff in
[`specs/035-conversational-evolution-handoff/`](specs/035-conversational-evolution-handoff/),
building on the runtime-profile benchmark in
[`specs/029-runtime-profile-benchmark/`](specs/029-runtime-profile-benchmark/), building on the
evolution Agent evidence work in
[`specs/030-evolution-agent-evidence/`](specs/030-evolution-agent-evidence/), and the structured
algorithm output work in
[`specs/031-structured-algorithm-outputs/`](specs/031-structured-algorithm-outputs/), building on the
algorithm input staging work in
[`specs/032-algorithm-input-staging/`](specs/032-algorithm-input-staging/), building on the
strict role evidence contracts in
[`specs/033-role-evidence-contracts/`](specs/033-role-evidence-contracts/), building on the
one-shot runtime artifact envelope in
[`specs/034-runtime-artifact-envelope/`](specs/034-runtime-artifact-envelope/), building on the
unified evolution benchmark in
[`specs/028-unified-evolution-benchmark/`](specs/028-unified-evolution-benchmark/), building on the
reproducible native benchmark in
[`specs/027-evolution-benchmark/`](specs/027-evolution-benchmark/), building on the evolution Agent
loop in
[`specs/026-evolution-agent-loop/`](specs/026-evolution-agent-loop/), building on the built-in
algorithm role DAG in
[`specs/025-algorithm-role-dag/`](specs/025-algorithm-role-dag/), building on the conversational
algorithm mission in
[`specs/024-conversational-algorithm-mission/`](specs/024-conversational-algorithm-mission/), building
on the verified candidate execution work in
[`specs/023-verified-algorithm-execution/`](specs/023-verified-algorithm-execution/), building on
the completed runtime-backed evolution and independent evaluator ensemble in
[`specs/022-runtime-backed-evolution/`](specs/022-runtime-backed-evolution/) and
[`specs/021-evaluator-ensemble/`](specs/021-evaluator-ensemble/), which is built on
independent artifact acceptance contracts in
[`specs/008-artifact-acceptance-contracts/`](specs/008-artifact-acceptance-contracts/) and domain
routing, profiles, and budgets in
[`specs/007-domain-routing-solver-evaluator/`](specs/007-domain-routing-solver-evaluator/). The earlier
WebAgent-style experiment is retained as a superseded draft in
[`specs/002-webagent-effect-parity/`](specs/002-webagent-effect-parity/).

## Conversational algorithm missions

You can now start an algorithm task without authoring a contract by hand. `solve` first compiles a
strict `AlgorithmProblemContract`, then attaches a versioned plan and runs the normal durable DAG:

```bash
lunar-agent solve "根据订单数据设计配送路线" --runtime mock --json --home .lunar
```

For a local model, use an explicit repository runtime (no global Hermes/OpenCode/Codex state is
read):

```bash
lunar-agent solve "根据订单数据设计配送路线" \
  --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1/chat/completions \
  --model your-local-model --json --home .lunar
```

The compiler must return a strict JSON envelope. If a material objective, input, constraint, or
deliverable is unknown it returns `status=awaiting_input`; answer the same run and it will resume
compilation:

```bash
lunar-agent answer <run-id> "最小化总行驶时间" \
  --runtime openai-compatible --endpoint http://127.0.0.1:11434/v1/chat/completions \
  --model your-local-model --json --home .lunar
```

The run ID remains stable. Contract, plan, compiler manifest, input answers, and generated task
artifacts are all local and SHA-256 indexed. The baseline generated DAG is
`data_discovery → formulate → solve → verify`; candidate evolution remains an explicit opt-in
stage through `evolve`.

For a conversational mission that should search candidates immediately, use `--evolve`. Lunar-
Agent compiles the contract first and then links a second durable evolution run:

```bash
lunar-agent solve "根据订单数据优化配送路线" \
  --runtime mock --evolve --strategy population --max-rounds 3 \
  --json --home .lunar
```

The JSON response includes the intake `run_id` and `evolution.run_id`. The intake keeps the
validated contract and explicitly supersedes its unstarted generated-plan tasks; the child owns
`evolution/archive.jsonl`, `state.json`, and `result.json`. Staged `--input` files are copied into
the child with the same SHA-256 and size, never with the source-machine path.

For native `loop` and `population`, every generated `.py` candidate now runs in its own archive
directory before model evaluation. It receives digest-checked `data/raw/*` copies and a minimal
non-secret environment. Required and present optional outputs must pass the immutable
CSV/JSON/JSONL/text contract; a process or output failure becomes local validity zero and skips the
model evaluator entirely. Successful evaluator requests contain a bounded source excerpt,
execution summary, and output path/schema/size/SHA-256 metadata—not raw input or output contents.
Source-only contracts receive the same process gate without requiring output files.

When the compiled contract declares `outputs`, Lunar-Agent then runs the selected best candidate
once more in a separate final workspace. Search-time output is evidence only and is never promoted
directly. The final candidate must recreate the exact declared files before their bytes are
atomically promoted to the intake workspace. The response exposes this as
`evolution.materialization`; a failed process, timeout, missing/malformed output, symlink,
oversized file, or conflicting destination makes the effective `solve` status fail and prevents
`deliver`.

Resuming the intake reuses the same child and terminal materialization, verifies candidate and
output digests, and rejects changed strategy settings instead of executing or overwriting again.
Contracts without `outputs` keep the existing source-only result. `evolve CONTRACT` remains
available when separate generator/evaluator commands or an OpenEvolve wrapper are needed.

When a domain already has an exact local objective or constraint checker, keep the conversational
compiler/generator path and replace only model scoring:

```bash
lunar-agent solve "optimize routes and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --strategy population \
  --evaluator-command "/absolute/python /absolute/score_routes.py" \
  --json --home .lunar
```

The harness receives the candidate path after local execution/output validation and can inspect its
sibling `data/raw/*`, `output/*`, and `execution.json`. It returns the existing strict
`EvaluationReport`; archive selection maximizes its non-negative `combined_score`, so a cost
minimizer can use `1 / (1 + cost)` and retain raw cost with direction `minimize` in
`detailed_scores`. The subprocess receives a minimal UTF-8/locale environment rather than model
credentials or arbitrary parent variables. Its command is fingerprinted but not persisted; resume
must supply the same `--evaluator-command` again. Final output still comes from the independent
clean-room materialization, never directly from search evidence.

If no exact scorer already exists, native search can explicitly compile one before the first
candidate:

```bash
lunar-agent solve "minimize route cost and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --compile-evaluator --strategy population \
  --max-rounds 5 --json --home .lunar
```

The evaluator compiler is a separate runtime turn. Before invoking it, Lunar-Agent verifies the
exact staged input ledger and locally profiles CSV, JSON, JSONL, or text data. The compiler sees
only relative paths, format, byte size/SHA-256, row or line count, actual field names, conservative
types, null counts, and unique counts. It never receives rows, raw values, samples, extrema,
category labels, or source-machine paths. Malformed/ambiguous data, unsupported formats, symlinks,
or ledger drift fail before the compiler or search runs.

The compiler must return a strict objective, Python evaluator, one synthetic rejecting probe per
hard constraint, at least two valid probes, and a declared better/worse score ordering. Lunar-Agent
statically rejects dangerous imports and dynamic execution, runs every probe locally, and parses
every result through `EvaluationReport`. It then starts a fresh adversarial auditor turn. The auditor
sees the immutable contract, private structural profile, objective, and evaluator source—but not
the compiler's probes, raw values, or any solver/search evidence—and must produce a second complete
probe suite. Search starts only after both suites prove constraint validity, matching error codes,
and strict score ordering. This catches correlated evaluator/self-test omissions such as accepting
duplicate entities merely because row counts match.

Lunar-Agent hashes and freezes `objective.md`, `evaluator.py`, canonical `probes.json`, independent
`audit.json`, canonical `input-profile.json`, and `manifest.json` under the intake run. The profile
and audit digests are part of bundle identity. Resume re-profiles current ledger-bound bytes and
reuses the same bundle without another compiler or auditor call; input, profile, audit, permission,
or manifest drift fails closed.

Once the bundle passes both gates, native Agent solver generations receive the complete canonical
hard/soft constraints and assumptions plus a fingerprinted scoring contract. The contract exposes
the frozen objective and a bounded evaluator excerpt in the prompt; exact read-only
`scoring/objective.md` and `scoring/evaluator.py` copies are available in the isolated generation
workspace. This lets the solver align I/O, feasibility, and the actual higher-is-better score before
its first candidate. The authoritative evaluator stays in the parent bundle, and `probes.json`,
`audit.json`, `input-profile.json`, raw values, and machine paths are never copied into solver
workspaces.

The generated evaluator is explicit local executable authority, not a claim of OS sandboxing. It
runs with isolated Python, closed stdin, minimal non-secret environment, timeout, and bounded
output. Its exact source is visible to compiled-evaluator solvers as read-only scoring guidance,
while compiler/audit probes remain private; the authoritative copy is independently reverified and
executed outside solver generation workspaces. Use `--evaluator-command` when an owner-reviewed
domain harness already exists; the two modes are intentionally mutually exclusive.

Provide real local data explicitly with repeatable `--input` options. A source is staged into the
run's `data/raw/` directory and copied into each isolated task attempt; use `SOURCE=DEST` when the
destination must match a contract path:

```bash
lunar-agent solve "根据订单数据设计配送路线" \
  --input ./orders.csv \
  --input ./vehicles.json=vehicles.json \
  --runtime openai-compatible --agent-loop --json --home .lunar
```

Inputs are recorded as `kind=input_data` with size and SHA-256 metadata. The source machine path is
never persisted, and resuming with the same bytes is idempotent. Algorithm roles read the verified
copies from `data/raw/...` in their own attempt workspace, just as they write outputs under their
private `output/` directory.

When a one-shot OpenAI-compatible model cannot call file tools, a structured task may return a
bounded JSON artifact envelope instead of writing directly:

```json
{"text":"Route table generated.","artifacts":[{"path":"output/routes.csv","content":"order_id,route_id\n1,r1\n"}]}
```

The runtime writes only these relative UTF-8 files into the private attempt workspace. The same
`OutputSpec`/role acceptance, hashing, retry, and delivery checks still apply; tool calls remain
available through the explicit `--agent-loop` option.

For a more explicit specialist workflow, add `--role-dag`:

```bash
lunar-agent solve "根据订单数据设计配送路线" --runtime mock --role-dag --json --home .lunar
```

This uses `data_discovery → problem_formulator → solver → evaluator → reviewer`. It is still the
same local SQLite run and artifact handoff; the switch only selects a richer built-in plan factory.
Each non-Solver role also has a strict hand-off contract: DataDiscovery must write
`data/processed/data-profile.json`, ProblemFormulator must write
`solve/problem-formulation.md`, Evaluator must write a schema-valid `evaluate/evaluation.json`, and
Reviewer must write `evaluate/review.md`. These files are hashed as `role_evidence` artifacts;
missing or malformed evidence causes a retry/failure even when the model returns convincing prose.

### Conversation versus result data

An algorithm mission has two deliberately separate result channels:

1. `result.txt` and role reports preserve the conversational explanation and evidence trail.
2. `algorithm_problem.outputs` declares machine-consumable files that the Solver must actually
   write. Supported formats are JSON, JSONL, CSV, and non-empty UTF-8 text; declared fields are
   checked independently of the Solver's prose.

The Solver writes logical paths such as `output/routes.csv` in its private attempt workspace. Only
after independent evaluation passes does Lunar-Agent copy the file to the stable run workspace,
`<run-workspace>/output/routes.csv`, hash it, and record it as `kind=output`. This means a parent
Agent can consume data deterministically:

```bash
lunar-agent status <run-id> --json   # algorithm_outputs + SHA-256 metadata
lunar-agent deliver <run-id> --json  # fail-closed delivery decision
```

Role-DAG evidence is available through the same `status --json` response under `role_evidence` and
is included in delivery evidence. It remains attempt-local, so only validated Solver data files
are promoted to the stable `output/` directory.

If a required output is missing or malformed, a convincing chat response cannot make the run
succeed. Contracts written before the optional `outputs` field remain fully compatible and keep
the existing result/runtime delivery behavior.

## Bootstrap

Using [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

Using Python's standard environment tooling:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run the standalone mock agent

```bash
uv run famou run "Create a durable local run report" --runtime mock
uv run famou status <run-id>
uv run famou events <run-id>
uv run famou resume <run-id>
```

The installed `lunar-agent` command is an equivalent alias for `famou`, which is convenient when a
parent Agent wants to invoke the project by its repository name.

The default home is `.famou/` in the current working directory. Set `FAMOU_HOME` or pass
`--home PATH` to use another local directory. The mock runtime is deterministic and requires no
network, credentials, model, or user-global Hermes state.

## Explicit external runtime

An external agent can be used only when explicitly configured:

```bash
export FAMOU_RUNTIME_COMMAND='my-agent --json'
uv run famou run "Inspect this repository" --runtime subprocess
```

The command receives the task prompt on stdin and runs inside the task workspace. Lunar-Agent never
searches for Hermes or imports `~/.hermes`.

## Explicit Agent delegation

Lunar-Agent can also act as a local control plane for another CLI/TUI Agent. The worker is supplied
explicitly; no Hermes, OpenCode, OpenClaw, or Codex installation is discovered or required:

```bash
lunar-agent delegate "inspect the repository and write an answer" \
  --agent-command "/absolute/path/to/agent-wrapper --json" \
  --agent-name my-worker --agent-role solver \
  --capability read_files --capability write_artifacts --json
```

The command receives one JSON request on stdin and returns one JSON object (or bounded plain text)
on stdout. The request includes the durable `run_id`, `task_id`, role, required capabilities,
attempt workspace, and timeout. A structured response can declare `text`, run-relative `artifacts`,
`metadata`, and `status`. Lunar-Agent verifies and SHA-256 hashes those artifacts, evaluates the
text, and remains the only component allowed to settle the SQLite task/run. Absolute executable
paths, timeouts, malformed output, non-zero exits, and workspace escapes fail closed.

For a long delegation, add `--detach`; the command returns a durable run ID and a local child keeps
working. Re-enter it later with the same explicit worker command:

```bash
lunar-agent delegate --run-id <run-id> \
  --agent-command "/absolute/path/to/agent-wrapper --json" \
  --agent-role solver --json
```

This makes the same project usable in three ways: directly as a standalone Agent, as a child called
by Codex/Hermes/OpenClaw, or as the controller that delegates a role to one of those tools. The
library equivalents are `AgentRequest`, `AgentResult`, `AgentRegistry`, `RuntimeAgentAdapter`, and
`CommandAgentAdapter` from `famou.agents`.

## Continuous Hermes-inspired model session

Lunar-Agent includes a dependency-free OpenAI-compatible HTTP adapter and a bounded continuous
tool-calling loop. Point it at a local Ollama, vLLM, LM Studio, or other compatible server:

```bash
export FAMOU_MODEL_ENDPOINT='http://127.0.0.1:11434/v1/chat/completions'
export FAMOU_MODEL='your-local-model'
lunar-agent run "Inspect this repository" --runtime openai-compatible --agent-loop --json
```

You can pass `--endpoint` and `--model` instead of environment variables. Hosted endpoints may use
`FAMOU_API_KEY` (or `--api-key`); the key is sent only as an Authorization header and is redacted
from persisted errors. The adapter accepts the standard OpenAI response shape plus Ollama-style
responses, and all normal retries, evaluator checks, artifacts, and recovery remain owned by the
local controller. Add `--allow-exec` to expose bounded no-shell command execution:

```bash
lunar-agent run "Run the tests and fix the failing file" \
  --runtime openai-compatible --agent-loop --allow-exec --max-steps 40
```

The controller remains the orchestrator: it validates and schedules optional dependency plans,
retries failed attempts, hands verified artifacts to dependent tasks, and recovers after an
interruption. It is not a WebAgent stage machine.

For plans with independent tasks, local workers can overlap without sharing runtime session state:

```bash
lunar-agent run --plan plan.json --runtime mock --workers 2 --json
lunar-agent resume <run-id> --runtime mock --workers 2 --json
```

The default is one worker, preserving serial behavior. `--workers N` is a local bounded thread
pool; the CLI creates a fresh repository-owned runtime adapter per task, while SQLite remains the
claim and dependency-ordering authority. Cancellation fans out to all active adapters, and late
results are discarded by the same durable rules as serial execution. No Hermes/OpenCode/Codex
installation or remote queue is required.

### Master policy and versioned plans

The local Master layer carries over WebAgent's highest-value effect-layer behavior without its
service plane. It chooses the smallest useful action, stores an auditable plan revision, and keeps
patch/replan and delivery decisions in SQLite:

```bash
lunar-agent decide "What does SQLite WAL mode provide?" --json
lunar-agent plan plan.json --runtime mock --json
lunar-agent plan <run-id> --json                 # inspect current revision
lunar-agent patch <run-id> patch.json --json
lunar-agent replan <run-id> replacement.json --json
lunar-agent resume <run-id> --runtime mock --json # execute newly opened tasks
lunar-agent deliver <run-id> --json
```

`plan` creation is atomic with the run and task DAG. Each revision has a parent version and remains
immutable. A stale patch is rejected before any write; completed task definitions cannot be
rewritten, while failed or superseded work can be reopened and resumed. `deliver` fails closed
unless the run passed independent evaluation and has hashed result/runtime artifacts; an
algorithm-output contract additionally requires every required `kind=output` artifact. All command
outputs support `--json`, making the CLI suitable for Codex, OpenClaw, Hermes, or another local
parent agent.

### Domain routing, profiles, and execution budgets

Every executable run receives a deterministic local route: `general`, `data`, `research`, or
`coding`. The selected Solver/Evaluator profile, matching evidence, and execution budget are stored
with the run and returned by `status --json`; no provider call or machine-wide Agent installation is
needed to choose them.

```bash
lunar-agent run "Analyze a CSV and write a report" --runtime mock --json
lunar-agent status <run-id> --json
```

Budgets fail closed: they bound scheduler task count, total attempts, session tool calls, controller
elapsed time, and indexed artifact bytes. A breach writes a `budget_exceeded` ledger event and makes
the run ineligible for `deliver`, without discarding prior artifacts. `PlanDocument` accepts an
optional `budget` object with `max_tasks`, `max_attempts`, `max_tool_steps`,
`max_runtime_seconds`, and `max_artifact_bytes`.

### Algorithm problem contracts (Feature 012)

For algorithmic work, a plan may carry an `algorithm_problem` contract. It records the problem type,
input schema, decision variables or prediction target, objective direction, provenance-backed hard
and soft constraints, success criteria, deliverables, and explicit assumptions. The contract is
validated before the run starts and is visible in both `plan` and `status --json`.

Contract-bearing runs reserve a local role workspace:

```text
data/raw/ · data/processed/ · solve/ · evaluate/ · output/ · evolution/
```

`algorithm-workspace.json` contains the plan revision and a SHA-256 digest of the canonical
contract. The directories are a boundary for Solver/Evaluator roles. The local evolution library
now consumes this contract without starting a remote service or importing a machine-wide Agent.

An algorithm mission can declare concrete data outputs instead of relying on prose deliverables
alone:

```json
{
  "outputs": [
    {"path": "output/routes.csv", "format": "csv", "fields": ["item_id", "route_id"]},
    {"path": "output/summary.json", "format": "json", "fields": ["total_distance"]}
  ]
}
```

Required outputs are independently checked after the Solver runtime returns. JSON/JSONL records are
parsed, CSV headers are checked, declared fields must exist, and text outputs must be non-empty.
Passing only a conversational completion claim is insufficient: after the checks pass, files are
promoted from the attempt workspace to the run-level `output/` directory, SHA-256-indexed as
`kind=output`, exposed under `algorithm_outputs` in `status --json`, and included by `deliver`. The
`outputs` field is optional, so older contracts remain compatible.

The contract accepts `loop` (the default WebAgent-style fresh-context serial rounds), `population`
(an explicit local candidate population), and `openevolve` (an optional explicit local subprocess).
All three share the same contract, append-only candidate archive, and frozen validity-first
evaluator boundary. The current local `--workers` option only parallelizes independent DAG tasks; it
is not population search.

### Local evolution strategies

The strategy seam is available as a library so a standalone caller or another Agent can supply its
own solver/generator and evaluator:

```python
from famou import CandidateDraft, EvolutionConfig, EvolutionContext, build_strategy

context = EvolutionContext(
    contract=contract,
    workspace=run_workspace,
    generate=lambda request: CandidateDraft("def solve():\\n    return 1\\n"),
    evaluate=lambda path, contract: report,
    config=EvolutionConfig(strategy="loop", max_rounds=5),
)
result = build_strategy(context).run()
```

`loop` archives one or more independently generated candidates per round and returns the best valid
candidate. `population` maintains a bounded active set plus the complete archive and can use local
islands and ring migration. `openevolve` is opt-in and requires an explicit absolute executable;
the base installation does not install or discover OpenEvolve. See
[`specs/013-evolution-strategies/`](specs/013-evolution-strategies/) for the SDD contract and
quickstart.

The same boundary is available through the standalone CLI.  Native strategies require explicit
local generator/evaluator commands; their first argument is a run-scoped request or candidate path
respectively:

```bash
lunar-agent evolve contract.json \
  --strategy loop \
  --generator-command "/absolute/python /absolute/generator.py" \
  --evaluator-command "/absolute/python /absolute/evaluator.py" \
  --json --home .lunar
```

The command creates a normal SQLite-backed run and returns `run_id`, candidate counts, the best
candidate, and the canonical workspace.  Use `--detach` for a durable child process, then resume
with the same contract and explicit commands:

```bash
lunar-agent evolve contract.json \
  --strategy population --population-size 8 --detach \
  --generator-command "/absolute/python /absolute/generator.py" \
  --evaluator-command "/absolute/python /absolute/evaluator.py" \
  --json --home .lunar
lunar-agent evolve contract.json --resume --run-id <run-id> \
  --generator-command "/absolute/python /absolute/generator.py" \
  --evaluator-command "/absolute/python /absolute/evaluator.py" \
  --json --home .lunar
```

Command-backed runs persist credential-safe SHA-256 fingerprints for both the generator/solver and
evaluator adapter profiles. Resume rejects a changed command, Agent name, role, or required
capability before claiming the task, so one candidate archive is never silently mixed across
different execution configurations. Raw command arguments are not written to strategy state.

For algorithm work that must prove a candidate actually runs, add an execution command. The runner
receives the candidate path, runs in that candidate's attempt directory, and produces bounded
`execution.json` evidence before the evaluator command is called:

```bash
lunar-agent evolve contract.json --strategy loop \
  --generator-command "/absolute/path/to/generator" \
  --candidate-runner-command "/absolute/path/to/run-candidate" \
  --evaluator-command "/absolute/path/to/evaluate-candidate" \
  --json --home .lunar
```

The evaluator keeps its existing candidate-path argument and can read the sibling
`execution.json`. A runner timeout, non-zero exit, oversized output, or path violation becomes an
invalid report before the evaluator is invoked and can never replace the best candidate. The
evidence file is indexed and hashed by the local ledger. The runner remains opt-in on this low-level
command, so historical command-only and Agent-backed evolution remains compatible.

### Repository-owned runtime evolution

Native evolution can use Lunar-Agent's own runtime as the solver, evaluator, or both. This is the
standalone path: it does not import or discover a machine-wide Hermes, OpenCode, Codex, Claude Code,
or DeepSeek Harness installation. The runtime profile is explicit and is adapted through the same
strict `AgentCandidateGenerator` / `AgentCandidateEvaluator` bridges as external workers:

```bash
# A local runtime command can produce candidate source for solver prompts and
# a strict EvaluationReport JSON object for evaluator prompts.
lunar-agent evolve contract.json --strategy population \
  --agent-runtime subprocess \
  --agent-runtime-command "/absolute/path/to/local-agent --json" \
  --json --home .lunar

# Or call an OpenAI-compatible local server directly.
lunar-agent evolve contract.json --strategy loop \
  --agent-runtime openai-compatible \
  --agent-runtime-endpoint "http://127.0.0.1:11434/v1/chat/completions" \
  --agent-runtime-model "your-local-model" \
  --json --home .lunar
```

The available profiles are `mock`, `subprocess`, and `openai-compatible`. A runtime fills either
or both unconfigured roles, so an explicit `--evaluator-command` (or Agent evaluator) can be paired
with a runtime-backed solver, and vice versa. `--agent-runtime` cannot be combined with
`openevolve`, and supplying it when both roles are already explicit is rejected as ambiguous.
Each role gets a fresh runtime adapter, while the SQLite ledger and candidate archive remain the
durable authority. Runtime kind, endpoint/model, command identity, role, and capabilities are
stored only as credential-safe fingerprints. Detached runs pass non-secret settings as arguments
and an API key through `FAMOU_AGENT_RUNTIME_API_KEY`, never through argv or state.

For an OpenAI-compatible local model that needs to inspect a candidate, edit files, or run tests
before returning, opt into the bounded repository-owned loop:

```bash
lunar-agent evolve contract.json --strategy loop \
  --agent-runtime openai-compatible \
  --agent-runtime-endpoint http://127.0.0.1:11434/v1/chat/completions \
  --agent-runtime-model your-local-model \
  --agent-runtime-loop --agent-runtime-session-history \
  --agent-runtime-allow-exec --agent-runtime-max-steps 40 \
  --json --home .lunar
```

The loop reuses the same confined `read_file`, `write_file`, `list_dir`, and optional no-shell
`run_command` tools used by normal Lunar-Agent sessions. Each solver and evaluator role receives a
fresh runtime and tool registry. The loop is bounded to at most 200 tool calls, and memory,
transcripts, and command execution are all explicit opt-ins. Its text still crosses the strict
candidate/evaluation bridges, so a model cannot claim validity or bypass the evaluator.

### Reproducible strategy benchmark

Use `benchmark` to compare native strategies with the same contract, command-backed generator and
evaluator, and bounded budget. Each strategy gets a fresh workspace and archive:

```bash
lunar-agent benchmark contract.json \
  --strategy loop --strategy population \
  --generator-command "/absolute/path/to/generator" \
  --evaluator-command "/absolute/path/to/evaluator" \
  --max-rounds 3 --population-size 4 --seed 7 \
  --json --home .lunar
```

The JSON report contains per-strategy status, elapsed time, candidate counts, best score, and
relative archive paths. Generator/evaluator identities are stored as SHA-256 fingerprints; raw
commands and model credentials are not included. The default benchmark compares the local `loop`
and `population` strategies. Add `--strategy openevolve --openevolve-command
"/absolute/path/to/wrapper"` to include the explicit OpenEvolve adapter; its wrapper receives a
generated config and must write the strict candidate result envelope. OpenEvolve remains an opt-in
subprocess and is never installed or discovered by Lunar-Agent.

The same benchmark can use Lunar-Agent's repository-owned runtime instead of command adapters. A
one-shot comparison uses:

```bash
lunar-agent benchmark contract.json --strategy loop --strategy population \
  --agent-runtime openai-compatible \
  --agent-runtime-endpoint http://127.0.0.1:11434/v1/chat/completions \
  --agent-runtime-model your-local-model \
  --json --home .lunar
```

Run the identical command in a new workspace with `--agent-runtime-loop` to measure the bounded
tool-capable profile. Loop settings are fingerprinted, and memory, transcripts, and no-shell
execution remain explicit opt-ins. Runtime-backed calls still use the strict candidate/evaluator
bridges, so a model response cannot bypass validity checks.

Hermes, DeepSeek Harness, Codex, Claude Code, and OpenClaw remain useful optional adapters or parent
processes. They are execution-plane integrations; Lunar-Agent's local controller, evolution
strategy, evaluator authority, artifacts, and resume semantics stay repository-owned.

For higher-assurance algorithm work, configure two or more independent evaluator Agents. Every
member reads the same candidate in an isolated workspace; validity is accepted only when all
members agree, while valid scores and common detailed metrics are combined with a median. A member
failure, malformed report, or validity disagreement is represented as a controlled invalid report
and cannot become the best candidate:

```bash
lunar-agent evolve contract.json --strategy population \
  --agent-command "/absolute/path/to/solver --json" \
  --evaluator-portfolio-command "/absolute/path/to/evaluator-a --json" \
  --evaluator-portfolio-command "/absolute/path/to/evaluator-b --json" \
  --json --home .lunar
```

The ordered evaluator command list and shared role/capability profile are included in the
credential-safe resume fingerprint. Use either this ensemble or one `--evaluator-command` /
`--evaluator-agent-command`; mixing evaluator modes is rejected before a run is created.

When an Agent is the solver, later generations receive execution-grounded refinement evidence for
their parent, population inspirations, and recent archive entries. The shared envelope combines a
bounded/redacted candidate source excerpt, source digest, controlled process/output-contract status,
verified output path/size/digest metadata, and the independent `evaluation_feedback` projection.
This lets native loop and population search repair a real failed attempt instead of merely sampling
again. It is reconstructed from the candidate archive on resume; no second feedback database or
in-memory chat dependency is required.

Raw input rows, output contents, candidate stdout/stderr, model credentials, and evaluator adapter
exceptions are excluded. Unsafe or oversized source/execution/output evidence degrades to a stable
unavailable category, and the complete generation prompt remains bounded. Direct callback and
command generators retain their existing `GenerationRequest`; this evidence join is specific to
the repository Agent bridge. See
[`specs/039-execution-grounded-refinement/`](specs/039-execution-grounded-refinement/) for the SDD
contract.

`status --json` and `events --json` expose the evolution result, iteration events, candidate archive
events, Agent model/tool lifecycle events, and indexed `evolution/archive.jsonl`,
`evolution/state.json`, `evolution/result.json`, and redacted solver/evaluator transcript artifacts.
OpenEvolve remains optional and is invoked only when `--openevolve-command` points to an existing
absolute executable; no global installation is discovered.

An explicit Agent can generate candidates directly while the evaluator remains independent:

```bash
lunar-agent evolve contract.json --strategy loop \
  --agent-command "/absolute/path/to/agent-wrapper --json" \
  --agent-role solver --agent-capability read_files \
  --evaluator-command "/absolute/path/to/evaluator-wrapper" \
  --json --home .lunar
```

The Agent receives a bounded algorithm context and returns source text or a `{\"source\": ...}`
object. Lunar-Agent archives and evaluates that proposal through the same validity-first path as
command generators; an Agent claim is never treated as evaluation evidence. See
[`specs/015-agent-backed-evolution/`](specs/015-agent-backed-evolution/) for the SDD contract.

If a separate evaluator Agent is available, use `--evaluator-agent-command` instead of
`--evaluator-command`; it must return a strict JSON `EvaluationReport` and is validated by the same
schema before influencing selection:

```bash
lunar-agent evolve contract.json --strategy population \
  --agent-command "/absolute/path/to/solver-wrapper --json" \
  --evaluator-agent-command "/absolute/path/to/evaluator-wrapper --json" \
  --json --home .lunar
```

Population search can also rotate multiple explicit solver Agents using repeatable
`--agent-portfolio-command` options:

```bash
lunar-agent evolve contract.json --strategy population \
  --agent-portfolio-command "/absolute/path/to/solver-a --json" \
  --agent-portfolio-command "/absolute/path/to/solver-b --json" \
  --evaluator-agent-command "/absolute/path/to/evaluator --json" \
  --json --home .lunar
```

Calls use the ordered portfolio deterministically in round-robin order. Every proposal still goes
through the same archive and independent evaluator, and the ordered command list is covered by the
resume fingerprint. The single `--agent-command` form remains unchanged.

The JSON result includes `best_candidate_path` when a valid candidate was selected. It is relative
to the returned `workspace`, so a parent Agent can inspect the source without parsing the internal
candidate archive. Failed or all-invalid runs return `null` for both the best candidate ID and path.

### Three local invocation modes

Lunar-Agent is the same independent agent in each mode; a parent Agent is optional.

1. Run it directly as a standalone local Agent. The repository-owned SQLite ledger and workspace
   are enough; no Hermes/OpenCode/Codex installation is discovered or imported.
2. Call it from Codex, Hermes, OpenClaw, or a script as a child process. Use `--json` and pass the
   goal/plan on arguments or stdin; parse the bounded stdout payload and inspect the returned
   `run_id`, status, artifacts, and plan metadata.
3. For a long task, request a durable handle with `--detach`, let the caller exit, then invoke
   `resume <run-id>` later. The same plan revision, algorithm contract, workspace, and ledger are
   recovered; the parent does not need to keep a model session alive.

Examples:

```bash
# 1. Standalone
lunar-agent plan routing-plan.json --runtime mock --home .lunar --json

# 2. Parent Agent child process (stdin/stdout JSON)
printf '%s' 'solve this routing problem' | lunar-agent run - --runtime mock --json --home .lunar

# 3. Detached then resumed (general agent run)
lunar-agent run "search for a feasible schedule" --runtime mock --detach --json --home .lunar
lunar-agent resume <run-id> --runtime mock --json --home .lunar
```

These are process/interface choices, not different evolution algorithms. `loop` remains the first
implementation target because it gives each round a fresh solver context and is easier to compare
under a fixed budget. `population` becomes worthwhile when a long local budget can pay for archive
selection and genuine diversity; it will sit behind the same Solver/Evaluator boundary rather than
being tied to a specific parent Agent.

If the session needs a decision, it can call `ask_user`. The run then becomes `awaiting_input` and
returns the question in JSON/status output. Answer the same durable run later; no duplicate task is
created:

```bash
lunar-agent answer <run-id> "json" --runtime openai-compatible \
  --endpoint "$FAMOU_MODEL_ENDPOINT" --model "$FAMOU_MODEL" --agent-loop --memory --json
```

The answer is written as a bounded run artifact and included in the next task prompt. Use `-` as the
answer to read it from stdin.

For retries and `resume` to replay recent model/tool context, add `--session-history`. This writes a
bounded, redacted JSONL transcript under the run workspace and indexes one stable session artifact:

```bash
lunar-agent run "Continue the migration" \
  --runtime openai-compatible --agent-loop --session-history --json
```

Session history is separate from durable memory. It is opt-in and retains only recent messages; use
`remember_memory` for concise facts that should outlive a session.

### Optional durable memory

Memory is explicitly opt-in because recalled local notes may be sent to the configured model
endpoint. Enable it for a session with `--memory`:

```bash
lunar-agent run "Continue the migration and remember the key decisions" \
  --runtime openai-compatible --agent-loop --memory --json
```

The model can call `recall_memory` and `remember_memory`. Entries are bounded and stored in the same
local SQLite database, with `global` and run-scoped namespaces. Notes are never injected into a
request silently; the model must explicitly request recall. No embeddings service or vector database
is required. Inspect notes locally with `lunar-agent memory --json` or search global notes with
`lunar-agent memory "deployment" --json`.

## Multi-step plans

For dependent work, provide a JSON plan. The controller validates the graph before creating a run,
executes ready tasks in order, and adds verified predecessor artifact paths/previews to each
dependent prompt:

```json
{
  "goal": "prepare a report",
  "tasks": [
    {"id": "research", "title": "Research", "prompt": "Collect facts"},
    {"id": "write", "title": "Write", "prompt": "Draft the report", "depends_on": ["research"]}
  ]
}
```

```bash
uv run famou run --plan plan.json --runtime mock --json
```

Malformed plans (duplicate IDs, unknown dependencies, or cycles) are rejected without leaving a
partial run in SQLite. A failed or rejected prerequisite blocks downstream tasks and the run settles
as failed. Each evaluator decision is also written to `evaluation.json` within the attempt
workspace and emitted as a structured event.

### Artifact acceptance contracts

An acceptance value can now verify observable local output, rather than only asking whether a
Worker's result text contains a phrase. These rules are evaluated in-process after the selected
Evaluator Profile passes. They never call a model, shell command, plugin, or network endpoint, and
they can only inspect regular files in the current task attempt workspace.

```json
{
  "id": "report",
  "title": "Write report",
  "prompt": "Create report.json and summarize the result",
  "acceptance": {
    "all": [
      {"result_contains": "report written"},
      {"artifact_exists": "report.json"},
      {"artifact_text_contains": {"path": "report.json", "contains": "summary"}},
      {"json_has_keys": {"path": "report.json", "keys": ["summary", "sources"]}}
    ]
  }
}
```

Supported leaves are `result_contains`, `artifact_exists`, `artifact_text_contains`, `json_parse`,
`json_has_keys`, and `output_valid`; compose them with non-empty `all` or `any` arrays. A plain string and the
legacy `{ "contains": "..." }` form still mean result-text containment. Paths must be portable,
relative, and remain below the current attempt directory; rule count/depth, contract text, and
inspected artifact bytes are bounded. Invalid JSON, missing keys, binary/oversized content, or a
symlink escape fail closed and leave an auditable failure rather than reading outside the workspace.

`output_valid` is the structured-output check used by `AlgorithmProblemContract.outputs`; its
payload is `{ "path": "output/...", "format": "json|jsonl|csv|text", "fields": [...] }`.

The `task_evaluated` event and attempt `evaluation.json` contain a bounded rule-level decision tree.
`lunar-agent status <run-id> --json` exposes the most recent evaluation summary under each task's
`evaluation` field, so a parent Agent can decide whether to patch or replan without scraping logs.
The complete v1 grammar and a runnable local example are in
[`specs/008-artifact-acceptance-contracts/contracts/acceptance-contract.md`](specs/008-artifact-acceptance-contracts/contracts/acceptance-contract.md)
and [`quickstart.md`](specs/008-artifact-acceptance-contracts/quickstart.md).

### Evidence-guided recovery proposals

After a failed verifier, exhausted runtime path, budget boundary, interruption, or input pause, ask
the local controller for an advisory next step:

```bash
lunar-agent recover <run-id> --json
lunar-agent status <run-id> --json
```

The deterministic local `RecoveryPolicy` returns one of `retry`, `ask_user`, `propose_patch`,
`propose_replan`, `stop`, or `none`. It reads only the durable ledger and does not call a model,
runtime, tool, shell, or network endpoint. Critically, it never resumes work, weakens acceptance,
changes a budget, or commits a plan revision itself: a parent Agent deliberately follows with the
existing `answer`, `resume`, `patch`, or `replan` command.

Each distinct proposal is written as a SHA-256-indexed
`recovery/proposals/<fingerprint>.json` audit artifact and an idempotent `recovery_proposed` event.
The latest proposal is available as the additive `recovery` field in `status --json`, alongside the
existing task evaluation. Proposal evidence uses only controlled IDs, statuses, rule kinds, and
budget names; it does not duplicate raw runtime errors, prompts, artifacts, answers, or model
content. The full contract and runnable fixture are in
[`specs/009-evidence-guided-recovery/contracts/recovery-proposal.md`](specs/009-evidence-guided-recovery/contracts/recovery-proposal.md)
and [`quickstart.md`](specs/009-evidence-guided-recovery/quickstart.md).

When a task is retried, the next attempt prompt keeps the immutable task request first and appends a
bounded feedback projection. A failed acceptance evaluation contributes only controlled rule names;
a runtime failure contributes generic recovery guidance. Raw provider errors, credentials, result
text, and artifact contents are never copied into retry prompts. The prompt is written and hashed
under the new attempt directory, so the correction loop remains inspectable without changing the
plan or acceptance contract. See
[`specs/011-verified-retry-feedback/`](specs/011-verified-retry-feedback/) for the contract.

## Called by another Agent

Codex or another local Agent can invoke the CLI as a child process. Use `--json` so stdout contains
one stable machine-readable value, and use the returned run ID as the durable handle:

```bash
result=$(uv run famou run "Inspect this repository" --runtime mock --json)
run_id=$(printf '%s' "$result" | python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')
uv run famou status "$run_id" --json
```

For a long-running goal, return the handle immediately and let a local child process continue:

```bash
result=$(uv run famou run "Inspect this repository" --runtime subprocess --detach --json)
run_id=$(printf '%s' "$result" | python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')
uv run famou status "$run_id" --json
```

The detached controller log is stored at `<run-workspace>/controller.log`.

`cancel` updates the ledger first, then terminates the detached controller's persisted process group.
If a runtime races with cancellation, its late result is discarded and recorded as
`task_result_discarded`; it cannot turn the run back to succeeded.

Long goals can be piped without shell escaping:

```bash
printf '%s' 'Analyze these three artifacts and produce a report' \
  | uv run famou run - --runtime mock --json
```

The TUI, if added later, is for human observation and approvals; the CLI/JSON contract remains the
automation boundary for Codex, Hermes, OpenClaw, and scripts.

## Development

```bash
uv run pytest
uv run --extra lint ruff check .
```

See the [quickstart](specs/001-standalone-local-agent/quickstart.md) for the recovery scenario and
the [runtime contract](specs/001-standalone-local-agent/contracts/runtime-adapter.md) before adding
an adapter.

The effect-layer design and WebAgent branch comparison are documented in
[`docs/architecture.md`](docs/architecture.md), with the active SDD feature in
[`specs/023-verified-algorithm-execution/`](specs/023-verified-algorithm-execution/).
