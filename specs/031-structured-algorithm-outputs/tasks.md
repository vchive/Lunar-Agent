# Tasks: Structured Algorithm Outputs

## Phase 1 — tests first

- [x] T031-01 Test `OutputSpec` parsing, canonical round-trip, bounds, and legacy digest behavior.
- [x] T031-02 Test JSON/JSONL/CSV/text output validation and malformed/missing-field failures.
- [x] T031-03 Test attempt-local Solver output promotion, SHA-256 indexing, stable delivery, and
  prose-only rejection.

## Phase 2 — implementation

- [x] T031-04 Add the bounded `outputs` contract model and conversational schema support.
- [x] T031-05 Reuse the acceptance interpreter for independent `output_valid` checks.
- [x] T031-06 Promote passing outputs to run-level `output/` and record `kind=output` artifacts.
- [x] T031-07 Make `deliver` require required output artifacts while preserving legacy behavior.

## Phase 3 — documentation and verification

- [x] T031-08 Document the data-output contract, lifecycle, CLI consumption, and SDD decisions.
- [x] T031-09 Run full tests, lint, compileall, diff checks, and Specify checks; commit as `vchive`
  on `main`.
