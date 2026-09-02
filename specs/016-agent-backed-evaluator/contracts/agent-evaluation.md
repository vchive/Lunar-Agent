# Agent Evaluation Contract

The evaluator receives a Feature 014 `AgentRequest` whose prompt identifies the candidate source
path and provides a bounded algorithm contract summary. It must return an `AgentResult` with
`status: succeeded` and `text` containing exactly one JSON `EvaluationReport` object. Plain text,
markdown, malformed JSON, non-success status, and reports violating validity-first invariants are
rejected as bounded `EvolutionError` failures.
