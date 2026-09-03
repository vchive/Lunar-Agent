# Research: Reproducible Evolution Benchmark

The existing `EvolutionContext` already isolates strategy state under a workspace and accepts
injected generator/evaluator callables. `LoopStrategy` and `PopulationStrategy` persist compatible
`StrategyResult` objects and bounded state. A benchmark should therefore orchestrate those
strategies rather than copy or alter their loops.

The CLI can reuse `CommandCandidateGenerator` and `CommandCandidateEvaluator`, but must create a
new adapter instance per strategy so a stateful Agent or runtime cannot leak conversation state
between comparisons. The benchmark report should hash command/profile identities with the same
SHA-256 convention used by evolution resume, while exposing only relative strategy workspaces.
