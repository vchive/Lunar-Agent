# Data Model: Evolution Result Handoff

No new durable table or migration is required.

`StrategyResult` gains one additive field:

| Field | Type | Meaning |
| --- | --- | --- |
| `best_candidate_path` | `string \| null` | Workspace-relative source path of the selected valid candidate |

The field is serialized in the existing strategy result payload. It is null whenever
`CandidateArchive.best()` returns no valid candidate or the selected record does not resolve to a
regular confined file (the latter is treated as a fail-closed evolution result).
