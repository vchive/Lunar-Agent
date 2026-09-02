# Feature Specification: Verified Evolution Feedback

**Feature Branch**: `019-verified-evolution-feedback`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Feed bounded evaluator evidence back into later Agent generations

## Context and scope

Agent-backed evolution currently gives a solver Agent candidate IDs and scores from the archive,
but not the structured reasons why candidates were invalid or how individual metrics scored. That
forces the solver to repeat failed ideas without using the independent evaluator's evidence. This
feature adds a bounded, read-only feedback projection to subsequent generation prompts. It carries
only fields already validated by `EvaluationReport`; candidate source, raw logs, prompts, and
unbounded evaluator output remain excluded.

## User Stories & Testing

### User Story 1 - Correct the next candidate (Priority: P1)

As a solver Agent working through loop or population rounds, I want to see verified constraint
failures and metric scores from prior candidates so that the next proposal can address them.

**Independent Test**: An invalid candidate report contains a controlled error code/message; the
next Agent generation prompt includes that feedback projection.

### User Story 2 - Keep evaluator evidence bounded (Priority: P1)

As a local owner, I want feedback to stay small and structured so long archives cannot overflow the
prompt or inject candidate source into the solver context.

**Independent Test**: Reports with many metrics/errors produce a prompt containing only bounded
entries and no candidate source or raw runtime error.

### User Story 3 - Preserve strategy and callback compatibility (Priority: P2)

As an existing library or command caller, I want loop/population behavior and non-Agent generators
to remain unchanged while Agent generation gains the optional feedback fields.

**Independent Test**: Existing full evolution and CLI tests remain green; callback generators never
receive or require a new argument.

## Functional Requirements

- **FR-1901**: Agent generation context MUST include a bounded evaluation feedback projection for
  archived candidates when an `EvaluationReport` is present.
- **FR-1902**: The projection MUST include validity, quality/combined score, at most eight metric
  summaries, and at most eight error entries with bounded code/message fields.
- **FR-1903**: Feedback MUST be derived only from schema-validated `EvaluationReport` fields; raw
  candidate source, prompts, logs, and adapter exception text MUST NOT be copied into the prompt.
- **FR-1904**: The projection MUST be labeled as evidence/data rather than executable instructions,
  and the existing generation prompt byte bound MUST remain enforced.
- **FR-1905**: Loop and population strategies MUST continue to use the same `GenerationRequest` and
  independent evaluator boundary; no evaluator result may directly mutate selection semantics.
- **FR-1906**: Malformed/legacy archive records without an evaluation object MUST degrade to the
  existing summary fields or be rejected by existing archive validation, never bypassing checks.

## Success Criteria

- **SC-1901**: A later solver generation can identify a prior verified constraint failure from its
  bounded prompt and produce a corrected candidate.
- **SC-1902**: Feedback remains below the prompt limit under maximal bounded reports and never
  includes candidate source text or unbounded error content.
- **SC-1903**: Existing tests, lint, compile, and Spec Kit checks remain green.

## Out of scope

- Letting a solver Agent override evaluator validity or ranking.
- Persisting new tables or retaining raw model/evaluator transcripts.
- Sending feedback to non-Agent command generators or changing callback signatures.
