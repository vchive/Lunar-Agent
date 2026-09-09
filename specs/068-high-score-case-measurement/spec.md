# Feature 068: High-Score Case Measurement

**Created**: 2026-09-09  
**Branch**: main  
**Status**: Complete

## Objective

Measure whether the current Lunar solver produces valid solutions on cases with consistently high
scores in the user's existing platform records. Previous supply_chain_inventory failures stopped
before scoring at 200000 tokens; they cannot establish inability to solve these different cases.
Change the measurement protocol before observing any new Lunar outcome, without product changes.

## Selection and comparator

Use the latest completed, selected GLM-5.2 normal experiment in the downloaded leaderboard:
fmexp-ac8297cd-53a6-4c1f-aa06-49751bc6ad05, famou-bench 1.10.6. Its recorded adapter is
AgentServer/OpenCode, workload webagent-agentserver, release
agentserver-online-v1-304d586a-20260828t121038z. Call this the platform WebAgent/AgentServer
(OpenCode) record; do not relabel it as an adapter=webagent export or a verified v2.5 source commit.
The GLM-5.1 experiment search returned no case-level record, so this new campaign explicitly uses
the recorded GLM-5.2 model. Previous GLM-5.1 campaigns remain unchanged and excluded.

Select cases with all three results validity=1 and conclusion-eligible; rank by mean overall score
descending and take the first two, breaking ties by case key. Freeze:

| Case | Recorded scores | Mean |
| --- | --- | ---: |
| sheet_metal_nesting | 0.996101, 0.999999, 0.999999 | 0.9986996667 |
| china_post_pickup_optimization | 1.0164, 0.7973, 0.9938 | 0.9358333333 |

Keep all three observations, including the score above one. Read-only baseline selection must not
expose old candidates, private evaluator content or historical model traces to the subject.

## Frozen execution protocol

- Exactly two fresh normal slots: one per selected case, each launched once, concurrency 2, one
  authorized CC Switch configuration snapshot. No connection probe, retry, replacement or extra slot.
- Current product source unchanged from 01c541e. Freeze source/input/scaffold SHA before dispatch,
  and commit the manifest anchor before the first model request.
- Solver GLM-5.2, 200 tool calls, 5400 seconds, 8000000 cumulative normalized tokens per subject;
  no assumed prices or monetary cost ceiling. Same prompt/tools as Feature 063/064 and diagnostics
  from 066. These explicit bounds replace 900s/40/200000 for this new campaign only.
- Recorded solve times are 1978–4433 seconds and tool calls 59–124. Historical totals reach about
  6.12 million with cache reads included. New bounds cover that observed scale with headroom;
  telemetry is not proof of the original configured limits, and token accounting differs.
- Reconstruct exact official 1.10.6 case content/public projections with the publication-period
  FM-Eval SDK and frozen publication mapping. Reject any digest mismatch. Supply only declared
  public files/request to a fresh subject; freeze separate private case trees for the harness.
- Only a successful, validated subject receipt and unchanged public projection permit the exact
  private extractor/evaluator. Extractor GLM-5.2, claude-agent-sdk 0.1.81; each harness phase at most
  1800 seconds. Outer process limits: subject 5430s, harness 3630s, slot 9300s.
- Use a separate harness environment with the previous exact dependency pins plus pandas 2.3.3
  and its frozen dependencies, required by the sheet_metal_nesting evaluator. The old harness
  environment is unchanged. Subject command environment remains the existing minimal PATH.

## Evidence and acceptance

1. Verify official identities, public/private hashes, dependencies, budgets, one-start guards and
   pre-execution registration offline. Keep credentials in subprocess environments only.
2. Run both Lunar subjects to terminal outcomes, then permitted harness stages. Retain every failure
   and unresolved outcome; retained files alone neither establish validity nor permit scoring.
3. Validate model/profile/source/request/receipt identities and strict v1/v2 diagnostics. Partial
   failure snapshots stay separate from complete usage. Unknown scores and costs remain null.
4. Report each case separately: process/extraction/evaluation completion, validity=1, score and
   descriptive difference from its recorded mean/range if scored. Do not average quality across
   cases or infer success probability from one attempt. Planned completion denominator is two.
   Validity=0 and partial validity are evaluated outcomes, not missing scores.
5. Audit inputs, historical and observed evidence, publish actual results and update HANDOFF.

## Scope and limitations

No product changes, WebAgent execution, platform mutation, private-solution transfer, manual algorithm
writing or historical backfill. Provider, tools, environment, cache accounting, concurrency and unknown
original configured limits differ. A high historical score motivates case selection but does not
guarantee Lunar success or establish a controlled framework comparison.
