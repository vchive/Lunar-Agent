# Contract: Validity-First Evaluation Report

An independent evaluator for a contract-bearing run returns one JSON object. The report is a
decision record, not a natural-language completion claim.

```json
{
  "schema_version": "1",
  "evaluator_id": "routing-v1",
  "validity": 1,
  "quality": 0.82,
  "combined_score": 0.82,
  "detailed_scores": {
    "travel_time": {"value": 0.82, "direction": "maximize"},
    "late_deliveries": {"value": 0.0, "direction": "minimize"}
  },
  "error_info": []
}
```

## Invariants

1. `validity` is exactly `0` or `1`.
2. `combined_score` is finite, non-negative, and higher-is-better.
3. `validity=0` implies `combined_score=0`.
4. `quality`, when present, is finite and non-negative.
5. `detailed_scores` is bounded; each entry has a finite numeric value and `maximize` or `minimize`
   direction.
6. An invalid candidate includes at least one bounded `error_info` entry identifying a failed hard
   constraint or a format/execution category. A valid candidate has no hard-constraint violations.
7. The evaluator must independently recompute hard constraints from the declared input and output
   fields whenever the constraint verification mode is `independent`; solver self-reported metrics
   are not proof.

## Error categories

- `format_error`: output cannot be parsed according to the solution schema;
- `execution_error`: candidate program failed or exceeded its execution boundary;
- `constraint_violation`: a declared hard constraint failed;
- `evaluator_error`: the evaluator itself could not establish a decision.

These categories are not interchangeable. A candidate constraint violation is an evaluated invalid
solution; a format/execution/evaluator error is a failed evaluation and should be handled by the
controller's retry/recovery policy.
