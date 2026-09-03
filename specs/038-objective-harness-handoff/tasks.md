# Tasks: Objective Harness Handoff

## Phase 1 — tests first

- [x] T038-01 Test a conversational loop selects and materializes by real harness score instead of
  a model evaluator claim.
- [x] T038-02 Test the harness reads verified candidate inputs/outputs/execution evidence but does
  not inherit model credentials or unrelated environment entries.
- [x] T038-03 Test malformed/non-zero/timeout harness failures become invalid candidates.
- [x] T038-04 Test configured-command persistence, matching resume, missing/changed command rejection,
  detached propagation, and post-clarification deferral.
- [x] T038-05 Test runtime evaluator, direct evolve, OpenEvolve, source-only, and population paths
  remain compatible.

## Phase 2 — implementation

- [x] T038-06 Extend `CommandCandidateEvaluator` with an optional bounded explicit environment.
- [x] T038-07 Add conversational CLI parsing, validation, request marker, detach/answer propagation,
  and credential-safe evaluator fingerprinting.
- [x] T038-08 Select the explicit harness in `_solve_evolution` and keep Feature 037 as the outer
  execution/output gate.
- [x] T038-09 Expose deterministic failure/status evidence without persisting raw command arguments.

## Phase 3 — documentation and verification

- [x] T038-10 Update README with objective normalization, security, recovery, and CLI examples.
- [x] T038-11 Run focused/full tests, lint, compileall, diff, quickstart, and Specify checks; commit
  and push as `vchive` on `main`.
