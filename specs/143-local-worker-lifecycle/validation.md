# Validation: Local multi-agent worker lifecycle

Implementation validation completed for the local worker control plane. The evidence boundary
remains deliberately offline: no provider request, real campaign, WebAgent rerun, or
provider-generated source execution was used.

Focused lifecycle suite: `./.venv/bin/pytest -q tests/test_workers.py` passed (8 tests).
Shared regression suite covering workers, Store, Controller, agents, runtime, and CLI passed.
Ruff passed for the changed worker, Store, Controller, model, export, and test modules;
`compileall` and `git diff --check` passed.

The full `PYTHONPATH=. ./.venv/bin/pytest -q` run reached 100%. All non-frozen tests passed.
The 24 Feature 123 registration setup cases intentionally rejected the changed product with
`product_changed`, because that suite is pinned to its historical product commit; this is the
expected frozen-evidence guard, not a worker regression. The migration path was exercised by
creating and initializing fresh SQLite stores and by repeated initialization of the worker
schema. Historical Feature 131/134/139 evidence was not modified or rerun.

Covered lifecycle evidence includes direct ownership and depth checks, wait timeout semantics,
send/resume, parent cascade cancellation, unrelated-worker preservation, idempotent settlement,
late-result precedence, restart-to-`lost` reconciliation, typed timeout classification, redacted
events, bounded results, and SHA-256-verified local result references.

The first implementation run must report focused lifecycle tests, shared regressions, Ruff,
compileall, diff checks, and historical Feature 131/134/139 inventory checks. It must state whether
any database migration was exercised. No provider request, real campaign, WebAgent rerun, or
provider-generated source execution is part of this feature's validation.
