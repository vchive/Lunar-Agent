# Data Model: Independent Evaluator Ensemble

No SQLite migration or new durable table is required. The ensemble returns the existing
`EvaluationReport` shape:

```json
{
  "schema_version": "1",
  "evaluator_id": "ensemble",
  "validity": 1,
  "quality": 0.8,
  "combined_score": 0.8,
  "detailed_scores": {
    "quality": {"value": 0.8, "direction": "maximize"}
  },
  "error_info": []
}
```

The ordered command list and shared role/capability profile are represented only by the existing
`evaluator_fingerprint` digest in strategy state.
