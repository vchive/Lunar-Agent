# Feature Specification: Adaptive Search Orchestration

**Feature Branch**: `045-adaptive-search-orchestration`
**Created**: 2026-09-04
**Status**: Implemented

## Context and scope

Lunar-Agent's loop and population strategies already select a parent/inspirations and retain a
verified archive. The Agent solver receives those objects but is left to infer the purpose of each
generation. A seed request, an infeasible repair, a local refinement, and a cross-island
recombination currently share the same generic instruction. Population can therefore emit near-
duplicate seeds, while loop can spend a round exploring after the latest candidate clearly needs a
bounded feasibility repair.

Feature 044 adds evaluator-grounded experiment memory. This feature turns strategy state and that
memory into one deterministic `search_directive` per Agent generation. The directive assigns a mode
(`explore`, `diversify`, `repair`, `refine`, or `recombine`), identifies evidence baselines, and
summarizes proven or exhausted change tags. It guides generation only; candidate evaluation,
selection, budgets, and recovery remain authoritative in existing strategy code.

## User stories and acceptance scenarios

### User Story 1 — Give every generation a clear search role (P1)

1. An empty archive produces `explore`; later seed requests without a parent produce `diversify`.
2. An invalid selected parent, or the latest invalid candidate when no selected parent exists, produces
   `repair` with bounded evaluator error codes and the candidate ID.
3. A valid parent produces `refine`; a valid parent plus inspirations produces `recombine` with
   exact baseline IDs.

### User Story 2 — Allocate experiments from measured history (P1)

1. Change tags with at least one verified improved outcome are reported as `proven_change_tags`.
2. Tags attempted only in invalid/regressed/unchanged outcomes are reported as
   `avoid_change_tags`, bounded and deterministically ranked by failure evidence.
3. The solver is instructed to declare one attributable experiment consistent with the mode and
   avoid simply repeating exhausted tags.

### User Story 3 — Improve loop and population without extra infrastructure (P1)

1. Population initial calls receive one explore seed followed by diversity-oriented seed roles;
   offspring receive repair/refine/recombine according to selected evidence.
2. Loop switches from feasibility repair to objective refinement after a valid candidate emerges.
3. A fresh generator after restart derives the same directive from the archive; no mutable
   scheduler state, model planner, service, or additional inference call is introduced.

## Functional requirements

- **FR-4501**: Add one versioned prompt-only search directive with exact fields for mode, priority,
  target candidate, parent/inspiration IDs, error codes, proven tags, and avoid tags.
- **FR-4502**: Derive mode exclusively from `GenerationRequest` and canonical archived evaluation
  validity: explore empty, repair invalid baseline, diversify parentless valid history, recombine
  valid parent plus inspirations, otherwise refine.
- **FR-4503**: In parentless repair select only the most recent invalid archived candidate; never
  treat an invalid candidate as an optimization baseline.
- **FR-4504**: Derive tag policy only from Feature 044 evaluator-grounded outcomes. Proven tags have
  an `improved` count; avoid tags have no improvement and at least one measured non-success.
- **FR-4505**: Bound every directive array to eight safe strings, order deterministically, and keep
  the total generation prompt within the existing 60 KiB limit.
- **FR-4506**: Include explicit, non-executable solver guidance per mode while continuing to require
  one attributable experiment declaration and independent evaluation.
- **FR-4507**: Keep strategy state, parent selection, candidate ranking, direct/command generators,
  OpenEvolve, compiled scoring, evaluator authority, and archive format unchanged.

## Success criteria

- **SC-4501**: Unit tests cover all five modes and their exact evidence IDs/error-code projections.
- **SC-4502**: A deterministic loop fixture uses a repair directive after invalid output and a
  refine directive after achieving feasibility.
- **SC-4503**: A deterministic population fixture receives explore/diversify/recombine roles rather
  than identical generic seed/offspring requests.
- **SC-4504**: Proven/avoid tag tests are derived from verified outcome cards, bounded, stable after
  restart, and cannot be overridden by model metadata.
- **SC-4505**: Focused/full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- A learned bandit, reinforcement-learning policy, extra planner/reflection model call, or automatic
  token/budget expansion.
- Changing population selection/migration, running generations concurrently, or claiming quality
  superiority without benchmark evidence.
- Domain-specific algorithm playbooks; directives orchestrate the configured Agent's own search.
