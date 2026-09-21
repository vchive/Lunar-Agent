# Implementation Plan: Local multi-agent worker lifecycle

**Date**: 2026-09-20
**Status**: Local lifecycle hardening and T009 bounded foreground delegation migration validated
on 2026-09-21

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

## T009 implementation slice: one foreground delegated task

1. Add a versioned worker-binding record linking exactly one run, task, and claimed task attempt
   to one worker and worker attempt. Commit the binding before the worker executor is released;
   bind failures leave the task claim recoverable without starting an adapter.
2. Construct `Controller` with the explicit delegation registry before creating `WorkerService`.
   Add a provider-neutral worker result envelope carrying the existing `AgentResult` identity,
   bounded metadata, status/error, and declared artifacts. Persist only bounded JSON and digests.
3. Let the foreground `delegate` consumer claim a task, create/bind an idle worker, start it, and
   wait with a separate observation timeout. Materialize result text and declared files into the
   existing task-attempt artifact workspace through the existing confinement checks.
4. Reuse controller evaluation and terminal settlement after worker completion. Check the binding
   and authoritative task state immediately before delivery; late or cancelled results are
   discarded and cannot settle a task or run. Parent cancellation and explicit recovery resolve
   the exact binding, cancel/reconcile only that worker, and remain idempotent.
5. Keep ordinary synchronous `run_agent`, detached delegation, AgentLoop, automatic solve and
   recursive workers unchanged. Add local command fixtures for success, typed failure, timeout,
   cancellation, artifact traversal/tampering, binding crash windows, registry isolation and
   recovery. No provider request or campaign is part of this slice.

The worker hardening and consumer migration do not replace or block Feature 142's separate
foreground automatic multi-file acceptance.

## Guardrails

Verification infrastructure first retains the unchanged split regression command's stdout and
JUnit reports in CI, publishes bounded failure annotations, and runs all supported Python versions
without matrix fail-fast. This addresses the inaccessible Linux failure diagnostics observed during
the audit; it does not classify the root cause or relax any product/frozen-history check.

Migration 8 adds nullable `worker_attempts.service_owner_id` and a separate process registration
table. Migration fixtures preserve old rows with unknown ownership and exercise repeated
initialization. No missing owner or lock is treated as proof of interruption.

## Accepted implementation decisions

- Worker execution uses a fresh adapter/runtime factory per attempt. Ordinary synchronous adapter
  selection remains compatible. Missing factories or reused live objects fail before invocation.
- A Store-scoped file lock establishes service liveness; explicit caller-scoped reconciliation
  acquires existing owner evidence before process cleanup and exact-attempt settlement.
- Active handles, callbacks, close and process registrations use attempt identity. A cancelled
  queued attempt never enters its adapter; an older finalizer cannot release a new attempt.
- Resume validates and consumes exactly its snapshotted input IDs in the same transaction as the
  attempt claim. A stale snapshot cannot invoke an adapter, and later arrivals remain queued.
- Registration failures stop the exact adapter even if a legacy runtime swallows observer errors.
  Unconfirmed cleanup retains process ownership and blocks continuation until verified cleanup.
- The runnable provider-free example is [quickstart.md](quickstart.md). T009 is separate from this
  local API acceptance and remains deferred.

## Complexity tracking

The extra process table and local advisory owner locks are necessary to distinguish a live peer,
an abandoned attempt and an uncertain retained process. Reusing a global recovery sweep or a
single process field cannot safely represent those states. No new dependency or service is added.


Do not use `tasks.parent_id` as a substitute for `parent_worker_id`; do not copy OpenCode HTTP or
plugin code into Lunar; do not run a provider campaign as implementation validation.
