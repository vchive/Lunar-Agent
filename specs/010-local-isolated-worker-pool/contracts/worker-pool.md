# Contract: Local Worker Pool

## Python API

```python
LocalController(
    config,
    runtime,
    ..., 
    runtime_factory: Callable[[], Runtime] | None = None,
    max_workers: int = 1,
)
```

- `max_workers < 1` raises `ValueError`.
- `max_workers > 1` without `runtime_factory` raises `ValueError` before a run is claimed.
- A factory exception is recorded as the affected task's runtime failure and follows normal retry
  policy; it never falls back to sharing the controller runtime.

## CLI

`run`, `resume`, `answer`, and `plan` accept `--workers N` (positive integer, default `1`). The
option is propagated through detached resume commands. Run-handle JSON adds:

```json
{"run_id":"…", "status":"succeeded", "workers":2, "workspace":"…"}
```

Existing keys retain their meaning. `status --json` continues to report durable task state; worker
parallelism is invocation metadata, not a durable run state.

## Event and artifact contract

Every worker emits the same event types and artifact kinds as the serial controller. Events must
carry their task ID. Prompt/result/evaluation artifacts are stored below
`tasks/<task-id>/<attempt-id>/`; concurrent tasks must never write another task's directory.

## Ordering contract

For every dependency edge `A -> B`, `task_claimed(B)` occurs only after `task_succeeded(A)` for the
same run. No more than `N` attempts may have status `running` when `max_workers=N`.
