# Tasks: Matched Deep-Evolution Effect Trial

## Phase 1 — specification and tests first

- [x] T051-01 Audit WebAgent source-default five-round behavior and existing Feature 048/049 seams.
- [x] T051-02 Record deep request, receipt, round-record, recovery, and report contracts.
- [x] T051-03 Add failing tests for deep subject request/receipt and score-free previous feedback.
- [x] T051-04 Add failing tests for five-round execution, exact harness-per-round scoring, and curves.
- [x] T051-05 Add failing tests for P50/P90, breakthrough semantics, tamper rejection, and resume.

## Phase 2 — implementation

- [x] T051-06 Implement deep subject adapter mode with fresh bounded round sessions.
- [x] T051-07 Implement recoverable `DeepEffectTrialRunner` and atomic round records.
- [x] T051-08 Implement report distributions and round-gain aggregation.
- [x] T051-09 Add CLI/public exports while preserving normal effect-trial compatibility.

## Phase 3 — documentation and verification

- [x] T051-10 Add deep-trial quickstart and architecture/report vocabulary.
- [x] T051-11 Run focused/full tests, lint, compileall, Specify checks, and diff review.
- [x] T051-12 Mark implemented, commit, and push as `vchive` on `main`.
- [x] T051-13 Add request-binding and full receipt-field tamper regression tests.
- [x] T051-14 Reject subject-created harness workspaces and rerun unrecorded harness results.
- [x] T051-15 Restrict same-attempt resume to clean incomplete prefixes and verify legacy completed
  records.
- [x] T051-16 Update recovery contracts and run the full validation checklist.
- [x] T051-17 Prevent unregistered future-run records from bypassing subject/harness execution.
- [x] T051-18 Reject symlinks in every ancestor of persisted or resumed attempt artifacts.
- [x] T051-19 Recover later-round record/state commit-window interruptions with a verified journal.
