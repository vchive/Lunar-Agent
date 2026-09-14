# Validation — 2026-09-14

## Results

- Diagnostic snapshot and materialization diagnostic tests: 136 passed in 20.67s (57 snapshot,
  79 report/CLI cases).
- The snapshot suite covers checkpointed and uncheckpointed WAL databases, missing/unsafe/
  malformed/oversized source nodes, changing sources, bounded rows and payloads, reserved identity
  drift, and cleanup of private copies.
- The diagnostic suite covers complete, failed, timed-out, validation-failed, launch-only and
  every 091/092 interruption boundary, legacy and fragmented evidence, busy locks, malformed
  records, missing homes/workspaces, CLI pre-initialization dispatch, sensitive-data redaction,
  and source byte/inode/mode/size/mtime/directory preservation.
- `ruff check src tests`, `compileall -q src tests`, and `git diff --check`: passed.
- Independent Store and report reviews: no remaining blocker.
- Final full repository regression: 3586 passed in 201.05s.

## Retained limits

The report is an inventory, not a recovery validator or authorization. It does not prove output
validity, identify surviving processes, authenticate unrelated writers, or reconstruct missing
records. SQLite and filesystem snapshots can still be unavailable or unstable under concurrent
changes; the command returns a bounded unavailable/busy result. Source reads may update access
times; contents, directory entries and business records remain the preservation boundary. No real
model, provider, WebAgent, producer, remote service or campaign ran.
