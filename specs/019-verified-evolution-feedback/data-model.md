# Data Model: Verified Evolution Feedback

No new durable model or migration is required. The projection is request-local JSON derived from an
existing `Candidate` record:

```json
{
  "validity": 0,
  "quality": null,
  "combined_score": 0,
  "detailed_scores": {
    "feasibility": {"value": 0, "direction": "maximize"}
  },
  "errors": [{"code": "constraint_violation", "message": "serve-all failed"}]
}
```

The projection is limited to eight metrics and eight errors. It is not persisted separately; the
archive's validated `evaluation` object remains authoritative.
