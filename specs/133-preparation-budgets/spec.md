# Feature 133: Separate evaluator preparation budgets

## Problem

Automatic multi-file solving used one `--timeout` value for candidate generation/evaluation and
the compiler/auditor requests that prepare the frozen evaluator. Users also lacked a bounded
total wait for both preparation requests plus local preflight and publication. Feature 132's
observed request timeout is useful evidence, but it is not itself a durable preparation policy.

## Scope

Add two preparation controls to native `solve --evolve --multi-file` and its `resume`/`answer`
continuations:

* `--evaluator-preparation-timeout SECONDS` caps each evaluator compiler or auditor model request.
  It is a request policy, not a promise about provider-side completion.
* `--evaluator-preparation-wall-timeout SECONDS` bounds one preparation attempt using a single
  monotonic deadline. Timing starts immediately after the durable `bundle_preparation_started`
  event. It covers subsequent input/profile checks, compiler and auditor requests, local probes
  and preflight, bundle validation and publication checks, and ends before candidate generation.
  Waiting to acquire the preparation lock and checks preceding the durable start are outside
  this attempt budget.

Both values are finite numbers in `(0, 86400]`; the wall budget must be at least the request
budget. On a new compiled solve, an omitted request value resolves to candidate `--timeout`
(900 seconds by default), and an omitted wall value resolves to
`min(86400, 2 * request_timeout + 60)`. Both resolved values are persisted. A wall budget equal
to the request budget is valid, but leaves less time for the second request and local work.

`--timeout` continues to control candidate generation, candidate execution and evaluator
execution. The frozen `bundle-profile.json` retains that execution timeout. Preparation policy
must never enter the profile schema, its digest or the evaluator execution identity.

## Durable policy and compatibility

For `bundle_mode=compiled`, the existing `evolution_requested` payload gains
`evaluator_preparation_timeout` and `evaluator_preparation_wall_timeout`. Their companion
`*_source` fields record `explicit` or `default`; `timeout_source` records the candidate timeout
origin. These are controller settings containing no credentials, prompts or response data.

`resume` and `answer` restore the parent policy. Explicit continuation settings must match it;
they cannot rewrite a historical event or extend an in-progress attempt. An explicit recovery
starts a new preparation attempt with a fresh deadline under the same persisted policy.

Old compiled events missing the request field fall back to their stored `timeout`. Those
missing the wall field retain a legacy-unbounded total budget. A finite wall value supplied on
continuation cannot replace legacy-unbounded policy. An explicit request value matching the
legacy fallback is allowed; a mismatch is rejected. Values stored without an origin field are
reported as `persisted`, since their explicit/default provenance cannot be reconstructed.

Prepared profiles remain byte-compatible and compare only their existing execution timeout.
Successful prepared runs remain idempotent and make no new model requests.

## Enforcement and failure semantics

The controller checks one monotonic deadline before and after expensive preparation phases and
before publishing a prepared profile. Compiler/auditor requests receive the smaller of their
request budget and remaining wall time. Local preflight processes receive the smaller of the
existing execution timeout and remaining wall time. Existing runtime profile caps can further
reduce request limits. Preparation does not reset the deadline between stages.

A non-positive remainder stops the attempt. After observed expiry, preparation cannot publish
the successful prepared event or create a child/candidate. Local synchronous work is checked at
phase boundaries: an already-started bounded file write or artifact registration can finish
before the next guard observes expiry. It can leave verified local materials for explicit
recovery, but those materials alone are not successful preparation authority. Recovery validates
them before reuse. This feature adds no rollback or asynchronous interruption of arbitrary
filesystem/database operations. Deadline enforcement does not claim a remote provider stopped.

Feature 132 typed request observations preserve the effective timeout and evidence from a
request that actually started. Wall exhaustion has a bounded preparation-budget diagnostic;
it must not include exception text, prompts, responses or inferred provider behavior. Cancellation,
terminal parent state, input drift and integrity failures retain their existing precedence.

The Feature 116 recovery contract remains in force: preparation failure leaves the parent
persisted as `running`, while its effective outward status is failed. Only explicit continuation
can retry. There is no automatic retry, response repair, request replacement or deadline extension.

JSON and text status show candidate timeout, preparation request timeout and preparation wall
timeout separately, with explicit/default/persisted/legacy origins as applicable. Legacy wall
policy is visibly unbounded. Status may expose bounded exhaustion evidence, without provider
secrets or unverified work claims.

## Acceptance

1. Both flags are accepted only for native compiled multi-file evolution. Bounds, ordering and
   incompatible modes are rejected before creating run state, events, artifacts or model calls.
2. Fresh compiled handoffs persist both resolved values and their origins. `resume`/`answer`
   restore policy and reject explicit mismatches before preparation or mutation. Old handoffs
   retain request fallback and legacy-unbounded wall behavior.
3. Candidate generation/execution and frozen evaluator execution retain `--timeout`. Preparation
   settings never change frozen profile bytes, its digest, evaluator identity or prepared reuse.
4. Both model requests and local preflight use the remaining attempt budget. Observed expiry
   before a request, between stages or before publication cannot produce a successful prepared
   event or child. Materials from an already-started bounded local operation require validation
   on explicit recovery and do not by themselves authorize candidate execution.
5. Request diagnostics retain actual bounded request evidence. Wall failure is typed and
   recoverable only through explicit continuation, which starts a new attempt using the same
   parent policy. No provider-side cancellation or completion is inferred.
6. Offline tests cover defaults, validation, routing, remaining-time clipping, deterministic
   exhaustion, persistence, origins, continuation mismatches, legacy events, explicit recovery,
   idempotency and profile byte stability. No real model call, frozen measurement rewrite or
   execution of historical captured source is part of this feature.

## Non-goals

Active-process cancellation orchestration, provider token/cost caps, detached execution,
external producer support and database migration remain outside this feature. Separate budgets
do not establish evaluator quality, fewer provider timeouts, WebAgent parity or real multi-file
end-to-end success.
