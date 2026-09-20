# Validation: Local multi-agent worker lifecycle

**Current status, 2026-09-21**: Initial local API validation passed; lifecycle acceptance is
reopened after three counterexamples. The repairs and their permanent regression tests are not
yet validated. Explicit consumer migration (T009) remains incomplete.

## Initial implementation validation, 2026-09-20

The initial implementation reported completed validation for the local worker control plane.
That historical result is retained below; the later audit limits the conclusions it supports.
The evidence boundary remains offline: no provider request, real campaign, WebAgent rerun, or
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

Initial fixtures covered direct ownership and depth checks, wait timeout semantics,
send/resume, parent cascade cancellation, unrelated-worker preservation, idempotent settlement,
late-result precedence, restart-to-`lost` reconciliation, typed timeout classification, redacted
events, bounded results, and SHA-256-verified local result references.

The first implementation run must report focused lifecycle tests, shared regressions, Ruff,
compileall, diff checks, and historical Feature 131/134/139 inventory checks. It must state whether
any database migration was exercised. No provider request, real campaign, WebAgent rerun, or
provider-generated source execution is part of this feature's validation.

## Audit and local counterexamples, 2026-09-21

Read-only inspection of the existing
`.lunar/test-results/feature142-phase-b-20260921/current.xml` report found **9** passing
`tests.test_workers` cases, with no failures or errors. The earlier focused count of 8 above is
the recorded initial result, not the current count. This audit did not rerun the full suite.
Those passing fixtures establish their covered cases only: they do not demonstrate independent
real adapter cancellation, coexistence of service owners, or suppression of cancelled queued
execution. In particular, the initial fixture's `cancel` sets an Event that its `run` ignores.

Temporary local scripts used isolated SQLite stores and event-controlled fake adapters to
reproduce the following failures. They did not edit repository source/tests, call a provider,
launch a campaign, or create a permanent regression artifact. All fixture threads were released
and temporary directories cleaned up.

| Counterexample | Observed behavior | Required acceptance |
| --- | --- | --- |
| Second WorkerService opens the same Store while the first is active | The original worker changed from `running` to `idle/lost` although its adapter was still blocked. Its later successful completion did not remove `lost`. | Preserve live-owner work; reconcile only verified interrupted owner scope. |
| Two workers use an adapter with one current invocation handle, matching CommandAdapter's ownership shape | Cancelling `target` invoked cancellation on `unrelated`; the unrelated worker became `stopped` while the target execution remained blocked. | Independent attempt handles; cancellation reaches only the requested worker/subtree. |
| One executor slot is occupied and the queued worker is cancelled | Before slot release, adapter calls were `['first']` and queued status was `stopped`. Afterwards calls became `['first', 'cancel-before-start']`, with queued status still `stopped`. | A cancelled queued attempt never enters `adapter.run`. |

All three temporary reproductions confirmed their assertions and completed successfully. These
are reproductions of defects, not successful repair validation.

Additional code inspection found that worker execution does not register actual adapter process
observations and that handle cleanup is keyed only by worker identity, leaving process cleanup
and cancel/resume late-finalizer behavior unproved. These require dedicated acceptance coverage;
the temporary scripts above do not establish their corrected behavior.

Current `send` behavior is queued input for a later explicit `resume`; it does not inject input
into the running adapter invocation. This is a scope clarification, not a new live-interruption
requirement. CLI `delegate` still calls the existing synchronous `run_agent` path, and AgentLoop
has no worker tool integration. T009 remains deferred until T006/T007 and T011–T015 pass.

## Required repair validation

CI diagnostic preparation adds an annotation helper and always-retained narrow stdout/JUnit
artifacts, with matrix fail-fast disabled. Four helper tests passed, covering failure/error node
identity, annotation escaping, missing/malformed reports and the bounded cross-report count.
Ruff and diff checks passed; the existing Phase B JUnit pair produced no false failures. The
regression runner and historical pins are unchanged. This is diagnostic visibility work, not a
repair or a successful rerun of the failing Linux product tests.

Continue the existing SDD tasks; no new feature is needed. Convert the three counterexamples
into permanent regressions, verify exact attempt handle release across cancel/resume, and add
local subprocess fixtures for real process observer ownership and cleanup failures. Run focused
and relevant shared suites, static checks, and historical inventory checks, documenting any
Store migration and the exact results. None of those repair checks is claimed complete here.

This audit does not alter Feature 131/134/139 evidence or Feature 142's separate foreground
automatic multi-file acceptance. A passing worker repair suite will not itself demonstrate
consumer integration or a real model end-to-end run.
