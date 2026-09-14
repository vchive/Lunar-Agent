# Feature 088: Recoverable evolved output publication

**Created**: 2026-09-14
**Status**: Complete

## Problem and scope

Feature 036 publishes output files and SQLite artifact rows one at a time. Failure on the second
output can leave a first file and a committed artifact row even though materialization failed.
This feature provides a recoverable publication batch for evolved outputs. Ordinary Solver output
publication, candidate execution, evaluator authority, and historical measurements are unchanged.

## Requirements and acceptance

- FR-088-01: Validate every output and existing parent file/ledger before publication. Preserve
  identical pre-existing files and single matching output rows, including another parent task's
  row. Reject conflicts, duplicate rows, unsafe nodes, invalid JSON and over-budget batches.
- FR-088-02: Stage bounded output bytes on the parent filesystem and durably publish an immutable
  journal before creating any final file. Publish with no-clobber links; never replace existing
  parent files. Record which files existed before the batch. Sync reused files and destination
  directories before database commit, including deletions completed by an interrupted rollback.
- FR-088-03: Commit all new output artifact rows, artifact events, the promotion event and journal
  digest acknowledgement in one FULL-synchronous SQLite transaction. Second-row or event failure
  rolls back the whole database batch. Idempotent replay requires exact evidence, not ID alone.
- FR-088-04: On a confirmed uncommitted batch, roll back only newly linked files still matching
  staged inode and digest. Preflight the complete batch before deleting anything. Preserve existing
  files/rows. When commit or rollback is uncertain, retain evidence and reject terminal claims.
- FR-088-05: On resume, reconcile a present journal against SQLite before inspecting the terminal
  materialization marker. Committed batches require every output and row to match; uncommitted
  batches roll back safely. Recovery never invokes the candidate or invents missing execution or
  terminal evidence. A missing terminal marker after execution still fails closed under Feature 085.
  A retained SQLite acknowledgement forbids fallback to journal-free history when staging is lost.
  Replay binds the owner and requested bytes as well as the output contract.
- FR-088-06: Serialize publication/recovery for one parent with a local process lock. Reject
  filesystem aliasing and cross-volume destinations. Staging and journal evidence are bounded per
  batch and retained for replay/diagnosis; no automatic garbage collection in this feature.
- FR-088-07: Offline fixtures cover success, reused outputs, second-file/second-row/event failure,
  process interruption before/after database commit, repeated recovery, conflicts and drift. Run
  full regression, Ruff, compileall, Specify and sealed-file checks before closure.

## Limits

The atomic delivery boundary is the SQLite batch and its verified promotion evidence. Arbitrary
filesystem readers can observe a prefix of files while publication is in progress; multiple path
updates cannot be one filesystem operation. A crash may leave a prefix until explicit resume
reconciles the journal. No external authenticity is claimed against same-user coordinated changes.
This does not close the Popen-to-execution-evidence window or the separate terminal marker/ledger
gap. Interrupted preparation before the complete journal exists retains staging and requires
diagnosis; it cannot publish final files or be automatically retried. A rolled-back batch is
terminal for that evolution run identity. Paths with case/Unicode aliases or file/directory prefix
conflicts are rejected conservatively even when an optional output is absent. The lock coordinates
this module's local publishers; unrelated same-user file writers do not participate in the protocol.
No model, provider, WebAgent, real producer, remote service or campaign is started, and there
is no effectiveness claim.
