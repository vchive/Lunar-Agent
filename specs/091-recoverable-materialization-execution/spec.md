# Feature 091: Recoverable materialization execution registration

**Created**: 2026-09-14
**Status**: Completed

## Problem and scope

Feature 090 prevents duplicate final-candidate launch, but execution artifacts and events are
still registered separately after the runner returns. An interruption can leave incomplete
execution ledger evidence that prevents even existing output/terminal recovery. Introduce an
explicit preparation and atomic execution registration for new final materializations.

The recovery boundary begins only after durable execution preparation. Raw execution.json,
temporary runner evidence, or a launch intent alone never authorizes creating that preparation
on resume. This feature registers execution evidence; it does not infer a terminal result, resume
output validation/promotion without a prepared terminal result, or change the generic runner.

## Requirements

- FR-091-01: After the final runner returns, validate its exact canonical, bounded execution.json
  against the returned CandidateExecution and intact 090 launch intent. Reject temporary runner
  evidence, unsafe nodes, changed candidate/launch/execution identity and unexpected old rows.
  Sync execution and its directory chain before preparing an immutable execution journal.
- FR-091-02: Bind parent/child/unique task, launch-intent digest, execution path/digest/size/inode
  and a deterministic artifact ID in a bounded canonical journal. Sync journal and directories,
  then record one FULL-synchronous SQLite prepared receipt. Only a first returned execution can
  initiate preparation; existing raw execution evidence cannot be upgraded implicitly.
- FR-091-03: One FULL-synchronous transaction records the execution artifact, artifact_recorded,
  existing evolved_candidate_executed and a committed acknowledgement. Preserve the existing
  execution and event schemas. Validate exact intent ownership and the entire batch in one
  database snapshot. Existing partial/conflicting rows are rejected, never completed piecemeal.
- FR-091-04: Resume under 090's lifecycle lock may register only an exact prepared execution
  whose batch is wholly absent, with no advanced output/terminal evidence. A filesystem completion
  receipt, including its temporary node, proves post-commit state and forbids rebuilding missing
  ledger evidence. Intact committed batches may finish a missing completion receipt. Requery
  unknown commit results before writing any new outcome; unqueryable state preserves evidence.
- FR-091-05: Check 091 evidence before 090's independent execution gate and any 088/089 mutation.
  Without any 091 evidence, preserve strict legacy execution replay. Modern evidence cannot
  downgrade when its journal is missing. Terminal validation also rechecks modern execution
  publication integrity. Missing 089 preparation still refuses automatic finalization after
  execution reconciliation; candidates and outputs are not reexecuted or newly published.
- FR-091-06: Offline tests cover successful/failed/timed-out execution, SQL rollback, postcommit
  exceptions, filesystem sync interruption, real controller exits, repeated recovery, evidence
  loss/drift, legacy behavior, and lifecycle concurrency. Complete independent review, full
  regression, static/Specify checks and unchanged sealed feature verification.

## Limits

An interruption before exact preparation remains unknown even if execution.json exists. Missing
execution bytes are never reconstructed. Recovery does not identify surviving processes, provide
exactly-once execution, or guarantee final delivery. Output-commit-to-terminal-preparation recovery
remains separate. Completion receipts and journals have bounded size and no GC. Advisory locks
do not authenticate unrelated same-user writers or coordinated removal of all completion and
database commit evidence. No real model, provider, producer, remote service, WebAgent or campaign
runs; offline correctness does not establish algorithm effectiveness.
