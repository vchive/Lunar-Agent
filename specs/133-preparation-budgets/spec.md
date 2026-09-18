# Feature 133: Separate evaluator preparation budgets

## Problem

Automatic multi-file solving currently uses one `--timeout` value for two different
authorities: candidate generation/evaluation and the compiler/auditor requests that prepare
the frozen evaluator. A slow evaluator preparation can therefore consume the candidate budget,
and a user cannot express a bounded total wait for the two preparation requests plus local
preflight and publication. The timeout observed by Feature 132 is useful evidence, but it is not
itself a durable preparation policy.

## Scope

Add two explicit preparation controls to native `solve --evolve --multi-file` and to its
`resume`/`answer` continuations:

* `--evaluator-preparation-timeout SECONDS` is the upper bound requested for each isolated
  evaluator compiler or auditor model request. It is a request policy, not a promise about
  provider-side completion.
* `--evaluator-preparation-wall-timeout SECONDS` is the total monotonic wall-clock budget for
  evaluator preparation. It covers the preparation lock, input/profile checks, compiler and
  auditor requests, local probes and preflight, bundle validation, artifact registration and
  profile publication. It ends before candidate generation starts.

Both values are finite positive numbers in the existing bounded timeout range. The wall budget
must be at least the per-request budget. When omitted on a new compiled solve, the request value
resolves to the existing candidate `--timeout` (900 seconds by default), and the wall value
resolves deterministically to `min(86400, 2 * request_timeout + 60)`. This allows the normal
compiler/auditor pair and bounded local work while keeping the old command usable without new
flags. The resolved values, rather than `null`, are persisted.

`--timeout` remains the candidate generation, candidate execution and evaluator execution
timeout. It continues to be written into the frozen `bundle-profile.json`; preparation policy
must never be added to that schema or to the evaluator execution identity.

## Durable policy and compatibility

For `bundle_mode=compiled`, the existing `evolution_requested` payload gains the bounded fields
`evaluator_preparation_timeout` and `evaluator_preparation_wall_timeout`. They are controller
settings only and contain no provider credentials, prompts or response data. A preparation
attempt uses the policy attached to its parent run, so an explicit continuation cannot silently
change the deadline used by a failed attempt.

Existing Feature 112-132 events without these fields remain readable. Their request timeout
falls back to the stored `timeout`, and their wall budget is treated as legacy-unbounded; status
must identify this legacy fallback. Explicit new values that differ from those derived legacy
settings are rejected rather than rewriting historical events. New runs always persist both
resolved values. Prepared profiles compare only their existing execution timeout and remain
byte-compatible with old frozen profiles.

## Enforcement and failure semantics

The controller starts one monotonic preparation deadline before the first expensive preparation
phase. Before each compiler/auditor request it passes the smaller of the per-request value and
the remaining wall budget to the runtime. Every local phase checks the same deadline before
doing work and before publishing files or events. A non-positive remainder fails preparation
without creating a child or candidate. The failure is recoverable only through explicit resume;
there is no automatic retry, request replacement, response repair or deadline extension.

Feature 132's typed request diagnostics remain authoritative for a request that actually started.
If the wall deadline limits that request, its observed request timeout is the remaining bounded
value. A wall-budget exhaustion is recorded as a bounded preparation-budget diagnostic with the
requested/effective budgets and exhausted scope, never an exception string or provider claim.
Cancellation, terminal parent state, input drift and integrity failures retain their existing
precedence. A failed parent remains eligible for the existing explicit recovery contract from
Feature 116; this feature does not rewrite the parent into a terminal state.

The JSON and text status surfaces show candidate timeout, preparation request timeout and
preparation wall timeout separately, including whether each value was explicit, defaulted or a
legacy fallback. They may show elapsed/exhausted scope, but must not expose prompts, model
responses, credentials or unverified provider work.

## Acceptance

1. New flags are accepted only for native compiled multi-file evolution and are validated before
   any run, event, artifact, model or filesystem mutation. Non-multi-file, explicit evaluator,
   OpenEvolve and unrelated commands reject them side-effect free.
2. Resolved preparation request and wall budgets are persisted in the parent evolution handoff;
   `resume` and `answer` restore and validate them, while legacy events use the defined fallback.
   Mismatched explicit continuation settings fail before preparation.
3. `--timeout` continues to control candidate generation/execution and frozen evaluator execution;
   preparation budgets never alter `bundle-profile.json`, its digest, evaluator identity or
   prepared-profile reuse.
4. Compiler and auditor receive bounded remaining deadlines, and all local preparation phases
   enforce one total wall deadline. Exhaustion cannot publish a partial preparation or create a
   child. Existing prepared runs remain idempotent and make no model requests.
5. Feature 132 request observations preserve actual per-request timeout evidence. Wall-budget
   failures are bounded, typed and recoverable only by explicit continuation; no automatic retry
   or provider-side completion is inferred.
6. Offline tests cover defaults, independent timeout propagation to both preparation stages,
   wall-deadline exhaustion before and during requests, persistence/restore, mismatch rejection,
   legacy events, prepared-profile byte stability and side-effect-free validation. No real model
   call, frozen measurement rewrite or generated-source execution is part of this feature.

## Non-goals

This feature does not add active-process cancellation orchestration, provider token/cost caps,
detached execution, external producer support, a new database migration, or a claim that a larger
or separate timeout improves evaluator quality, WebAgent parity or end-to-end success.
