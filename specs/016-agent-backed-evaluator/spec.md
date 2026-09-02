# Feature Specification: Agent-Backed Evaluator

**Feature Branch**: `016-agent-backed-evaluator`
**Created**: 2026-09-02
**Status**: Implemented
**Input**: Allow an explicitly configured evaluator Agent to close the local algorithm evolution
loop while preserving structured validity-first verification.

## Context and scope

Feature 015 lets an Agent generate candidates, but the CLI still requires a separate evaluator
command. This feature adds an `AgentCandidateEvaluator` bridge. It asks an explicitly selected
evaluator Agent for one JSON `EvaluationReport`; the report is validated by the existing algorithm
contract before the candidate can become valid or best. The bridge is optional and does not make an
Agent claim, natural-language answer, or global runtime installation authoritative.

## User Stories & Testing

### User Story 1 - Complete local Agent evaluation (Priority: P1)

As a local owner, I want a solver Agent and evaluator Agent command to run loop/population without
writing a custom evaluator executable, while keeping their roles and capabilities explicit.

**Independent Test**: A fixture evaluator Agent returns a valid report; the bridge returns a parsed
`EvaluationReport` and the strategy selects the candidate.

### User Story 2 - Reject unverifiable evaluator output (Priority: P1)

As a problem owner, I want malformed, non-success, or invalid evaluation responses to become
invalid evidence rather than success.

**Independent Test**: Return malformed JSON, a failed Agent result, or a report with inconsistent
validity/score and verify no best candidate is selected.

### User Story 3 - Preserve command evaluator compatibility (Priority: P2)

As an existing caller, I want `--evaluator-command` to remain valid and to choose exactly one
evaluator mode.

**Independent Test**: Supplying both evaluator options fails before the evolution run is created;
legacy command-generator/evaluator tests remain green.

## Functional Requirements

- **FR-1601**: The system MUST expose an `AgentCandidateEvaluator` implementing the existing
  `CandidateEvaluator` callable.
- **FR-1602**: The bridge MUST send a bounded prompt containing candidate path, contract objective,
  statement, constraints, and instructions for exactly one JSON `EvaluationReport`.
- **FR-1603**: Only a successful Agent result with a parseable, schema-valid `EvaluationReport` MAY
  be returned; all other output MUST raise a bounded `EvolutionError`.
- **FR-1604**: EvaluationReport validity-first invariants remain enforced by
  `EvaluationReport.from_dict`; Agent text alone MUST NOT bypass them.
- **FR-1605**: The CLI MUST accept `--evaluator-agent-command` as an alternative to
  `--evaluator-command` and MUST reject both together.
- **FR-1606**: Solver and evaluator commands MUST remain explicit absolute executables and use the
  Feature 014 JSON protocol; no PATH/global discovery is allowed.
- **FR-1607**: Existing evolution state, archive, OpenEvolve, delegation, and resume behavior MUST
  remain backward compatible.

## Success Criteria

- **SC-1601**: A fixture solver Agent plus evaluator Agent completes a loop and population run using
  only local explicit commands and the repository.
- **SC-1602**: Invalid/malformed evaluator responses never create a valid/best candidate.
- **SC-1603**: Existing tests and command evaluator workflows remain green.

## Out of scope

- Automatically deciding whether solver and evaluator Agents are independent.
- Accepting natural-language scores or executable evaluator claims.
- Remote evaluator queues, service APIs, or global Agent discovery.
