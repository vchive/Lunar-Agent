# Lunar-Agent

Lunar-Agent is a standalone, local-first agent inspired by Hermes' continuous sessions, practical
tools, and long-running memory. It keeps the durable task ledger, artifacts, and optional memory in
a run-scoped local directory. It does **not** require a machine-wide Hermes, OpenCode, or Codex
installation.

The project is being developed with Spec-Driven Development (SDD). The current effect-layer work is
captured in [`specs/019-verified-evolution-feedback/`](specs/019-verified-evolution-feedback/), built on
independent artifact acceptance contracts in
[`specs/008-artifact-acceptance-contracts/`](specs/008-artifact-acceptance-contracts/) and domain
routing, profiles, and budgets in
[`specs/007-domain-routing-solver-evaluator/`](specs/007-domain-routing-solver-evaluator/). The earlier
WebAgent-style experiment is retained as a superseded draft in
[`specs/002-webagent-effect-parity/`](specs/002-webagent-effect-parity/).

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
unless the run passed independent evaluation and has hashed result/runtime artifacts. All command
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

When an Agent is the solver, later generations also receive a small `evaluation_feedback` projection
for recent candidates: validity, metric scores, and controlled constraint error codes/messages. It
is reconstructed from validated archive reports on resume, capped at eight metrics/errors, and
explicitly labeled as evidence. Candidate source, prompts, logs, and adapter exception text are not
copied into the solver prompt.

`status --json` and `events --json` expose the evolution result, iteration events, candidate archive
events, and indexed `evolution/archive.jsonl`, `evolution/state.json`, and `evolution/result.json`
artifacts.  OpenEvolve remains optional and is invoked only when `--openevolve-command` points to an
existing absolute executable; no global installation is discovered.

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
and `json_has_keys`; compose them with non-empty `all` or `any` arrays. A plain string and the
legacy `{ "contains": "..." }` form still mean result-text containment. Paths must be portable,
relative, and remain below the current attempt directory; rule count/depth, contract text, and
inspected artifact bytes are bounded. Invalid JSON, missing keys, binary/oversized content, or a
symlink escape fail closed and leave an auditable failure rather than reading outside the workspace.

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
[`specs/019-verified-evolution-feedback/`](specs/019-verified-evolution-feedback/).
