# Tasks: Evolved Output Materialization

## Phase 1 — tests first

- [x] T036-01 Test a valid evolved CSV/JSON output is executed, independently validated, promoted,
  hashed, reported, and delivered from the intake run.
- [x] T036-02 Test missing required output, malformed format/fields, non-zero exit, and timeout fail
  without a parent output artifact.
- [x] T036-03 Test path escape, symlink, oversized output, and conflicting parent bytes fail closed.
- [x] T036-04 Test successful and failed terminal materializations resume without another execution,
  and tampered identity/digest evidence is rejected.
- [x] T036-05 Test source-only contracts and existing solve/evolve command behavior are unchanged.

## Phase 2 — implementation

- [x] T036-06 Add the isolated Python final-candidate runner and deterministic attempt/result model.
- [x] T036-07 Add exact `OutputSpec` validation and conflict-safe parent output promotion.
- [x] T036-08 Integrate materialization into the conversational evolution handoff and durable events.
- [x] T036-09 Expose composite status/output metadata and enforce the result in `deliver`.
- [x] T036-10 Update Agent generation instructions and repository mock fixtures for executable output
  candidates without weakening independent evaluation.

## Phase 3 — documentation and verification

- [x] T036-11 Document the execution protocol, data lifecycle, recovery behavior, and CLI example.
- [x] T036-12 Run focused and full tests, lint, compileall, diff, quickstart, and Specify checks;
  commit and push as `vchive` on `main`.
