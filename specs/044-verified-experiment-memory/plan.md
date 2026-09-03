# Implementation Plan: Verified Experiment Memory

**Branch**: `main` | **Date**: 2026-09-04 | **Spec**: [spec.md](spec.md)

## Technical context

Agent responses already support bounded candidate metadata, and every `Candidate` persists lineage
plus a validated `EvaluationReport` in `archive.jsonl`. Feature 044 uses those two existing fields:
strictly normalize one optional experiment plan at the Agent bridge, then compute read-only cards
when constructing later prompts.

## Decisions

1. **Plan, not reasoning trace** — persist only hypothesis, change tags, and target metrics. Do not
   request or retain analysis steps.
2. **One candidate, one experiment** — encourages attributable changes and avoids an unbounded
   notebook protocol.
3. **Evaluator owns outcomes** — improvement, regression, validity, and metric deltas come only from
   archived reports; candidate metadata cannot override them.
4. **Derived memory** — no `knowledge.md`, new database table, or mutable summary file. Cards are a
   pure function of archive records, so recovery has no split-brain state.
5. **Bounded recent evidence** — include at most eight recent cards and compact tag counts under the
   existing 60 KiB generation prompt boundary.
6. **Backward-compatible bridge** — legacy plain source and existing metadata continue to work.
   The new prompt strongly prefers the structured JSON envelope but does not break other Agents.

## Data flow

```text
solver -> {source, experiment plan} -> candidate execution -> independent evaluator
                    |                                      |
                    +-> persisted candidate metadata       +-> verified report
                                                              |
archive lineage + metadata + reports -> derived experiment cards -> next solver prompt
```

## Recovery and safety

- Strict plan field sets, byte/count limits, safe tags, finite metric facts, and secret redaction.
- Cards contain IDs, declared bounded plan text, scores, and metric facts only.
- Missing/legacy parents or incompatible metrics degrade to seed/no-delta facts.
- Total prompt compaction may omit older cards, while full canonical evidence remains in archive.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Pure Python archive projection, no dependency. |
| Local-First and Durable State | Pass | Plans/reports already persist in append-only candidate records. |
| Runtime Adapter Isolation | Pass | Only the Agent response/prompt bridge changes. |
| Artifact-First Verification | Pass | Outcomes come from verified EvaluationReport facts. |
| Bounded Autonomy | Pass | Strict schema, redaction, limits, no hidden reflection call. |
| Test-First Recovery | Pass | Delta, malformed, population, and resume tests precede code. |

## Complexity tracking

No CLI option, database migration, dependency, service, evaluator protocol, or strategy state
change. Candidate metadata remains within its existing 8 KiB bound.
