# Validation: bounded recursive worker lifecycle

**Validated**: 2026-09-22
**Status**: Implemented and locally verified; provider-free only

Feature 146 is validated as a local WorkerService and AgentLoop extension. The default service
depth remains one. A configured recursive service accepts depths `0..N`, with a protocol maximum of
32 and at least `N + 1` executor slots. Worker-tool child creation requires a running parent, and
the cancellation race leaves a terminal child that cannot be resumed. Worker ancestry, result
reads, cancellation, and wait observations remain owner- and subtree-scoped.

The focused recursive suite passed **18 tests**:

```text
./.venv/bin/python -m pytest -q tests/test_agent_worker_tools.py tests/test_workers.py
18 passed
```

It covers a three-level AgentLoop spawn/wait chain, depth and executor bounds, stopped-parent
admission, ancestor cancellation through a grandchild while preserving an unrelated worker,
subtree result isolation, private workspaces, and clamping `wait_worker` to the enclosing
AgentLoop execution deadline.

The related shared selection passed **166 tests**:

```text
./.venv/bin/python -m pytest --disable-warnings -ra \
  tests/test_agent_worker_tools.py tests/test_workers.py \
  tests/test_worker_adapter_isolation.py tests/test_worker_bindings.py \
  tests/test_worker_delegate.py tests/test_worker_delivery_recovery.py \
  tests/test_worker_lifecycle_hardening.py tests/test_worker_process_ownership.py \
  tests/test_worker_result_envelope.py tests/test_worker_store_ownership.py \
  tests/test_store.py tests/test_agent_loop.py tests/test_staged_agent_loop.py \
  tests/test_run_wall_clock_budget.py
166 passed
```

Static checks also passed:

- `.venv/bin/ruff check src tests tools`
- `.venv/bin/python -m compileall -q src tests`
- `git diff --check`

The parent-running admission check and child insertion now execute after an explicit SQLite
`BEGIN IMMEDIATE`, serializing them with cancellation-tree mutations. A regression traces the
transaction ordering so a child cannot commit from a stale running-parent observation.

The existing SQLite schema was exercised through fresh Store fixtures; Feature 146 adds no schema
migration. No provider, campaign, remote worker, external producer, WebAgent, or generated source
execution was used. This validation does not claim automatic solve integration or a real-model
end-to-end result.
