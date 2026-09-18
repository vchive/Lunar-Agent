# Implementation Plan: Propagate run wall-clock remainder to active Agent requests

**Date**: 2026-09-18  
**Spec**: [spec.md](spec.md)

## Technical approach

1. Trace the controller paths from `run_agent()` and `resume()` through `_execute_task()`,
   `AgentRequest`, `RuntimeAgentAdapter`, and `Runtime.run()`. Preserve the existing adapter
   selection, task claim, process observer, cancellation, artifact, retry, and settle boundaries.
2. Add a small controller-local deadline helper that validates the run budget, computes one
   monotonic `deadline = started + max_runtime_seconds`, returns a fresh positive remainder, and
   routes non-positive values through `_check_budget()`/`_budget_fail()`. Keep the helper free of
   wall-clock timestamps and persistent state.
3. In `run_agent()`, run the existing pre-claim admission first, then clip the validated explicit
   or configured delegation timeout to the remaining duration immediately before constructing the
   immutable `AgentRequest`. Do not mutate the caller's explicit timeout or `Config`.
4. In `resume()`, pass the same deadline (or an equivalent immutable deadline value) through the
   synchronous and `ThreadPoolExecutor` paths. Compute the runtime timeout at the point each
   worker is about to invoke `runtime.run()`, so queueing and earlier workers consume the shared
   budget. Do not submit new work after an exhausted pre-claim check.
5. Keep the existing post-request `_check_budget()` and `BudgetExceeded` handling. Ensure a
   budget exception from one concurrent worker is observed without masking cancellation or
   skipping cleanup of other active runtimes. Preserve the Store's idempotent event and terminal
   status precedence rather than adding a second failure event.
6. Add focused deterministic tests using synthetic clocks/runtimes/adapters. Assert timeout
   values at every request boundary, shared behavior under parallel workers, no request after
   exhaustion, and cancellation races. Keep existing tests for configured runtime timeouts and
   candidate budgets unchanged except where the narrowed value is the intended assertion.
7. Run focused controller/adapter/runtime tests, lint, compileall, Specify checks and the full
   two-stage regression. Inventory Feature 134 files and hashes before commit; stop on any
   historical diff.

## Proposed contract names

Names may follow repository style, but the behavior should be recognizable as:

- `RunWallDeadline` or an equivalent immutable controller-local value containing the monotonic
  deadline and `max_runtime_seconds` authority.
- `remaining_run_timeout(deadline, now)` returning a validated positive finite duration or
  raising through the existing `max_runtime_seconds` budget boundary.
- `effective_request_timeout(configured_timeout, remaining)` returning the smaller finite value.

These names need not become a public CLI or persisted schema. The `AgentRequest.timeout` and
`Runtime.run(..., timeout=...)` values are the observable contract.

## Alternatives rejected

- Passing `Config.runtime_timeout` unchanged and relying only on post-request checks leaves an
  active request free to outlive the run budget.
- Giving every worker its own `started` timestamp resets the allowance under concurrency and makes
  the run budget meaningless.
- Persisting a monotonic timestamp or converting it to wall-clock time would require a schema,
  suspend/resume clock policy, and detached-process semantics outside this focused propagation
  feature.
- Passing zero/negative timeout to runtimes would conflate budget exhaustion with a runtime
  timeout and would violate existing positive-timeout contracts; exhaustion must fail before the
  request instead.
- Calling `cancel()` solely because a local deadline elapsed would change the existing ownership
  and cancellation race. Request clipping plus the current budget guard provides the bounded local
  behavior while retaining explicit user cancellation.
- Retrying an invocation with a fresh timeout or extending the deadline would create unregistered
  work and weaken the persisted budget authority.

## Verification strategy

Use deterministic fake monotonic clocks and runtimes that record every timeout, block on an event,
and return late or after cancellation. Cover run-agent explicit/configured timeout clipping,
synchronous resume, two-worker resume, no-remainder admission, post-request exhaustion, and
cancel-before/cancel-during/cancel-after races. Assert Store event counts, terminal status,
attempt/task states, cleanup, and absence of stale request copies. Then run the shared controller,
agent, runtime, budget and cancellation regressions, Ruff, compileall, Specify prerequisites,
`git diff --check`, and the full two-stage suite. Do not call a provider or execute retained
generated source.
