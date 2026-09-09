# Feature Specification: Budget-Guided Fixed Measurement

**Branch**: `main`
**Created**: 2026-09-09
**Status**: Registered; not started

## Objective

Measure the combined Feature 063/064 runtime variant on the existing `supply_chain_inventory`
publication with `glm-5.1`, including every failed attempt. This is independent measurement, not
a causal estimate for one change, a matched WebAgent baseline, or a run-until-success exercise.

## Frozen protocol

- Exactly two new normal-mode subject attempts, launched concurrently through one snapshot of the
  explicitly authorized CC Switch configuration. Record shared-provider concurrency as a limitation.
- Same model profile as Feature 062: 40 tool calls, 900-second subject timeout, 200,000 cumulative
  token ceiling, no invented prices. Preserve the configured single-command cap of 300 seconds;
  Feature 064 may tighten it to the remaining invocation time.
- Source implementation is `6189e50ed714685cfe218d76c8ca818d3ffe4186`, including tool descriptions,
  transient budget hints, deadline propagation, atomic write_file, and timeout stream normalization.
  Freeze actual source/runner/request/config hashes before any subject starts.
- Reuse the exact suite, public ledger, private case and harness hashes. Extractor remains `glm-5.2`
  with `claude-agent-sdk==0.1.81`. Subject has no private evaluator content or old candidate/memory.
- Each slot is used once. Failure, validity or observed quality cannot trigger replacement, retries,
  model/prompt/budget changes, or a third attempt. Existing pilot and campaigns are excluded.

## Evidence and statistics

Immutable manifest holds pre-execution identity; separate started/report/slot files hold observations.
Reject drift before execution. An interrupted runner with no report is unresolved, not fabricated
failure or success. Subjects and harnesses retain their existing process and receipt validation.

Count planned, started, process termination/success, subject receipt, harness invocation/receipt,
evaluator completion, validity, and usage-known separately. File presence is only retained-artifact
evidence: a failed subject with files cannot authorize harness execution or receive a score.

The final valid-solution rate uses the planned denominator 2 only after both slots are resolved.
Evaluated invalid attempts have observed validity but are separate from unscored failures. Quality
summaries use completed valid evaluations only, with explicit n; absent or failure-placeholder values
remain null. Keep any raw accepted evaluator receipt separate from conditional summary statistics.

No matched baseline is supplied and no breakthrough/delta or statistical superiority is calculated.
The previous 0/2 result may be described with its configuration, never relabeled or pooled into this
new denominator. Usage or returned model identity must come from accepted subject receipts; probe
results and incomplete event counts cannot supply missing failure usage.

## Acceptance

1. Manifest and frozen inputs precede both started markers; no overwritten or reused attempt directory.
2. Pre/post-run source/input/receipt/diagnostic checks and slot aggregation are reproducible offline.
3. Both slots have terminal observations or remain explicitly unresolved; no outcome-dependent retries.
4. Report real outcomes and limitations in HANDOFF, preserving all historical evidence.

## Scope

Protocol and ignored local experiment scripts only. No product changes, WebAgent execution, new
company data requests, provider configuration changes, raw process logs, or credential persistence.
