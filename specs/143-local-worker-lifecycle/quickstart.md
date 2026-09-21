# Local worker API quickstart

From the repository's installed environment, run this provider-free Python example. It creates
only a temporary Store and one local Python process; it does not invoke a model or campaign.

```python
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from lunar_evolution.agents import AgentRegistry, CommandAgentAdapter
from lunar_evolution.store import Store
from lunar_evolution.workers import WorkerService

with TemporaryDirectory() as directory:
    root = Path(directory)
    store = Store(root / "state.db")
    store.initialize()
    registry = AgentRegistry([
        CommandAgentAdapter([sys.executable, "-c", "print('local worker completed')"]),
    ])
    service = WorkerService(store, registry, root / "sessions")
    try:
        worker = service.dispatch("local-owner", prompt="Run the configured local command", timeout=5)
        result = service.wait("local-owner", worker.id, timeout=10)
        assert result.outcome.value == "success"
        print(service.read_result("local-owner", worker.id))
    finally:
        service.close()
```

`dispatch` returns a stable worker identity. `wait` with an expired timeout reports the current
state without declaring failure. `cancel(owner_id, worker_id)` stops the owned subtree, while
`close()` stops only the service's own exact attempts. A runtime that cannot stop immediately
may still return late; its result cannot replace cancellation or a newer attempt.

For a runtime adapter, supply `RuntimeAgentAdapter(runtime, runtime_factory=make_runtime)`.
Each factory call must create an independent runtime, including its tools, session and cancellation
state. Custom adapters register with `registry.register(prototype, execution_factory=make_adapter)`.
Factories returning a registered or previously issued live instance are rejected. Ordinary
`AgentRegistry.select` callers retain their existing contract.

`send` queues input for the next explicit `resume`; it does not interrupt a live invocation.
Resume claims its attempt and consumes exactly the snapshotted messages in one transaction;
a stale input snapshot is rejected and messages arriving later stay queued.
After a process restart, `service.reconcile("local-owner")` inspects that caller's retained
attempts, cleans verified groups and marks verified interrupted work `lost`. Live services,
legacy attempts without an owner, missing lock evidence and uncertain cleanup are preserved.
Do not delete owner lock files to force recovery. A retained process registration blocks a new
attempt until cleanup is verified.

This is the typed local API. The foreground CLI `lunar-evolution delegate` now uses the durable
worker binding and result-delivery path described in the Feature 143 specification. AgentLoop
worker tools, recursive workers, and automatic solve integration remain outside this bounded
consumer; automatic multi-file background execution is Feature 142 Phase C.

A second `delegate --run-id` observation reuses an active binding. If another process is delivering
the result, `wait_timeout` still bounds the observation. After a delivery owner exits, an explicit
later observation can recover its reservation once it is stale (1–30 seconds, based on the original
active timeout), using the stored envelope without running the worker again. Missing/unsafe lock
evidence keeps the outcome unresolved. Cancellation cleans the exact abandoned staging batch.
