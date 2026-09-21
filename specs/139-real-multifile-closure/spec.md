# Feature Specification: Real automatic multi-file closure acceptance

**Created**: 2026-09-19
**Status**: Offline implementation and T007 full regression complete. The user authorized the
sole real attempt with a 50-minute wall limit on 2026-09-20; fresh registration and launch preflight
are required after superseding the unused 40-minute registration.
**Input**: Feature 134's preparation-only outcome, Feature 136/137 budget contracts, and
Feature 138's status/recovery projection

## Problem

The current product has a locally verified multi-file pipeline and a real Feature 134 run that
completed preparation and all eight holdouts, but produced no completed candidate. That run
therefore never exercised candidate execution, independent scoring, selection, or parent delivery.
This feature defines one fresh, fixed-condition real run whose only product claim is an observed
end-to-end closure. It does not reopen Feature 134 or compare with WebAgent.

## User scenarios

### US1 - Run one new automatic multi-file attempt (P1)

Given a committed product, a newly pushed registration, and an unused campaign root, the system
performs one bounded attempt through preparation, candidate generation, candidate execution,
independent scoring, selection, and parent delivery. Every admitted request belongs to the same
registration and attempt.

**Independent test**: Inspect the retained registration, stage receipts, request ledger, execution
artifact, evaluator report, selection event, delivery package, and cleanup record without rerunning
the provider or generated source.

### US2 - Count success only after a completed candidate is delivered (P1)

At least one parser-accepted `completed` candidate must have a durable generation receipt. That
candidate must execute successfully in an isolated workspace, pass the independent evaluator,
be named by a verified selection receipt, and be delivered to the parent with unchanged source,
input, output, and evidence bindings.

**Independent test**: Recompute all stage digests and identity links from retained artifacts. A
preparation success, holdout success, self-reported score, or partial source tree alone cannot
produce primary or joint success.

### US3 - Preserve one honest failure denominator (P1)

The run is once-only. A timeout, cancellation, malformed response, missing receipt, cleanup
uncertainty, or provider failure is reported as the outcome of the one attempt. No retry, resume,
replacement, repair, fallback, or second candidate slot is admitted.

**Independent test**: Confirm one `registration_id`, one `campaign_id`, one `attempt_id`, one
campaign root, and a complete request ledger with no pending or silently discarded exchange.

### US4 - Inspect safely and keep historical evidence immutable (P2)

The public report exposes bounded metadata, stage outcomes, scores/check results, and hashes. It
does not expose prompts, provider response text, credentials, endpoint values, generated source,
or arbitrary exception text. Feature 131/134 files and WebAgent history remain unchanged.

## Authorized pre-admission revision (2026-09-20)

The user explicitly authorized the real acceptance attempt and requested changing its total wall
limit from 40 to 50 minutes before launch. The original 40-minute manifest is retained byte for
byte at [measurement/registrations/unlaunched-40min.json](../../docs/history-archive.md)
(30,853 bytes; SHA-256 `26fb2d8b447fd5f5b848016a55e041c5f273903f610d4b7c39c0bf10613f19f9`).
Its root `.lunar/real-automatic-multifile-closure-20260920` had not been created; no admission,
attempt, worker, or provider request occurred. Its status is **superseded before admission**,
not a failed run, retry, resumed attempt, or replacement of an executed slot.

The active registration uses these new identities:

- `registration_id=registration-139-real-multifile-closure-50min`
- `campaign_id=campaign-139-real-multifile-closure-20260920-50min`
- `campaign_root=.lunar/real-automatic-multifile-closure-20260920-50min`
- `attempt_id=attempt-001`, with one attempt total after admission.

Only the whole-attempt wall budget changes to 3,000 seconds. Product pin, input/task bytes,
provider/model identity, population, ordinary/preparation request limits, preparation wall limit,
request/token/step limits, holdouts, and all success/failure rules remain unchanged. The old
manifest is included in the new measurement inventory and prior-identity/root checks; none of its
identities or root may be reused. The new manifest must be freshly registered, committed/pushed,
and verified before the single authorized launch. Failure after that admission remains `0/1`
with no retry, resume, repair, or replacement. Feature 131/134 evidence remains untouched.

## Fixed registration and run-slot contract

- A new opaque `registration_id`, `campaign_id`, and `attempt_id=attempt-001` are created for this
  feature. Their concrete values are recorded in a manifest before launch; no value from Feature
  131 or 134 may be reused.
- The manifest pins the product commit including Features 140 and 141, all measurement/spec files,
  task and input bytes, provider/model identity, runtime options, evaluator profile, budgets, and
  the unique campaign root. Secrets, prompts, response bodies, and endpoint URLs are excluded.
- Launch requires a clean worktree, `HEAD == origin/main`, a fresh unused root, preflight identity
  checks, and a pushed manifest. A changed pin or reused root fails closed before any provider
  request.
- Exactly one attempt is allowed. Any process resume, request retry, response repair, fallback
  candidate, replacement attempt, or post-slot provider request is out of scope and invalidates
  the measurement.

## Stage contract

The controller must durably record the following ordered stages. Each receipt binds the previous
stage's identity and includes a stable schema version, stage outcome, timestamps, bounded budget
metadata, and SHA-256 digests of private artifacts.

1. **Preparation**: compile and independently audit the evaluator/profile, validate the task and
   input, and freeze the declared holdouts. A failed or unknown preparation stops model admission.
2. **Candidate generation**: use the automatic native population path with a small fixed search
   configuration. A candidate counts only when the native candidate parser accepts a non-empty
   source bundle and the completion diagnostic is `completed`; a tool-budget exhaustion, timeout,
   malformed response, empty response, or tool failure produces no candidate.
3. **Candidate execution**: stage the complete source bundle and registered input in an isolated
   workspace, run the declared entrypoint under the registered limits, and retain an execution
   receipt with process exit, output digest, and cleanup observation. Generated source is never
   trusted as its own evidence.
4. **Independent scoring**: run the prepared evaluator against the registered input and the
   execution snapshot. The evaluator, not the candidate or producer, owns validity and score; the
   report must contain typed checks and a bound candidate/execution identity.
5. **Selection**: record one verified selection event that names an independently scored candidate,
   binds its generation/execution/evaluation digests, and uses the native validity-first ranking.
   A candidate's self-reported score cannot influence this event.
6. **Parent delivery**: copy the selected, verified source, output, input, contract, and
   evaluation evidence into the parent publication package. Inspect the package read-only and
   record its digest, reciprocal links, and delivery receipt before marking the parent successful.

Missing, duplicate, out-of-order, conflicting, or unbound receipts are stage failure or unknown;
they never get treated as success by inference from a later stage.

## Budgets and bounded search

The following values are proposed registration defaults and must be frozen in the manifest before
launch. If preflight cannot prove that the implementation honors a value, the run is not started.

- Ordinary/provider request timeout: **600 seconds**.
- Preparation request timeout: **900 seconds**.
- Preparation wall-clock limit: **1,860 seconds**.
- Whole-attempt wall-clock limit: **3,000 seconds (50 minutes)**, shared across every stage.
- Maximum provider requests: **20**; stop admission before request 21.
- Observed-token stop threshold: **160,000**. This is local accounting, not a provider token cap.
- Candidate generation: one island, one population member, one offspring/round, one round, and
  **12 tool steps per candidate request**. The candidate budget is fixed per request; no extension,
  prefix execution, retry, or implicit repair is allowed.
- Holdouts: the same eight predeclared deterministic holdouts used by the supported evaluator, with
  at most **5 seconds per holdout** after a verified candidate is selected.
- Artifact and source limits remain those of the pinned product `BudgetSpec`; no feature-specific
  relaxation or database migration is introduced.

The candidate step ceiling is deliberately higher than Feature 134's registered four-step ceiling,
but remains small and auditable. It is not evidence that a model will complete generation.

## Success and failure rules

The report has exactly one denominator for this feature: `1` attempt. It reports separate bounded
counts for preparation, completed candidates, execution, independent scoring, selection, delivery,
and holdouts, plus `primary_success` and `joint_success` as `0/1` or `1/1`.

- `preparation_success=1/1` requires a verified evaluator/profile and holdout contract.
- `primary_success=1/1` requires `completed_candidate_count >= 1`, a successful bound execution,
  an independent valid score, a verified selection receipt, and a verified parent delivery.
- `joint_success=1/1` requires primary success, all eight holdouts matching their registered
  expected outputs, clean native/process exit, and verified cleanup. It also requires no unresolved
  pending or unknown stage receipt.
- If any primary prerequisite is absent or unknown, primary and joint remain `0/1`; no partial
  source, preparation result, holdout result, or evaluator self-claim can promote them.
- Known usage is summed only from completed, bound exchanges. Missing usage, HTTP status, or cleanup
  evidence remains unknown/null rather than zero or successful.

## Evidence and privacy

Retain private campaign evidence under the fresh campaign root: manifest, request ledger, stage
receipts, evaluator/profile artifacts, candidate source, execution snapshot, output, score report,
selection, delivery package, and cleanup observation. Public results contain only allow-listed
metadata, bounded status/reason codes, counts, outputs/check summaries where safe, and SHA-256
digests. No prompt, captured provider text, credential, URL, generated source, or arbitrary error
string crosses the public boundary.

The postrun report and independent audit are read-only over retained evidence. Summarization writes
new report/evidence inventories once and never calls a provider or executes generated source.

## Offline integration contract

The requirements below have passed direct offline entrypoint validation and independent review
as of 2026-09-20. The native CLI fixture uses substituted HTTP responses and retains 5 requests,
2 completed candidates, all 8 holdouts, and verified parent delivery. This validates the harness;
the completed T007 full regression does not replace concrete registration, launch preflight, or
the real attempt. Current evidence and review scope are recorded in [validation.md](validation.md)
and [preregistration-audit.md](preregistration-audit.md).

Later registration status is determined by `measurement/manifest.json` and read-only launch checks,
with T008 verification evidence kept under ignored local paths. This specification records the
offline checkpoint and does not require amendment after its registration freeze.

The campaign's actual `worker.main()` and `runner.summarize()` / `analysis.summarize()` entrypoints
must be verified with repository-owned synthetic data before registration. Passing an in-memory
`ClosureCampaign` fixture or testing a receipt mapper in isolation does not satisfy this contract.

1. Retained Store generation events must enter the actual summary through the native receipt
   verifier. Parser completion, event/run/task/budget/candidate identity, the registered tool-step
   ceiling, and the retained source-bundle digest must agree. A delivery package or a later score
   cannot substitute for a missing, failed, malformed, conflicting, or unbound generation event.
   Such evidence cannot increment completed-candidate counts or yield primary/joint success.
2. The actual summary must verify the six stages from retained native evidence and cross-check
   their request, budget, source, input, execution, evaluation, selection, and delivery bindings.
   Repository-owned temporary Store/workspace fixtures must cover a valid complete chain and
   missing/tampered prerequisites. Inspection must preserve retained bytes, including SQLite/WAL,
   and must never call a provider or execute a candidate/evaluator.
3. `worker.main()` must capture the native CLI's ordinary text output as exclusive, UTF-8 JSON
   evidence. An offline invocation that prints text must not fail because stdout is a binary
   stream. Existing capture files must not be overwritten, and the native exit result and bounded
   worker terminal record must remain inspectable on both successful and failed paths.
4. `holdout_gate` is a recognized worker failure stage. If primary completion, valid output, or
   source evidence is absent, the worker must retain that stage and execute no holdout. The actual
   summary must accept and expose this bounded failure, preserve unknown fields, and keep primary
   and joint success at `0/1`; it must not crash on an unknown-stage check or infer completion from
   preparation alone.

## Boundaries and non-goals

- This is one newly registered real local automatic run; no provider request is made while writing
  or validating this SDD.
- Do not reopen, resume, append to, or rewrite Feature 131 or 134. Their registrations, results,
  reports, audits, evidence, and hashes remain frozen.
- Do not run WebAgent, compare WebAgent parity, claim a regression/improvement, or infer general
  model quality from eight holdouts.
- Do not add OpenEvolve/Shinka producer import, remote scheduling, detached restart semantics,
  global retry policy, stronger sandboxing, or a database migration here. Those require separate
  SDDs after this native automatic path is observed.
- A completed measurement may be an honest `0/1`; only `primary_success=1/1` and
  `joint_success=1/1` establish this feature's closure acceptance.

## Acceptance criteria

1. Offline fixtures prove registration immutability, stage ordering, one-slot accounting, budget
   propagation, candidate completion gating, identity binding, redaction, and failure denominator
   behavior before launch.
2. The pushed manifest and product pins are independently verified with no provider request.
3. The sole run retains preparation, candidate generation, execution, independent score, selection,
   parent delivery, cleanup, and request-ledger evidence, or records the exact first failed/unknown
   stage without fabricating later success.
4. Primary/joint success is `1/1` only when at least one completed candidate satisfies every stated
   stage gate; otherwise the result remains `0/1` with unknown fields preserved.
5. Historical Feature 131/134 and WebAgent files are byte/SHA unchanged, and the final audit does
   not rerun a provider or generated source.
6. Provider-free integration fixtures call the actual worker and summarization entrypoints and
   satisfy every offline integration requirement above. Their retained native receipt and
   holdout-gate negative cases pass before the final full/current and frozen-history regressions;
   no isolated mapper result is reported as retained-evidence integration completion.
