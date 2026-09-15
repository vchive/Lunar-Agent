# Plan

1. Add immutable workspace-plan and materialization result DTOs with canonical path-free digests.
2. Reuse Feature 102 validation and the descriptor-based bounded reader for source observations.
3. Copy only declared files into a unique temporary directory, fsync and re-read destinations, and
   remove the directory on every failure.
4. Add focused filesystem and structural replay tests plus an early static CLI command.
5. Update public exports, README, architecture, roadmap, and handoff; run full regression locally.

## Decisions

The materialized directory is returned as an in-memory path and is not attached to Run, Store, or
Candidate state. A later feature may decide how a runner owns and cleans it. The destination is a
fresh unique directory, so no caller-selected final path or overwrite operation is needed.

## Complexity tracking

No dependencies, migrations, runtime adapters, or evaluator behavior are added. Source bytes are
read once per declared file and destination bytes are re-read before success. This preserves the
per-file observation guarantee while detecting ordinary replacement and partial-write failures.
