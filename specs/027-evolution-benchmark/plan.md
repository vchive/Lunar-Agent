# Implementation Plan: Reproducible Evolution Benchmark

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Add a small benchmark module over the existing evolution strategy boundary, then expose a local
`benchmark` CLI that runs `loop` and `population` against one contract and one command-backed
generator/evaluator pair. The report is additive and independent of SQLite task state.

## Decisions

1. **Library first** — `BenchmarkRunner` receives factories so tests and parent Agents can inject
   deterministic or runtime-backed roles without the CLI knowing provider details.
2. **Fresh workspaces** — every strategy is rooted at `<benchmark>/strategies/<name>`; no archive or
   transcript is shared across runs.
3. **Partial progress** — one strategy failure is captured as a report entry and the remaining
   strategies continue. Invalid configuration fails before any strategy starts.
4. **Relative evidence** — reports expose paths relative to the benchmark root and hash identities;
   raw commands and model credentials stay out of the report.
5. **Native MVP** — `loop` and `population` are the fair local comparison set. OpenEvolve continues
   through its explicit adapter until an equivalent process/result envelope is available.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Standard library and existing evolution module only. |
| Local-First and Durable State | Pass | Independent local workspaces and bounded JSON report. |
| Runtime Adapter Isolation | Pass | Factories enter through `EvolutionContext`, not strategy code. |
| Artifact-First Verification | Pass | Existing archives/evaluation reports remain authoritative. |
| Bounded Autonomy | Pass | Shared max rounds/population limits and bounded report fields. |
| Test-First Recovery | Pass | Failure isolation, determinism, and path tests precede implementation. |

## Complexity tracking

No new dependency, database table, or service is introduced. The CLI delegates command-backed
generation/evaluation to the already-tested adapters, so benchmark behavior cannot bypass existing
command and report validation.
