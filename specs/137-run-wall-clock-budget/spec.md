# Feature Specification: Run wall-clock budget propagation to active Agent requests

**Created**: 2026-09-18  
**Status**: Specification-first  
**Input**: The existing `BudgetSpec.max_runtime_seconds` guard, Controller Agent/runtime
boundaries, Feature 133 preparation budgets, and the Feature 136 offline-only boundary.

## Problem

`BudgetSpec.max_runtime_seconds` is currently checked before claiming work and after a task or
delegated Agent returns. The request running between those checks still receives the complete
`Config.runtime_timeout` (or the complete explicit delegation timeout). A long Agent invocation
can therefore outlive the run's remaining wall budget, and concurrent workers can each start with
a full request timeout even though they share one run budget. The existing budget failure event
and cancellation fan-out are useful boundaries; this feature makes the remaining run time an
input to those active requests without changing their authority or retry semantics.

## User scenarios

### US1 - Delegate one Agent inside the remaining run budget (P1)

`run_agent()` selects an adapter and sends an `AgentRequest`. The request timeout is the smaller
of the existing configured/explicit delegation timeout and the positive remainder of the run's
wall budget. When no remainder is available, the controller records the existing typed
`max_runtime_seconds` budget failure and does not claim or invoke the adapter.

### US2 - Bound synchronous and concurrent `resume` work (P1)

One `resume()` call creates one monotonic deadline for the run execution and shares it with every
task worker. Each runtime request receives the smaller of `Config.runtime_timeout` and the
remaining seconds at that worker's invocation. A worker must not reset the deadline for a new
task, and a concurrent worker must not obtain a fresh full timeout merely because it was submitted
later. Once the shared deadline is exhausted, no additional task is claimed and the existing
budget failure path settles the run.

### US3 - Preserve cancellation when it races with a deadline (P1)

`cancel()` continues to mark the run/tasks cancelled, fan out `runtime.cancel()` or adapter
cancel requests, and terminate a detached process group. A result that returns after cancellation
is discarded by the existing late-result boundary. If cancellation is durably observed first,
the run remains cancelled and is not rewritten as a budget failure; if the budget failure is
durably recorded first, the run remains failed with its one idempotent `budget_exceeded` event.
Neither outcome claims that a remote provider stopped at the local deadline.

## Definitions and authority

For one active `run_agent()` or `resume()` controller execution, record `started = monotonic()`
after loading/recovering the run and before the first budget admission check. Define the shared
deadline as:

```text
deadline = started + budget.max_runtime_seconds
remaining = deadline - monotonic()
```

The deadline is shared by all synchronous work and all workers spawned by that controller call;
it is not reset per task, retry, adapter request, or worker submission. A later explicit
continuation is a separate controller execution with its own existing run lifecycle. This feature
does not add a persisted monotonic timestamp or a database migration. `BudgetSpec` remains the
durable authority for the maximum; a monotonic clock remains the admission authority for the
active process.

`remaining` is clipped to the positive finite value accepted by the runtime/adapter timeout
contract. A non-positive remainder is budget exhaustion, not a zero-second request. The existing
`_check_budget()`/`_budget_fail()` path persists `limit=max_runtime_seconds`, bounded actual and
maximum values, transitions unfinished work according to the current Store contract, and raises
`BudgetExceeded`.

## Requirements

### Deadline and request propagation

- **FR-001**: `run_agent()` and `resume()` must create one shared monotonic deadline from the
  active execution's `started` value and the run's `BudgetSpec.max_runtime_seconds`. All budget
  admissions and request timeout clipping in that execution use this deadline.
- **FR-002**: Before claiming work and before each request, compute a fresh positive remaining
  duration from the same deadline. A request's effective timeout is
  `min(existing_request_timeout, remaining)`; it must never be increased. The existing finite
  timeout validation, including explicit `run_agent(timeout=...)`, remains in force.
- **FR-003**: If the remainder is non-positive before a claim or Agent/runtime invocation, use
  the existing `BudgetExceeded("max_runtime_seconds", ...)` persistence path and do not claim,
  start, retry, or invoke that work. The failure payload contains no prompt, response, provider
  usage, or inferred remote state.
- **FR-004**: `run_agent()` places the clipped timeout in the immutable `AgentRequest` delivered
  to the selected adapter. `RuntimeAgentAdapter` and its wrapped runtime must receive the same
  effective timeout; candidate-generation timeout narrowing remains an independent, tighter
  boundary when present.
- **FR-005**: `_execute_task()` passes the clipped timeout to `runtime.run()` for every normal
  `resume()` worker. The call must use the run deadline even when `max_workers > 1`; workers do
  not each receive `Config.runtime_timeout` as a fresh allowance.
- **FR-006**: A finite configured/runtime timeout remains finite and positive. No new `None`,
  zero, negative, NaN, infinity, token, cost, tool-step, artifact, or task limit is invented by
  clipping. Existing runtime and adapter implementations that accept `float | None` remain
  compatible.

### Completion, failure, and concurrency

- **FR-007**: Keep the existing post-request budget check. If a runtime returns after the deadline,
  the controller may retain the existing bounded local session/result artifacts already written
  before that check, but it must not publish a successful task, promote outputs, evaluate a new
  retry, or deliver a child after `max_runtime_seconds` is observed.
- **FR-008**: A shared deadline exhaustion in synchronous or concurrent `resume()` causes one
  idempotent budget failure event and prevents further claims. Other workers already in flight
  receive their clipped request timeout, are allowed to unwind, and cannot overwrite the durable
  failure with a success or an unbounded retry.
- **FR-009**: Cancellation remains a separate terminal authority. The race is resolved by the
  durable Store transition: cancellation first preserves `cancelled` and late results are
  discarded; budget failure first preserves `failed` and its existing evidence. Cleanup must
  continue to all active runtimes/adapters even when one cancellation callback raises.
- **FR-010**: The existing process observer, active-runtime/adapter registries, process-group
  termination, `settle_run()`, and recovery of stale runners remain compatible. No remote
  cancellation or provider completion is inferred from a local timeout.
- **FR-011**: The run's persisted `BudgetSpec` and existing `budget_exceeded` event shape remain
  compatible. If bounded timeout observation is surfaced, it contains only local elapsed,
  maximum, effective request timeout, and a fixed stage/category; arbitrary exception prose is
  excluded.

### Preservation and measurement boundaries

- **FR-012**: Existing adapter request identity, prompt bytes, task workspace, replayable
  transcript, runtime events, retry policy, evaluator invocation, and cancellation semantics stay
  compatible except for the effective timeout value passed to an active request.
- **FR-013**: `Config.runtime_timeout` remains the per-request ceiling and is never rewritten in
  configuration or persisted run/profile data. An explicit `run_agent(timeout=...)` value remains
  request-local and is only narrowed by the shared deadline.
- **FR-014**: Feature 134's registration, manifest, product/measurement pins, preparation and
  campaign budgets, postrun diagnosis, report, results, audit, evidence inventory, denominator,
  and failure interpretation remain byte-for-byte unchanged. This feature uses deterministic
  offline fixtures and does not rerun, resume, append to, or repair that campaign.
- **FR-015**: No real model/provider request, new campaign, WebAgent measurement, evaluator
  quality claim, CLI policy, schema migration, or detached-run redesign is authorized by this
  specification. A future real run requires a fresh SDD, pushed product, fixed conditions, and a
  unique registration/slot.

## Acceptance criteria

1. A deterministic `run_agent()` fixture with a run budget of 10 seconds and an explicit request
   timeout of 30 seconds receives a timeout no greater than the measured remaining budget. An
   already-exhausted fixture records `max_runtime_seconds` and invokes no adapter.
2. A synchronous `resume()` with two tasks computes one deadline; the second task receives only
   the remainder after the first task, never a fresh configured timeout. The run fails closed when
   no positive remainder remains and no later task is claimed.
3. A `max_workers=2` fixture records both worker request timeouts from the same deadline. A delayed
   worker cannot extend the other worker's allowance or cause a second budget event; all in-flight
   workers unwind and the run settles deterministically.
4. Runtime/adapter request copies, prompts, transcripts, events, and persisted `BudgetSpec` bytes
   contain no mutable deadline object and no stale timeout from an earlier request. Explicit
   delegation timeout validation and candidate-generation timeout narrowing remain intact.
5. A runtime that returns after its clipped timeout yields existing bounded failure/late-result
   behavior. It cannot promote outputs, publish success, or retry after the post-request budget
   guard observes exhaustion; no remote completion or cancellation is inferred.
6. Cancellation immediately before, during, and immediately after a clipped request preserves
   the Store winner: cancelled runs retain cancellation and discard late results; budget-first
   runs retain one `budget_exceeded` event and failed status. Cancellation fan-out reaches every
   active worker even if one callback fails.
7. Existing controller, runtime, adapter, retry, evaluator, process cleanup, and full offline
   regressions pass. Feature 134 retained files and hashes remain unchanged.

## Non-goals and limits

This feature does not guarantee that a model stops at the exact deadline, cancel remote provider
work, add a second token/cost/tool budget, change the configured runtime timeout, roll back files
written before a post-request check, or make a wall deadline survive a detached process restart.
It does not reset a deadline after cancellation, input waiting, task retry, or worker completion,
and it does not infer quality, usage, or WebAgent parity from timeout behavior.
