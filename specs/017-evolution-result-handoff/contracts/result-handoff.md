# Evolution Result Handoff Contract

The existing strategy result object remains additive:

```json
{
  "strategy": "loop",
  "status": "completed",
  "best_candidate_id": "candidate-0001",
  "best_candidate_path": "evolution/candidates/candidate-0001/candidate.py"
}
```

`best_candidate_path` is always relative to the run workspace and is emitted only for a selected
valid candidate. It is not an authorization to execute or deliver the source; callers must use the
existing run status and delivery contracts.
