# Data Model: Solver Scoring Contract

## SolverScoringContract

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | `"1"` | Projection schema |
| `authority` | `"frozen_evaluator"` | Source of ranking semantics |
| `bundle_sha256` | 64-char hex | Verified v2 aggregate identity |
| `objective` | bounded text | Frozen optimization objective |
| `evaluator_source` | bounded UTF-8 | Exact frozen Python scorer |
| `evaluator_sha256` | 64-char hex | Exact scorer identity |

The in-memory object contains exact text. Its prompt projection replaces `evaluator_source` with:

```json
{
  "path": "scoring/evaluator.py",
  "size": 1234,
  "sha256": "...",
  "source_excerpt": "...",
  "truncated": false
}
```

The generation workspace also contains `scoring/objective.md`, `scoring/evaluator.py`, and a
canonical `scoring/manifest.json`. The manifest repeats only relative paths, sizes, and hashes.
There is no field for compiler probes, audit probes, private profile, or parent workspace.
