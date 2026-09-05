# Feature 053: Deep Effect Failure Statistics

## Goal
Expose bounded, auditable execution health counters in each `effect-deep-trial` case report. This helps diagnose model and harness reliability before historical FM-Eval comparisons are available.

## Scope
- Count failed logical runs by durable `error_code` (including `process_timeout`).
- Count per-round feedback failure categories (`none`, `invalid_candidate`, `evaluation_failed`, `score_unavailable`).
- Report recorded/completed rounds and deterministic per-round counters.
- Keep score authority unchanged: counters are projections of validated records and never infer or create baseline scores.

## Contract
Each case report gains `failure_statistics` with `runs`, `failed_runs`, `run_error_codes`, `rounds`, `completed_rounds`, `round_failure_categories`, `round_error_codes`, `timeout_count`, and `per_round` (one entry for every configured outer round). `completed_rounds` means a round record completed the subject and harness protocol; score validity remains represented by the existing `valid_runs` and feedback categories. Missing/partial records remain visible through recorded/completed counts.

The `timeout_count` is the number of canonical `process_timeout` codes observed at either the
logical-run or round level. The projection counts the `none` feedback category as an explicit
successful round outcome so the category totals reconcile with recorded rounds.
