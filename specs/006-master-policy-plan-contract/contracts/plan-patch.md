# Plan Patch and Replan Contract

`patch` accepts a JSON object:

```json
{
  "plan_id": "plan-abc123",
  "base_version": 1,
  "reason": "verification found a missing source",
  "evidence": ["evaluator: missing-source"],
  "operations": [{"op": "update_task", "id": "research", "prompt": "Collect primary sources"}]
}
```

The base version must equal the current version. Valid operations produce version 2 and retain
version 1. `replan` uses the same shape but may replace the complete task/constraint set and must
record a reason/evidence. A stale or invalid patch returns an error and commits nothing.

