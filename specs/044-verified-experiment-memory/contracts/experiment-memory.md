# Contract: Verified Experiment Memory

## Agent response

A structured candidate may add top-level `experiment` beside `source`, optional `filename`, and
optional legacy `metadata`. Experiment fields are exact and bounded:

- `schema_version="1"`
- non-empty `hypothesis`
- one to eight safe `change_tags`
- one to eight `target_metrics`, each with `metric` and `direction` (`increase` or `decrease`)

It cannot provide outcome, validity, score, or delta fields.

## Outcome authority

Lunar-Agent joins each candidate to `parent_id` in the same archive. It computes outcomes from
canonical `EvaluationReport` objects. Higher `combined_score` is always better. Raw detailed metric
values use their declared `maximize`/`minimize` direction. Missing or direction-mismatched pairs are
not compared.

## Prompt projection

`experiment_memory` contains at most eight recent cards plus lexically sorted per-tag outcome
counts. It is advisory evidence: it may guide the next experiment but cannot affect selection,
validity, or scoring.
