# Feature Specification: Agent Solver Portfolio

**Feature Branch**: `020-agent-solver-portfolio`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Allow population evolution to use multiple explicit solver Agents without a service layer

## Context and scope

Lunar-Agent can currently use one explicit solver Agent as its candidate generator. Population
search benefits from independent proposal styles, but callers must otherwise build their own
round-robin wrapper outside the repository. This feature adds a small local portfolio bridge and a
repeatable CLI option. Each generation selects one explicitly configured solver in deterministic
round-robin order; all proposals still pass through the same archive and independent evaluator.

## User Stories & Testing

### User Story 1 - Combine independent solver Agents (Priority: P1)

As a local owner solving a hard algorithm problem, I want population rounds to alternate between
multiple local solver CLIs so that different search heuristics contribute candidates.

**Independent Test**: Two fixture solver adapters receive alternating generation requests and every
candidate is evaluated and archived normally.

### User Story 2 - Preserve deterministic recovery (Priority: P1)

As a parent Agent resuming a detached run, I want the same ordered portfolio and profile to be
required so that candidate lineage is not silently changed after interruption.

**Independent Test**: A changed portfolio command or order changes the persisted fingerprint and is
rejected by the existing resume configuration check.

### User Story 3 - Keep single-agent and callback compatibility (Priority: P2)

As an existing caller, I want `--agent-command`, command generators, OpenEvolve, and callback
strategies to remain unchanged while the portfolio option is additive.

**Independent Test**: Existing full test suite passes and supplying both single-agent and portfolio
options fails before creating a run.

## Functional Requirements

- **FR-2001**: The library MUST expose an `AgentPortfolioGenerator` implementing the existing
  `CandidateGenerator` callable for two or more explicit `AgentAdapter` instances.
- **FR-2002**: Portfolio selection MUST be deterministic round-robin by generation call order and
  MUST preserve the existing bounded prompt, response, workspace, and evaluator boundaries.
- **FR-2003**: Each adapter MUST be explicitly registered and satisfy the requested role and
  capabilities; no PATH, global configuration, or remote discovery is allowed.
- **FR-2004**: The CLI MUST accept repeatable `--agent-portfolio-command` options for loop and
  population and reject them when combined with `--agent-command`, `--generator-command`, or
  OpenEvolve.
- **FR-2005**: Resume state MUST persist one credential-safe fingerprint covering the ordered command
  list and shared Agent profile; changing a command, order, role, name, or capability MUST fail closed.
- **FR-2006**: One portfolio member failing MUST produce the existing bounded generation failure;
  it MUST not make an unverified candidate valid or bypass the independent evaluator.

## Success Criteria

- **SC-2001**: A local population run can alternate two solver commands with no Hermes/OpenCode/
  service dependency.
- **SC-2002**: Same portfolio resumes deterministically; changed command/order/profile is rejected.
- **SC-2003**: Existing single-agent, command-generator, evaluator, OpenEvolve, and callback tests
  remain green.

## Out of scope

- Dynamic agent discovery, remote queues, cross-machine scheduling, or consensus voting.
- Per-agent heterogeneous roles in one portfolio; all members share the explicit solver profile.
- Changing population ranking or evaluator semantics.
