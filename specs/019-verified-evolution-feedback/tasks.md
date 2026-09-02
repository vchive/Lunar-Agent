# Tasks: Verified Evolution Feedback

## Phase 1 — tests

- [x] T019-01 Add failing tests proving invalid evaluator feedback appears in a later Agent prompt.
- [x] T019-02 Add failing bounds/leakage tests for metric/error projection.

## Phase 2 — implementation

- [x] T019-03 Add bounded `EvaluationReport` projection to Agent generation summaries.
- [x] T019-04 Label feedback as evidence and retain prompt-size/failure boundaries.

## Phase 3 — documentation and verification

- [x] T019-05 Update README and architecture docs.
- [x] T019-06 Run pytest, Ruff, compileall, `git diff --check`, and `specify check`; commit as
  `vchive` on `main` only after all checks pass.
