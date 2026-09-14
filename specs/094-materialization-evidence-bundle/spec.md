# Feature 094: Portable materialization evidence bundle

**Created**: 2026-09-14
**Status**: Complete

## Problem and scope

093 can inspect retained materialization evidence, but a process failure or workspace cleanup can
make the report hard to preserve for review. Add `export-materialization-evidence PARENT CHILD
--output FILE [--home PATH] [--json]` to write a bounded,脱敏 evidence bundle outside the run.

## Requirements

- FR-094-01: Dispatch before ordinary CLI initialization. Read only through 093's snapshot and
  diagnostic APIs; never construct a controller, initialize Store, acquire/create source locks,
  invoke recovery/publish/rollback, execute a candidate or write events/receipts/workspace files.
- FR-094-02: Require an explicit output path. Refuse symlinks, non-regular existing nodes, existing
  destination files and paths inside either run workspace. Write with O_EXCL to a sibling temporary
  file, fsync it and its parent, then no-clobber link/rename; bounded output is at most 256 KiB.
- FR-094-03: Bundle schema 1 contains run IDs, the 093 observation report, and allowlisted protocol
  envelopes only: event id/run/task/type plus payload SHA-256 and size; artifact id/run/task/kind,
  size and SHA-256. Never include goals, commands, candidate/output bytes, absolute workspaces,
  retained payloads, logs, secrets or raw exceptions.
- FR-094-04: Capture one stable diagnostic snapshot. If source DB/files change or a lock is busy,
  return fixed unavailable/busy without creating the destination. Exported report always retains
  `recovery_eligibility: not_assessed`.
- FR-094-05: Repeated export with different destination paths is byte-identical for stable evidence;
  existing destination and partial temporary files are refused. Export is a review artifact, not
  recovery authorization or proof of success.
- FR-094-06: Cover WAL, crash fragments, sensitive redaction, destination safety/interruption,
  concurrent changes, missing source, source preservation and full/static/Specify/sealed checks.

## Limits

The bundle is a bounded observation captured at one stable point. It does not authenticate writers,
identify processes, prove validity or authorize manual edits/recovery. Output path metadata is
allowlisted but may still reveal user-chosen filenames; callers must choose a suitable destination.
No real model/provider/WebAgent/remote service/campaign is run.
