# Tasks: Conversational Evolution Handoff

## Phase 1 — tests first

- [x] T035-01 Test parser and payload for `solve --evolve` with mock runtime.
- [x] T035-02 Test intake/evolution link idempotency and no duplicate child run on resume.
- [x] T035-03 Test staged input copy preserves digest/size and rejects conflicts/symlinks.
- [x] T035-04 Test generated plan tasks are superseded only when unstarted.
- [x] T035-05 Test runtime-backed solver/evaluator roles produce a valid strategy result.

## Phase 2 — implementation

- [x] T035-06 Add bounded solve evolution options and detached propagation.
- [x] T035-07 Add controller APIs for superseding pending plan tasks and copying input artifacts.
- [x] T035-08 Add CLI bridge that creates, links, runs, and reports the evolution child.
- [x] T035-09 Make the mock runtime emit a strict evaluator report for evolution role prompts.

## Phase 3 — documentation and verification

- [x] T035-10 Document conversational evolution quickstart and two-run recovery model.
- [x] T035-11 Run full tests, lint, compileall, diff checks, and Specify checks; commit as `vchive`
  on `main`.
