# Tasks: Session Transcript Recovery

**Input**: [spec.md](./spec.md), [plan.md](./plan.md)

## Phase 1: Transcript core

- [x] T001 Implement bounded JSONL transcript with load/append/compaction and redaction.
- [x] T002 Add runtime session path/context hooks and explicit history mode.

## Phase 2: Controller and CLI

- [x] T003 Wire stable run/task transcript paths and artifact indexing for success/pause/retry.
- [x] T004 Add `--session-history` and detached/answer propagation.

## Phase 3: Verification and release

- [x] T005 Add transcript continuity, bounds, credential redaction, and regression tests.
- [x] T006 Update README/contracts/quickstart and run all supported Python versions.
- [x] T007 Commit as `vchive` and push `main`.
