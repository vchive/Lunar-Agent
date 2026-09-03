# Data Model: Quality-Diversity Population Selection

## Derived candidate family

```json
{
  "candidate_id": "candidate-0004",
  "problem_type": "routing",
  "family_tag": "two_opt_local_search",
  "validity": 1,
  "combined_score": 0.81
}
```

This is a conceptual in-memory projection, not a persisted record. `family_tag` exists only when an
exact tag in `Candidate.metadata.experiment.change_tags` belongs to the canonical repertoire for
the current contract. Validity and score come from `EvaluationReport` and remain authoritative.

## Active quality-diversity set

The existing `PopulationState.active_ids` schema is unchanged. Its ordered values are now selected
as:

1. best valid candidate under existing rank;
2. best valid candidate from each remaining recognized family under rank;
3. remaining candidates under rank until island capacity.

No family name, grid, novelty score, or selection outcome is added to state JSON.
