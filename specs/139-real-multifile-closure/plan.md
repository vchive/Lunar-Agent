# Implementation Plan: Real automatic multi-file closure acceptance

**Date**: 2026-09-19
**Spec**: [spec.md](spec.md)
**Status**: Offline implementation, retained integration, and independent review complete
(2026-09-20); T007 full regression passed; registration and real attempt pending at this checkpoint

## Scope

This is a measurement and preregistration feature, not a product feature. The final product pin
must include the separately implemented Features 140 and 141 and is frozen before registration.
The implementation work is limited to a campaign-local measurement harness,
offline tests, manifest/report tooling, and postrun audit documentation. No provider call is
allowed until the manifest is pushed and the unique slot passes preflight.

## Technical approach

1. Copy the reviewed local acceptance harness into this new campaign directory and replace every
   historical registration, root, and evidence reference with new opaque IDs. Keep the task/input,
   supported evaluator, eight holdouts, and privacy rules explicit.
2. Add offline registration tests that reject dirty/unpushed pins, changed product or provider
   identity, reused roots, duplicate attempts, request 21, token/wall-clock overrun, and candidate
   budgets outside the frozen manifest. These tests must use mock runtimes and synthetic ledgers.
3. Add stage-receipt fixtures for preparation failure, candidate budget exhaustion, malformed/empty
   candidates, execution failure, evaluator invalidity, selection drift, interrupted delivery,
   cleanup uncertainty, and one complete success. Assert that later evidence never upgrades an
   earlier missing or conflicting receipt.
4. Add a read-only analysis/audit that verifies the six-stage chain, candidate/execution/evaluation
   identity, source/input/output hashes, parent delivery digest, one-slot accounting, safe public
   projection, and unchanged historical inventories. Wire native generation receipt verification
   into the actual retained-evidence `summarize()` path; an in-memory campaign audit alone is not
   this integration.
5. Freeze the final manifest and product commit, run full offline validation, commit and push the
   preregistration, verify `HEAD == origin/main`, then launch exactly one real attempt. Do not make
   implementation changes after launch.
6. Summarize once, independently audit the retained evidence, update the handoff/readiness/roadmap
   only after the outcome is known, and push the report. A failed or unknown attempt remains the
   sole denominator.

## Campaign-local touch points

The campaign-local modules are implemented, with direct native-entrypoint integration and
independent review and T007 full regression complete. Preregistration remains a separate gate.
Scope remains this feature's subtree, not shared product modules:

- implemented modules: `measurement/case.py`, `campaign.py`, `native_receipts.py`,
  `native_trace.py`, `retained_chain.py`, `registration.py`, `runner.py`, `worker.py`,
  `observation.py`, `supervision.py`, and `analysis.py`;
- `measurement/manifest.json`, created only when the preregistration gates have passed;
- focused `tests/test_measurement139_*.py` fixtures for registration, stage receipts, budgets,
  redaction, and read-only audit;
- `postrun/results.json`, `postrun/evidence.json`, `postrun/report.md`, and `postrun/audit.json`
  created only after the sole attempt.

If a product defect blocks a required contract, stop before registration and open a separate product
SDD. Do not patch shared runtime code inside this measurement feature or alter Feature 134.

## Retained-evidence integration closure (2026-09-20)

The B001–B011 corrections, request/stage timing checks, registration, observer, worker,
supervision, native trace, and retained chain passed offline integration and independent review.
The final full current/frozen-history regression passed with overall exit 0. The following original
integration requirements are retained as acceptance contracts; all three are now implemented
and directly validated offline:

- The retained summary must load canonical native generation receipts from the retained Store,
  verify them against the actual candidate bundle and registered authority, and use them in its
  completed-candidate and primary/joint gates. Exercise this through the actual summarization
  entrypoint with temporary native Store/workspace material. Delete, fail, or alter a receipt and
  confirm later execution/score/delivery cannot restore success. Verify request and stage links
  and retained file integrity in the same path.
- Replace the worker's binary stdout target with exclusive UTF-8 text capture appropriate for
  ordinary CLI printing. Directly invoke `worker.main()` with a synthetic native CLI that prints
  JSON; inspect the capture, native exit, worker terminal record, and no-clobber failure behavior.
- Keep `holdout_gate` in the worker/summary stage contract. A valid preparation with invalid or
  absent primary/output/source evidence must perform zero holdouts, remain a bounded failed
  attempt, and summarize without treating the stage as unknown or the preparation as delivery.

These tests use repository-owned synthetic candidates/evaluators and substitute HTTP responses
while exercising the real native CLI, runtime, Store, receipts, execution, evaluation and delivery.
They do not bypass the receipt verification or summary gates. The successful retained fixture has
5 requests, 2 completed candidates and 8 matching holdouts. Negative cases cover evidence gaps,
budget/timing drift, unknown states and failure reporting. Inspection remains read-only and does
not call the provider or execute candidates/evaluators; no historical generated source is used.
See [validation.md](validation.md) and [preregistration-audit.md](preregistration-audit.md) for the
completed offline checks and full regression counts. At this offline implementation checkpoint
no real registration or campaign has been created or launched. Subsequent registration status is
determined by `measurement/manifest.json` and read-only launch checks. T008 verification evidence
is kept under ignored local paths, without changing the frozen plan after registration.

## Data and identity model

Every stage receipt contains `schema_version`, `registration_id`, `campaign_id`, `attempt_id`,
`stage`, `outcome`, `started_at`, `finished_at` or explicit pending/unknown state, and bounded
artifact digests. Generation adds `candidate_id` and `budget_id`; execution adds `execution_id`;
scoring adds `evaluation_id`; selection and delivery bind all prior IDs. Request rows include a
request index and request digest; transport status is projected only through Feature 138's safe
binding rules.

The public summary is derived from private evidence and cannot be used to authorize a new request.
The controller/Store remains the state authority; worker claims, model text, producer scores, and
filesystem presence alone are insufficient.

## Budget and launch decisions

The proposed fixed budgets are in the spec. Any change to request timeout, preparation wall time,
campaign wall time, request count, token threshold, candidate steps, population/rounds, holdout
count, or source contract creates a new registration and requires a fresh push. There is no hidden
retry or budget borrowing from a later stage.

The run must use the current native automatic path. External OpenEvolve/Shinka producers,
detached workers, remote backends, and WebAgent comparison are deferred to separate work.

## Verification strategy

Before launch, run focused offline fixtures, the current full regression, the frozen historical
stage, Ruff, compileall, Specify checks, diff checks, and independent Feature 131/134 file/SHA
inventories. The launch preflight must be model-free and report the exact manifest hash.
The focused fixtures include direct worker entrypoint and retained-evidence summarization
integration, rather than only separately tested helpers or in-memory receipt chains.

After launch, run no test that calls the provider or generated source. Summarization and audit read
retained evidence only; a temporary read-only SQLite copy is allowed for inspection. The report must
state request counts, known/unknown usage, stage outcomes, primary/joint counts, cleanup, and all
limitations without converting unknown into failure or success by inference.

## Alternatives rejected

- Appending another attempt to Feature 134 would destroy its one-slot denominator and historical
  interpretation.
- Declaring preparation or holdout success as product success would leave the untested execution,
  scoring, selection, and delivery path unverified.
- Allowing a candidate's claimed score or a producer-provided result to select itself would violate
  independent evaluation authority.
- Increasing budgets after launch, automatic retries, or response repair would invalidate the
  registration and hide the true outcome.
- Comparing with WebAgent in this run would mix historical conditions and answer a different question.

## Complexity tracking

No shared product change, dependency, migration, remote service, external producer, or constitutional
exception is planned. The only irreversible action is the separately authorized sole provider run
after the concrete manifest and preflight evidence are reviewable.
