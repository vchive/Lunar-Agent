# Data Model

`RouteDecision` contains domain, reason, confidence, required capabilities, solver/evaluator profile
names, `BudgetSpec`, and evidence. `BudgetSpec` contains positive `max_tasks`, `max_attempts`,
`max_tool_steps`, `max_runtime_seconds`, and `max_artifact_bytes`. All strings and arrays are bounded
and credential-like values are rejected before persistence.
