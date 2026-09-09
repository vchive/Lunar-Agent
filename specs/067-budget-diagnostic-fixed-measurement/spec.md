# Feature 067: Budget Diagnostic Fixed Measurement

**Created**: 2026-09-09
**Branch**: main
**Status**: Complete

## Objective

Obtain real observations with Feature 066's bounded budget diagnostics. This independent campaign
measures the current Lunar implementation on the existing supply_chain_inventory case; it does not
backfill prior failures, require a successful solution, or attribute performance changes to diagnostics.

## Frozen protocol

- Exactly two fresh normal-mode slots, each launched once with concurrency 2 and one authorized
  CC Switch environment snapshot. No connection probe, retries, replacement or third attempt.
- Source implementation: 01c541e714bc0d1c0ebebdb7a4dcb564c3a8dbe5. Freeze all product source and
  launcher/summarizer/input hashes before dispatch and commit registration before execution.
- Same glm-5.1, 40 tool calls, 900-second subject timeout and 200000 cumulative token ceiling.
  Same Feature 063/064 model-visible behavior and command cap; no new prices or cost ceiling.
- Reuse exact suite, public file ledger, profile, private case/harness and extractor glm-5.2 with
  claude-agent-sdk 0.1.81. Each subject receives only fresh public inputs and its request.
- Preserve Feature 062/065 and exploratory pilot as excluded history. Do not pool denominators.

## Evidence and acceptance

1. Newly checked local readiness, immutable manifest and two empty-of-results workspaces precede
   dispatch; reject any drift, stale marker or extra file before reading the launch configuration.
2. Keep all actual success/failure outcomes. Missing starts/reports remain unresolved; no relaunch.
   V1, absent, invalid or non-budget diagnostics are allowed outcomes, not grounds for replacement.
3. Validate v2 with Feature 066's strict parser and preserve its budget projection. Count available
   budget evidence and limit/state groups separately. accepted_usage/observed_usage remain partial;
   they never populate complete usage, cost, scores, receipts, harness authority or model identity.
4. Valid-solution rate uses the planned denominator 2 once both slots resolve. Conditional quality
   has explicit n and null when unscored. A retained candidate does not authorize scoring after failure.
5. Audit source/input/history/observation SHA links offline, report actual measurements and limits,
   and update HANDOFF without modifying prior manifests, outputs or source anchors.

## Scope and interpretation

No product changes, WebAgent runs, company data queries, model upgrades, provider settings changes
or secret/raw-log persistence. Only local measurement scaffolding and tracked SDD/handoff documents.
Two concurrent samples cannot establish framework superiority, a diagnostics performance effect,
provider fault, or the trigger of any historical failure. Only the new observations identify their
own typed budget limit where available; observed usage is not a provider invoice.
