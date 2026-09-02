# Tasks: Algorithm Problem Contract and Solver/Evaluator Workspace

**Input**: Design documents from `/specs/012-algorithm-problem-contract/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

## Phase 1 — Contract and report model (P1 MVP)

- [x] T001 [P] [US1] Add valid/invalid contract fixtures for all seven problem types, provenance,
  objective direction, strategy defaults, duplicate IDs, secrets, and unsafe paths in
  `tests/test_algorithm.py`.
- [x] T002 [P] [US3] Add evaluation-report fixtures covering validity-first score invariants,
  bounded errors, metric direction, and malformed numeric values in `tests/test_algorithm.py`.
- [x] T003 [US1] Implement bounded `AlgorithmProblemContract`, `InputSpec`, `ObjectiveSpec`,
  `ConstraintSpec`, and `EvolutionSpec` canonicalization in `src/famou/algorithm.py`.
- [x] T004 [US3] Implement `EvaluationReport` validation and structured error categories in
  `src/famou/algorithm.py`.

## Phase 2 — Isolated algorithm workspace (P1)

- [x] T005 [P] [US2] Add workspace manifest/digest and path-confinement tests, including raw input
  immutability and symlink escape rejection, in `tests/test_algorithm.py`.
- [x] T006 [US2] Implement fixed role-directory materialization and canonical manifest writing in
  `src/famou/algorithm.py`.
- [x] T007 [US2] Integrate contract validation and workspace materialization into
  `src/famou/controller.py` without copying or mutating input files.

## Phase 3 — Versioned plan and parent-Agent integration (P2)

- [x] T008 [P] [US5] Add optional `algorithm_problem` round-trip coverage and legacy-plan regression
  tests in `tests/test_plan.py`.
- [x] T009 [P] [US5] Add additive `plan`/`status --json` contract metadata assertions in
  `tests/test_cli.py`.
- [x] T010 [US5] Extend `PlanDocument` and patch/replan reconstruction in `src/famou/policy.py` to
  preserve the optional algorithm contract immutably.
- [x] T011 [US5] Expose the canonical contract and workspace manifest metadata through existing
  status/plan JSON in `src/famou/cli.py`.

## Phase 4 — Documentation and verification

- [x] T012 [P] Update `README.md` and `docs/architecture.md` with the algorithm contract boundary,
  the loop/population strategy distinction, and the three local invocation forms.
- [x] T013 [US5] Add a replan integration test proving that a changed algorithm contract refreshes
  the manifest and appends a versioned registration event without rewriting completed task output.
- [x] T014 Run `quickstart.md`, full pytest, Ruff, and compileall; record results in the feature
  documents and resolve any migration or compatibility failures.
- [ ] T015 Commit with `vchive` identity and push `origin main` after all checks pass.

## Dependencies and execution order

1. T001–T004 define and test the core value objects; T003 precedes integration.
2. T005–T007 depend on the contract model and provide the P1 workspace slice.
3. T008–T011 depend on T003/T006 and preserve plan/CLI compatibility.
4. T012–T015 are final cross-cutting verification.

Parallel opportunities: T001/T002, T005, T008, T009, and T012 touch separate test/documentation
files and may be developed in parallel after the contract shape is agreed.

## Deliberately deferred follow-up features

- Feature 013: conversational clarification and data discovery;
- Feature 014: isolated Solver/Evaluator Agent roles and executable evaluator loading;
- Feature 015: WebAgent-like fresh-context loop evolution;
- Feature 016: candidate archive and population selection;
- Feature 017: optional multi-island migration after equal-budget evidence.
