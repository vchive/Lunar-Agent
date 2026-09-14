# Validation — 2026-09-14

## Results

- Seven-module quickstart regression: 252 passed in 34.47s across launch, lifecycle concurrency,
  durability faults, launch Store, existing materialization and terminal publication/concurrency.
- Full repository regression: 3016 passed in 102.26s, including all quickstart scenarios.
- New launch durability module: 10 passed in 1.84s. This overlaps the quickstart set; counts
  are not additive.
- `ruff check src tests`, `compileall -q src tests`, Specify prerequisites with required tasks,
  and `git diff --check`: passed.
- All 601 tracked files under Feature 051/074/076/078/082 match pre-feature commit `a28411a`.
- Independent Store and filesystem/controller reviews found no remaining blocker after the
  reported RuntimeError classification gap was fixed and verified in both regression sets.

## Recovery and integrity exercised

Interruption after durable intent but before runner entry preserves the unused attempt and refuses
automatic execution. A real local candidate writes its execution counter, then its controller
uses `os._exit` inside Popen's return boundary before any execution file is published. Repeated
resume keeps the counter at one and changes neither retained files nor ledger rows.

Two real controller processes compete for the first materialization. The first holds a barrier
after authorization; the second must return `materialization_already_running` before the first
is released. A later cached call reuses the one execution and terminal result. Ordinary runner
exceptions, including RuntimeError, become a fixed unknown-outcome error without a fabricated
pre-execution failure or terminal claim. BaseException still crosses the interruption boundary.

Completed success and failure results replay with a different requested timeout without execution.
Feature 089 prepared terminal recovery requires intact launch and independently recorded execution
evidence. Missing or changed intent/event, duplicate ownership evidence, unsafe filesystem nodes,
temporary-only fragments and an exact repeated prepare request never authorize a new launch.
True pre-execution failures and legacy complete results retain their existing semantics.

Source file/directory sync failures before any intent allow one safe later execution. Partial
writes, zero write progress, temporary-directory sync, intent-file sync and post-link directory
sync failures retain uncertainty and refuse repeated cleanup or execution. A commit that succeeds
before raising may authorize only the same first caller after a fresh exact probe. If that probe
is unavailable, both committed and uncommitted cases preserve the attempt and grant no later
launch permission.

Store tests cover FULL-synchronous transactions, deterministic event identity, exact unique
parent/child/task ownership, canonical bounded intent, event insert failure, conflicting evidence,
malformed data and missing databases. Read probes do not create absent databases. Store's
idempotent registration never provides replayable controller launch permission.

## Retained limits

The intent records authorization, not proof that Popen happened. A controller interruption after
intent can leave zero executions and still require diagnosis. The guarantee is at most one
authorized runner entry under this protocol, not exactly-once execution or guaranteed completion.
Candidate processes may outlive a crashed controller; recovery does not guess identity or kill
unknown processes. The generic runner and ordinary evolutionary candidate paths are unchanged.

Execution file/artifact/event reconciliation and recovery before terminal preparation remain
unimplemented. Complete execution evidence is required before existing Feature 088 recovery can
validate or safely roll back output publication, or Feature 089 can resume a prepared terminal
result. An intent alone cannot repair execution or infer a terminal result.

Advisory locks do not coordinate unrelated same-user writers or authenticate coordinated removal
of all filesystem and database intent evidence. Retained records have per-attempt bounds and no
GC. Feature 088's filesystem-prefix visibility boundary remains. No real model, provider,
WebAgent, OpenEvolve/ShinkaEvolve producer, remote service or campaign ran; offline correctness
does not establish effectiveness or parity.
