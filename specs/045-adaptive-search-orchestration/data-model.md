# Data Model: Adaptive Search Orchestration

## Search directive

```json
{
  "schema_version": "1",
  "mode": "repair",
  "priority": "restore_feasibility",
  "target_candidate_id": "candidate-0001",
  "parent_id": null,
  "inspiration_ids": [],
  "error_codes": ["serve-all"],
  "proven_change_tags": ["two-opt"],
  "avoid_change_tags": ["unsafe-shortcut"],
  "instruction": "Repair the target's reported failures before optimizing score."
}
```

This object exists only in an Agent generation prompt. IDs and outcomes come from canonical
candidate records; tags come from verified experiment-memory aggregation. It is not persisted as
strategy state and has no effect on evaluator authority.
