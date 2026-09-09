# Plan: High-Score Case Measurement

1. Independently audit recorded experiment identity and deterministic case selection.
2. Recompute case archives with SDK b17023d3f849f3312f8fc79f366b0c18495ee726 in a separate directory,
   freeze public/private trees and validate each TrialSuite. Do not switch external repo branches.
3. Adapt local runners/summarizer for two cases and explicit budgets. Validate the model, steps and
   nested timeouts; retain success/failure authority checks.
4. Prepare fresh attempts, refresh readiness without model calls, freeze source, baseline, inputs,
   history and scripts. Verify offline error boundaries, independently review and commit/push anchor.
5. Dispatch each slot once and wait for outcomes, using metadata-only progress monitoring. Keep raw
   model/tool output and credentials out of evidence; never alter an active experiment.
6. Validate receipts/public projections, summarize per-case comparisons and failure diagnostics,
   independently audit, update this feature/HANDOFF and commit/push the completed record.

## Data model, contracts and recovery

Manifest: common solver identity, per-slot case/suite/private harness identities, selected baseline
and its source digests. Separate started/report markers per slot and started/terminated campaign
markers leave missing reports unresolved without relaunch. Subject success alone is not validity.
Per-case descriptive comparisons remain separate from automated promotion, which stays disabled.
Private paths are launcher settings, never subject request/prompt fields. Only solver credentials
reach the subject, only extractor credentials reach its harness. No migrations or new product
dependencies. A separate local harness venv adds pandas 2.3.3 for the exact sheet evaluator, retaining
all old package pins; freeze its requirements and verify all four case script imports offline.

## Decisions and alternatives

Use one attempt per each of the two highest mean cases satisfying three valid historical results,
instead of adding more supply_chain_inventory slots. Match the recorded GLM-5.2 model explicitly.
Increase bounded resources using measured baseline scales instead of preserving an unrelated 15-minute
pilot limit. Defer context changes so this experiment measures the current implementation. These
are case-selected exploratory measurements, not causal proof or whole-suite performance estimates.

## Quickstart and verification

```bash
.venv/bin/python .lunar/real-eval-glm-5.2-high-score-20260909/run_campaign.py --check-only
.venv/bin/python .lunar/real-eval-glm-5.2-high-score-20260909/check_summary.py
# After registration, exactly once; never rerun a started campaign:
.venv/bin/python .lunar/real-eval-glm-5.2-high-score-20260909/run_campaign.py
# After termination:
.venv/bin/python .lunar/real-eval-glm-5.2-high-score-20260909/summarize.py --check-only
```

Product source already passed 726 tests under Feature 066. Verify changed scaffolding, manifest
guards, partial/unknown usage, per-case aggregation and receipt score domains locally, plus Specify
and diff checks. No product edits during the measurement; no constitution exception is required.
