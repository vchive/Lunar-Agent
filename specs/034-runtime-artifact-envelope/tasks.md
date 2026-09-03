# Tasks: One-shot Runtime Artifact Envelope

## Phase 1 — tests first

- [x] T034-01 Test valid/prose/compiler envelope parsing and atomic file materialization.
- [x] T034-02 Test unsafe paths, symlinks, duplicate files, metadata, and byte/file limits.
- [x] T034-03 Test a one-shot OpenAI-compatible structured-output run through promotion/delivery.

## Phase 2 — implementation

- [x] T034-04 Add strict envelope parsing and confined writes to `OpenAICompatibleRuntime`.
- [x] T034-05 Add bounded structured-task prompt guidance.

## Phase 3 — documentation and verification

- [x] T034-06 Document the envelope and one-shot usage in README/architecture.
- [x] T034-07 Run full tests, lint, compileall, diff checks, and Specify checks; commit as `vchive`
  on `main`.
