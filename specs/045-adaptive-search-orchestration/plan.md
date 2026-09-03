# Implementation Plan: Adaptive Search Orchestration

**Branch**: `main` | **Date**: 2026-09-04 | **Spec**: [spec.md](spec.md)

## Technical context

`GenerationRequest` contains iteration, selected parent, inspirations, archive, and workspace.
Feature 044 now derives bounded verified experiment memory from that archive. Feature 045 adds one
pure prompt projection in `AgentCandidateGenerator`; strategies and public request types remain
unchanged.

## Decisions

1. **Deterministic mode table** — mode follows concrete selection/validity state, not an additional
   model opinion.
2. **Repair latest failure** — when `best()` yields no parent, use the newest invalid candidate as a
   repair target so serial loop does not restart blindly.
3. **Feasibility before quality** — repair priority contains only validated error codes; refinement
   and recombination retain the frozen higher-is-better scoring contract.
4. **Evidence-based tag policy** — improved tags are proven; tags with measured failures and zero
   improvements are avoided. Mixed tags remain proven and are not called exhausted.
5. **Guidance, not authority** — directive affects prompt intent only. Strategy selection and
   evaluator results still decide lineage, archive, and best candidate.
6. **No new durable state** — recompute from `GenerationRequest` and archive, preserving recovery and
   command/callback compatibility.

## Mode table

| Condition | Mode | Priority |
|---|---|---|
| no parent, empty archive | explore | establish distinct feasible baseline |
| no parent, latest archived invalid | repair | fix reported hard failure |
| no parent, valid archive exists | diversify | use a different algorithm/change family |
| valid parent + inspirations | recombine | combine complementary verified structure |
| valid parent, no inspirations | refine | improve objective without losing feasibility |

## Recovery and safety

- Candidate IDs/errors are read from validated archive objects and bounded by existing contracts.
- Tag policy consumes normalized experiment memory only and caps lists at eight.
- Prompt compaction can discard older experiment cards but never the small directive.
- Invalid/missing legacy experiment metadata produces empty tag policy, not a strategy failure.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Pure deterministic projection, no dependency. |
| Local-First and Durable State | Pass | Directive reconstructs from durable archive. |
| Runtime Adapter Isolation | Pass | Only Agent prompt contents change. |
| Artifact-First Verification | Pass | Repair/tag facts originate in EvaluationReport. |
| Bounded Autonomy | Pass | Fixed modes, strict caps, no extra inference/budget. |
| Test-First Recovery | Pass | All modes, loop/population, tag, and resume tests precede code. |

## Complexity tracking

No CLI option, database migration, dependency, service, strategy-state change, or evaluator change.
