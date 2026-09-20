# Feature Specification: Local multi-agent worker lifecycle

**Created**: 2026-09-20
**Status**: Local APIs implemented; lifecycle acceptance reopened by the 2026-09-21 audit;
explicit delegation migration remains deferred
**Input**: WebAgent famou-v2.5 multiagent review and Lunar capability comparison

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
- **FR-015**: No OpenCode plugin, remote FamouClient, SSE protocol, GPU sandbox, or multi-tenant
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
    cleanup failure remains visible. These checks precede explicit consumer migration (T009).

## Non-goals

No dynamic role prompt catalog, approval gate, remote cancellation promise, cumulative budget,
automatic retry, live message interruption, WebAgent effect/parity claim, or real provider campaign
is included. T009 remains deferred until the reopened lifecycle acceptance passes; its absence
does not block Feature 142's separate foreground automatic multi-file acceptance.
