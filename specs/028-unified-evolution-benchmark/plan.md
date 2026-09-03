# Implementation Plan: Unified Evolution Benchmark Adapters

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Extend the Feature 027 benchmark config with a credential-safe map of external strategy commands,
allow `openevolve` in the CLI, and pass a bounded budget projection into the existing
`OpenEvolveStrategy`. Native strategies and OpenEvolve still execute through `build_strategy` in
separate workspaces.

## Decisions

1. **One strategy seam** — no benchmark-specific OpenEvolve implementation; use
   `EvolutionConfig(strategy="openevolve", command=...)`.
2. **Explicit executable** — the benchmark validates the executable in the existing strategy and
   stores only a hash in `BenchmarkConfig.to_dict()`.
3. **One evaluator contract** — the benchmark's explicit evaluator remains the fallback verifier
   when OpenEvolve's `result.json` omits an evaluation report.
4. **Backward-compatible default** — omitting `--strategy` still selects loop and population.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | OpenEvolve is never a dependency; command remains opt-in. |
| Local-First and Durable State | Pass | All archives/configs stay under isolated local workspaces. |
| Runtime Adapter Isolation | Pass | External process enters through existing strategy adapter. |
| Artifact-First Verification | Pass | Only bounded result.json/candidate/evaluator evidence is imported. |
| Bounded Autonomy | Pass | Existing subprocess timeout, path, and output limits remain authoritative. |
| Test-First Recovery | Pass | Fixture success/failure and report redaction are tested before completion. |

## Complexity tracking

No new dependency, database table, or service is introduced. The only new persisted field is a
credential-safe command digest map in the benchmark report.
