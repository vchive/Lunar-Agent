# Feature Specification: Local multi-agent worker lifecycle

**Created**: 2026-09-20
**Status**: Local lifecycle hardening validated on 2026-09-21; T009 explicit delegation
migration is in progress under the bounded single-task scope below
**Input**: WebAgent reference-engine-v2.5 multiagent review and Lunar capability comparison

## Problem

Lunar can route a role to an adapter and can schedule persistent tasks in a dependency DAG. That
does not provide the interactive worker contract used by WebAgent v2.5. A caller cannot retain a
worker identity, continue the same session, send a message to a running worker, wait for one
worker, or cancel only its owned worker subtree. Treating `tasks.parent_id` as a worker session
tree would mix two different lifecycles and would make ownership and late-result handling unsafe.

## Scope

This feature adds a local, provider-neutral worker control plane on top of the existing Store,
Controller, AgentRegistry, and runtime adapters. It applies to explicitly delegated local workers
and to future automatic orchestration that opts into the worker API. Existing task DAG scheduling,
ordinary `run_agent()`, population evolution, external producer handoffs, and WebAgent/OpenCode
HTTP compatibility remain unchanged until an integration feature opts in.

The 2026-09-21 audit reproduced cancellation isolation, live-owner reconciliation, and queued
execution defects in the existing local APIs. Their correction remains within this feature's
lifecycle contract; it does not require a new feature. The API implementation and its original
offline fixtures are not sufficient evidence that concurrent real adapters are ready for use.

## User-visible contract

The controller exposes these operations to a trusted caller:

- `dispatch`: create a worker or resume an idle worker, returning a stable `worker_id`;
- `send`: append bounded input to a running worker without waiting for its result; the input is
  queued for a later explicit `resume`, rather than delivered into the current adapter invocation;
- `list`: list workers directly owned by the caller, filtered by `running` or `all`;
- `wait`: wait for one worker with a bounded timeout; timeout means the worker is still unknown,
  never failure;
- `cancel`: stop one directly owned worker and its descendants;
- `resume`: start another run for an idle worker while retaining its prior outcome as history.

The API is local and typed. It does not expose credentials, arbitrary exception text, provider
response bodies, or filesystem paths in worker status.

## Requirements

### Worker identity and ownership

- **FR-001**: A worker has an immutable `worker_id`, direct `parent_worker_id` (or root owner),
  owner identity, role/agent type, bounded description, depth, and creation time.
- **FR-002**: Only the direct owner may send, wait, resume, list, or cancel a worker. Unknown,
  unrelated, and non-direct descendants are rejected without runtime or Store side effects.
- **FR-003**: Dispatch enforces a configured maximum depth. Workers cannot silently acquire the
  ability to dispatch more workers unless a later feature explicitly grants it.

### Two-dimensional state and settlement

- **FR-004**: Worker activity is represented separately from the previous run outcome. `phase` is
  `running` or `idle`; an idle worker may retain `success`, `failure`, `stopped`, or `lost` as its
  last outcome.
- **FR-005**: Runtime callbacks and idle/error notifications are hints only. Settlement must
  re-check the authoritative attempt/runtime state and the final bounded result before publishing
  an outcome.
- **FR-006**: Settlement is idempotent. Duplicate idle/error/abort callbacks cannot duplicate a
  result, notification, waiter wakeup, or child cancellation.
- **FR-007**: A worker result has exactly one delivery path per run: a registered waiter receives
  it, otherwise a bounded parent notification is recorded. A wait timeout does not suppress a
  later notification or turn into failure.

### Continuation, cancellation, and recovery

- **FR-008**: `resume` starts a new attempt for an idle worker, clears run-specific stop metadata,
  retains the previous outcome as history, and rejects resume of a running worker. Queued `send`
  input is consumed by this explicit continuation; current-invocation interruption is not promised.
- **FR-009**: Cancelling a worker marks the requested worker and all owned descendants through
  verified links, reaches active runtimes and local process groups, and preserves the first durable
  terminal outcome against late results.
- **FR-010**: Cleanup is best effort across all owned processes. One failed cleanup callback cannot
  prevent other owned processes from being stopped. Cleanup releases only the corresponding
  attempt's handles and verified process ownership; failure must not be reported as successful
  cleanup or release another attempt's resources.
- **FR-011**: Worker records and attempts survive process restart. Reconciliation walks only the
  caller's verified worker tree; an interrupted run with no authoritative terminal evidence becomes
  `lost` and cannot be presented as success. Constructing another Controller or WorkerService is
  not evidence of owner death: a live owner's attempts must remain running. Reconciliation requires
  verified owner scope and liveness evidence before classifying an attempt as interrupted.

### Persistence and compatibility

- **FR-012**: Store persistence uses explicit worker and worker-attempt records or an equivalent
  versioned representation. Existing run/task/attempt rows and historical handoffs are unchanged.
- **FR-013**: Worker events include fixed type, worker identity, phase/outcome, and bounded reason
  codes. They exclude prompts, secrets, provider text, and unbounded tracebacks.
- **FR-014**: Existing `run_agent()`, ordinary `resume`, population evolution, and detached
  ordinary solves retain their current behavior until explicitly migrated to this API.
- **FR-015**: No OpenCode plugin, remote reference-engine client, SSE protocol, GPU sandbox, or multi-tenant
  service is introduced by this feature.

### Reopened lifecycle acceptance, 2026-09-21

- **FR-016**: Each active attempt owns an independent adapter execution and cancellation target.
  Selecting the same registered adapter for multiple workers must not share mutable invocation
  state. Cancelling one worker or subtree cannot stop an unrelated worker using that adapter type.
- **FR-017**: An attempt cancelled while queued cannot enter `adapter.run` when executor capacity
  becomes available. Execution must re-check authoritative attempt state before invocation, and
  completion or cleanup from an older attempt cannot remove a resumed attempt's active handle.
- **FR-018**: Actual local runtime process observations are registered against the owning worker
  attempt. Cancellation and recovery use verified attempt/process ownership, try cleanup for
  every owned process, and retain evidence of incomplete cleanup. Adapter callbacks alone do
  not establish that local processes have exited.

## Acceptance criteria

1. A caller can dispatch, list, wait, send, cancel, and resume a worker through typed local APIs.
2. Ownership, depth, duplicate settlement, wait timeout, late result, and cancel race fixtures
   prove no cross-owner or double-delivery behavior.
3. Parent cancellation reaches descendants and all registered local runtime/process resources;
   an unrelated worker remains untouched.
4. Restart reconciliation marks an interrupted worker `lost`, preserves bounded evidence, and
   permits an explicit resume only under the documented policy.
5. Worker status and events contain no secret, prompt, provider body, arbitrary traceback, or
   unbounded result. Large results use a bounded tail plus a verified local artifact reference.
6. Existing shared regressions and historical measurement inventories pass without changes.
7. Two workers using the same adapter type have independent execution/cancellation handles;
   cancelling one while both are active leaves the unrelated worker able to complete normally.
8. A second service using the same Store cannot mark a live first service's worker `lost`;
   verified interrupted owners can still be reconciled without touching other owners' workers.
9. With one executor slot occupied, cancelling a queued attempt prevents any adapter invocation
   for it. A late callback from an earlier attempt cannot release a resumed attempt's handle.
10. Local subprocess fixtures verify that actual PID/PGID observations belong to the right
    attempt, cancellation reaches its owned process group, unrelated processes survive, and
    cleanup failure remains visible. The bounded T009 consumer additionally verifies durable
    delegate binding, result/artifact delivery, cancellation races, and duplicate-observer
    idempotency.

## Non-goals

No dynamic role prompt catalog, approval gate, remote cancellation promise, cumulative budget,
automatic retry, live message interruption, WebAgent effect/parity claim, or real provider campaign
is included. AgentLoop worker tools, recursive workers, and automatic solve integration remain
outside the bounded T009 consumer; their absence does not block Feature 142's separate foreground
automatic multi-file acceptance.

## Execution and migration contract

Concurrent workers allocate a fresh adapter with `AgentRegistry.create_execution_adapter`.
Built-in command adapters reuse only their configuration. Runtime adapters require an explicit
`runtime_factory`; custom adapters require a registered `execution_factory`. Missing or reused
execution instances are rejected before invoking a worker. Ordinary `select`/`run_agent` entry
and selection contracts remain compatible; shared command process cleanup and re-entry are also
hardened. This deliberately tightens the initial worker API, whose shared instances were not
safe for concurrent execution. Factories must also isolate any mutable state inside their objects.

Schema migration 8 adds a nullable service execution owner to worker attempts and an independent
process registration table. Existing rows remain readable; absent owner evidence is unknown,
not proof of a dead service. A service takes a Store-scoped owner file lock before claiming an
attempt and keeps it until its last active attempt has drained. Opening another service does
not reconcile anything. Explicit `reconcile(owner_id)` checks only that caller's attempts and
requires an existing, safely opened, unheld owner lock before cleanup and exact-attempt `lost`
settlement. Missing/unsafe locks and unconfirmed process cleanup retain the prior records.

Cancellation, service close, process release and late finalizers refer to exact attempt identities.
Explicit resume can start an isolated new attempt after cancellation when there are no retained
process registrations; an older callback cannot remove the new handle or replace its outcome.
Queued messages are snapshotted for resume; their existence is checked and only those exact IDs
are consumed atomically with the attempt claim. A stale snapshot is rejected before invocation,
and a message arriving during the new execution remains available for its next continuation.

See [quickstart.md](quickstart.md) for the explicit local API and recovery limits.

## T009 bounded consumer: explicit foreground `delegate`

The first consumer is deliberately one foreground CLI path: `lunar-evolution delegate`. It is
opt-in and single-task. Ordinary `run_agent`, AgentLoop, automatic multi-file solve, detached
delegation, recursive worker creation, and model-facing worker tools remain unchanged until a
later acceptance expands this scope.

Before a worker starts, the controller claims one ready task and durably binds the worker to the
parent run, task, and task attempt in one binding record. A crash before the binding is committed
must leave no worker execution; a crash after it is committed leaves an auditable binding for
explicit reconciliation. The worker receives the task's effective prompt and a bounded active
execution timeout; `wait` timeout is only a caller observation limit and never settles the worker.

The worker result is converted back to the existing `AgentResult` contract, including adapter and
role identity, status/error, bounded metadata, and every declared artifact. Artifacts are copied or
materialized into the bound task-attempt workspace through `ArtifactStore.safe_path`; traversal,
symlink escape, missing files, digest mismatch, and unsupported result shapes fail closed. The
existing controller evaluator, task settlement, run settlement, and artifact ledger remain the
authority: a worker success alone never marks a task successful. Result materialization reserves
the binding as `delivering`. The owner holds a stable per-worker liveness lock through artifact
staging, evaluation, and commit. A second observer waits while that lock is live; it may reopen
`delivering` only after the timestamp is stale and the owner lock is available, so a live delivery
is never reset by a later observer.

Parent cancellation and budget exhaustion look up the exact binding and cancel only its worker
tree. A late worker result is recorded as discarded when the task is no longer running and cannot
replace a terminal task/run. Explicit recovery first proves the service owner is inactive and
cleanup is complete, then settles the bound attempt as `lost`; recovery is idempotent and never
starts a new attempt automatically.

T009 acceptance is provider-free. It requires successful and failed local command consumers,
correct registry construction, durable pre-start binding, complete result/artifact handoff,
parent cancellation and timeout isolation, late-result rejection, and owner-scoped recovery.
