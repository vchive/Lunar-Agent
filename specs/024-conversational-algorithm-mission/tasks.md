# Tasks: Conversational Algorithm Mission

## Phase 1 — tests first

- [x] T024-01 Add compiler envelope/schema/secret/path tests.
- [x] T024-02 Add awaiting-input and same-run answer/resume tests.
- [x] T024-03 Add generated DAG, manifest, status, and detached propagation tests.

## Phase 2 — implementation

- [x] T024-04 Implement bounded `CompilationResult`, `ContractCompiler`, and runtime compiler.
- [x] T024-05 Add same-run plan promotion to the SQLite store/controller.
- [x] T024-06 Add `solve` CLI, compiler fingerprinting, resume, and answer integration.
- [x] T024-07 Export the compiler seam and preserve existing command behavior.

## Phase 3 — documentation and verification

- [x] T024-08 Update README and architecture documentation with conversational intake.
- [x] T024-09 Run pytest, Ruff, compileall, diff checks, and Specify checks; commit as `vchive` on
  `main`.
