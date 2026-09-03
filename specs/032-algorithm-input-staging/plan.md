# Implementation Plan: Algorithm Input Staging

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Add an explicit local input boundary that hashes files at the run level and copies only verified
bytes into private task attempts. Reuse the existing artifact store, path-confinement helpers, and
CLI JSON output; no external storage or database migration is needed.

## Decisions

1. **CLI syntax** — repeatable `--input SOURCE[=DEST]`; basename inference keeps the common case
   short while `=DEST` supports contract-specific names.
2. **Run-level source of truth** — `data/raw/<DEST>` is immutable for a run after staging; retries
   and resumes must see identical bytes.
3. **Attempt-local copies** — each runtime sees only its own copy at `data/raw/<DEST>`, preserving
   workspace isolation and making tool-capable Agent access straightforward.
4. **Input artifact kind** — `input_data` is separate from interactive `input` answers and is not
   considered deliverable output.
5. **Bounded metadata** — event/status payloads contain destination, size, and digest only.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Local files and standard-library hashing only. |
| Local-First and Durable State | Pass | Inputs are persisted in the run workspace and ledger. |
| Runtime Adapter Isolation | Pass | Attempts receive verified copies, never the source path. |
| Artifact-First Verification | Pass | Digest mismatch blocks runtime execution. |
| Bounded Autonomy | Pass | File count, size, path, and symlink limits are explicit. |
| Test-First Recovery | Pass | Idempotent, changed-data, and attempt-copy tests cover resume. |

## Complexity tracking

No service, queue, dependency, or schema migration is introduced. Staging adds bounded local I/O
before compilation/execution and a bounded copy per attempt.
