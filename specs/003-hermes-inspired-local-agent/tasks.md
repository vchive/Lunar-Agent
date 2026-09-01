# Tasks: Hermes-Inspired Local Agent Core

**Input**: [spec.md](./spec.md), [plan.md](./plan.md)

## Phase 1: Durable memory

- [x] T001 Add local SQLite memory schema with global/run scopes and bounded lexical recall.
- [x] T002 Add explicit `remember_memory` and `recall_memory` tool schemas and policy checks.

## Phase 2: Continuous session

- [x] T003 Generalize the model tool loop with a Hermes-inspired system contract and bounded errors.
- [x] T004 Persist session identity through controller context and wire explicit memory-enabled
  runtime construction through the controller; model checkpoints are written via `remember_memory`.

## Phase 3: Orchestration and invocation

- [x] T005 Preserve the DAG scheduler, retries, recovery, artifact handoff, and cancellation as the
  orchestration boundary.
- [x] T006 Add `--agent-loop`, `--max-steps`, `--allow-exec`, and detached propagation.
- [x] T007 Add a human/parent-Agent memory inspection command and document the JSON contract.

## Phase 4: Verification and release

- [x] T008 Add fixture tests for memory round-trip, tool loop, safety, limits, and scheduler reuse.
- [x] T009 Update README, runtime contract, quickstart, and mark feature 001 complete.
- [ ] T010 Run Python 3.11/3.12/3.13 tests and lint, commit as `vchive`, and push `main`.
