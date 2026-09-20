# Feature Specification: Local multi-agent worker lifecycle

**Created**: 2026-09-20
**Status**: Specification only; implementation has not started
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

## User-visible contract

The controller exposes these operations to a trusted caller:

- `dispatch`: create a worker or resume an idle worker, returning a stable `worker_id`;
- `send`: append bounded input to a running worker without waiting for its result;
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
  retains the previous outcome as history, and rejects resume of a running worker.
- **FR-009**: Cancelling a worker marks the requested worker and all owned descendants through
  verified links, reaches active runtimes and local process groups, and preserves the first durable
  terminal outcome against late results.
- **FR-010**: Cleanup is best effort across all owned processes. One failed cleanup callback cannot
  prevent other owned processes from being stopped or the worker ownership record from clearing.
- **FR-011**: Worker records and attempts survive process restart. Reconciliation walks only the
  caller's verified worker tree; an interrupted run with no authoritative terminal evidence becomes
  `lost` and cannot be presented as success.

### Persistence and compatibility

- **FR-012**: Store persistence uses explicit worker and worker-attempt records or an equivalent
  versioned representation. Existing run/task/attempt rows and historical handoffs are unchanged.
- **FR-013**: Worker events include fixed type, worker identity, phase/outcome, and bounded reason
  codes. They exclude prompts, secrets, provider text, and unbounded tracebacks.
- **FR-014**: Existing `run_agent()`, ordinary `resume`, population evolution, and detached
  ordinary solves retain their current behavior until explicitly migrated to this API.
- **FR-015**: No OpenCode plugin, remote FamouClient, SSE protocol, GPU sandbox, or multi-tenant
  service is introduced by this feature.

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

## Non-goals

No dynamic role prompt catalog, approval gate, remote cancellation promise, cumulative budget,
automatic retry, WebAgent effect/parity claim, or real provider campaign is included.
