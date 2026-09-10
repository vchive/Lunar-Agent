# Plan: Master Planning Role Fixed Measurement

## Design decisions

Use the 076 campaign wrappers and native `EffectTrialRunner`/exact harness seam through small,
explicit bindings. Change only registration metadata, slot preparation and postrun projections;
do not fork the subject adapter or copy evaluator logic. The manifest must pin the integrated 077
source and every executable helper before launch.

Keep the protocol deliberately matched to 076. Reusing its cases, model, budgets and wave makes
the observed stage counts comparable as context, while the two campaigns remain independent
denominators. The comparison is descriptive only because attempts are not paired controls and
provider conditions can differ.

## Execution sequence

1. Write the registration, source/input/helper inventory and acceptance rules; run an independent
   preaudit and guarded dry-run with provider access blocked.
2. Commit and push the registration before any start marker. Verify that both slot workspaces are
   fresh, exclusive and free of result artifacts.
3. Launch exactly once and observe both slots through terminal state. Use read-only progress polling;
   do not run a second launch or repair a failed slot.
4. After termination, run the independent final audit, native summary reconciliation and scoped
   process check. Render a report that keeps unresolved fields `null` and records visibility limits.
5. Re-read the evidence hashes and update the SDD task status and `HANDOFF.md` only after sealing.

## Required report fields

Per slot: case/arm identity, subject process state, Master plan accepted, Build entered, checkpoint
and resume flags, candidate metadata-only observations, subject receipt state, harness/evaluator
state, validity, quality/overall scores, bounded diagnostic projection, terminal outcome and SHA
links. Aggregate: planned/started/terminal counts, plan and Build conditional rates, valid-solution
rate, scored-valid sample count, and explicit unknown usage/cost/duration fields.

## Failure handling

An unstarted or interrupted slot is unresolved until its durable terminal marker is independently
verified. A failed slot is retained as observed and never replaced. Candidate files are inspected
only for metadata and are never executed or sent to the harness after subject failure. Any source,
manifest, input or helper drift aborts prelaunch without attempting a model call.

## Deferred work

Provider-failure subtype telemetry (for example transport versus malformed response) is intentionally
out of scope. If still needed after this measurement, specify it as a separate feature with its own
offline contract and a new registration; do not alter this campaign after launch.
