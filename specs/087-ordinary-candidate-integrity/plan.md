# Plan: Ordinary Candidate Integrity

## Technical approach

Add a small canonical ordinary receipt DTO in the runtime-neutral evolution layer. Resolve one
credential-free authority tuple from explicit `EvolutionConfig` identities (with documented native
protocol defaults for backward-compatible direct callers), and pass it to the shared persistence
path used by initialization and offspring attempts. Hold no-follow source and execution descriptors
from evaluation through publication, deep-snapshot the returned report, write a receipt sidecar and
compact candidate projection, then append the archive line. Bind archive order and causal lineage,
fsync new directories, cap aggregate journal size, and roll back a failed append to its prior
durable length.

Put the integrity gate in the strategy state load/resume path. It validates every new ordinary
candidate before selection or evaluator/generator calls, while preserving read-only parsing of old
archives and the existing verified-seed transaction path. Controller artifact indexing is additive
and idempotent. Seeded controller resume performs the ordinary preflight before seed evaluation; an
exception path indexes only the exact state-bound archive prefix. Invalid evaluated candidates stay
outside active/parent/best selection, while journal-proven empty-population retries remain valid
generation-zero roots. Rebuild the modern active, best, RNG, migration, and stagnation projections
by replaying the validated seed/iteration archive through the existing rank, trim, and migrate
rules. Check exact numeric types, projection-consistent terminal status, and the required outcome
binding as one group, then reject a mismatch without changing the established incomplete-pending
and empty-seed error order. Preserve an established ordinary marker monotonically through later
states, including seeded failed-only batches, so that deleting the outcome group while the marker
remains visible fails closed. Treat the selection rules as part of the integrity protocol: a future
algorithm change must bump its schema or migrate old projections explicitly.

## Verification

Use deterministic fake generators/evaluators and temporary directories. Cover receipt round-trip,
source/lineage/authority tampering, evaluator failure and source rewrite, atomic publication and
legacy policy, plus controller artifact indexing. Run focused and full offline tests, Ruff,
compileall, Specify prerequisites, diff checks, and sealed-artifact verification.

No test or implementation step starts a real model, provider, OpenEvolve, ShinkaEvolve, WebAgent,
remote transport, scheduler, or campaign.
