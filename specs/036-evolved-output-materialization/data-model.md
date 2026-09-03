# Data Model: Evolved Output Materialization

No SQLite migration is required. The child workspace stores a bounded JSON result; existing event
and artifact rows index the cross-run outcome.

## Materialization result

`evolution/materialization/result.json` is the canonical child record:

```json
{
  "schema_version": "1",
  "status": "succeeded|failed",
  "parent_run_id": "…",
  "evolution_run_id": "…",
  "contract_sha256": "…",
  "candidate_id": "candidate-0001",
  "candidate_path": "evolution/candidates/candidate-0001/candidate.py",
  "candidate_sha256": "…",
  "attempt_path": "evolution/materialization/candidate-0001-0123456789ab",
  "execution": {
    "status": "succeeded|failed|timed_out",
    "exit_code": 0,
    "duration_ms": 12,
    "evidence_path": "evolution/materialization/candidate-0001-0123456789ab/execution.json"
  },
  "validation": {
    "passed": true,
    "reason": "…",
    "evidence": ["output valid: output/routes.csv"]
  },
  "outputs": [
    {
      "path": "output/routes.csv",
      "format": "csv",
      "fields": ["item_id", "route_id"],
      "required": true,
      "size": 42,
      "sha256": "…"
    }
  ],
  "error": null
}
```

Raw stdout/stderr remain in the separately bounded `execution.json`. The result stores neither
output contents nor source-machine paths.

## Parent event and artifacts

The parent receives one deterministic `evolved_candidate_materialized` event with the result's
bounded identity/status metadata. Successful promotion also emits `evolved_outputs_promoted`.
Promoted files use existing artifact rows with `kind=output`; their paths are contract-relative and
their digest/size must match the materialization result.
