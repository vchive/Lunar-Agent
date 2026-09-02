# Tasks: Evidence-Guided Recovery Proposals

## Phase 1 — Specification and Test Contract

- [x] T001 Record goal, decision precedence, safety alternatives, data model, CLI contract, and
  quickstart in this feature package.
- [x] T002 Define deterministic fixtures for acceptance, input, runtime configuration, budget,
  retry, terminal, and idempotency cases.

## Phase 2 — Pure Policy (US1, US2)

- [x] T003 [US1] Add bounded immutable `RecoveryProposal` and runtime-neutral `RecoveryPolicy` in
  `src/famou/recovery.py`.
- [x] T004 [US1] Add unit/controller fixtures proving failed acceptance maps to a versioned-task
  patch proposal and makes no plan/task mutation.
- [x] T005 [US2] Add precedence fixtures for input, runtime configuration, budget, retry, success,
  and cancellation.

## Phase 3 — Durable Parent-Agent Integration (US3)

- [x] T006 [US3] Add idempotent proposal event/artifact persistence in `LocalController`.
- [x] T007 [US3] Add `recover --json` plus `status --json.recovery`, and CLI contract coverage.

## Phase 4 — Polish and Verification

- [x] T008 Update README and architecture documentation with the advisory recovery boundary.
- [x] T009 Run Ruff, full pytest, Python 3.11+ compilation, and the documented local quickstart.
- [x] T010 Commit with `vchive` identity and push `origin main`.
