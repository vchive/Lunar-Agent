# Tasks: Verified Experiment Memory

## Phase 1 — tests first

- [x] T044-01 Test strict Agent experiment response parsing and legacy compatibility.
- [x] T044-02 Test evaluator-derived seed/improved/unchanged/regressed/invalid outcome cards.
- [x] T044-03 Test metric deltas/directions and prove model claims cannot override evaluator facts.
- [x] T044-04 Test bounded/redacted plans, tags, counts, and prompt compaction.
- [x] T044-05 Test loop/population projections and reconstruction by a fresh resumed generator.

## Phase 2 — implementation

- [x] T044-06 Implement bounded experiment-plan normalization in the Agent bridge.
- [x] T044-07 Implement deterministic archive/lineage outcome and metric-card derivation.
- [x] T044-08 Add recent cards/tag outcome counts to bounded generation context.
- [x] T044-09 Update solver response instructions while preserving legacy generator seams.

## Phase 3 — documentation and verification

- [x] T044-10 Update README and architecture with verified experiment memory semantics.
- [x] T044-11 Run focused/full tests, lint, compileall, diff, quickstart, and Specify checks; mark
  implemented, commit, and push as `vchive` on `main`.
