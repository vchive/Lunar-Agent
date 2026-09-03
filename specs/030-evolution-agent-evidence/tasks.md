# Tasks: Evolution Agent Evidence

## Phase 1 — tests first

- [x] T030-01 Test solver/evaluator transcript artifacts are indexed through the evolution ledger.
- [x] T030-02 Test model/tool/failure events are bounded and role/adapter tagged.
- [x] T030-03 Test missing, escaping, and symlink artifacts fail closed and secrets are redacted.
- [x] T030-04 Test callback, command, OpenEvolve, and resume compatibility.

## Phase 2 — implementation

- [x] T030-05 Add optional observer binding to Agent evolution bridges and strategy initialization.
- [x] T030-06 Forward runtime lifecycle events and validate/emit Agent artifacts.
- [x] T030-07 Record evolution Agent artifacts/events in `LocalController` with path/kind idempotency.

## Phase 3 — documentation and verification

- [x] T030-08 Add SDD data model, contract, quickstart, and README/architecture notes.
- [x] T030-09 Run tests, lint, compile, diff, and Specify checks; commit as `vchive` on `main`.
