# Tasks: Verified Algorithm Candidate Execution

**Input**: Design documents from `/specs/023-verified-algorithm-execution/`

## Phase 1 — tests first

- [x] T023-01 Add failing library tests for successful runner evidence, non-zero exit, timeout,
  bounded output, and path confinement in `tests/test_evolution.py`.
- [x] T023-02 Add failing evaluator-wrapper tests proving execution evidence is visible and runner
  failures become invalid reports in `tests/test_evolution.py`.
- [x] T023-03 Add failing CLI tests for runner option conflicts, artifact indexing, detached
  propagation, secret-safe state, and resume provenance in `tests/test_cli.py`.

## Phase 2 — implementation

- [x] T023-04 Implement immutable `CandidateExecution`, `CandidateRunner`, and explicit command
  runner in `src/famou/evolution.py`.
- [x] T023-05 Implement execution-aware evaluator composition while preserving the legacy evaluator
  command protocol in `src/famou/evolution.py`.
- [x] T023-06 Add CLI runner construction, fingerprints, validation, and detached propagation in
  `src/famou/cli.py`.
- [x] T023-07 Index execution evidence and preserve cancellation/retry behavior in
  `src/famou/controller.py`.
- [x] T023-08 Export the new library seam from `src/famou/__init__.py`.

## Phase 3 — documentation and verification

- [x] T023-09 Update README and `docs/architecture.md` with execution-backed evaluation.
- [x] T023-10 Run pytest, Ruff, compileall, `git diff --check`, and SDD prerequisite checks; update
  this feature status to Implemented and commit as `vchive` on `main`.
