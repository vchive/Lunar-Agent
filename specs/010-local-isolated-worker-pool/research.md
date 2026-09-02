# Research: Local Isolated Worker Pool

## Decision 1: Local thread pool over process pool

**Decision**: Use `concurrent.futures.ThreadPoolExecutor` inside one controller process.

**Rationale**: Runtime adapters already perform blocking HTTP/subprocess I/O, SQLite is configured
for WAL, and threads preserve the simple Runtime protocol and durable workspace paths. A process
pool would require pickling arbitrary adapters, duplicate cancellation metadata, and complicate
the local-only contract.

**Alternative rejected**: Process pool; it cannot reliably clone user-supplied runtime objects and
would make task cancellation and event ownership harder to audit.

## Decision 2: Factory is the isolation boundary

**Decision**: Keep the existing `runtime` object for the compatible single-worker path and add an
optional `runtime_factory`. Parallel execution requires a factory that returns a fresh adapter for
each task.

**Rationale**: Runtime adapters contain mutable context (`set_context`, transcript, event sink,
observer, and cancellation). Shallow copying would leak locks, model sessions, or transcript state.
An explicit factory makes ownership visible and lets the CLI recreate repository-owned adapters.

## Decision 3: Batch ready tasks, then refill

**Decision**: The controller claims up to the available worker slots, submits them, waits for the
batch to finish, and repeats. SQLite remains authoritative for each claim.

**Rationale**: A batch avoids a scheduler thread and makes budget/cancellation behavior predictable.
After each batch, dependency promotion observes committed predecessor states before dependent work
is claimed. Claim races are harmless because `claim_task` is conditional and atomic.

## Decision 4: Run-scoped budget checks are conservative

**Decision**: Check the existing run budget before each claim and after each task, as well as when a
worker records a result. Concurrent workers may observe the same ledger snapshot; a limit breach
fails the run durably and prevents further claims. No limit is increased automatically.

**Rationale**: SQLite transactions make state transitions safe, while exact reservation accounting
would require a schema migration and would alter existing budget semantics. The controller errs on
the side of stopping before another claim once a limit is observed.

## Decision 5: Cancellation is cooperative plus durable

**Decision**: `cancel` marks the run/tasks cancelled transactionally, then calls `cancel()` on all
currently active runtime instances. Each worker checks task state before committing output, so late
results are discarded.

**Rationale**: Adapters differ in how quickly they stop. Durable state and the existing late-result
discard path provide the safety boundary even if a runtime ignores cancellation.
