# Validation — 2026-09-14

## Results

- Final seven-module quickstart: 359 passed in 64.02s, including execution publication,
  execution concurrency/Store, existing materialization, launch, terminal publication and
  launch concurrency.
- Execution publication and real-process concurrency modules: 98 passed in 26.19s.
- Final combined Store regression: 280 passed in 1.86s, including 87 new execution Store tests.
  These focused counts overlap and are not additive.
- Final full repository regression: 3201 passed in 136.98s.
- `ruff check src tests`, `compileall -q src tests`, Specify prerequisites with required tasks,
  and `git diff --check`: passed.
- All 601 tracked files under Feature 051/074/076/078/082 match pre-feature commit `2e3cd95`.
- Independent Store and filesystem/controller reviews, including re-review of the surviving
  child output event fix: no remaining blocker.

## Recovery and integrity exercised

Successful, failed and timed-out executions recover registration after exact preparation, SQLite
commit and completion link interruption. Two real controller subprocesses use `os._exit` after
preparation and commit; repeated resume retains the original execution bytes and counter of one.
Another real process pair proves lifecycle-lock contention during recovery. Missing terminal
preparation still raises the existing missing-marker error after successful reconciliation, with
no runner calls, output publication or terminal claims.

Every execution batch insert failure rolls back the transaction. Successful preparation/commit
followed by an exception requires fresh exact confirmation. Unqueryable commit state preserves
evidence and never becomes a fabricated failed terminal result. File/directory sync faults,
completion partial writes and missing completion receipts exercise the durability boundary.

Tests reject return-value/file mismatch, temporary runner evidence, raw-only or fragmented
preparation, unsafe nodes, malformed/duplicate-key/nonfinite JSON, content/inode/owner drift,
missing individual records, retained completion with deleted whole batches, downstream evidence
with missing batches, and missing modern journals. Status and writes recheck exact launch intent
in the same SQLite snapshot. Store probes preserve ordinary legacy records, budgets apply to
preparation and commit, and read-only APIs never create absent databases.
An independent review found that a child output artifact row could be removed while retaining
its artifact event. The final fix rejects that surviving downstream event in both absent and
prepared states before any status-based repair, without rejecting other children's parent outputs.

Existing materialization tests now inject the pre-preparation interruption at its new Store
boundary. The pre-launch-protocol legacy fixture creates the actual old execution registration
without modern execution receipts before removing launch evidence; it verifies read-only replay
instead of simulating legacy by partially deleting modern records.

## Retained limits

Recovery starts at exact filesystem and SQLite preparation. A raw execution.json or an interrupted
preparation remains insufficient even if the candidate already ran. Missing execution bytes are
never rebuilt. Reconciliation of the execution ledger does not authorize resuming output
validation, publishing new outputs, or creating a missing terminal preparation. Those phases
remain a separate recovery boundary.

Feature 090's at-most-one authorized runner entry still applies; this is not exactly-once
execution or guaranteed completion. Recovery neither identifies nor kills surviving processes.
The generic runner and ordinary evolution evaluations remain unchanged. Per-attempt records
are bounded and retained without GC. Advisory locks do not authenticate unrelated same-user
writers or coordinated removal of all completion/downstream and database commit evidence.
Feature 088's filesystem-prefix visibility limit remains.

No real model, provider, WebAgent, OpenEvolve/ShinkaEvolve producer, remote service or campaign
ran. Offline correctness results do not establish effectiveness or parity.
