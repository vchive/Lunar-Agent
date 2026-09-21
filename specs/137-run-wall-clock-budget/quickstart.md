# Offline verification

Feature 137 is implemented with deterministic local timeout fixtures. Run them before the shared
regression:

```sh
.venv/bin/pytest -q tests/test_run_wall_clock_budget.py \
  tests/test_controller.py tests/test_agents.py tests/test_runtime.py
.venv/bin/ruff check src/lunar_evolution/controller.py src/lunar_evolution/agents.py \
  tests/test_run_wall_clock_budget.py
.venv/bin/python -m compileall -q src tests
```

The fixtures use local runtimes/adapters that record the timeout received by every invocation. They
cover these cases:

1. `run_agent()` with an explicit timeout longer than the remaining run budget receives only the
   remainder; an exhausted run makes no adapter call.
2. Synchronous `resume()` runs two tasks under one deadline; the second request receives the
   reduced remainder and no new task is claimed after exhaustion.
3. Two concurrent workers receive invocation-time remainders from one shared deadline. A blocked
   worker can be cancelled or return late without extending its peer's timeout or producing a
   duplicate budget event.
4. Cancellation immediately before, during, and after a clipped request preserves the durable
   Store winner, fans out to every active runtime, and discards late results.

Inspect request values, task/attempt states, terminal run status, `budget_exceeded` event count,
artifacts, process cleanup and cancellation calls directly. The fixtures must not call a provider,
execute generated source, or touch Feature 134 evidence. Then run the two-stage regression and
Specify checks from [validation.md](validation.md). Passing these checks establishes local
deadline propagation and race behavior; it does not establish remote cancellation or real-agent
performance.
