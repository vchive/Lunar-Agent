# Validation — 2026-09-14

## Results

- Four-module focused regression: 251 passed in 24.97s across terminal publication, its Store
  operations, existing evolved materialization and Feature 088 output publication.
- Terminal publication and real-process concurrency modules: 51 passed in 10.53s. This overlaps
  the focused set; counts are not additive.
- Full repository regression: 2903 passed in 89.67s, including all quickstart scenarios.
- `ruff check src tests`, `compileall -q src tests`, Specify prerequisites with required tasks,
  and `git diff --check`: passed.
- All 601 tracked files under Feature 051/074/076/078/082 match the pre-feature HEAD.
- Independent Store and filesystem/controller final reviews: no remaining blocker.

## Recovery and integrity exercised

Succeeded, execution-failed and failed-before-execution results recover after prepared receipt,
marker publication, database commit, and before the completion receipt. Every recovery forbids
candidate execution and output publication and preserves the original prepared payload. Three
real child processes use `os._exit` at preparation, marker and commit boundaries. Two concurrent
processes demonstrably contend for the same child lock and return the same result while recording
exactly one terminal artifact and one event batch.

SQL faults at the artifact and each terminal event roll back the entire batch. Preparation
failure leaves no authoritative marker and does not permit unprepared recovery. Preparation or
commit that succeeded before raising is checked by a new database snapshot. Unqueryable commit
state preserves the successful prepared result and never rewrites it into a failure claim.

Partial rows/events, owner or journal drift, duplicate evidence, budget exhaustion, malformed JSON,
non-finite values, oversized results, unsafe nodes and absent databases are covered. Normal finite
validation measurements remain accepted. Previously completed results reject deleted marker,
artifact, artifact event, parent event, prepared/committed acknowledgement, stage or journal. A
retained completion receipt also rejects deletion of the entire terminal batch. A temporary
completion receipt has the same post-commit authority; it cannot authorize batch re-creation.

An intact marker/database batch may finish a missing completion receipt. A link followed by failed
directory fsync is resumed by syncing both the completion file and its directory. Prepared results
reject changed candidate, execution, output or marker evidence before making repairs. Legacy
success and failure fixtures retain their random artifact IDs and remain strictly read-only.

## Retained limits

Recovery begins at durable terminal preparation. Earlier interruption still requires diagnosis,
including process launch, execution evidence/artifact/event registration, and the interval after
output commit but before terminal preparation. There is no exactly-once execution claim. Feature
088's filesystem-prefix visibility limit remains. Retained staging has per-result bounds and no GC.

Advisory locks do not coordinate unrelated same-user writers. The protocol does not authenticate
against coordinated deletion or rewriting of every completion receipt and terminal database
record. No real model, provider, WebAgent, OpenEvolve/ShinkaEvolve producer, remote service or
campaign ran. Offline correctness results do not establish algorithm effectiveness or parity.
