# Feature 090: Durable materialization launch intent

**Created**: 2026-09-14
**Status**: Completed

## Problem and scope

The final materialization runner currently records execution only after its subprocess returns.
If the controller exits after Popen but before execution evidence, resume can mistake the attempt
for unused staging, delete it and launch the same candidate again. Concurrent materialization
calls can also pass the absence check together. This feature records launch intent durably before
entering the final runner and serializes the complete controller materialization lifecycle.

The generic candidate runner and ordinary evolutionary evaluations are unchanged. This feature
prevents automatic relaunch of a possibly executed final attempt; it does not infer completion or
repair the separate execution artifact/event registration gap.

## Requirements

- FR-090-01: A nonblocking child lock covers output/terminal recovery, marker checks, staging
  cleanup, final candidate launch and publication. A concurrent caller fails with a bounded busy
  error. Validate the parent/child contract and selected candidate before obtaining a writable
  lock, and revalidate after acquiring it before mutating the materialization attempt.
- FR-090-02: After input preparation, Python eligibility and runner construction, persist a strict
  bounded immutable launch-intent file outside the cleanup target. Bind parent/child/task,
  contract, candidate ID/path/digest, attempt, runner fingerprint and effective timeout. Sync the
  file and directory chain, then register its digest in one FULL-synchronous SQLite transaction.
  The runner is callable only after both exact filesystem and database evidence are confirmed.
- FR-090-03: Only the current first preparation may authorize one runner invocation. An existing
  exact intent is observation, never new launch permission. Any final/temporary intent node,
  malformed or partial evidence, or retained modern database event prevents attempt cleanup and
  relaunch. Missing filesystem evidence cannot downgrade a modern attempt to unused staging.
- FR-090-04: Completed terminal results and Feature 089 prepared terminal recovery still work
  after validating any present launch evidence and its complete independently recorded execution.
  Such execution also permits Feature 088's existing output validation and safe rollback. Without
  a validated cached or explicitly prepared terminal result, resume preserves the attempt and
  reports unknown outcome without running a candidate, publishing new outputs or creating a
  terminal claim. Launch evidence also requires real execution
  evidence in a terminal result; an ambiguous runner exception cannot become execution=None.
- FR-090-05: Legacy results without launch evidence keep strict read-only replay and existing
  execution-marker refusal. Truly unused pre-execution staging may still be cleaned once. Input
  or unsupported-language failures before launch preparation keep existing failure semantics.
- FR-090-06: Offline tests cover interruption before/after intent commit, after actual process
  start without execution evidence, unsafe nodes and evidence drift, missing intent with retained
  SQLite evidence, runner exceptions, completed replay, and real-process concurrent calls. Run
  full regression, static/Specify/sealed checks and independent review before completion.

## Limits

An intent does not prove that Popen happened. Exiting after intent but before the call deliberately
leaves an unknown attempt that will not automatically retry. This is an at-most-one authorized
runner-entry guarantee under the protocol, not exactly-once execution or guaranteed completion.
The runner's descendants may outlive a crashed controller; recovery neither guesses process
identity nor kills unrelated processes. Unrelated same-user writers and coordinated removal of all
filesystem and database intent evidence are outside the authenticity boundary. A launch intent
does not repair execution evidence, execution ledger/event or pre-terminal preparation gaps.
Evidence is bounded per attempt and retained without GC. No real model, producer, remote service,
WebAgent or campaign is started; offline correctness does not establish effectiveness.
