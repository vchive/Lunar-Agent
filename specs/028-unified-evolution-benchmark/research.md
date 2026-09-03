# Research: Unified Evolution Benchmark Adapters

`OpenEvolveStrategy` already writes a generated config under
`evolution/external/openevolve`, invokes an explicit executable without a shell, validates the
bounded `result.json`, confines the candidate path, and imports an optional strict
`EvaluationReport`. This is sufficient to participate in the same `EvolutionContext` orchestration.

The missing pieces are selection/configuration: `BenchmarkConfig` currently rejects `openevolve`
and has no per-strategy command map, while the CLI exposes only native strategy choices. Passing the
common budget in the generated config gives external fixtures a fair measurement surface without
assuming OpenEvolve's internal implementation.
