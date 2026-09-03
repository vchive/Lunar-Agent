# Tasks: Agent Solver Portfolio

## Phase 1 — tests

- [x] T020-01 Add failing library tests for deterministic round-robin selection and member failure.
- [x] T020-02 Add failing CLI tests for repeatable commands, conflicts, and fingerprint sensitivity.

## Phase 2 — implementation

- [x] T020-03 Implement `AgentPortfolioGenerator` over the existing Agent bridge.
- [x] T020-04 Add repeatable CLI option, explicit adapter construction, detached propagation, and
  ordered provenance fingerprint.

## Phase 3 — documentation and verification

- [x] T020-05 Update README and architecture docs.
- [x] T020-06 Run pytest, Ruff, compileall, `git diff --check`, and `specify check`; commit as
  `vchive` on `main` only after all checks pass.
