# Tasks: Independent Evaluator Ensemble

## Phase 1 — tests

- [x] T021-01 Add failing library tests for unanimous validity, median scores, disagreement, and
  member workspace isolation.
- [x] T021-02 Add failing CLI tests for repeatable evaluator portfolio commands and conflicts.

## Phase 2 — implementation

- [x] T021-03 Implement `AgentEvaluatorEnsemble` over the strict evaluator bridge.
- [x] T021-04 Add repeatable CLI option, isolated adapter construction, detached propagation, and
  ordered evaluator provenance fingerprint.

## Phase 3 — documentation and verification

- [x] T021-05 Update README and architecture docs.
- [x] T021-06 Run pytest, Ruff, compileall, `git diff --check`, and `specify check`; commit as
  `vchive` on `main` only after all checks pass.
