# Implementation Plan: Standalone Local Famou Agent

**Branch**: `001-standalone-local-agent` | **Date**: 2026-09-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-standalone-local-agent/spec.md`

## Summary

Build a local-first Famou controller that owns durable run state and artifacts while delegating
execution through a replaceable Runtime Adapter. The first increment is a synchronous CLI with a
SQLite ledger, run-scoped filesystem artifacts, recovery of interrupted tasks, a deterministic mock
runtime, and a subprocess runtime contract. Hermes is deliberately not a required dependency and
must not be discovered from the user's machine.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Python standard library for the runtime; `pytest` as a development-only
test dependency; `uv` for reproducible environment setup when available

**Storage**: SQLite (WAL mode, migration table) for control-plane state; local filesystem for
artifacts and logs

**Testing**: `pytest` plus subprocess/temporary-directory integration tests

**Target Platform**: macOS and Linux local workstations

**Project Type**: Installable Python CLI/library

**Performance Goals**: Status lookup under one second for 10,000 events; mock P1 run under two
minutes including bootstrap

**Constraints**: Single user; local-only by default; no global Hermes/OpenCode/Codex dependency; no
public server; artifact paths confined to a run workspace; recoverable after process interruption

**Scale/Scope**: One local user, up to eight concurrently ready tasks in the first controller model,
with no distributed coordination

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Standalone Distribution: PASS — core has no Hermes import or global executable discovery.
- Local-First and Durable State: PASS — SQLite ledger and run-scoped filesystem are mandatory.
- Runtime Adapter Isolation: PASS — runtime calls cross a Protocol boundary.
- Artifact-First Verification: PASS — outputs are files with metadata and evaluator hooks are
  explicit.
- Bounded Autonomy: PASS — subprocess runtime receives an explicit command and confined workspace.
- Test-First Recovery: PASS — recovery and idempotency are P1 acceptance tests.
- Small Surface Area: PASS — standard library, SQLite, CLI, and no distributed services.

## Research Summary

See [research.md](./research.md) for decisions and alternatives. The main decision is to keep the
controller independent from Hermes and make Hermes an optional future adapter rather than a runtime
precondition.

## Project Structure

### Documentation (this feature)

```text
specs/001-standalone-local-agent/
├── plan.md
├── research.md
├── data-model.md
├── contracts/
│   └── runtime-adapter.md
├── quickstart.md
└── tasks.md
```

### Source Code (repository root)

```text
src/famou/
├── __init__.py
├── __main__.py
├── cli.py
├── config.py
├── controller.py
├── models.py
├── runtime.py
└── store.py

tests/
├── test_controller.py
├── test_runtime.py
└── test_store.py
```

**Structure Decision**: A single `src/famou` package keeps the local application easy to install and
keeps domain, storage, runtime, and CLI boundaries visible without premature service decomposition.

## Phase 0: Research

1. Confirm an isolated Python bootstrap path that does not invoke global Hermes state.
2. Confirm SQLite WAL, migration, event idempotency, and crash-recovery practices.
3. Define a subprocess Runtime Adapter contract that can later host Hermes, OpenCode, Codex, or a
   fully bundled runtime without leaking host-specific APIs.

## Phase 1: Design

1. Model Run, Task, Attempt, Event, Artifact, and Approval entities.
2. Document the Runtime Adapter and CLI contracts.
3. Provide a quickstart that proves a clean-environment mock run and resume workflow.

## Phase 2 completion design

The P2 increment keeps orchestration in one local controller process. SQLite stores the dependency
array and runner process identity; the filesystem stores result and evaluator JSON artifacts. A plan
is validated in memory and inserted in one transaction, so a bad plan cannot leave an orphan run.
The scheduler promotes only dependency-satisfied tasks and marks downstream work blocked when an
upstream task fails. Handoff is explicit: the dependent prompt contains run-relative artifact paths
and bounded previews, while the task workspace remains the source of truth for large files.

## Complexity Tracking

No constitution violations are expected. A separate evaluator service and distributed queue remain
out of scope; detached execution uses a local process group and durable PID metadata only.
