# Tasks: Local Evolution Strategies

**Input**: Design documents from `/specs/013-evolution-strategies/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

## Phase 1: Foundational strategy boundary

- [x] T001 [P] Add deterministic candidate, archive, and strategy result fixtures in `tests/test_evolution.py`.
- [x] T002 [P] Add the strategy protocol, configuration validation, and shared result models in `src/famou/evolution.py`.
- [x] T003 [P] Add the canonical evolution strategy contract to `specs/013-evolution-strategies/contracts/evolution-strategy.md`.
- [x] T004 Implement workspace-confined candidate persistence and atomic state replacement in `src/famou/evolution.py`.

## Phase 2: User Story 1 — bounded local loop (P1 MVP)

**Independent test**: deterministic generator/evaluator runs multiple rounds, archives every candidate,
stops on round/stagnation budget, and returns the best valid candidate.

- [x] T005 [P] [US1] Add failing loop tests for best-so-far, stagnation, invalid candidates, cancellation, and resume in `tests/test_evolution.py`.
- [x] T006 [US1] Implement `LoopStrategy.run` and `LoopStrategy.resume` with fresh round contexts and append-only archive in `src/famou/evolution.py`.
- [x] T007 [US1] Add loop strategy metadata to the algorithm workspace manifest in `src/famou/algorithm.py` without changing legacy contracts.
- [x] T008 [US1] Document the loop invocation and expected archive output in `specs/013-evolution-strategies/quickstart.md` and `README.md`.

## Phase 3: User Story 2 — explicit population (P1)

**Independent test**: deterministic population search retains a bounded active set, records all
evaluated candidates, preserves a novel candidate, and selects only valid best candidates.

- [x] T009 [P] [US2] Add failing population tests for capacity, objective ordering, novelty retention, islands, migration, and deterministic seed behavior in `tests/test_evolution.py`.
- [x] T010 [US2] Implement `PopulationConfig`, `PopulationState`, objective-aware selection, token novelty, and active-set trimming in `src/famou/evolution.py`.
- [x] T011 [US2] Implement optional island assignment and ring migration in `src/famou/evolution.py`.
- [x] T012 [US2] Add population strategy parsing and bounds to `src/famou/algorithm.py`, preserving the loop default and canonical contract digest.
- [x] T013 [US2] Document population configuration and loop-vs-population tradeoffs in `docs/architecture.md`.

## Phase 4: User Story 3 — optional OpenEvolve adapter (P2)

**Independent test**: a fake explicit executable writes a valid result that is imported into the
canonical archive; absent, unsafe, timed-out, and malformed commands fail without partial import.

- [x] T014 [P] [US3] Add fake executable and adapter failure fixtures in `tests/test_evolution.py`.
- [x] T015 [US3] Implement `OpenEvolveStrategy` using an explicit argument list, bounded subprocess output, timeout, and result validation in `src/famou/evolution.py`.
- [x] T016 [US3] Add optional `openevolve` strategy selection and a clear CLI/configuration error when no executable is supplied in `src/famou/cli.py` and `src/famou/algorithm.py`.
- [x] T017 [US3] Document optional installation/executable configuration and the no-remote-service guarantee in `README.md` and `specs/013-evolution-strategies/quickstart.md`.

## Phase 5: User Story 4 — local/parent-Agent interoperability (P1)

**Independent test**: direct library/CLI and detached/resume paths expose the same additive result
metadata and do not require a global agent runtime.

- [x] T018 [P] [US4] Add strategy result JSON and detached/resume regression tests in `tests/test_cli.py` and `tests/test_evolution.py`.
- [x] T019 [US4] Add an evolution command or controller entry point that selects a strategy while retaining SQLite run authority in `src/famou/controller.py` and `src/famou/cli.py`.
- [x] T020 [US4] Ensure cancellation, timeout, and recovery events preserve archive/state evidence in `src/famou/controller.py` and `src/famou/store.py`.

## Phase 6: Polish and verification

- [x] T021 [P] Update `docs/architecture.md` with the strategy seam and OpenEvolve adapter boundary.
- [x] T022 Run the feature quickstart, full pytest, Ruff, and compileall; record results in `specs/013-evolution-strategies/quickstart.md`.
- [x] T023 Review Feature 012 compatibility and mark completed tasks in this file; commit as `vchive` on `main` only after all checks pass.

## Dependencies and execution order

- T001–T004 are foundational and block all strategy implementation.
- T005–T008 deliver the MVP loop and can be validated independently.
- T009–T013 depend on the shared archive and loop boundary but do not change the controller DAG.
- T014–T017 are optional integration work and must not add a base dependency.
- T018–T020 integrate strategies with parent-Agent/CLI behavior after library tests pass.
- T021–T023 are final cross-cutting verification.

## Implementation strategy

1. Deliver the native loop first and verify archive/evaluator invariants.
2. Add a minimal single-process population, then islands/migration only behind bounded config.
3. Add OpenEvolve as a subprocess adapter; never make it the canonical state owner.
4. Integrate CLI/controller entry points additively and compare all modes under equal budgets.
