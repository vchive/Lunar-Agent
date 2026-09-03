# Implementation Plan: Quality-Diversity Population Selection

**Branch**: `main` | **Date**: 2026-09-04 | **Spec**: [spec.md](spec.md)

## Technical context

`PopulationStrategy` owns `_rank`, `_trim`, `_select_parent`, `_inspirations`, and `_migrate` over
canonical `Candidate` records. Feature 046 currently keeps its repertoire inside the Agent bridge.
Feature 047 moves that immutable vocabulary to the runtime-neutral algorithm contract module and
uses exact experiment-tag membership as an advisory structural descriptor. Evaluation validity and
score stay authoritative.

## Decisions

1. **Family is a descriptor, not evidence** — exact canonical experiment tags say which technique
   the solver intended; they never override validity, score, or final-best selection.
2. **Global elite plus family elites** — retain the island's best valid candidate, then best valid
   representatives of other families, ordered by existing rank. This is a small quality-diversity
   archive inside the already bounded active set.
3. **Validity before diversity** — invalid candidates may remain only when capacity exceeds valid
   candidates or no valid repair baseline exists. They never consume a protected family slot.
4. **Family-aware parents** — the stochastic parent pool contains the best candidate from each
   valid family before clones. Existing seeded RNG chooses among the top bounded pool.
5. **Complementary inspirations** — select valid candidates from families different from the parent
   and each other first; token novelty and score break ties/fill missing descriptors.
6. **Legacy fallback** — when no candidate carries a recognized family, selection reduces to the
   historical validity/score/token-novelty ordering.
7. **No new state** — reconstruct descriptors from the canonical contract and archive metadata;
   state continues to store active IDs only.

## Data flow

```text
contract.problem_type -> canonical family repertoire
candidate experiment.change_tags -> exact family descriptor (or none)

active island candidates -> validity/score/token rank
                         -> global valid elite
                         -> one valid elite per remaining family
                         -> ranked fallback fill
                         -> bounded active IDs

family elites -> seeded parent pool
valid cross-family peers -> inspirations
```

## Recovery and safety

- Candidate metadata is already bounded and JSON-safe; malformed experiment shapes produce no
  descriptor rather than a strategy error.
- Unknown tags cannot create an unlimited niche or protected slot.
- Stable rank keys and canonical repertoire order make trim/reconstruction deterministic.
- Archive and state validation remain unchanged; no source/output content enters metadata policy.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Pure standard-library selection. |
| Local-First and Durable State | Pass | Family reconstructs from canonical archive. |
| Runtime Adapter Isolation | Pass | Strategy sees candidate metadata, not Agent runtime. |
| Artifact-First Verification | Pass | Validity/score always precede descriptor diversity. |
| Bounded Autonomy | Pass | Existing capacity, two inspirations, no new call/budget. |
| Test-First Recovery | Pass | Trim/parent/inspiration/restart tests precede code. |

## Complexity tracking

No CLI/configuration option, database/archive migration, dependency, service, inference call, or
evaluator change.
