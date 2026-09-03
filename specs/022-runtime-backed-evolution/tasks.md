# Tasks: Runtime-Backed Evolution Agents

## Phase 1 — tests

- [x] T022-01 Add failing CLI tests for runtime-backed solver/evaluator and mixed role modes.
- [x] T022-02 Add failing tests for runtime fingerprints, conflicts, secret-safe state, and detach.

## Phase 2 — implementation

- [x] T022-03 Add explicit runtime profile options and construct fresh `RuntimeAgentAdapter` instances.
- [x] T022-04 Add credential-safe runtime fingerprints and detached propagation.

## Phase 3 — documentation and verification

- [x] T022-05 Update README and architecture docs with standalone runtime evolution.
- [x] T022-06 Run pytest, Ruff, compileall, `git diff --check`, and `specify check`; commit as
  `vchive` on `main` only after all checks pass.
