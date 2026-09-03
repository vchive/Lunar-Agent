# Feature Specification: Verified Experiment Memory

**Feature Branch**: `044-verified-experiment-memory`
**Created**: 2026-09-04
**Status**: Implemented

## Context and scope

Feature 039 gives a solver the source and evaluation evidence of recent candidates, and Feature 043
adds complete constraints and the frozen scoring contract. The archive still does not say what a
candidate was trying to change or whether that change helped relative to its parent. Later rounds
must infer experiment intent repeatedly from code excerpts, so loop and population can revisit
failed ideas or make several changes without attribution.

WebAgent's evo-builder writes a per-round `PLAN.md` and accumulates `knowledge/insights.md`.
OpenEvolve similarly uses an archive as an experience database. Lunar-Agent can retain the useful
effect without storing chain-of-thought or introducing mutable knowledge state: an Agent response
may declare one bounded experiment plan next to its candidate source; after independent evaluation,
Lunar-Agent derives an outcome card from persisted candidate lineage and verified scores. Future
prompts reconstruct cards from the append-only archive, making resume deterministic.

## User stories and acceptance scenarios

### User Story 1 — Declare one attributable change (P1)

1. The solver prompt asks for one JSON candidate containing source plus an experiment with a short
   hypothesis, bounded change tags, and target metric directions.
2. Plain source and legacy `{source, metadata}` responses remain accepted, but produce no declared
   experiment card.
3. Malformed, oversized, credential-bearing, or unsafe experiment metadata is rejected/redacted
   before it enters candidate state.

### User Story 2 — Learn from independently measured outcomes (P1)

1. For every declared experiment, Lunar-Agent combines the persisted plan with candidate/parent
   `EvaluationReport` values; the model cannot self-report success or score deltas.
2. Cards classify seed, improved, unchanged, regressed, and invalid outcomes and expose bounded
   per-metric before/after/delta facts when both reports contain the metric.
3. The next Agent prompt receives recent cards and an aggregate attempted-tag outcome summary, so it
   can exploit successful changes and avoid repeating failed ones.

### User Story 3 — Share experiment memory across strategies and recovery (P1)

1. Loop parents, population parents, and cross-island inspirations all use one archive-derived
   experiment memory projection.
2. A fresh generator after restart reconstructs byte-equivalent cards from `archive.jsonl`; no
   transcript, extra database, or model distillation call is required.
3. Callback/command generators, evaluator authority, candidate ranking, and OpenEvolve remain
   unchanged.

## Functional requirements

- **FR-4401**: Define a strict versioned experiment plan with one bounded hypothesis, one to eight
  safe change tags, and one to eight `{metric, direction}` targets.
- **FR-4402**: Accept the plan only from an Agent candidate JSON response, normalize/redact it, and
  persist it under bounded candidate metadata without treating it as evidence of quality.
- **FR-4403**: Derive outcome and `combined_score_delta` only from canonical candidate and parent
  evaluations; invalid candidates have outcome `invalid` and no claimed improvement.
- **FR-4404**: Derive bounded metric facts only for finite numeric metrics present in both reports
  with matching directions; mark whether each raw change improved that metric.
- **FR-4405**: Add recent experiment cards plus deterministic per-tag outcome counts to Agent
  generation context. Apply existing total prompt limits and expose no raw data/output content.
- **FR-4406**: Reconstruct all memory from the archive and lineage on every prompt, including after
  resume; do not create mutable insight files or hidden model state.
- **FR-4407**: Keep legacy Agent responses, direct/command generators, evaluator execution,
  compiled scoring contracts, strategy selection, and archive schema backward compatible.

## Success criteria

- **SC-4401**: A deterministic three-round fixture sees seed then independently measured improved
  and regressed/invalid experiment cards in later prompts.
- **SC-4402**: Actual score and metric deltas equal evaluator facts even when model metadata attempts
  to claim a different outcome.
- **SC-4403**: Loop, population, and a fresh resumed generator project the same bounded experiment
  card schema from persisted candidates.
- **SC-4404**: Tests cover malformed shapes, bounds, unsafe tags, credential redaction, unknown
  metadata, and legacy plain-source compatibility.
- **SC-4405**: Focused/full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- Storing chain-of-thought, free-form transcripts, raw datasets, raw outputs, or evaluator probes.
- A separate reflection model call, automatic code-diff semantic analysis, embeddings, or a vector
  database.
- Changing population parent selection or claiming statistical causality from one candidate delta.
