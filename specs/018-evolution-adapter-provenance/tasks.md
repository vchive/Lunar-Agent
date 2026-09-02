# Tasks: Evolution Adapter Provenance

## Phase 1 — contract and tests

- [x] T018-01 Add failing tests for optional config fingerprints and legacy state compatibility.
- [x] T018-02 Add failing CLI resume tests for changed command/profile fingerprints.

## Phase 2 — implementation

- [x] T018-03 Add validated optional fingerprints to `EvolutionConfig.to_dict()`.
- [x] T018-04 Compute canonical solver/generator/evaluator fingerprints in the evolve CLI.
- [x] T018-05 Reject fingerprint drift before task claim and preserve detached/resume propagation.

## Phase 3 — documentation and verification

- [x] T018-06 Update README and architecture docs with provenance behavior.
- [x] T018-07 Run pytest, Ruff, compileall, `git diff --check`, and `specify check`; commit as
  `vchive` on `main` only after all checks pass.
