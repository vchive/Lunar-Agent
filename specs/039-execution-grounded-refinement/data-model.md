# Data Model: Execution-Grounded Refinement

No persisted schema or SQLite migration is required.

## Refinement evidence envelope

The following versioned object exists only inside an Agent generation prompt and is reconstructed
from a `Candidate` plus its workspace:

```json
{
  "schema_version": "1",
  "source": {
    "excerpt": "...",
    "size": 1234,
    "sha256": "...",
    "truncated": false
  },
  "execution": {
    "status": "failed",
    "exit_code": 1,
    "duration_ms": 42,
    "stdout_bytes": 0,
    "stderr_bytes": 147,
    "error": "output_contract_invalid",
    "artifacts": []
  },
  "verified_outputs": [
    {"path": "output/result.csv", "size": 321, "sha256": "..."}
  ]
}
```

If evidence cannot be admitted safely, the envelope contains only `schema_version` and a stable
`unavailable_reason`, such as `source_unavailable`, `execution_unavailable`, or
`artifact_unavailable`. It never contains the caught exception string.

## Candidate summary

Existing candidate identity, lineage, score, and evaluation feedback fields remain unchanged. A new
`refinement_evidence` field contains the envelope. Because the object is prompt-only, archive JSONL
and strategy state formats do not change.
