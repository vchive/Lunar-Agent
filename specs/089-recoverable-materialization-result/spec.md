# Feature 089: Recoverable materialization result publication

**Created**: 2026-09-14
**Status**: Complete

## Problem and scope

After final candidate execution and Feature 088 output publication, the controller currently
writes `evolution/materialization/result.json`, adds its child artifact row, and appends the parent
materialization event separately. A crash between these steps leaves a valid result that resume
must reject. This feature completes an explicitly prepared terminal publication without running
the candidate again. It covers succeeded, failed and failed-before-execution terminal results.

## Requirements

- FR-089-01: Preserve the existing result payload and parent event shapes. Validate the contract,
  candidate, execution evidence, output publication and output artifacts before preparing or
  recovering a terminal result. Legacy results without modern publication evidence remain subject
  to strict read-only replay; never infer preparation from a loose legacy marker or execution file.
- FR-089-02: Stage bounded immutable result bytes and a strict journal under the child workspace.
  Persist a FULL-synchronous SQLite preparation receipt binding journal digest, result digest,
  parent/child/task and deterministic result artifact identity before publishing the final marker.
- FR-089-03: Publish the marker without replacing an existing node, fsync its file and directories,
  then atomically commit its child artifact, artifact event, existing parent materialization event
  and new commit acknowledgement in a FULL-synchronous SQLite transaction. Budget and ownership
  are rechecked inside the transaction. No partial terminal batch is accepted or repaired.
- FR-089-04: With exact prepared evidence and no terminal batch, recovery may publish the retained
  result bytes and complete the terminal transaction. With a complete batch it validates every
  binding. A durable filesystem completion receipt must exist before returning normally; it
  forbids repairing deleted database evidence or missing markers on subsequent replay.
- FR-089-05: Commit exceptions require a fresh exact database inspection. Unknown state, partial
  rows/events, conflicting markers, missing prepared evidence or drift preserve the attempt and
  stop delivery. Recovery never invokes a runner, scorer, generator or output promotion. It may
  complete a missing completion receipt only when marker and complete database batch both verify.
  A temporary completion receipt also proves a prior commit and forbids re-creating deleted batch
  rows. Recovery syncs an existing completion receipt before returning.
- FR-089-06: Serialize terminal publication/recovery with a local child lock; retain bounded
  staging, journal and completion receipt. Reject unsafe filesystem nodes and journal-free
  downgrade while modern SQLite evidence remains. Missing legacy markers still fail closed.
- FR-089-07: Cover failures before/after marker publication, within each database write, after
  commit, during completion receipt publication, process exit and repeated recovery. Preserve the
  existing cached-result tamper tests. Run full regression, static checks, Specify and sealed-file
  checks, and perform independent review.

## Limits

This closes the terminal publication gap once a durable preparation receipt exists. A process
interrupted before preparation, including the Popen-to-execution-evidence window, still requires
diagnosis. No exactly-once execution claim is made. Output batch visibility remains Feature 088's
SQLite logical boundary. The protocol assumes the local filesystem and SQLite honor successful
fsync/commit; it is not externally authenticated against coordinated same-user rewriting or removal
of every completion acknowledgement and terminal database record. No automatic staging GC, model,
real producer, external service or campaign is included; offline correctness is not effectiveness.
