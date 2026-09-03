# Runtime-Backed Evolution Contract

`--agent-runtime` is an explicit adapter profile, not runtime discovery. It is converted into one
fresh `RuntimeAgentAdapter` per unbound role and then consumed by the existing strict evolution
bridges. Solver output is normalized as candidate source; evaluator output must parse as a validated
`EvaluationReport`. Any failure follows the existing bounded evolution error path.
