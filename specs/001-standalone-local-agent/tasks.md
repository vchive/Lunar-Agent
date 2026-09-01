# Tasks: Standalone Local Famou Agent

**Input**: Design documents from `/specs/001-standalone-local-agent/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/runtime-adapter.md](./contracts/runtime-adapter.md)

**Tests**: Required for the P1 recovery, idempotency, and CLI acceptance scenarios.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Make the repository installable without any machine-wide Agent Runtime.

- [x] T001 Create `pyproject.toml` with Python 3.11 metadata, `famou` console entry point, and dev dependencies
- [x] T002 [P] Add repository `.gitignore` for virtual environments, local `.famou/` state, secrets, and `.hermes/`
- [x] T003 [P] Add `README.md` describing standalone bootstrap, runtime independence, and SDD workflow

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement durable state and safe workspace boundaries before Agent execution.

- [x] T004 Implement domain enums and dataclasses in `src/famou/models.py`
- [x] T005 Implement SQLite schema, migrations, WAL mode, and idempotent events in `src/famou/store.py`
- [x] T006 [P] Implement config/home/workspace resolution in `src/famou/config.py`
- [x] T007 [P] Implement artifact path confinement and SHA-256 metadata in `src/famou/artifacts.py`
- [x] T008 Add recovery and idempotency tests in `tests/test_store.py`

## Phase 3: User Story 1 - Run and Resume a Local Task (Priority: P1) 🎯 MVP

**Goal**: Submit a goal, persist it before execution, recover an interrupted task, and inspect the
result from the CLI.

**Independent Test**: Run the mock runtime in a temporary home, induce recovery of a running task,
resume the run, and assert one successful terminal result and one artifact.

- [x] T009 [P] [US1] Define Runtime Adapter protocol and result type in `src/famou/runtime.py`
- [x] T010 [P] [US1] Implement deterministic `MockRuntime` in `src/famou/runtime.py`
- [x] T011 [US1] Implement task claiming, retries, recovery, and terminal settlement in `src/famou/controller.py`
- [x] T012 [US1] Implement `run`, `resume`, `status`, `events`, and `cancel` commands in `src/famou/cli.py`
- [x] T013 [US1] Add module entry point in `src/famou/__main__.py` and package metadata in `src/famou/__init__.py`
- [x] T014 [US1] Add controller and CLI acceptance tests in `tests/test_controller.py`
- [x] T015 [US1] Add runtime contract tests in `tests/test_runtime.py`

## Phase 4: User Story 2 - Execute and Verify a Multi-Step Plan (Priority: P2)

**Goal**: Execute dependent tasks with artifact handoff and structured evaluator decisions.

**Independent Test**: Run a two-task plan with a rejecting evaluator and verify that dependent task
ordering and non-success settlement are visible in the ledger.

- [ ] T016 [P] [US2] Add dependency-aware task creation and ready-queue scheduling in `src/famou/controller.py`
- [x] T017 [P] [US2] Add structured evaluator protocol and default acceptance evaluator in `src/famou/evaluator.py`
- [ ] T018 [US2] Add plan input format and CLI option in `src/famou/cli.py`
- [ ] T019 [US2] Add multi-step/evaluator integration tests in `tests/test_plan.py`

## Phase 5: User Story 3 - Use a Self-Contained Runtime Boundary (Priority: P3)

**Goal**: Support an explicitly configured external command without discovering global Hermes state.

**Independent Test**: Run from a clean virtual environment with only the repository installed and
execute a subprocess fixture through the adapter.

- [x] T020 [P] [US3] Implement explicit `SubprocessRuntime` with timeout and stderr capture in `src/famou/runtime.py`
- [x] T021 [US3] Add clean-environment bootstrap and subprocess fixture tests in `tests/test_runtime.py`
- [x] T022 [US3] Document runtime command configuration and data-egress policy in `README.md`

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T023 [P] Add launchd/systemd user-runner documentation for detached local execution in `docs/background-runner.md`
- [x] T024 [P] Add JSON output mode and stable CLI exit-code documentation in `src/famou/cli.py` and `specs/001-standalone-local-agent/contracts/runtime-adapter.md`
- [ ] T025 Run the [quickstart](./quickstart.md), recovery suite, and static checks in CI configuration `.github/workflows/test.yml`
- [x] T026 Add `run --detach` durable-handle launch and coverage in `src/famou/cli.py` and `tests/test_cli.py`

## Dependencies & Execution Order

- Setup (Phase 1) precedes Foundational (Phase 2).
- Foundational (Phase 2) blocks all user stories.
- P1 (Phase 3) is the MVP and can ship without P2/P3.
- P2 depends on P1 task and artifact semantics.
- P3 depends on the Runtime protocol from P1 but does not change controller state ownership.
- Polish follows the desired user stories.

## Parallel Opportunities

- T002, T003, T006, and T007 can proceed in parallel after the repository is initialized.
- T009, T010, and T015 can proceed in parallel once the runtime contract is agreed.
- T016 and T017 can proceed in parallel after P1 state and artifact APIs exist.
- T020 and T024 can proceed in parallel with evaluator work.

## Implementation Strategy

1. Complete setup and durable storage first.
2. Deliver P1 with the mock runtime and recovery tests; this is the first usable local Famou Agent.
3. Add dependency-aware planning and evaluator control as P2.
4. Add external runtime execution only through the adapter as P3.
5. Defer background launch, UI, and service integrations until recovery behavior is proven.
