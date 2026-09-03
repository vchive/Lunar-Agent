# Implementation Plan: Structured Algorithm Outputs

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Treat algorithm data files as a typed contract rather than an informal deliverable. Reuse the
existing local acceptance interpreter for format/field checks, add a controller promotion boundary,
and keep the append-only artifact ledger as the source of delivery metadata.

## Decisions

1. **Attempt-local generation, run-level delivery** — runtimes stay confined to
   `tasks/<task-id>/<attempt-id>/`; successful files are copied to stable `<run>/output/` paths.
2. **Output artifact kind** — promoted files use `kind=output`; result/runtime/session/evaluation
   records remain separate for audit and backwards compatibility.
3. **Independent enforcement** — generated plans may include `output_valid` acceptance rules, but
   the controller adds missing required checks for custom plans and validates optional files when
   present.
4. **Fail closed** — missing required files, malformed data, traversal/symlink paths, and oversized
   files prevent task success or delivery; no model claim can override the contract.
5. **No schema migration** — `outputs` lives in the immutable plan JSON and existing SQLite tables
   already accept a bounded artifact `kind` string.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Standard-library parsing and local files only. |
| Local-First and Durable State | Pass | Attempt evidence and promoted outputs are local and hashed. |
| Runtime Adapter Isolation | Pass | Runtime only writes its private attempt workspace. |
| Artifact-First Verification | Pass | Output validity is independent of Solver prose. |
| Bounded Autonomy | Pass | Paths, fields, bytes, and formats are bounded and fail closed. |
| Test-First Recovery | Pass | Success, missing, malformed, and legacy cases are covered. |

## Complexity tracking

No service, queue, dependency, or database migration is introduced. The controller adds a small
promotion step and `status` reuses the existing artifact list.
