# Plan

1. Add optional complete source maps to CandidateDraft and a strict explicit bundle-evidence
   projection to Candidate/receipt v2, leaving v1 serialization unchanged.
2. Implement a MultiFileCandidatePipeline which binds command/input/evaluator settings, prepares
   private workspaces and staged inputs, runs/records once, and independently evaluates snapshots.
3. Branch only the persistence/evidence seams in the existing PopulationStrategy and CandidateArchive.
   Reuse lineage, validity-first ranking, migration, outcomes and durable archive publication.
4. Extend local command generation and source-context reading to complete bundles; reject implicit
   fallback to entrypoint-only evaluation. Keep external seed import protocol scope unchanged.
5. Add controller support and explicit delivery of full code and previously evaluated outputs.
   Validate saved evidence and selection before delivery; do not call old single-file materialization.
6. Exercise real local generations including helper-only improvement, failure/invalid results,
   resume without relaunch, tamper rejection, final delivery and legacy compatibility. Update docs.

## Decisions

Entry point hash keeps its existing meaning; a separate bundle binding covers all declared files.
New receipts use version 2 rather than altering version 1 hash input. Evidence is created at its
final retained location because Feature 107/108 bind inode identities. Failed attempts survive
candidate ID reuse in a separate execution area. No new database tables or runtime dependencies.

## Deferred

Automatic default task routing, remote producers, OpenEvolve/Shinka bundle seed admission, new
real comparisons and generic workflow/repository candidates are outside this local integration.
