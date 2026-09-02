# Implementation Plan: Local Isolated Worker Pool

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)

## Summary

Add an opt-in local thread pool around the existing durable scheduler. Extract one-task execution
into a worker method, inject fresh runtime instances through a factory, and fan cancellation out to
active workers. Keep SQLite operations, event names, artifacts, recovery, and default serial
behavior unchanged.

## Phases

1. Define the SDD contract and deterministic concurrency fixtures.
2. Add controller worker isolation and batch scheduling with `max_workers=1` compatibility.
3. Construct runtime factories in the CLI and propagate `--workers` through direct/detached paths.
4. Verify race, dependency, cancellation, JSON, Ruff, compile, and quickstart behavior; commit and
   push with the `vchive` identity.

## Constitution Check

| Principle | Result | Design response |
| --- | --- | --- |
| Standalone distribution | Pass | Threads and standard library only. |
| Local-first durable state | Pass | SQLite remains the only scheduling authority. |
| Runtime Adapter isolation | Pass | Fresh factory instance per active task. |
| Artifact-first verification | Pass | Existing per-attempt paths and acceptance evaluation remain intact. |
| Bounded autonomy | Pass | Parallelism is explicit and bounded; no automatic decomposition. |
| Test-first/small surface | Pass | Worker extraction plus focused contract fixtures. |
