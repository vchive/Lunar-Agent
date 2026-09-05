# Data Model: Matched Deep-Evolution Effect Trial

## DeepEffectTrialConfig

`runs_per_case` (1–10), `outer_rounds` (1–20; default 5), timeout, requested model, explicit subject
and harness commands, and separately allowlisted environments. Its safe identity stores command
hashes and environment names, never raw values.

## Deep round receipt

Subject-owned `receipts/NNN.json` contains mode, round index, outer-round count,
requested/effective model, model evidence, turns, and nullable token usage. Built-in receipts also
contain `request_sha256`, binding the receipt to the canonical request, including its logical-run
identity. The receipt contains no `run_index` field and no score. Harness-owned
`harness-NNN/receipt.json` contains the exact frozen identities and evaluator metrics.

## Deep logical-run record

The runner-owned `record.json` contains run identity, aggregate model telemetry, best valid score,
and a bounded ordered `rounds` array. Each round includes readiness, extraction status, validity,
quality, overall score, detail metrics, and receipt references. The record digest is indexed in
`control/state.json` for recovery.

New round records include `harness_request_sha256` and preserve the subject's `request_sha256` when
present. Legacy completed records without these fields remain readable. A recorded harness request
is re-read and checked against its digest; receipt model/usage fields and harness metric projections
must exactly match the round record. Only a clean `incomplete_rounds` prefix resumes in the same
attempt. Other failures retry in a new attempt, and an unrecorded harness result is always rescored.

Before replacing a state-registered `record.json`, the runner writes `record.previous.json` with the
exact state-authorized record. The journal remains until `control/state.json` atomically registers
the new digest. Resume restores it only when its digest matches state, then reruns the uncommitted
round; any other mismatch fails closed.

Legacy completed records without request digests remain readable for compatibility. Reading them
does not prove that an older runner could not have registered a subject-preseeded record before
these checks existed; conclusions requiring the hardened authority boundary need a fresh run.

## Report

The report declares protocol `famou-bench-deep-evolution-v1`, mode `deep_evolution`, strategy
`loop`, source-default alignment, per-run records, per-case best/delta and distribution summaries,
round-best/P50/P90 curves, milestone, comparability, and limitations.
