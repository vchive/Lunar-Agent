# Data Model: Local Evolution Strategies

## Candidate

One evaluated program or solver artifact.

| Field | Type | Rules |
|---|---|---|
| `candidate_id` | string | Stable run-scoped identifier; safe path segment. |
| `code_path` | string | Relative path below `evolution/candidates/<id>/`. |
| `parent_id` | string/null | Existing candidate ID for a derived candidate. |
| `generation` | integer | Non-negative lineage depth. |
| `iteration` | integer | Positive strategy iteration. |
| `strategy` | enum | `loop`, `population`, or `openevolve`. |
| `island_id` | integer/null | Population island; absent for loop. |
| `evaluation` | EvaluationReport | Immutable validity-first result. |
| `metadata` | object | Bounded JSON metadata, no credentials. |

Candidate source is copied into the run-relative candidate directory. Candidate records are appended
to `evolution/archive.jsonl`; an existing record is never overwritten.

## CandidateArchive

The archive is the complete history of evaluated candidates for one run.

- `archive.jsonl`: one canonical Candidate JSON object per line;
- `candidates/<candidate_id>/`: source and optional auxiliary artifacts;
- `best_candidate_id`: derived from valid candidates and higher-is-better `combined_score`;
- `contract_sha256`: binds the archive to the immutable algorithm contract.

An invalid candidate is retained for diagnosis but is excluded from `best_candidate_id`.

## PopulationState

Mutable state for the population strategy.

| Field | Type | Rules |
|---|---|---|
| `iteration` | integer | Number of completed offspring batches. |
| `population_size` | integer | 1–10,000 active candidates globally. |
| `offspring_per_iteration` | integer | 1–256. |
| `num_islands` | integer | 1–64 and no greater than `population_size`. |
| `active_ids` | object | Island ID to bounded candidate ID list. |
| `best_candidate_id` | string/null | Best valid archived candidate. |
| `rng_seed` | integer/null | Optional deterministic selection seed. |
| `last_migration_iteration` | integer | Migration watermark. |

The first implementation uses score plus token novelty. Each island retains its best candidate and
fills remaining slots by score/novelty ranking. Migration is optional and copies only bounded
candidate records; it never deletes archive history.

## EvolutionRunContext

Immutable inputs supplied to a strategy:

- validated `AlgorithmProblemContract`;
- run workspace root and contract digest;
- candidate generator callback;
- evaluator callback returning `EvaluationReport`;
- strategy configuration and optional cancellation callback.

The context contains no model credentials and no agent-specific session object.

## StrategyResult

The JSON-safe return value shared by all strategies:

```json
{
  "strategy": "loop",
  "status": "completed",
  "iterations": 5,
  "evaluated_candidates": 5,
  "valid_candidates": 4,
  "best_candidate_id": "candidate-0004",
  "best_score": 0.91,
  "archive_path": "evolution/archive.jsonl",
  "error": null
}
```

`status` is one of `running`, `completed`, `stagnated`, `cancelled`, or `failed`. Errors are
bounded strings and do not contain raw credentials or unbounded subprocess output.
