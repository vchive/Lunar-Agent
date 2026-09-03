# Data Model: Verified Experiment Memory

## Experiment plan

```json
{
  "schema_version": "1",
  "hypothesis": "A feasibility-preserving relocation should reduce total distance.",
  "change_tags": ["relocation", "delta-evaluation"],
  "target_metrics": [{"metric": "distance", "direction": "decrease"}]
}
```

The normalized object is stored at `Candidate.metadata.experiment`. It describes intent only.

## Derived experiment card

```json
{
  "schema_version": "1",
  "candidate_id": "candidate-0002",
  "parent_id": "candidate-0001",
  "plan": {"...": "..."},
  "outcome": "improved",
  "validity": 1,
  "combined_score": 0.8,
  "combined_score_delta": 0.3,
  "metrics": {
    "distance": {
      "before": 120.0,
      "after": 110.0,
      "delta": -10.0,
      "direction": "minimize",
      "improved": true
    }
  }
}
```

Cards are prompt projections, not new archive records. Per-tag summaries count card outcomes and
are recomputed deterministically.
