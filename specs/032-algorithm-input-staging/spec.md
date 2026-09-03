# Feature Specification: Algorithm Input Staging

**Feature Branch**: `032-algorithm-input-staging`  
**Created**: 2026-09-03  
**Status**: Implemented  
**Input**: Local algorithm missions need a safe, reproducible way to provide real data to isolated roles.

## Context and scope

`AlgorithmProblemContract` describes input paths, but previously callers had to know the generated
run directory and copy files there manually. Worse, role runtimes execute inside an attempt-local
workspace and could not see run-level `data/raw` files. This feature adds an explicit CLI staging
boundary and materializes verified copies into every task attempt.

`--input SOURCE` stages a file as `data/raw/<basename>`. `--input SOURCE=DEST` chooses a portable
relative destination. The source is never persisted in the ledger; the run-relative destination,
size, and SHA-256 are. Repeating the same command is idempotent, while replacing an existing
destination with different bytes is rejected.

## User stories and acceptance scenarios

### User Story 1 — Provide real local data (P1)

1. Given one or more `--input` files, when `solve` or `run` starts, then files appear under the
   run workspace's `data/raw/` directory and are reported as `kind=input_data` artifacts.
2. Given `SOURCE=DEST`, when staging succeeds, then `DEST` is preserved below `data/raw/` without
   allowing absolute paths, traversal, backslashes, NUL bytes, or symlinks.

### User Story 2 — Give isolated roles deterministic read access (P1)

1. Given staged input artifacts, when any task attempt starts, then verified copies are available at
   the same `data/raw/...` paths inside that attempt workspace.
2. Given a staged file whose bytes no longer match its ledger digest, when an attempt starts, then
   execution fails closed before the runtime can consume it.
3. Given a prompt for an algorithm task, when staged inputs exist, then the prompt lists their
   task-relative paths without embedding file contents.

### User Story 3 — Resume safely (P1)

1. Given a detached solve that is resumed with the same `--input`, then staging does not duplicate
   artifact rows or alter the input.
2. Given a resume with a different file at an existing destination, then the command rejects the
   change instead of silently changing the problem definition.

## Functional requirements

- **FR-3201**: Expose repeatable `--input SOURCE[=DEST]` on local `solve` and `run` commands.
- **FR-3202**: Enforce at most 64 staged files and 16 MiB per file; accept only regular,
  non-symlink sources.
- **FR-3203**: Store staged files below run-relative `data/raw/` with deterministic destination
  validation and atomic writes.
- **FR-3204**: Record each staged file as a SHA-256 `input_data` artifact and emit a bounded,
  idempotent `algorithm_input_staged` event without source-machine paths or file contents.
- **FR-3205**: Copy ledger-verified input bytes into each task attempt's `data/raw/` before runtime
  execution; reject missing, oversized, symlinked, or digest-mismatched inputs.
- **FR-3206**: Add bounded input-path guidance to task prompts while preserving existing dependency
  artifact previews and retry behavior.
- **FR-3207**: Keep runs without `--input` and all existing runtime/plan behavior compatible.

## Success criteria

- **SC-3201**: `--input orders.csv` creates one `data/raw/orders.csv` artifact and an isolated
  attempt copy readable by the selected runtime.
- **SC-3202**: The same input staged twice creates one artifact row and succeeds; changed bytes,
  traversal, and symlink sources fail closed.
- **SC-3203**: Full legacy tests, lint, compile, diff, and Specify checks remain green.

## Out of scope

- Remote uploads, object stores, streaming datasets, automatic schema inference, or data cleaning.
- Implicit filesystem discovery outside explicitly staged files.
- Copying input bytes into event payloads, prompts, or model configuration metadata.
