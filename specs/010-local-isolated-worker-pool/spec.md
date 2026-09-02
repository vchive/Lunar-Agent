# Feature Specification: Local Isolated Worker Pool

**Feature Branch**: `010-local-isolated-worker-pool`  
**Created**: 2026-09-02  
**Status**: Implemented

## Goal

Execute independent tasks in a local plan concurrently while keeping each task's runtime context,
transcript, process observer, artifacts, and durable events isolated. This supplies the local
effect-layer equivalent of parallel sub-agents without adding a service, queue, or dependency on a
machine-wide Hermes/OpenCode/Codex installation.

## User Scenarios & Testing

### User Story 1 — Parallelize independent work (Priority: P1)

As a local owner, I want independent ready tasks to overlap so a multi-step plan completes faster.

**Independent Test**: A deterministic runtime blocks two root tasks on a barrier; a run with
`max_workers=2` completes while both tasks are active, and a run with the default completes
serially.

### User Story 2 — Preserve dependency ordering (Priority: P1)

As a parent Agent, I want parallel workers to respect the task DAG and expose only verified
predecessor artifacts to dependent tasks.

**Independent Test**: Two root tasks run concurrently and a dependent task is not claimed until both
roots succeed; the dependent prompt contains both predecessor artifacts.

### User Story 3 — Keep runtime state and cancellation isolated (Priority: P1)

As a local owner, I want cancellation, retries, input pauses, process metadata, and transcripts to
belong to the correct task even when workers overlap.

**Independent Test**: Factories return runtimes that record context/session/event sink values; two
tasks receive distinct values, and cancellation requests every active worker.

### User Story 4 — Remain a stable CLI boundary (Priority: P2)

As Codex, Hermes, OpenClaw, or another parent Agent, I want to request local parallelism through
the CLI while the default JSON shape remains backward compatible.

**Independent Test**: `run`/`resume --workers 2 --json` accepts the option and reports the selected
worker count; omitted `--workers` reports `1` and preserves existing output fields.

## Requirements

- **FR-1001**: Schedule only tasks returned as ready by the durable SQLite ledger; a task with
  unsatisfied dependencies MUST NOT run.
- **FR-1002**: At most `max_workers` tasks may execute at once. `max_workers` MUST be a positive
  integer and defaults to `1`.
- **FR-1003**: Each concurrent task MUST receive an independent Runtime instance. Mutable context,
  session path, event sink, process observer, cancellation state, and process metadata MUST NOT be
  shared between active tasks.
- **FR-1004**: A caller may inject `runtime_factory: () -> Runtime`. With `max_workers > 1`, a
  factory is required; omitting it MUST fail before execution. With `max_workers == 1`, the existing
  runtime instance remains supported.
- **FR-1005**: SQLite task claiming remains the source of truth. A claim race MUST result in at most
  one successful attempt; losing workers simply refill their slot.
- **FR-1006**: Retries, evaluator results, acceptance contracts, artifacts, budgets, input pauses,
  recovery, and run settlement MUST retain their existing durable event semantics under overlap.
- **FR-1007**: `cancel` MUST request cancellation on all active runtimes and terminate the detached
  controller process group when applicable. Late results MUST be discarded using existing ledger
  rules.
- **FR-1008**: `--workers N` is added to `run`, `resume`, `answer`, and planned execution commands;
  default is `1`. JSON responses add only an additive `workers` field where a run handle is emitted.
- **FR-1009**: No remote queue, HTTP/SSE endpoint, multi-tenancy, cloud sandbox, billing, or
  mandatory Hermes/OpenCode/Codex dependency is introduced.

## Success Criteria

- **SC-1001**: Independent fixture tasks overlap with `max_workers=2`; dependent fixtures never
  overlap before prerequisites succeed.
- **SC-1002**: Every active task has isolated runtime callbacks and run-relative transcript paths.
- **SC-1003**: Cancellation leaves no running task/attempt and sends cancellation to every active
  runtime.
- **SC-1004**: Existing tests pass unchanged; new concurrency, factory, dependency, cancellation,
  and CLI contract tests pass deterministically.
- **SC-1005**: Ruff and Python 3.11+ compilation pass; default single-worker quickstart needs no
  runtime factory and no external agent environment.

## Non-Goals

- Distributed workers or cross-process scheduling.
- Automatic plan decomposition or model-driven orchestration.
- Making a non-thread-safe custom Runtime safe without a factory.
