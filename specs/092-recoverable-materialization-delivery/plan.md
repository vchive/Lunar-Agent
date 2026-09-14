# Plan

Add a materialization delivery module owned by the controller lifecycle lock. It observes
complete 091 evidence and prepares a plan after the existing independent output validator.
The plan records a result template with no artifact IDs and ordered byte metadata for the
present outputs. Sync the existing output files, plan and directories before recording an
exact SQLite receipt. A new first call and a resume with intact modern execution and no downstream
evidence may both initiate this purely local verification/preparation.

Expose an 088 recovery API that returns status and exact output projection, with optional
expected byte metadata checked under its parent lock before reconciliation. Existing APIs keep
their behavior. Plan recovery uses committed projection directly, translates verified rollback
to a deterministic failure, or invokes the existing promoter only when no batch exists.

Expose read-only 089 inspection of a complete committed result. A delivery completion receipt
requires this check before any recovery can mutate terminal state. Otherwise reuse 089 recovery
first, then prepare a result from the plan and exact output outcome. Terminal validation rechecks
plan authority and agreement. Final result/event schemas remain unchanged.

For complete modern execution without a delivery plan, skip writable output recovery. An exact
old prepared 089 result still authorizes its own completion after read-only output inspection;
an intact old terminal remains replayable without migration. Other downstream fragments must
be rejected before reconciliation or delivery preparation writes.

Store uses one deterministic delivery-prepared event, exact read probes and FULL transactional
registration tied to the 090 intent and committed 091 batch in the same snapshot. Add 092 evidence
to 091 downstream refusal. No migration, dependency, generic runner or ordinary evolution change.

## Alternatives and complexity

Inferring a terminal result directly from an output commit loses the independent validation
decision. Repeating the promoter after commit conflicts with its no-existing-event gate.
Freezing artifact IDs before the parent publication lock would race reuse by another child;
088 remains authoritative for IDs/owners while the delivery plan binds bytes and contract.
Copying output bytes into a second staging tree is unnecessary: existing terminal validation
already requires the original attempt and the plan now binds its exact contents.

## Validation

Use bounded local fixtures, real controller exits and two-process lifecycle contention. A
counter must remain one while resume completes terminal success or explicit failure. Exercise
output commit before terminal preparation, 088 rollback, prepared 089, plan/receipt loss,
unsafe nodes, unknown database outcomes and reuse of existing parent output owners. Preserve
all 601 sealed tracked files under 051/074/076/078/082 and prior validation counts. No constitution
exception is required.
