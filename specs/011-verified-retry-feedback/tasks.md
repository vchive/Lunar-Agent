# Tasks: Verified Retry Feedback

## Phase 1 — Specification and Test Contract

- [x] T001 Define feedback precedence, safety bounds, artifact rendering, and non-goals.
- [x] T002 Add deterministic evaluator/runtime failure and secret-isolation fixtures.

## Phase 2 — Feedback Projection (US1–US3)

- [x] T003 Add bounded task-scoped evaluation projection helpers.
- [x] T004 Append feedback only on retry prompts while preserving original task prompt.
- [x] T005 Cover malformed/legacy events with generic runtime-failure fallback.

## Phase 3 — Regression and Documentation (US4)

- [x] T006 Add parallel task isolation and prompt artifact audit tests.
- [x] T007 Update README/architecture docs with verified retry feedback.

## Phase 4 — Verification

- [x] T008 Run pytest, Ruff, compileall, quickstart; commit as `vchive` and push `origin main`.
