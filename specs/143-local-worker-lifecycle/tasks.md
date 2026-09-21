# Tasks

The initial 2026-09-20 implementation history is preserved in [validation.md](validation.md).
The 2026-09-21 audit reopened T006 and T007 after three local counterexamples. Their repairs
and T011–T016 are now complete: final shared 260 passed; complete current regression 8708 passed,
1 skipped, 24 deselected; frozen123 24 passed. T008/T010 retain the original delivery history.
The original local API checkpoint below predates the T009 consumer migration; it did not complete
the CLI integration.

- [x] T001 Freeze the worker record, ownership, phase/outcome, stop-reason, depth, waiter, and
      bounded result contracts.
- [x] T002 Decide the versioned Store representation and migration/compatibility behavior.
- [x] T003 Implement pure ownership, depth, settlement, single-delivery, and cascade decisions.
- [x] T004 Add Store worker and worker-attempt operations with idempotent event emission.
- [x] T005 Add controller dispatch/send/list/wait/resume/cancel APIs over existing adapters.
- [x] T006 Complete runtime/process cancellation and cleanup acceptance; preserve unrelated workers
      with real local process fixtures, after T011, T013, and T014.
- [x] T007 Complete owner-scoped restart reconciliation and `lost` acceptance after T012.
- [x] T008 Add initial focused worker lifecycle fixtures and run shared regressions/inventory checks.
- [x] T009 Migrate one explicit delegation consumer after T006, T007, and T011–T015 passed.
      The bounded scope is one single-task `delegate` path, including its durable child host;
      AgentLoop, automatic solve and recursive workers remain unchanged.
- [x] T010 Review, update HANDOFF, commit, and push the initial implementation.

## Reopened acceptance completed, 2026-09-21

- [x] T011 Isolate adapter execution and cancellation per attempt. With two active workers selecting
      the same registered adapter type, cancel one and prove only its execution stops while the
      unrelated worker completes. Preserve existing adapter selection compatibility.
- [x] T012 Establish owner identity/liveness and restrict reconciliation to verified interrupted
      owners. Prove that constructing a second service against the same Store leaves a live first
      service's worker running, while a verified interrupted owner becomes `lost` and other owners
      remain unchanged.
- [x] T013 Check authoritative attempt state before adapter invocation and release handles by exact
      attempt identity. With one executor slot occupied, cancel a queued attempt and prove it never
      calls `adapter.run`; after cancel/resume, prove an older attempt's finalizer cannot remove the
      resumed attempt's runtime/future/process handle.
- [x] T014 Wire actual runtime process observers and verified cleanup to worker attempts. Local
      subprocess fixtures must cover PID/PGID association, subtree cleanup, unrelated processes,
      observer/cleanup failures, and accurate retained or released ownership.
- [x] T015 Add permanent regressions for the three reproduced counterexamples and the T011–T014
      acceptance cases. Verify queued `send` input is consumed by explicit `resume`; run focused
      and relevant shared regressions, static checks, and historical inventory checks. Record
      actual results and any migration exercised without claiming a provider end-to-end pass.
- [x] T016 Review and document the completed hardening, update HANDOFF, and commit/push only the
      verified changes. The later T017–T022 acceptance completes T009 through the CLI consumer
      rather than API tests alone.

## T009 bounded consumer tasks

- [x] T017 Add a versioned durable worker binding for one run/task/task-attempt and require the
      binding to commit before releasing the worker executor; preserve explicit crash recovery.
- [x] T018 Construct the worker service with the selected delegation registry and persist a bounded
      result envelope containing AgentResult identity, status/error, metadata, text and artifacts.
- [x] T019 Route foreground `delegate` through claim → bind → start → wait, with an independent
      observation timeout and a durable CLI child host; keep ordinary `run_agent` and AgentLoop unchanged.
- [x] T020 Materialize and verify worker result artifacts in the bound task-attempt workspace,
      then reuse existing evaluation/settlement. Reject traversal, symlink escape, missing or
      tampered artifacts and late results without overwriting terminal state.
- [x] T021 Wire exact-bound cancellation, budget stop and owner-scoped explicit recovery; add
      provider-free command fixtures for success/failure, cancellation, timeout, crash windows,
      registry isolation and idempotent result delivery.
- [x] T022 Run focused T009, shared worker/controller/CLI regressions, static checks, SDD/link
      checks and retained-evidence inventory; only then mark T009 complete and push.

## Delivery interruption audit, 2026-09-22

- [x] T023 Reserve delivery under a stable owner lock and test duplicate observers and stale recovery.
- [x] T024 Release observation locks on every exit, bound peer waits, and preserve committed evidence.
- [x] T025 Recover partial result/runtime/output batches without duplication; clean cancelled batches
      even when publication stopped between a file write, artifact row, and promotion event.
- [x] T026 Count promoted output bytes in the artifact budget and make CI ordering fixtures deterministic.
- [x] T027 Complete the three regression phases, update verification records, push, and inspect Linux CI.
      Current 6722 passed/1 skipped, archived 2294 passed, frozen123 24 passed; `0adb637` Linux CI
      passed on Python 3.11, 3.12, and 3.13.
