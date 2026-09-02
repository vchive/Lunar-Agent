# Feature Specification: Evidence-Guided Recovery Proposals

**Feature Branch**: `009-evidence-guided-recovery`
**Created**: 2026-09-02
**Status**: Implemented

## Goal

Turn durable local failure evidence into a bounded, runtime-neutral recovery proposal. Lunar-Agent
must recommend the next safe control-plane action without silently retrying, changing an accepted
plan, calling a model, or executing a tool.

## User Scenarios & Testing

### User Story 1 — Diagnose a Failed Verified Task (Priority: P1)

As a local owner or parent Agent, I want a failed independent acceptance check translated into a
specific patch proposal for its logical plan task, so I can correct the task without scraping logs
or guessing which plan version is current.

**Independent Test**: Run a task whose required artifact is missing, then call `recover`; it returns
`propose_patch`, references the current plan version and failed task, persists an event/artifact,
and never creates a new revision.

**Acceptance Scenarios**:

1. Given a failed `task_evaluated` event with failed acceptance details, when recovery is requested,
   then the proposal is `propose_patch` with bounded evaluation-oriented guidance.
2. Given the same unchanged ledger, when recovery is requested twice, then the proposal is stable
   and only one idempotent recovery event/artifact is indexed.

### User Story 2 — Escalate the Correct Boundary (Priority: P1)

As a parent Agent, I want failures caused by missing input, runtime configuration/authority, or a
budget boundary to produce the appropriate `ask_user` or `propose_replan` action, so a local
controller never fabricates authority or silently relaxes a bound.

**Independent Test**: Deterministic fixtures cover a pending input request, a configuration-shaped
runtime failure, and a budget-exceeded run without using a model or network.

**Acceptance Scenarios**:

1. Given a waiting task, recovery returns `ask_user` and points to the durable input request.
2. Given a runtime failure indicating configuration or authority is required, recovery returns
   `ask_user` with a generic, non-secret question.
3. Given `budget_exceeded`, recovery returns `propose_replan`; it never expands a budget itself.

### User Story 3 — Let Parent Agents Consume Proposals Reliably (Priority: P2)

As Codex, Hermes, OpenClaw, or another parent Agent, I want a JSON CLI command and status field for
the most recent recovery proposal, so the CLI remains the stable local integration boundary.

**Independent Test**: `lunar-agent recover <run-id> --json` emits one proposal object; a following
`status --json` exposes the same stored proposal under `recovery`.

## Edge Cases

- An active or recovered `ready`/`uncertain` task receives a `retry` proposal only; `recover` does
  not call `resume` or claim work.
- A succeeded run returns `none`; a cancelled run returns `stop`.
- Legacy runs without a versioned plan receive a replan-oriented proposal rather than an invalid
  patch reference.
- Proposal evidence uses controlled identifiers/states/rule kinds only. It does not copy runtime
  errors, prompts, artifact contents, secrets, or model output into a new durable record.
- The latest proposal changes only when its deterministic payload changes. Its event ID and JSON
  artifact name are content-derived, so repeated reads are idempotent.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-901**: Provide a deterministic local `RecoveryPolicy` which maps run, task, evaluation,
  input, and budget evidence to `none`, `retry`, `ask_user`, `propose_patch`, `propose_replan`, or
  `stop`.
- **FR-902**: Treat recovery as advisory: it MUST NOT call a Runtime Adapter, model, tool, shell,
  network endpoint, `resume`, `patch`, or `replan`.
- **FR-903**: A failed acceptance contract on a versioned plan MUST produce a patch proposal tied to
  the current `(plan_id, version)` and logical task ID, with no fabricated patch payload.
- **FR-904**: A budget failure or an unplanned/structural failure MUST recommend replan rather than
  changing tasks, acceptance, or limits automatically.
- **FR-905**: Waiting input and configuration/authority-shaped runtime failures MUST request explicit
  user/parent input using generic bounded questions.
- **FR-906**: Persist each distinct proposal in an idempotent `recovery_proposed` event and a
  SHA-256-indexed `recovery/proposals/<fingerprint>.json` artifact.
- **FR-907**: Add `recover <run-id> [--json]` and expose the latest stored proposal as the additive
  `recovery` field of `status --json`.
- **FR-908**: Preserve Features 001–008: durable retry/recovery, plan revisions, budgets, delivery,
  acceptance contracts, Runtime Adapter isolation, and existing CLI JSON payloads.
- **FR-909**: Remain local-first and standard-library-only; add no service endpoint, queue,
  multi-tenancy, cloud component, or mandatory Hermes/OpenCode/Codex dependency.

## Success Criteria *(mandatory)*

- **SC-901**: All deterministic decision fixtures return the expected action with no model,
  runtime, tool, shell, or network call.
- **SC-902**: Repeating `recover` for unchanged state produces one proposal event and one indexed
  proposal artifact in 100% of fixtures.
- **SC-903**: Every proposal carries no more than 16 controlled evidence entries and contains no
  credential-like material from failure data.
- **SC-904**: `recover --json` and `status --json` expose the same latest proposal and preserve all
  earlier JSON fields.
- **SC-905**: Full tests, Ruff, Python 3.11+ compilation, and the documented CLI quickstart pass.

## Assumptions

- Applying a proposal remains a parent/user action through the existing `patch`, `replan`, `answer`,
  or `resume` commands.
- Deterministic evidence classification is the baseline; a future planner may consume this schema
  but must not bypass the authority boundary.
