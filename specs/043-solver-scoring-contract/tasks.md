# Tasks: Solver Scoring Contract

## Phase 1 — tests first

- [x] T043-01 Test persisted contract projection retains hard/soft constraints and assumptions.
- [x] T043-02 Test verified objective/evaluator guidance is staged read-only before Agent invocation.
- [x] T043-03 Test prompt projection is bounded, hashed, relative, and excludes probes/profile/raw
  values/machine paths.
- [x] T043-04 Test compiled conversational solve wires guidance into the first candidate and keeps
  authoritative evaluation/materialization unchanged.
- [x] T043-05 Test bundle tamper fails before guidance and unchanged resume makes zero extra
  compiler/auditor calls.

## Phase 2 — implementation

- [x] T043-06 Add bounded immutable `SolverScoringContract` and verified bundle projection.
- [x] T043-07 Stage fixed read-only scoring files and add a bounded prompt summary.
- [x] T043-08 Complete canonical constraint projection from persisted contracts.
- [x] T043-09 Wire only conversational compiled-evaluator Agent generation; preserve other seams.

## Phase 3 — documentation and verification

- [x] T043-10 Update README and architecture with the solver-visible scoring boundary and private
  probe boundary.
- [x] T043-11 Run focused/full tests, lint, compileall, diff, quickstart, and Specify checks; mark
  implemented, commit, and push as `vchive` on `main`.
