# Research: Runtime Profile Benchmark

`evolve` already constructs repository-owned runtimes with `_build_evolution_runtime` and wraps
them in `RuntimeAgentAdapter` plus strict evolution bridges. The benchmark can call the same helper
for each selected native strategy, ensuring one-shot and loop behavior does not drift between the
two commands.

`AgentLoopRuntime` accepts context/session paths from `RuntimeAgentAdapter`, and its
`OpenAICompatibleRuntime.complete` method preserves structured tool calls. The benchmark only needs
to expose those existing flags and record their fingerprint; it must not duplicate tool schemas or
relax evaluator parsing.
