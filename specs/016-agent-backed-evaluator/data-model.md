# Data Model: Agent-Backed Evaluator

`AgentCandidateEvaluator` stores no new state. It contains an explicit `AgentAdapter`, evaluator
role/capabilities, timeout, and optional in-memory `AlgorithmProblemContract`.

For each candidate it creates an `AgentRequest` with a bounded prompt and a generation-specific
evaluation workspace. The Agent response text must be one JSON object matching the existing
`EvaluationReport` schema. The normalized report is returned to the strategy and persisted in the
existing candidate archive/state files.
