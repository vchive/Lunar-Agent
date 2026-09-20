# Implementation Plan: Local multi-agent worker lifecycle

**Date**: 2026-09-20
**Status**: Implemented locally; explicit delegation migration remains deferred

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

## Guardrails

No database migration is assumed until the record shape and compatibility fixtures are accepted.
Do not use `tasks.parent_id` as a substitute for `parent_worker_id`; do not copy OpenCode HTTP or
plugin code into Lunar; do not run a provider campaign as implementation validation.
