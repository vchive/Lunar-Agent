# Tasks: Artifact Acceptance Contracts

## Phase 1 — Specification and Test Contract

- [x] T001 Record user stories, research decisions, data model, contract, and quickstart in
  `specs/008-artifact-acceptance-contracts/`.
- [x] T002 Define bounded leaf/composite rule fixtures and legacy-compatibility expectations.

## Phase 2 — Safe Acceptance Interpreter (US1, US2)

- [x] T003 [US1] Extend `src/famou/evaluator.py` with canonical contract compilation, bounded
  result/artifact/JSON rules, and structured rule evidence.
- [x] T004 [US2] Validate contracts in `src/famou/policy.py` and `src/famou/store.py` before run
  creation; test traversal, symlink, malformed, oversized, secret, and unknown-rule rejection.
- [x] T005 [US1] Add unit fixtures in `tests/test_evaluator.py` and controller fixtures in
  `tests/test_plan.py`, then preserve legacy `contains` behavior.

## Phase 3 — Auditable Integration (US3)

- [x] T006 [US3] Add `Evaluation.details` to controller events/audit JSON and the latest per-task
  status payload without changing the Runtime Adapter contract.
- [x] T007 [US3] Add status/event/delivery/replan integration coverage in `tests/test_cli.py` and
  `tests/test_plan.py`.

## Phase 4 — Polish and Verification

- [x] T008 Update `README.md` and `docs/architecture.md` with contract syntax and local boundary.
- [x] T009 Run Ruff, full pytest, `compileall`, and the documented local CLI quickstart.
- [x] T010 Mark this task list complete, commit with `vchive` identity, and push `origin main`.
