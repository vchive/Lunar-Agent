# Research: Independent Evaluator Ensemble

## Existing seam

`AgentCandidateEvaluator` already performs strict `AgentResult` status checking, JSON parsing, and
`EvaluationReport.from_dict` validation. `EvaluationReport` enforces validity-first score invariants
and bounded error/metric fields. The evolution strategy accepts one `CandidateEvaluator` callable.

## Decision

Compose multiple `AgentCandidateEvaluator` instances in `AgentEvaluatorEnsemble`. Each member gets a
unique workspace suffix. Reports are aggregated deterministically: validity must be unanimous;
valid numeric values use `statistics.median`; common metrics with matching directions are median
aggregated. Any member failure is converted to a controlled invalid report rather than raising
through the strategy, so the candidate remains archived as rejected evidence.

## Alternatives considered

1. **Majority vote on validity** — rejected because a minority constraint failure must not be
   silently overridden for algorithm deliverables.
2. **Average scores** — rejected because one outlier evaluator can dominate selection; median is
   robust and deterministic.
3. **Call all evaluators through one shared workspace** — rejected because evaluator-written files
   could collide or influence another evaluator's evidence.
