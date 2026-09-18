# Validation

## Implemented boundary

`evaluator_request_diagnostics` projects only a direct, exact `ModelRequestFailure` with exact
typed evidence. Its copied schema 1 payload has only `reason`, `response_status`, optional local
request/transport observations and its schema version. It never reads exception prose, response
bodies or causes, and it does not infer provider activity, remote completion, token use or
evaluator quality. Invalid optional observations drop to less detail; invalid persisted detail
falls back to a coarse, nonrecoverable validation failure.

Compiler and auditor runtime boundaries carry that validated projection in
`EvaluatorBundleRuntimeError`. Automatic preparation writes schema 3 only for an accepted,
recoverable runtime failure and binds it to the parent, attempt and one unique immediately
preceding start event. Reads preserve schema 1 runtime failures and schema 2 local failures.
Cancellation, terminal parent state, input drift and verified preparation override stale detail.
The detail is advisory only: it cannot authorize reuse, scoring, freeze, delivery or retry.

Normal JSON and text status expose only validated fields. `transport_timeout` has fixed guidance:
remote completion and usage are unknown; the transport milestone is a local observation; explicit
resume may issue a new model request. This feature leaves prompts, request deadlines, model
parameters and retry policy unchanged. The parent run remains durably `running` where Feature 116
requires recoverability; its effective outward status remains failed.

## Focused offline verification

- **84 request-diagnostic tests passed** in `tests/test_evaluator_request_failure.py`. They cover
  the bounded loopback `wait_response_headers` timeout, worker cleanup, compiler/auditor HTTP 429
  propagation, direct-type-only projection and staged degradation of malformed optional evidence.
- **75 durable preparation tests passed** in `tests/test_preparation_request_failure.py`. They
  cover schema 3 persistence, tampering, immediate-start binding, read-only status, cancellation,
  input drift, terminal/prepared precedence, explicit resume and terminal idempotency.
- Existing Feature 116/127 preparation recovery tests passed: **109 tests** across
  `test_preparation_recovery.py`, `test_preparation_recovery_cli.py` and
  `test_preparation_local_diagnostics.py`.
- The Feature 112 quickstart still selects 7 from scores 1/2/6/7. Compiler/evaluator
  compiler/evaluator auditor/Agent/candidate calls remain 1/1/1/4/4 across terminal resume and
  delivery still produces one copy.
- Ruff, compileall, `git diff --check`, Specify prerequisites and the local Markdown link check
  passed. The eight updated documents contain 52 resolvable relative links. Independent reviews
  found no blocking issue and confirmed the Feature 116 durable `running` state is intentional.

## Full Regression

The two-stage regression completed successfully with:

```sh
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature132
```

- Current tree: **7512 passed, 1 skipped, 24 deselected** in **541.58s**. The JUnit result has
  7513 tests, 0 failures and 0 errors.
- Frozen Feature 123 checkout: **24 passed** in **22.55s**. The JUnit result has 24 tests,
  0 failures and 0 errors.
- The runner exited **0**. Its pin check reported 77 product files, 14 measurement files and
  69 historical files in the frozen checkout.

## Preservation and Limits

No real provider, WebAgent, external evolution framework, frozen campaign or captured response is
called, resumed or executed. Feature 131 remains its independently registered 0/1 timeout result;
this offline work does not show faster evaluator generation, fewer timeouts, WebAgent parity or a
real automatic multi-file delivery.

Read-only inventory checks retain Feature 131's 21 files (155485 bytes), Feature 129's 16 files,
Feature 128's 63 files, Feature 125's 16 files and Feature 123's 15 files with no SHA-256 mismatch.
Historical evidence and reports are not rewritten. Any real retry must be a separately registered
and pushed measurement with fixed conditions; it cannot reopen Feature 131.
