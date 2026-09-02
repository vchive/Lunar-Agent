# Plan Document Contract

`plan` inspection returns the immutable document and current pointer:

```json
{
  "plan_id": "plan-abc123",
  "version": 2,
  "parent_version": 1,
  "schema_version": "1",
  "goal": "prepare and verify a report",
  "hard_constraints": ["use local artifacts"],
  "soft_constraints": [],
  "objective": "report",
  "evidence": ["user confirmed CSV"],
  "assumptions": [],
  "tasks": [{"id": "research", "title": "Research", "prompt": "Collect facts", "depends_on": []}],
  "acceptance": {},
  "verification": {"required": true},
  "delivery": {"artifacts": true}
}
```

The document is immutable once committed. Task IDs are mapped to the existing scheduler and every
revision is recoverable after restart.

