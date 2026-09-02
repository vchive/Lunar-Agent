# Tasks: Agent-Backed Evolution

## Phase 1 — bridge

- [x] T015-01 Implement bounded Agent-to-CandidateGenerator bridge.
- [x] T015-02 Normalize plain/JSON source responses and fail closed on Agent errors.
- [x] T015-03 Add bridge tests with deterministic fixture adapters.

## Phase 2 — CLI

- [x] T015-04 Add explicit `--agent-command`, role, and capability options to `evolve`.
- [x] T015-05 Preserve generator-command, population, OpenEvolve, detach, and resume behavior.
- [x] T015-06 Add CLI Agent-generation regression and quickstart documentation.

## Phase 3 — verification

- [x] T015-07 Run pytest, Ruff, compileall, diff check, and `specify check`.
