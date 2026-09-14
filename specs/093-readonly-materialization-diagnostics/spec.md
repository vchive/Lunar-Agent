# Feature 093: Read-only materialization diagnostics

**Created**: 2026-09-14
**Status**: Complete

## Problem and scope

The 088–092 protocols deliberately retain ambiguous evidence and stop. Users need a bounded
inspection command that identifies missing or abnormal records without invoking recovery.
Add `diagnose-materialization PARENT_RUN_ID EVOLUTION_RUN_ID [--home PATH] [--json]`.
It reports observations for launch, execution registration, delivery, outputs and terminal result.
It never assesses recovery eligibility or proves candidate/output validity or successful delivery.

## Requirements

- FR-093-01: Dispatch before ordinary CLI configuration initializes storage. Do not construct a
  controller/runtime, initialize/migrate storage, create source locks, or call recovery/publish APIs.
  Do not execute a candidate, rollback outputs, repair receipts, clean staging or write events.
- FR-093-02: Inspect only an existing database. Copy bounded, regular, non-symlink main DB and
  optional WAL bytes to private temporary storage; open SQLite only on the copy. Include committed
  WAL state. Reject unsafe nodes, a rollback journal, excessive sizes/rows/payloads, unreadable or
  changing source evidence. Source SHM is not copied. No source file content or directory entry
  may be changed; ordinary read access-time metadata is outside this guarantee.
- FR-093-03: Query the requested run pair, tasks and relevant event/artifact evidence in a bounded
  snapshot. Missing/ambiguous runs, malformed storage and unsafe workspaces produce fixed errors
  without raw database diagnostics, record contents, commands, logs, goals or absolute paths.
- FR-093-04: Report all five stages separately using fixed observation states. Inspect bounded
  protocol records and known attempt execution evidence. Distinguish absent, partial, malformed,
  unsafe and unreadable evidence; compare available receipt digests with the observed file bytes.
  Presence or structural matching is never called committed, successful or recoverable.
- FR-093-05: Open only existing safe lock files for nonblocking shared inspection, never create
  them. An active lifecycle/output/terminal publisher yields busy; missing locks are reported
  without creating them. Detect changes to inspected filesystem evidence and decline a stable
  report. This is a bounded observation, not an atomic filesystem/database validity proof.
- FR-093-06: Emit versioned JSON or concise human-readable output. Always report
  `recovery_eligibility: not_assessed`; fixed next-step guidance preserves evidence and leaves
  authorization checks to normal resume. Exit 0 means an inspection report was generated,
  including attention-required observations, not task success; busy/unavailable return 2.
- FR-093-07: Cover complete, prepared, fragmented, legacy, malformed, missing, concurrent and
  uncheckpointed-WAL fixtures. Assert unchanged source content/entries and no runtime/recovery
  calls. Run focused/full/static/Specify/sealed checks and independent review.

## Limits

This is a diagnostic inventory, not a second recovery validator. It does not inspect all candidate,
input or output bytes, authenticate unrelated writers, identify surviving processes, authorize
manual edits or automatically determine whether resume will succeed. A busy or changing source
should be inspected again after the operation settles. Records remain retained without GC.
No real model, provider, WebAgent, producer, remote service or campaign is run. Existing sealed
measurements and historical validation counts remain unchanged.
