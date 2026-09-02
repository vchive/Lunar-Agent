# Tasks: Local Isolated Worker Pool

## Phase 1 — Specification and Test Contract

- [x] T001 Define concurrency scope, isolation, factory, cancellation, CLI, and compatibility rules.
- [x] T002 Add deterministic overlap, dependency ordering, factory validation, cancellation, and
  CLI JSON fixtures.

## Phase 2 — Controller (US1–US3)

- [x] T003 Add `runtime_factory` and validated `max_workers` to `LocalController`.
- [x] T004 Extract serial task execution into an isolated worker method preserving all durable
  event/artifact/evaluation transitions.
- [x] T005 Implement bounded local thread-pool batches and SQLite claim-race refill behavior.
- [x] T006 Fan cancellation out to active runtimes and preserve late-result discard semantics.

## Phase 3 — CLI Boundary (US4)

- [x] T007 Add `--workers` to execution commands and build fresh repository runtime factories.
- [x] T008 Include additive worker metadata in direct and detached run/resume JSON handles.

## Phase 4 — Verification

- [x] T009 Update README/operator docs and quickstart for local parallel plans.
- [ ] T010 Run pytest, Ruff, compileall, and quickstart; commit as `vchive` and push `origin main`.
