# Validation — 2026-09-14

## Results

- Final seven-module quickstart: 532 passed in 91.29s, covering delivery, delivery Store and
  real-process concurrency, existing output materialization, execution registration, terminal
  publication and output publication.
- New delivery modules contain 249 cases: 94 controller/filesystem, one real-process concurrency,
  and 154 Store cases. These are included in the quickstart and full regression, not additive.
- Combined Store regression: 434 passed in 2.57s, covering delivery, execution, launch, terminal,
  output publication and base Store behavior; this overlaps the quickstart.
- Final full repository regression: 3450 passed in 173.17s.
- `ruff check src tests`, `compileall -q src tests`, Specify prerequisites with required tasks,
  and `git diff --check`: passed.
- All 601 tracked files under Feature 051/074/076/078/082 match pre-feature commit `6d6ad49`.
- Independent Store and filesystem/controller reviews, including re-review of the missing-plan
  recovery-order fix: no remaining blocker.

## Recovery and integrity exercised

Complete execution registration now authorizes independent validation and delivery preparation
when no downstream evidence exists. Success, failed process, timeout and output-validation failure
resume after execution preparation, execution commit and delivery preparation with one candidate
execution. Committed outputs are reused without invoking the promoter. Verified output rollback
finishes an explicit failed result with no outputs and no republication. All-optional absent outputs
can finish successfully without an output batch. Reused parent outputs retain their artifact IDs
and legitimate owners, including an owner from another parent task.

Four real controller subprocesses exit via `os._exit` after execution commit, plan registration,
output commit and terminal preparation. Each resumes to the exact terminal result without a new
candidate run. A separate process pair proves lifecycle-lock contention during delivery: a second
caller returns busy while the first owns the attempt, then reuses its completed result.

Plan registration uses a FULL SQLite transaction and confirms exact receipt state after a commit
exception. Unknown output commits cannot become fabricated failures. FS-only/DB-only plans,
duplicate or malformed JSON, nonfinite values, unsafe nodes, owner/identity/byte/validation drift,
and incomplete execution/output/terminal preparations preserve evidence and stop recovery.
Status probes and registration verify complete launch/execution authority in one snapshot; they
reject duplicate, partial or advanced ledger evidence. Read-only APIs do not create absent databases.
Surviving child output events and reserved parent output identities block inappropriate preparation
even after their artifact rows or kind fields are changed.

Completion faults retain the original terminal outcome. Either final or temporary delivery
completion requires intact committed terminal evidence, so deleted rows cannot be reconstructed.
An intact terminal can finish a missing delivery completion without database writes. A delivery
plan also prevents 091 from rebuilding a deleted execution batch.

Independent review found an ordering defect when complete modern execution had no delivery plan:
the old output recovery call could roll back an 088 pending batch before delivery rejected its
downstream evidence. The controller now skips writable output recovery in this state. A snapshot
regression verifies that the pending links and journal remain unchanged. Exact older prepared 089
results retain their existing recovery authorization after read-only output inspection; a second
regression proves completion without a new plan or candidate execution. Both reviews confirmed
the fix. Existing complete legacy terminal results remain replayable without migration.

Previous execution-only tests now stop at the execution-registration boundary to retain their
phase-specific assertions; the new tests cover continuation through delivery. Legacy fixtures
remove complete newer protocols before constructing genuine older records. Existing output
uncertainty tests now assert success or confirmed rollback failure once the database is queryable.

## Retained limits

Raw execution bytes and incomplete execution or delivery preparation still require diagnosis.
Recovery does not reconstruct missing candidate, execution or attempt output bytes. Exact output
and terminal preparation evidence is still required for their respective interrupted phases;
pre-journal output interruption retains 088's diagnostic boundary. A rolled-back batch is never
republished. Completion and plan records are bounded per attempt and retained without GC.

Feature 090's at-most-one authorized runner entry remains; this is not exactly-once execution or
guaranteed successful delivery. Recovery neither identifies nor kills surviving processes. The
generic runner and ordinary evolution evaluation paths remain unchanged. Advisory locks and
digests do not authenticate unrelated writers or coordinated removal of all protocol evidence.
Feature 088's filesystem-prefix visibility limit remains.

No real model, provider, WebAgent, OpenEvolve/ShinkaEvolve producer, remote service or campaign
ran. Offline correctness results do not establish effectiveness or parity. Earlier validation
counts and sealed measurement artifacts are preserved.
