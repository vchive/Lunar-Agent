# Feature Specification: Experimental WebAgent-Style Core Loop (Superseded)

**Feature Branch**: `002-webagent-effect-parity`

**Created**: 2026-09-01

**Status**: Superseded by `003-hermes-inspired-local-agent`

**Input**: User goal: first match the user-visible execution capabilities of Famou WebAgent while
remaining an independent local agent.

> This draft captured a possible WebAgent-style stage machine. The product direction was changed:
> Lunar-Agent is now Hermes-inspired at the session/runtime layer, with durable local memory and a
> scheduler for orchestration. It must not implement WebAgent's intake/clarify/build/verify/deliver
> pipeline as its primary architecture. The reusable tool-loop and safety work is carried forward
> into feature 003.

## User Scenarios & Testing

### User Story 1 - Orchestrate a Goal Through Durable Stages (Priority: P1)

As a user, I can submit a goal and observe a durable Master workflow that separates intake,
clarification, planning, build execution, verification, and delivery. The controller—not the model—
owns stage transitions and the task ledger.

**Independent Test**: A two-task plan produces phase events in order, dispatches Build only after the
plan is validated, and settles only after evaluator-backed artifacts are present.

### User Story 2 - Complete a Task Through Tools (Priority: P1)

As a user, I can give Lunar-Agent a goal and let a configured model iteratively inspect files,
write files, and optionally run bounded commands until it returns a deliverable, rather than getting
one opaque text completion.

**Independent Test**: A fixture model returns two tool calls followed by a final answer; the agent
executes them in order inside the run workspace and records their events and artifacts.

### User Story 3 - Keep the Loop Bounded and Recoverable (Priority: P1)

As a user, I can set a maximum number of model/tool steps and a runtime timeout. Every turn and tool
result is persisted as a structured event, and cancellation/restart cannot mark an unfinished task
successful.

**Independent Test**: A model that repeatedly asks for tools reaches the step limit with a failed,
auditable task and no unbounded process.

### User Story 4 - Preserve Local Safety (Priority: P1)

As a local user, I can use read/list/write tools confined to the task workspace. Command execution
is disabled unless explicitly enabled, and path traversal or malformed tool arguments are rejected.

**Independent Test**: Tool calls for `../outside` fail without creating files outside the workspace;
`run_command` is unavailable by default and available only with `--allow-exec`.

### User Story 5 - Provide a WebAgent-Compatible Build Contract (Priority: P2)

As a user, the model receives a stable build-oriented system contract: work from the persisted task
prompt and dependency artifacts, validity before quality, incremental artifacts, and a concise final
delivery summary. This is the local equivalent of Famou's Build Agent boundary; it does not import
Hermes or expose implementation internals to the model.

## Functional Requirements

- **FR-201**: The runtime layer MUST represent a model turn with text and zero or more structured
  tool calls, while preserving the existing one-shot RuntimeResult contract.
- **FR-202**: The controller MUST support an `--agent-loop` mode that repeats model turns until a
  final text answer, cancellation, timeout, or configured step limit.
- **FR-203**: Built-in tools MUST include `read_file`, `write_file`, and `list_dir`; all paths MUST
  be confined below the task workspace.
- **FR-204**: `run_command` MUST require explicit `--allow-exec`, use argument-array execution
  without a shell, and enforce a per-command timeout/output cap.
- **FR-205**: Every model turn and tool invocation MUST produce a structured event without raw API
  credentials or unbounded tool output.
- **FR-206**: Tool-produced files MUST be returned to the controller as relative artifacts and
  receive the existing SHA-256 metadata treatment.
- **FR-207**: The step limit MUST be enforced before executing a tool call beyond the limit, and the
  resulting task/run MUST not settle as successful.
- **FR-208**: Detached `run --agent-loop` MUST propagate endpoint/model/step/tool configuration to
  the child controller without putting an API key in its argument vector.
- **FR-209**: The controller MUST expose durable orchestration phases (`intake`, `clarify`, `plan`,
  `build`, `verify`, `deliver`) as events and MUST NOT dispatch Build work before a validated plan.
- **FR-210**: A plan and any replan patch MUST be persisted as run-scoped files and represented in
  the ledger; a model-generated plan MUST pass the same dependency/cycle validation as a CLI plan.
- **FR-211**: Clarification MUST be represented as structured questions/answers with an explicit
  `awaiting_input` state for interactive or parent-Agent callers; the Master MUST be able to resume
  from the answer without recreating the run.
- **FR-212**: Verification and delivery MUST be separate from Build: a worker's final text alone
  MUST NOT satisfy the run, and missing required artifacts MUST produce a retry or replan event.

## Non-Goals

- Full WebAgent product UI, HTTP/SSE service, billing, or multi-tenant deployment.
- Automatic model/provider discovery or Hermes/OpenCode/Codex installation.
- Deep evolution search, billing, SSE service, and a graphical UI remain follow-up features built on
  this durable loop. The orchestration state machine itself is in scope.

## Success Criteria

- **SC-201**: A local OpenAI-compatible fixture can complete a three-turn tool loop and produce a
  final result plus indexed tool artifacts.
- **SC-202**: A looping fixture stops deterministically at the configured step limit and emits no
  successful terminal event.
- **SC-203**: Safety tests prove no built-in tool can escape its task workspace and command execution
  is opt-in.
- **SC-204**: Existing P1/P2/P3 tests remain green without an external Hermes/OpenCode/Codex setup.
- **SC-205**: A parent Agent can parse an `awaiting_input` JSON response, submit an answer, and
  resume the same durable run through planning/build/verify/delivery without duplicate tasks.
