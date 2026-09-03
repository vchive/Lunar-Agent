# Tasks: Algorithm Input Staging

## Phase 1 — tests first

- [x] T032-01 Test explicit staging, idempotence, changed-byte rejection, and artifact metadata.
- [x] T032-02 Test verified input copies and path guidance in isolated task attempts.
- [x] T032-03 Test source/destination traversal, symlink, count, and size boundaries.

## Phase 2 — implementation

- [x] T032-04 Add repeatable `--input SOURCE[=DEST]` CLI options and bounded staging helper.
- [x] T032-05 Record `input_data` artifacts/events without source-machine paths or contents.
- [x] T032-06 Materialize digest-verified copies into each runtime/Agent attempt.
- [x] T032-07 Include staged input paths in task prompts and solve JSON payloads.

## Phase 3 — documentation and verification

- [x] T032-08 Add SDD specification, contract, data model, quickstart, and README guidance.
- [x] T032-09 Run full tests, lint, compileall, diff checks, and Specify checks; commit as `vchive`
  on `main`.
