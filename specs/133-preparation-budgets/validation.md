# Validation

## Current validation status

The request-plus-wall implementation, independent review, focused verification and two-stage
full regression are complete. The final narrow diagnostic-binding correction was also verified
by the targeted regression described below.

## Verified boundary

Automatic native multi-file `solve`, `resume` and `answer` accept independent preparation request
and wall flags. Fresh solves validate finite `(0, 86400]` values, wall at least request and mode
compatibility before creating local state. New compiled handoffs persist resolved values and
origins. Continuations restore policy and reject explicit mismatch; legacy events retain their
stored request fallback and unbounded total budget.

One monotonic deadline begins immediately after durable preparation start. Subsequent requests
and local subprocesses are clipped to remaining time, with checks between expensive phases and
before publication. Observed expiry prevents the successful prepared event and child creation.
An already-started bounded write or artifact registration may complete before the next guard;
retained material alone grants no preparation authority and must be validated on explicit
recovery. Recovery starts a new attempt under the same parent policy. Frozen profile schemas
remain unchanged, and candidate/evaluator execution still uses the original `--timeout`.

Feature 132 typed request evidence remains available; bounded wall-budget evidence does not
claim remote cancellation or completion. Feature 116 persisted-running/effective-failed recovery
semantics remain in force. JSON/text show separate candidate/request/wall budgets and verified
origins, including legacy-unbounded wall policy.

## Focused offline verification

- **84 CLI policy tests passed** in `tests/test_preparation_wall_timeout_cli.py`, including
  defaults/origins, legacy compatibility, side-effect-free mismatch rejection, malformed legacy
  values and persisted-policy validation on `solve --resume --evolve`.
- **41 deadline tests passed** in `tests/test_preparation_wall_budget.py`, covering request and
  subprocess clipping, deterministic expiry, durable-start timing, profile byte equality,
  publication-boundary recovery, typed request evidence, precedence and diagnostic tampering.
- A final strict check prevents boolean policy fields from comparing equal to one-second
  numeric values. After that check, **169 tests passed** in 30.01 seconds across deadline,
  local-diagnostic and request-diagnostic suites. This check and its new test were added after
  the full-regression process below had collected its tests.
- **276 integrated regression tests passed** in 78.85 seconds across automatic bundle preparation,
  conversational automatic solving, preparation recovery, local/request diagnostics and budget
  status. CLI expiry leaves no child/profile, status is read-only, and explicit resume creates
  another attempt with the same policy. The focused groups overlap and are not additive.
- The Feature 112 offline quickstart still selects 7 from scores 1/2/6/7, delivers one copy and
  preserves compiler/evaluator-compiler/auditor/Agent/candidate call counts 1/1/1/4/4 on terminal
  resume.
- Ruff, compileall, Specify prerequisites and `git diff --check` passed. Six updated documents
  have five valid local Markdown links.
- Independent reviews identified and resolved early mode validation, malformed legacy fallback,
  resume default comparison, source-origin validation and oversized-integer rejection issues.
  The evaluator timeout-routing review found no remaining actionable issue.

## Full regression

The two-stage runner exited **0**:

```sh
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature133
```

- Working product: **7661 passed, 1 skipped, 24 deselected** in **525.38 seconds**. JUnit
  records 7662 tests, zero failures and zero errors.
- Frozen Feature 123 checkout: **24 passed** in **11.64 seconds**. Its immutable pins cover
  77 product files, 14 measurement files and 69 historical files.
- The subsequent 169-test check includes the final added boolean-binding test; the full suite
  was not repeated after that narrow change.

## Historical preservation

Read-only inventories verified all 131 retained evidence files (377335 bytes): Feature 131 has
21 files/155485 bytes; Feature 129 has 16/122657; Feature 128 has 63/74305; Feature 125 has
16/13017; Feature 123 has 15/11871. Sizes and SHA-256 values match with no missing/extra files
or symlink path components. Twenty historical manifest/inventory/results/report files retain
their exact committed bytes.

## Limits

No real provider request, frozen campaign, historical evidence or captured generated source is
executed. This feature validates timeout policy, routing and recovery; it does not establish
faster evaluator generation, fewer provider timeouts, WebAgent parity or real multi-file
end-to-end success. Synchronous local work is bounded at phase checks, and provider work after
a timeout remains unknown.
