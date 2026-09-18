# Implementation Plan: Real automatic multi-file closure acceptance

**Date**: 2026-09-19
**Spec**: [spec.md](spec.md)

## Scope

This is a measurement and preregistration feature, not a product feature. Product code is frozen
after Feature 138. The implementation work is limited to a campaign-local measurement harness,
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
   projection, and unchanged historical inventories.
5. Freeze the final manifest and product commit, run full offline validation, commit and push the
   preregistration, verify `HEAD == origin/main`, then launch exactly one real attempt. Do not make
   implementation changes after launch.
6. Summarize once, independently audit the retained evidence, update the handoff/readiness/roadmap
   only after the outcome is known, and push the report. A failed or unknown attempt remains the
   sole denominator.

## Campaign-local touch points

Expected files are under this feature's future campaign subtree, not shared product modules:

- `measurement/manifest.json`, `case.py`, `campaign.py`, `worker.py`, `observation.py`,
  `supervision.py`, and `analysis.py`;
- focused `tests/test_measurement139_*.py` fixtures for registration, stage receipts, budgets,
  redaction, and read-only audit;
- `postrun/results.json`, `postrun/evidence.json`, `postrun/report.md`, and `postrun/audit.json`
  created only after the sole attempt.

If a product defect blocks a required contract, stop before registration and open a separate product
SDD. Do not patch shared runtime code inside this measurement feature or alter Feature 134.

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
