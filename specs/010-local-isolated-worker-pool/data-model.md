# Data Model: Local Isolated Worker Pool

## Controller configuration

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `runtime` | `Runtime` | required | Legacy adapter used when `max_workers == 1`. |
| `runtime_factory` | `Callable[[], Runtime] \| None` | `None` | Creates one fresh adapter per concurrent task. |
| `max_workers` | `int` | `1` | Maximum active tasks for this controller invocation. |

`max_workers` is controller-local and is not persisted as run truth. The selected value is emitted
in run-handle JSON for parent-Agent observability; task state and attempts remain in SQLite.

## Worker context

Each submitted task owns an ephemeral `WorkerContext` containing:

- the claimed `Task` and `Attempt`;
- its runtime instance;
- run/task/attempt workspace paths;
- event sink closure scoped to the task;
- process observer closure scoped to the attempt;
- cancellation and completion bookkeeping held by the controller.

No context object is shared between workers. Durable records continue to use the existing `tasks`,
`attempts`, `events`, and `artifacts` tables; no migration is required.

## State transitions

```text
ready|uncertain --claim_task--> running --finish_task--> succeeded|failed
                                   |                    \
                                   +--await_input------> waiting
                                   +--retry_task-------> ready
run cancellation -------------------------------> cancelled
```

Dependencies are promoted by `Store.next_task()` only after every predecessor is `succeeded`.
Independent roots can therefore be claimed by different workers; a dependent task is claimed in a
later scheduling batch.

## Failure and cancellation records

- Runtime exceptions are sanitized and persisted exactly as in the serial path.
- A worker that observes a cancelled/non-running task invokes `discard_attempt_outputs` and emits
  `task_result_discarded`.
- `Store.cancel_run` marks all non-terminal tasks and running attempts cancelled. The controller
  then signals every active runtime instance.
- Existing `recover_running` converts tasks left running after a controller restart to `uncertain`;
  a later resume may claim them with fresh worker runtime instances.
