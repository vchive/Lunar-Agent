# Tasks

- [ ] T001 Freeze the worker record, ownership, phase/outcome, stop-reason, depth, waiter, and
      bounded result contracts.
- [ ] T002 Decide the versioned Store representation and migration/compatibility behavior.
- [ ] T003 Implement pure ownership, depth, settlement, single-delivery, and cascade decisions.
- [ ] T004 Add Store worker and worker-attempt operations with idempotent event emission.
- [ ] T005 Add controller dispatch/send/list/wait/resume/cancel APIs over existing adapters.
- [ ] T006 Connect runtime/process cancellation and cleanup; preserve unrelated workers.
- [ ] T007 Add restart reconciliation and `lost` handling with bounded diagnostics.
- [ ] T008 Add focused worker lifecycle fixtures and run shared regressions/inventory checks.
- [ ] T009 Migrate one explicit delegation consumer only after the lifecycle contract is stable.
- [ ] T010 Review, update HANDOFF, commit, and push the verified implementation.
