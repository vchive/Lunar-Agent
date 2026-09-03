# Feature Specification: Quality-Diversity Population Selection

**Feature Branch**: `047-quality-diversity-population`
**Created**: 2026-09-04
**Status**: Implemented

## Context and scope

Feature 046 allocates distinct algorithm families to Agent generations, but the population strategy
does not understand that identity. Active candidates are sorted lexicographically by validity,
score, and code-token novelty. When several high-scoring variants share one family, they can fill
an island and evict a slightly lower-scoring but complementary family. Parent sampling from the
top three can then keep refining one basin, while inspiration selection ranks token difference
without first requiring validity or a different family.

This feature adds a deterministic, bounded quality-diversity policy to the existing local
`PopulationStrategy`. It recognizes Feature 046 canonical family tags in normalized experiment
metadata, preserves a global valid elite plus one valid elite per family where capacity permits,
samples parents from family elites, and prefers valid cross-family inspirations. Untagged legacy
candidates retain the existing score/token-novelty fallback. The append-only archive and final
best candidate remain purely evaluator-owned.

## User stories and acceptance scenarios

### User Story 1 — Prevent premature family collapse (P1)

1. When an island has capacity three, two high-scoring candidates from one family and lower-scoring
   candidates from two other valid families, trim retains the global best plus the two distinct
   family elites.
2. A family elite is the highest-ranked valid member of that canonical problem-type repertoire;
   arbitrary metadata tags do not create protected niches.
3. Invalid candidates never displace valid family elites, and the global best archived candidate
   is never removed from its active island by diversity policy.

### User Story 2 — Search across viable basins (P1)

1. Parent selection draws from distinct valid family elites before same-family clones, retaining
   seeded deterministic behavior.
2. Inspiration selection first requires validity, then prefers families different from the parent
   and from already selected inspirations, then uses code-token novelty and score.
3. If no family metadata exists, parent/inspiration/trim behavior degrades to the existing
   validity, score, and token-novelty ordering rather than failing.

### User Story 3 — Preserve recovery and evaluator authority (P1)

1. Family identity is derived only from exact repository-owned tags in bounded experiment metadata;
   outcome or score claims in metadata are ignored.
2. State continues to persist only active candidate IDs; a fresh process reconstructs identical
   family elites from the append-only archive and canonical problem contract.
3. Loop, OpenEvolve, callback/command generators, evaluator rules, final best selection, and all
   public configuration remain unchanged.

## Functional requirements

- **FR-4701**: Expose one shared immutable canonical algorithm-family repertoire keyed by every
  supported problem type so generation and population selection cannot drift.
- **FR-4702**: Derive a candidate family only by exact matching a canonical repertoire tag inside
  its bounded experiment `change_tags`; ignore unknown/malformed metadata.
- **FR-4703**: Trim each island validity-first: retain the global valid elite when present, then the
  highest-ranked valid elite of distinct remaining families, then fill capacity from the existing
  score/token-novelty order without duplicates.
- **FR-4704**: When the number of family elites exceeds capacity, order family elites by the same
  evaluator score/token-novelty rank; diversity must never reverse validity or fabricate quality.
- **FR-4705**: Build a parent pool with at most one valid candidate per recognized family before
  same-family candidates; retain seeded deterministic selection and invalid-only repair fallback.
- **FR-4706**: Select at most two inspirations by validity, cross-family complementarity, distinct
  inspiration family, code-token novelty, score, and stable candidate identity. Exclude invalid
  inspirations whenever any valid inspiration exists.
- **FR-4707**: Keep state/archive schemas, public configuration, evaluator authority, stagnation,
  budgets, migration bounds, loop, OpenEvolve, and base dependencies unchanged.

## Success criteria

- **SC-4701**: Unit tests prove a same-family score cluster cannot evict valid elites from distinct
  families while global best remains active.
- **SC-4702**: Parent sampling uses only one elite per recognized family until fallback is needed
  and is reproducible under the configured seed.
- **SC-4703**: Inspiration tests select valid, distinct, cross-family candidates and exclude invalid
  or duplicate-family alternatives when better evidence exists.
- **SC-4704**: An end-to-end population fixture retains three algorithm families even when the
  evaluator scores one family's clones above the others.
- **SC-4705**: Recovery reconstruction, legacy metadata fallback, focused/full tests, lint, compile,
  diff, quickstart, and Specify checks pass.

## Out of scope

- MAP-Elites grids with user-configured feature descriptors, novelty archives, embeddings, or a
  learned selection/bandit policy.
- Changing evaluator scores, validity, final archive best semantics, or claiming benchmark
  superiority without equal-budget trials.
- Adding population flags, database columns, services, remote workers, or third-party packages.
