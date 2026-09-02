# Tasks: Evolution Result Handoff

## Phase 1 — result contract

- [x] T017-01 Add failing library tests for best path and all-invalid null behavior.
- [x] T017-02 Add `best_candidate_path` to `StrategyResult` and derive it from the confined archive.

## Phase 2 — integration and documentation

- [x] T017-03 Add CLI/status/result artifact assertions for the additive field.
- [x] T017-04 Update README and architecture docs with parent-Agent handoff usage.
- [x] T017-05 Run full pytest, Ruff, compileall, `git diff --check`, and `specify check`; commit as
  `vchive` on `main` only after all checks pass.
