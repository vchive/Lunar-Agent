# Plan

## Decisions

Implement the full Feature 133 scope: one independent compiler/auditor request timeout and one
monotonic total budget per evaluator preparation attempt. Preserve `--timeout` for candidate
generation/execution and frozen evaluator execution. New compiled solves resolve and persist
both preparation values; continuation reuses the parent policy.

Begin timing immediately after the durable `bundle_preparation_started` event, when an attempt
has an identity and can record a bounded failure. Lock acquisition and pre-start admission checks
remain outside the deadline. Every subsequent expensive phase checks it; model and subprocess
timeouts are capped by its remaining time. Check again before publishing the prepared profile.
Synchronous local operations remain subject to boundary checks rather than a new cancellation
mechanism. An already-started bounded write or artifact registration can finish before a guard
observes expiry, leaving local material for validated explicit recovery. Its presence does not
replace the successful prepared event or authorize child creation; no rollback is introduced.

## Alternatives

Increasing the shared `--timeout` would also change candidate/evaluator execution authority.
Adding only a request timeout would leave combined preparation work without a total bound.
Persisting preparation settings in `bundle-profile.json` would change existing profile bytes and
execution identity. Keep these settings in the parent controller handoff instead.

## Data model and contracts

Extend compiled `evolution_requested` with `evaluator_preparation_timeout`,
`evaluator_preparation_wall_timeout`, their `*_source` fields and `timeout_source`. Fresh origins
are `explicit` or `default`. Existing values lacking origin are displayed as `persisted`; missing
preparation values use `legacy` origins. Resolve the request default from `timeout`, and the wall
default from `min(86400, 2 * request_timeout + 60)`. Enforce finite `(0, 86400]` values and wall
greater than or equal to request before fresh state creation or continuation mutation.

Legacy compiled handoffs fall back to their stored `timeout` for requests and have no total wall
deadline. Explicit continuation flags must match that durable policy, so a finite wall value
cannot be introduced to a legacy-unbounded parent. Prepared profile loading and comparison use
only the existing execution timeout. No database migration or frozen schema change is needed.

Pass a remaining-time callback through evaluator compilation/audit and local preflight. Clip
runtime request limits by preparation request budget; clip subprocess limits by execution
timeout. Both are also capped by remaining wall time. Preserve Feature 132 request observations
and ModelProfile's tighter caps.

Bounded attempts use a schema 2 started observation with `preparation_budgets` containing
`candidate_timeout_seconds`, `request_timeout_seconds` and `wall_timeout_seconds`. Wall failure
uses a schema 4 preparation
observation with `error_category=preparation_timeout`, `recoverable=true` and a `wall_failure`
diagnostic containing only `schema_version`, `reason`, `elapsed_ms` and `wall_timeout_ms`.
Its reason is `wall_timeout`; elapsed milliseconds are rounded up and capped at 86,400,000.
An optional `request_failure` preserves typed model evidence when a request also failed at the
deadline; it remains subject to the existing bounded diagnostic validation.
Stages identify preparation, evaluator compile/audit, compiler/auditor preflight or profile
publication. Legacy-unbounded/API calls preserve the earlier start schema. No successful
prepared event or candidate is published after observed expiry.

JSON/text status project three distinct budgets and their origins. The projection must validate
persisted data and make legacy-unbounded policy explicit; it must not guess provenance or remote
provider activity.

## Recovery and verification

Keep Feature 116 semantics: recoverable preparation failure leaves the parent persisted
`running` with effective failed status; only explicit continuation starts a new attempt and
deadline under the same policy. Preserve cancellation, terminal-state, drift and integrity
precedence, as well as prepared-run idempotency.

Use deterministic clocks and synthetic runtimes for request clipping, local preflight clipping,
expiry before/between requests and before publication, plus resume recovery. CLI tests cover
solve/resume/answer validation, persistence, origins, legacy compatibility and frozen profile
stability. The runnable offline commands are in [quickstart.md](quickstart.md); final results
belong in [validation.md](validation.md).

## Complexity tracking

No new dependency, database migration or constitutional exception is required. Changes remain in
the native CLI/controller and evaluator preparation boundary. Historical measurement artifacts
and captured generated source are not modified or replayed.
