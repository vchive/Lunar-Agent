# Validation: Local multi-agent worker lifecycle

**Current status, 2026-09-21**: Lifecycle hardening passed its final shared and complete two-stage
local regressions: 260 shared; current 8708 passed, 1 skipped, 24 deselected; frozen123 24 passed.
The close-before-spawn repair is included. Final Linux CI also passed on Python 3.11, 3.12 and
3.13 at commit `8e1e089`; details are recorded at the end. Explicit consumer migration (T009)
remains incomplete. Earlier implementation and counterexample history is retained below.

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
Store migration and the exact results. The completed checks are recorded in the following section.

This audit does not alter Feature 131/134/139 evidence or Feature 142's separate foreground
automatic multi-file acceptance. A passing worker repair suite will not itself demonstrate
consumer integration or a real model end-to-end run.


## Lifecycle hardening validation, 2026-09-21

The final shared regression passed **260 tests in 31.50 seconds**. Its JUnit report is
`.lunar/test-results/feature143-final-close-20260921/shared.xml`, including all 77 worker cases:

| Test module | Passed | Acceptance |
| --- | ---: | --- |
| `test_workers` | 9 | Existing ownership, messaging, results and lifecycle compatibility |
| `test_worker_adapter_isolation` | 29 | Fresh execution factories, declarations, guarded cancellation, command cleanup and retained re-entry |
| `test_worker_store_ownership` | 21 | Schema migration, exact owner/process predicates, claim/settle races, atomic input consumption |
| `test_worker_lifecycle_hardening` | 13 | Concurrent services, queued cancellation, late finalizers, exact close, delayed launch and Store-failure cleanup |
| `test_worker_process_ownership` | 5 | Real private groups, parent-child cascade, unrelated survival, registration failure and retained cleanup |

The shared suite also covered agents, runtime, CLI, Controller, Store, input waiting, automatic
runtime processes and Phase B automatic cancellation. It included the actual
`RuntimeAgentAdapter(SubprocessRuntime)` registration-error case: even when that runtime swallows
observer exceptions, the exact command stops and the worker settles `failure/process_cleanup`.
The late-result and interrupted-close fixtures retain the durable terminal winner.

Independent review found and closed shared input-consumption races, cross-service close scope,
exception-path owner-lock leaks, transient close settlement classification, and the legacy runtime
observer exception path. A second review of worker/service lock, callback and cleanup paths found
no further reproducible blocker. Real command descendants run in an isolated test subprocess with
Linux subreaping when needed; no main-pytest global reaper state is changed.

Migration 8 was exercised against legacy worker rows and repeated Store initialization. Legacy
NULL owner remains unknown; missing/unsafe lock files cannot cause a `lost` transition. Claim and
input consumption share one immediate transaction; stale/missing/foreign message snapshots leave
both messages and attempts unchanged. Newly arrived input survives the prior snapshot's claim.

The [quickstart](quickstart.md) ran successfully and printed `local worker completed`. Ruff for
all `src`, `tests`, and `tools`, compileall, diff checks and Specify prerequisites with
`--require-tasks --include-tasks` passed. Specify's feature selection side effect was restored.

Retained inventories were checked read-only, with exact path set, size and SHA-256 matches:

| Feature | Files | Bytes |
| --- | ---: | ---: |
| 131 | 21 | 155485 |
| 134 | 97 | 327394 |
| 139 | 70 | 298462 |

All 188 files / 781341 bytes match their existing evidence, with no extra files or symlink
replacement. The three historical specs/campaign directories have no Git changes. No historical
Store was opened for mutation, and no generated source, provider or campaign was executed.

The first complete-regression attempt used
`.lunar/test-results/feature143-release-regression-20260921/`. During its execution a deterministic
close-before-spawn counterexample showed that transient close settlement failure could leave an
attempt running in Store: a delayed subprocess then launched after service close and wrote an
output even though its final outcome became `stopped`. The run was deliberately interrupted and
is an intermediate checkpoint, not final evidence. The process observer now also checks local
service closure and stops the exact adapter; exception settlement preserves `stopped/cancelled`
even when a legacy runtime loses the observer exception chain. The added permanent regression
and the related worker/lifecycle/process suite passed **27 tests** after this repair.

The final 260-test shared suite above includes that guard and the new permanent regression.
The fresh final two-stage run completed at
`.lunar/test-results/feature143-final-verified-20260921/`:

- Current working-tree product: **8708 passed, 1 skipped, 24 deselected**, 764.19 seconds, exit 0.
- Unchanged frozen123 snapshot: **24 passed**, 13.90 seconds, exit 0.
- Overall runner exit: **0**. It verified 77 product, 14 measurement and 69 historical pins.

The source and test tree includes all worker fixes plus CI fixture commit `93469e7`. No product
or test file changed after this final regression began. Earlier 249- and 259-test shared
checkpoints predate the last close-before-spawn guard; the interrupted complete-regression
checkpoint is retained separately and never replaces this final report pair.

## CI diagnostics and release boundary

Diagnostic commit `c22bd37` retained narrow stdout/JUnit artifacts, emitted bounded public failure
annotations and disabled matrix fail-fast without changing the split runner or historical guards.
[Run 35523896293](https://github.com/vchive/Lunar-Evolution/actions/runs/35523896293) completed with
96 reported failures on each supported Python version. Bounded annotations identified
`candidate_execution_evidence_runner_failed` cases; full diagnostic artifacts were uploaded.
A controlled local reproduction confirmed that an executable named through a symlink produces
that error (`executable_unsafe` at the runner boundary), while its resolved executable succeeds.
Ubuntu commonly aliases `/bin` and `/bin/sh`, unlike the original local fixture assumption.

Commit `93469e7` changes only four positive candidate-execution fixtures to resolve `/bin/sh`
and `/bin/echo` before recording the executable identity; derived budget plans reuse the original
command. Product no-follow checks, negative symlink tests, split-runner guards and frozen evidence
are unchanged. Seven directly affected/shared fixture modules passed **164 tests in 4.08 seconds**;
Ruff and diff checks passed. The fix was pushed independently to start its Linux matrix while
worker regression proceeds. That matrix must confirm whether all 96 failures share this cause;
no complete cross-platform pass is inferred from the local reproduction. The new
[run 35525074826](https://github.com/vchive/Lunar-Evolution/actions/runs/35525074826) is in progress.

T009 remains deferred: CLI `delegate` and AgentLoop do not yet consume these worker APIs.
Feature 142 Phase C automatic background execution and new real-model foreground acceptance
remain separate work. Passing local fixtures cannot change Feature 139's primary/joint `0/1`.


## CI environment follow-up after the worker commit

Worker commit `e9ea0de` was pushed after the complete local regression above. The first CI fixture
fix (`93469e7`, run 35525074826) removed the candidate-execution failures, but all three versions
still exposed four historical-environment failures; Python 3.12 additionally exposed one
intermittent attestation fixture failure. These are new concrete diagnostics, not evidence that
the earlier worker regression failed locally.

- Three 076/078/082 history unit tests depended on eight untracked local campaign files. A
  tracked-only temporary checkout reproduces the refusal. The current regression tests now first
  verify the actual tracked sealed files against their unchanged pins, then run the unchanged
  historical algorithm against an explicit, complete synthetic chain in a temporary directory.
  The predecessor path set and 24/30/36 chain sizes are preserved. This tests the algorithm; it is
  **not** a fresh verification of real private historical inventories. No private campaign bytes
  are exported, and no historical manifest, helper, loader pin or retained result is edited.
- Thirty-nine new negative/isolation cases check actual seal drift, missing/changed/linked
  dependencies, invalid maps, resealed final acceptance semantics, and refusal by the original
  validator when a real inventory is absent. The three audit modules plus these cases passed
  **193 tests**. Independent review confirmed that no reader, hash check or history validator
  is stubbed to return success. Prior tests loaded as sealed helpers are still the unchanged
  Feature 074 files; the 076/078 current regression edits do not rewrite their historical pins.
- The unchanged Feature 082 runtime test requires a repository `.venv` and the frozen supported
  console-launcher format. CI now creates the matrix interpreter's `.venv` and uses fixed
  `uv==0.11.8` to install the editable dev/lint environment. A fresh temporary source copy with
  Python 3.11 and that installation passed the original identity capture and verification.
  The 082 runtime plus diagnostic helper suite passed **41 tests**. The frozen runtime test and
  identity helper bytes are unchanged.
- Python 3.12 reproduced the attestation fixture failure in 6 of 20 runs: garbage collection
  closed old SQLite connections and checkpointed the live WAL during the protected snapshot.
  The guard correctly rejected `diagnostic_database_changed`. The receipt immutability test
  now holds its own fixture connection through CLI completion and also forces GC in a second
  case. The same stress check then passed 20 of 20; each of Python 3.12 and 3.13 passed all
  **76 attestation tests**, and related snapshot/diagnostic/Store suites passed **250 tests**.
  Source Store, snapshot, authorization and attestation checks were not changed.

These later changes affect only CI setup, current regression fixtures and their documentation;
they do not change the worker product validated by the 8708/24 report pair. Their focused suites,
Ruff and diff checks passed. The final Linux matrix below supplies complete cross-platform
acceptance; the earlier local full count is not relabeled as a rerun of the additional fixtures.


## Final Linux matrix acceptance

[GitHub Actions run 35526731156](https://github.com/vchive/Lunar-Evolution/actions/runs/35526731156)
verified commit `8e1e0896a9b71a4959962eaf6df72a12be5e68bd`. The jobs API was checked at
2026-09-20 18:05:13 UTC (2026-09-21 02:05:13 Asia/Shanghai):

| Python | Install | Complete split regression | Reports/annotations | Ruff |
| --- | --- | --- | --- | --- |
| 3.11 | success | success | success | success |
| 3.12 | success | success | success | success |
| 3.13 | success | success | success | success |

All three jobs completed successfully. The split runner validates its expected current test set
and the unchanged 24-node frozen123 phase before returning success. No new failure was reported.
This closes the code regression/CI gate and the local worker hardening acceptance. T009, automatic
background execution and real-model delivery acceptance remain separate, incomplete scopes.

The follow-up commit only records these completed checks in documentation. Product source,
tests, dependency declarations and CI configuration remain byte-identical to the verified commit; that
record-only update does not require another full matrix.
