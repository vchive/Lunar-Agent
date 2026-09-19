# Feature Specification: Real automatic multi-file closure acceptance

**Created**: 2026-09-19
**Status**: Offline harness in progress; preregistration audit has unresolved blockers
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
- Whole-attempt wall-clock limit: **2,400 seconds**, shared across every stage.
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
