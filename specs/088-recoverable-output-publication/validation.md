# Validation — 2026-09-14

## Results

- Focused quickstart: 196 passed in 15.30s across output publication, Store publication,
  process contention and controller materialization tests.
- Full repository regression: 2787 passed in 83.45s.
- `ruff check src tests`, `compileall -q src tests`, Specify prerequisites with required tasks,
  and `git diff --check`: passed.
- All 601 tracked files under Feature 051/074/076/078/082 match the pre-feature HEAD.
- Independent Store review and final module/controller review: no remaining blocker.

## Evidence exercised

The offline fixtures cover successful multi-output commit, exact replay, existing identical files
and another parent task's ledger row, per-batch budget, second-link failure, second-artifact and
artifact-event failure, promotion-event failure, and failure after an actual database commit.
Commit queries that become unavailable preserve evidence and do not generate a terminal claim.
Conflicting ownership, reserved partial rows and orphan events are rejected before final links.

Real child processes exit after the first link and after database commit. Recovery either removes
the uncommitted owned links or verifies the committed batch. A separate interruption during
rollback verifies that a later process syncs the already-deleted path's directory before recording
rollback. Two real publishers contend for the same parent lock during staging and both return the
same outputs, with one artifact batch and one promotion/commit event pair.

Changed requests, contract projections, stage inodes, target files, journal content, lost journal
directories, unsafe nodes, path aliases and simulated cross-volume destinations are rejected.
Reused files are synced before commit and preserved on sync failure. Controller fixtures verify
replayable confirmed failure, no terminal marker on uncertain publication, reconciliation before
the existing marker gate, and zero candidate reexecution on resume.

## Limits retained

SQLite defines logical batch publication. Filesystem readers may see a prefix while publication
is active or before explicit crash recovery. A journal-free interrupted preparation keeps staging
for diagnosis. Staging and journals are retained with per-batch bounds and no automatic GC.
The advisory lock coordinates this module's publishers; it is not an external authenticity
boundary against coordinated same-user changes.

Recovery does not run candidates or fabricate missing terminal results. The process-launch to
durable execution-evidence window and the separate terminal marker/materialization-ledger gap
remain unresolved. No real model, provider, WebAgent, OpenEvolve/ShinkaEvolve producer, remote
service or campaign ran. These results measure offline correctness, not algorithm effectiveness
or parity with WebAgent.
