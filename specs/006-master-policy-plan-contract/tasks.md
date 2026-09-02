# Tasks: Master Policy and Plan Contracts

**Input**: Design documents from `/specs/006-master-policy-plan-contract/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required by the constitution and explicitly defined by the feature acceptance scenarios.

## Phase 1: Setup (Shared Infrastructure)

- [x] T001 Add feature-006 storage/domain module placeholders and export paths in `src/famou/` per `specs/006-master-policy-plan-contract/plan.md`
- [x] T002 [P] Add contract fixture JSON examples under `tests/fixtures/feature006/`

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 [P] Define bounded plan and policy dataclasses plus validation helpers in `src/famou/policy.py`
- [x] T004 [P] Add policy, plan, patch, and delivery JSON contract tests in `tests/test_policy.py`
- [x] T005 Add additive SQLite migration for `plan_revisions`, `policy_decisions`, and current-plan columns in `src/famou/store.py`

## Phase 3: User Story 1 - Choose the Smallest Useful Action (Priority: P1) 🎯 MVP

**Goal**: Classify simple, complex, and underspecified goals with bounded structured decisions.

**Independent Test**: Deterministic fixture policy returns `answer`, `execute_plan`, or `ask_user` as appropriate and persists decisions only when a run exists.

- [x] T006 [P] [US1] Add heuristic `MasterPolicy.decide` implementation in `src/famou/policy.py`
- [x] T007 [US1] Add `decide` CLI command and stable JSON output in `src/famou/cli.py`
- [x] T008 [US1] Persist run-associated policy decisions idempotently and expose them in status JSON in `src/famou/store.py` and `src/famou/cli.py`
- [x] T009 [US1] Add unit and CLI acceptance tests for direct answer, plan routing, bounded questions, and secret rejection in `tests/test_policy.py` and `tests/test_cli.py`

## Phase 4: User Story 2 - Execute an Auditable Versioned Plan (Priority: P1)

**Goal**: Atomically create, execute, inspect, and recover immutable plan revisions.

**Independent Test**: A valid multi-task plan executes through the existing scheduler; invalid plans leave zero orphan rows; restart returns the same plan ID/version.

- [x] T010 [P] [US2] Implement plan normalization and revision serialization in `src/famou/policy.py`
- [x] T011 [US2] Implement atomic `create_planned_run` and `get_current_plan` store operations in `src/famou/store.py`
- [x] T012 [US2] Add `plan` CLI command and current revision/status payload in `src/famou/cli.py`
- [x] T013 [US2] Wire planned-run creation into `LocalController` while preserving legacy `run --plan` behavior in `src/famou/controller.py`
- [x] T014 [US2] Add scheduler, migration, restart, and atomic-invalid-plan tests in `tests/test_plan.py` and `tests/test_store.py`

## Phase 5: User Story 3 - Patch or Replan After New Evidence (Priority: P1)

**Goal**: Apply typed optimistic patches and explicit replans without losing history or duplicating tasks.

**Independent Test**: A patch from version 1 produces version 2, stale patches fail atomically, and replan preserves both revisions and evidence.

- [x] T015 [P] [US3] Implement typed patch operations and resulting-plan validation in `src/famou/policy.py`
- [x] T016 [US3] Implement transactional patch/replan revision methods with optimistic base-version checks in `src/famou/store.py`
- [x] T017 [US3] Add `patch` and `replan` CLI commands with JSON errors and version output in `src/famou/cli.py`
- [x] T018 [US3] Add patch/replan integration and concurrency tests in `tests/test_plan.py` and `tests/test_store.py`

## Phase 6: User Story 4 - Deliver Verified Results (Priority: P2)

**Goal**: Return delivery only when the controller has verified task results and hashed artifacts.

**Independent Test**: Successful evaluated runs yield a `deliver` decision with artifact evidence; failed runs never do.

- [x] T019 [US4] Implement evidence-based delivery decision in `src/famou/controller.py` and `src/famou/policy.py`
- [x] T020 [US4] Add `deliver` CLI command and parent-Agent JSON contract in `src/famou/cli.py`
- [x] T021 [US4] Add positive/negative delivery and artifact-evidence tests in `tests/test_plan.py` and `tests/test_cli.py`

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T022 [P] Update README and feature quickstart/contracts with final command examples
- [x] T023 [P] Add migration/recovery and WebAgent effect-layer rationale to `docs/architecture.md`
- [ ] T024 Run Python 3.11/3.12/3.13 tests, Ruff, and feature quickstart; record results in feature docs (3.13 full suite and 3.11 AST parse completed; 3.12 interpreter unavailable)
- [x] T025 Commit with `vchive` identity and push `main` to `origin`

## Dependencies & Execution Order

- Phase 1 has no dependencies.
- Phase 2 depends on Phase 1 and blocks all user stories.
- US1 can complete as an MVP after Phase 2.
- US2 depends on the storage migration and policy models; US3 depends on US2's revision methods.
- US4 depends on evaluator/artifact queries from US2 but does not alter runtime adapters.
- Polish depends on all desired stories.

## Parallel Opportunities

- T002, T003, and T004 can proceed in parallel.
- T006 and T009 are mostly independent after foundational models exist.
- T010 and T015 are domain-only work and can proceed separately from CLI tasks.
- Documentation tasks T022 and T023 can run in parallel with final verification.

## Implementation Strategy

1. Complete foundational domain validation and migration first.
2. Deliver US1 deterministic policy and JSON contract as the first demonstrable increment.
3. Add US2 durable revisions and scheduler integration, then US3 patch/replan.
4. Add US4 evidence-based delivery and finish with compatibility, recovery, lint, and push checks.
