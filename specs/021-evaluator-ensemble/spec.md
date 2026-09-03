# Feature Specification: Independent Evaluator Ensemble

**Feature Branch**: `021-evaluator-ensemble`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Verify algorithm candidates with multiple explicit evaluator Agents

## Context and scope

Lunar-Agent currently supports one independent evaluator Agent per evolution run. A single
evaluator can make a false validity decision or score an edge case incorrectly. This feature adds a
local evaluator ensemble: two or more explicitly configured evaluator Agents inspect the same
candidate, and Lunar-Agent aggregates only schema-valid reports. Validity requires unanimous
agreement; disagreement or an evaluator failure is represented as an invalid report and cannot
produce a best candidate. When all evaluators agree valid, numeric scores use a robust median and
common detailed metrics are aggregated by median.

## User Stories & Testing

### User Story 1 - Cross-check candidate validity (Priority: P1)

As a problem owner, I want independent evaluator Agents to cross-check hard constraints so that one
model's mistaken pass does not make an unsafe algorithm candidate best.

**Independent Test**: Two evaluators agree on validity and produce an aggregated valid report; one
evaluator disagrees and the ensemble returns an invalid report with no best candidate.

### User Story 2 - Keep ensemble evidence deterministic (Priority: P1)

As a parent Agent resuming a long evolution, I want the ordered evaluator list and profile to be
fingerprinted and each evaluator to use an isolated workspace.

**Independent Test**: Reordering evaluator commands changes the resume fingerprint; each fixture
receives a distinct workspace and the same candidate path.

### User Story 3 - Preserve single evaluator compatibility (Priority: P2)

As an existing caller, I want `--evaluator-agent-command` and `--evaluator-command` to retain their
current behavior while a repeatable ensemble option is additive.

**Independent Test**: Existing evolution, Agent, OpenEvolve, and callback tests remain green;
supplying ensemble plus a single evaluator option fails before run creation.

## Functional Requirements

- **FR-2101**: The library MUST expose an `AgentEvaluatorEnsemble` implementing the existing
  `CandidateEvaluator` callable for two or more explicit evaluator Agents.
- **FR-2102**: Every member MUST receive the same candidate and contract through the strict Agent
  evaluation bridge and an isolated run-relative workspace.
- **FR-2103**: Only schema-valid `EvaluationReport` responses participate; a member invocation
  failure or malformed report MUST yield an invalid aggregate report.
- **FR-2104**: Aggregate validity MUST be 1 only when every member reports validity 1. Any validity
  disagreement MUST yield validity 0, combined_score 0, and a controlled `evaluator_disagreement`
  error entry.
- **FR-2105**: When all members are valid, aggregate `combined_score` and quality MUST use the
  median of member values; common detailed metric names with matching directions MUST use median
  values. The aggregate evaluator ID MUST be stable and safe.
- **FR-2106**: The CLI MUST accept repeatable `--evaluator-portfolio-command` options for loop and
  population and reject them with single evaluator options or OpenEvolve.
- **FR-2107**: Resume state MUST fingerprint the ordered evaluator command list and shared profile;
  raw commands and evaluator output MUST not be persisted in the fingerprint.

## Success Criteria

- **SC-2101**: Two agreeing evaluator Agents produce one valid, median-scored result.
- **SC-2102**: Disagreement, failure, or malformed output never selects a best candidate.
- **SC-2103**: Existing single evaluator and all legacy tests remain green with no new dependency.

## Out of scope

- Probabilistic majority voting, remote evaluator queues, or automatic Agent discovery.
- Per-evaluator heterogeneous contracts or roles in one ensemble.
- Changing population ranking beyond the aggregated report supplied to the existing strategy.
