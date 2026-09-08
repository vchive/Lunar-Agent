# Feature 059: Model Profile Execution Boundaries

## Goal

Make the existing model policy apply consistently to solver sessions and isolated compiler/audit
turns. A missing provider usage record must not silently disable a requested token/cost ceiling,
and a caller must not loosen a profile timeout. Reuse the owner's existing historical data; this
work requires no WebAgent run, platform query, new export, or real Lunar trial.

## Contract

- With a profile, `run()` and `run_isolated()` use the smaller of the explicit positive finite
  timeout and the profile timeout. Without an explicit timeout, use the profile timeout.
  Invalid explicit timeouts fail before a model call. No-profile behavior remains compatible.
- Each invocation owns a fresh `UsageLedger`. Isolated calls neither inherit nor modify normal
  session usage, transcripts, memory, tools or history.
- A profile with a token or cost ceiling requires normalized usage on every returned turn.
  Missing or malformed usage fails before tool actions, transcript append or successful result.
  Profiles without spend ceilings permit absent usage and do not invent usage or cost.
- Record valid samples through the existing ledger. Above-ceiling samples remain rejected without
  mutating accepted totals. A final text response exactly at a ceiling may succeed. A response
  requesting tools at a reached ceiling fails before those tools or any subsequent model call.
- Profile-enabled isolated calls validate usage and limits before accepting text. Success exposes
  the profile name, observed model identity and complete usage/cost as ordinary credential-free
  runtime metadata, while retaining `mode=agent-loop-isolated` and `session_history=false`.
- Model calls receive a remaining timeout. Profile-enabled paths also check the deadline after
  a model returns and before/after tool execution, so an overdue response does not become a
  successful result or cause a further action. This is cooperative deadline enforcement: running
  model/tool implementations still own cancellation of an in-flight operation.

## Acceptance criteria

1. Both paths cap longer explicit timeouts, honor tighter ones, reject invalid values and stop
   accepting responses after the configured deadline.
2. Missing/malformed usage with ceilings fails; no tool file, success transcript or result is
   accepted from the rejected turn. No-profile and unbounded-profile missing usage remain valid.
3. Token/cost overshoot and exact-ceiling tool continuations are rejected. An exact-ceiling final
   result succeeds and reports its actual accepted usage.
4. Alternating normal and isolated invocations have independent usage and preserve isolated
   tool/history/memory boundaries. Subject adapter failures produce no completed receipt.
5. Focused and full tests, lint, compileall, build, Specify prerequisites and diff checks pass.

## Limits

Usage becomes known after a provider response. These checks prevent accepting or continuing an
over-budget response; they do not undo billed usage or guarantee an in-flight request cannot
overshoot. Caps are per invocation (one fresh subject round), not an aggregate trial budget.
This feature adds no provider-specific output-token parameters, pricing discovery, global spend
ledger, budget changes, score authority changes, or new benchmark results.
