# Implementation Plan: Local multi-agent worker lifecycle

**Date**: 2026-09-20
**Status**: Local APIs implemented; lifecycle hardening reopened on 2026-09-21;
explicit delegation migration remains deferred

## Phase A: Durable model and pure lifecycle rules

1. Add typed worker and worker-attempt records with stable phase/outcome/stop-reason enums.
2. Add Store operations for create, ownership lookup, child listing, append input, attempt claim,
   idempotent settlement, bounded events, and restart reconciliation.
3. Keep settlement decisions pure: gather authoritative facts, decide one outcome, then perform
   side effects. Add unit tests for duplicate callbacks and result single-delivery.

## Phase B: Controller worker service

1. Add dispatch/send/list/wait/resume/cancel methods to a small controller-owned worker service.
2. Reuse AgentRegistry and runtime adapters for execution, while keeping worker identity separate
   from task and attempt identity.
3. Thread cancellation and stop callbacks through runtime and process observers. Reuse existing
   terminal precedence and cleanup paths.
4. Add ownership, depth, parent-cascade, timeout, and late-result integration fixtures.

## Phase C: Recovery and opt-in integrations

1. Reconcile worker trees after restart and classify uncertain runs as `lost` without inventing
   success.
2. Add bounded result rendering and parent notification events.
3. Migrate one explicit delegation path as a consumer. Leave automatic multi-file and detached
   entry points behind separate lifecycle work until cleanup acceptance passes.

## 2026-09-21 audit: complete the existing lifecycle contract

The initial implementation and offline validation remain recorded in [validation.md](validation.md).
Three local reproductions exposed gaps in the original acceptance. Continue this SDD before
Phase C consumer migration; do not treat the existing APIs as completed integration evidence.

1. Give each active attempt an independent adapter execution/cancellation handle. Preserve
   deterministic adapter selection while avoiding shared mutable runtime, process, or observer
   state between workers. Verify simultaneous workers selecting the same adapter type.
2. Establish service owner identity and liveness for reconciliation. Inspect only verified scope;
   opening another service or Controller must preserve live owners. Exercise live coexistence,
   verified owner interruption, and unrelated-owner preservation against a shared Store.
3. Prevent queued cancellation from reaching `adapter.run`. Bind active handles, futures, process
   observations, and release callbacks to the exact attempt so an earlier attempt's completion
   cannot release a resumed attempt. Include deterministic queue and late-callback fixtures.
4. Register actual runtime process observations for each attempt and connect cancellation to
   verified process cleanup. Test local subprocess groups, unrelated process preservation,
   observer failures, cleanup failures, and accurate release state without any provider request.
5. Retain the current message contract: `send` queues bounded input for a later explicit `resume`.
   Verify that consumption and continuation remain correct; do not add live interruption as a
   release prerequisite.
6. Turn the three reproduced failures into regression tests, add the process and attempt-isolation
   coverage, and run focused plus relevant shared regressions. Update validation with actual
   results and migration checks before considering T009 complete. Preserve frozen evidence.

T009 remains a later opt-in integration step. The worker hardening and consumer migration do not
replace or block Feature 142's separate foreground automatic multi-file acceptance.

## Guardrails

Verification infrastructure first retains the unchanged split regression command's stdout and
JUnit reports in CI, publishes bounded failure annotations, and runs all supported Python versions
without matrix fail-fast. This addresses the inaccessible Linux failure diagnostics observed during
the audit; it does not classify the root cause or relax any product/frozen-history check.

No database migration is assumed until the record shape and compatibility fixtures are accepted.
Do not use `tasks.parent_id` as a substitute for `parent_worker_id`; do not copy OpenCode HTTP or
plugin code into Lunar; do not run a provider campaign as implementation validation.
