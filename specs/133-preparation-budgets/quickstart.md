# Offline verification

From the repository root with its development environment installed:

```sh
.venv/bin/pytest -q tests/test_conversational_automatic_bundle.py
.venv/bin/pytest -q tests/test_preparation_wall_timeout_cli.py tests/test_preparation_wall_budget.py tests/test_preparation_budget_status.py
.venv/bin/pytest -q tests/test_preparation_request_failure.py tests/test_preparation_recovery_cli.py
.venv/bin/pytest -q tests/test_automatic_solve_bundle.py tests/test_snapshot_evaluator_bundle.py tests/test_evaluator_request_failure.py
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature133
.venv/bin/ruff check src/lunar_evolution tests
.venv/bin/python -m compileall -q src/lunar_evolution
git diff --check
```

The fixtures use synthetic runtimes and deterministic timing. The full regression command also
covers the dedicated wall-budget and status tests. No provider request,
historical response or frozen measurement is replayed.

## Budget example

For native `solve --evolve --multi-file`, settings `--timeout 3
--evaluator-preparation-timeout 7 --evaluator-preparation-wall-timeout 20` keep candidate/frozen
evaluator execution at 3 seconds. Each preparation request is capped at 7 seconds, with the
entire attempt capped at 20 seconds from its durable start. If 5 seconds remain, the next model
request receives at most 5 seconds and a local preflight process receives at most 3 seconds.
The runtime's existing model profile can impose a tighter request cap.

Omitting the wall flag in that example resolves it to `2 * 7 + 60 = 74` seconds. Omitting both
preparation flags with default candidate timeout resolves request/wall to 900/1860 seconds.
Status reports the independent values and their origins. `resume` and `answer` may omit the
flags or supply matching values; they cannot change the parent policy. A legacy parent without
preparation fields keeps its stored request fallback and unbounded total preparation policy.

Check that successful profile JSON still contains only the execution timeout and observed expiry
prevents the successful prepared event and child creation. An already-started bounded local write
may leave material, which explicit recovery must validate before reuse. Recovery starts a new
attempt, and a successfully prepared parent remains idempotent. Passing offline fixtures
establishes control flow and durable policy, not provider performance or real multi-file delivery.
