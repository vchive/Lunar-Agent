# Tasks

The initial 2026-09-20 implementation history is preserved in [validation.md](validation.md).
The 2026-09-21 audit reopened T006 and T007 after three local counterexamples. Their repairs
and T011–T016 are now complete: final shared 260 passed; complete current regression 8708 passed,
1 skipped, 24 deselected; frozen123 24 passed. T008/T010 retain the original delivery history.
T009 remains deferred and is not completed by these local API checks.

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
- [ ] T009 Migrate one explicit delegation consumer only after T006, T007, and T011–T015 pass.
      The CLI and AgentLoop currently do not consume this worker API.
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
      verified changes. Keep T009 deferred until its own consumer integration is implemented and
      validated; do not mark it complete through API tests alone.
