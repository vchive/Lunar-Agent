# Implementation Plan: Conversational Algorithm Mission

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Add a strict runtime-backed contract compiler and a `solve` orchestration path. The compiler runs
as the first durable task, pauses through the existing input lifecycle when clarification is
needed, and promotes the same run to a validated algorithm plan after compilation. The generated
plan reuses the current SQLite ledger, role workspace, scheduler, evaluator, and resume behavior.

## Technical context

**Language/Version**: Python 3.11+
**Dependencies**: standard library; existing pytest/Ruff tools
**Storage**: SQLite ledger plus run-relative JSON artifacts
**Testing**: pytest, Ruff, compileall, quickstart, Specify checks
**Boundary**: one local process by default; explicit runtime adapter only

## Design decisions

1. **Compiler envelope** — The model/runtime returns exactly one JSON object:
   `{"status":"compiled","contract":{...}}` or
   `{"status":"needs_input","questions":[{"question":"...","options":[...]}]}`.
   A legacy direct contract object is not accepted by the CLI compiler, preventing accidental
   acceptance of prose or an unreviewed shape.
2. **Conservative provenance** — Every constraint carries the existing `source` and
   `verification`; generated assumptions are explicit. A compiler response with unresolved fields
   must ask rather than fill values. The validator performs structural checks and records compiler
   evidence; it does not pretend to prove domain semantics.
3. **Same-run promotion** — The intake task is completed first. A new `Store.attach_plan` operation
   writes the plan revision and generated tasks into the existing run, preserving run ID and
   answer/compile audit history. Generated task IDs are namespaced by the run as in normal plans.
4. **Durable recovery** — A compiler manifest records status, digest, runtime fingerprint, and
   relative artifact paths. Resume compares the fingerprint before claiming an unfinished intake
   task. Response content is retained only in bounded local artifacts, never in provenance state.
5. **Generated DAG** — Four bounded tasks are emitted: `data_discovery`, `formulate`, `solve`, and
   `verify`, with linear dependencies. This is deliberately a small deterministic baseline; later
   features can add parallel portfolio/evolution tasks without changing intake.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Compiler uses existing repository runtimes only. |
| Local-First and Durable State | Pass | Same-run promotion and SQLite input lifecycle. |
| Runtime Adapter Isolation | Pass | Compiler accepts only the Runtime protocol. |
| Artifact-First Verification | Pass | Contract/plan/manifest are hashed; tasks use normal evaluators. |
| Bounded Autonomy | Pass | Strict schema, bounded prompts, no shell or implicit discovery. |
| Test-First Recovery | Pass | Fixtures cover malformed, awaiting input, resume, and idempotency. |

## Complexity tracking

- `Store.attach_plan` is an additive transaction and does not migrate the schema.
- Generated tasks use the existing baseline non-empty evaluator; domain evaluation/evolution stays
  explicit and is intentionally deferred.
