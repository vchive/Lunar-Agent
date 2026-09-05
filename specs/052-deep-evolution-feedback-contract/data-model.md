# Data Model: Controlled Deep-Evolution Feedback Contract

## `RoundFeedback`

```json
{
  "schema_version": "1",
  "round_index": 2,
  "validity_score": 1.0,
  "overall_score": 0.55,
  "quality_score": 0.55,
  "score_delta": 0.05,
  "best_overall_score": 0.55,
  "best_round_index": 2,
  "failure_category": "none",
  "detail_metrics": {"objective": 0.55},
  "candidate_manifest": [{"path": "answer.json", "size_bytes": 42, "sha256": "sha256:..."}],
  "stagnation": {"detected": false, "consecutive_rounds": 0, "window": 2},
  "directive": "refine_best"
}
```

All paths are relative, all scores are finite or null, and all enum values are closed. The
manifest is a bounded projection and is not an exhaustive archive.

## Compatibility

The old `{round_index, validity_score, overall_score, quality_score}` object is accepted at the
subject boundary and normalized to the full contract with an empty manifest and neutral directive.
New runner records always persist the full contract.
