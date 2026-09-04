# Data Model: Matched Deep-Evolution Effect Trial

## DeepEffectTrialConfig

`runs_per_case` (1–10), `outer_rounds` (1–20; default 5), timeout, requested model, explicit subject
and harness commands, and separately allowlisted environments. Its safe identity stores command
hashes and environment names, never raw values.

## Deep round receipt

Subject-owned `receipts/NNN.json` contains mode, run/round identity, requested/effective model,
provider evidence, turns, and optional token usage. It contains no score. Harness-owned
`harness-NNN/receipt.json` contains the exact frozen identities and evaluator metrics.

## Deep logical-run record

The runner-owned `record.json` contains run identity, aggregate model telemetry, best valid score,
and a bounded ordered `rounds` array. Each round includes readiness, extraction status, validity,
quality, overall score, detail metrics, and receipt references. The record digest is indexed in
`control/state.json` for recovery.

## Report

The report declares protocol `famou-bench-deep-evolution-v1`, mode `deep_evolution`, strategy
`loop`, source-default alignment, per-run records, per-case best/delta and distribution summaries,
round-best/P50/P90 curves, milestone, comparability, and limitations.
