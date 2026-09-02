# Feature Specification: Agent-Backed Evolution

**Feature Branch**: `015-agent-backed-evolution`
**Created**: 2026-09-02
**Status**: Implemented
**Input**: Use the explicit Agent Adapter boundary to solve algorithm problem contracts through the
native loop/population strategies without requiring a global Hermes/OpenCode/OpenClaw/Codex setup.

## Context and scope

Feature 013 provides local loop and population search, but its generator and evaluator seams are
currently callback- or command-oriented. Feature 014 provides a role/capability-aware Agent
Adapter. This feature bridges a selected Agent to candidate generation so a local Agent can propose
algorithm candidates while Lunar-Agent retains archive, evaluation, recovery, and run authority.
The evaluator remains an independent injected boundary. OpenEvolve remains a separate optional
strategy and is not silently mixed with an Agent-backed generator.

## User Stories & Testing

### User Story 1 - Generate algorithm candidates with an explicit Agent (Priority: P1)

As a local owner, I want loop/population evolution to call an explicitly configured Agent for fresh
candidate ideas so that the system can use Hermes, OpenCode, Codex, OpenClaw, or a local wrapper
without importing those tools.

**Independent Test**: Supply a fixture Agent Adapter and deterministic evaluator, run loop and
population strategies, and verify candidate drafts are archived and evaluated.

### User Story 2 - Preserve validity-first independent evaluation (Priority: P1)

As a problem owner, I want Agent output to be treated as a proposal rather than a success claim so
that only the existing evaluator can make a candidate valid or best.

**Independent Test**: Return a candidate source from an Agent and a rejected evaluation report;
verify the archive keeps the candidate but no best candidate is selected.

### User Story 3 - Invoke the bridge from the local CLI (Priority: P1)

As a parent Agent or shell script, I want `lunar-agent evolve --agent-command ...` to use the same
durable evolution run and JSON status as command generators.

**Independent Test**: Run a fixture JSON Agent command with an explicit absolute executable,
evaluate its generated source, and inspect the resulting run/artifacts/events.

## Functional Requirements

- **FR-1501**: The system MUST expose an `AgentCandidateGenerator` that converts a bounded
  `GenerationRequest` into an `AgentRequest` and a validated `CandidateDraft`.
- **FR-1502**: The bridge MUST include contract objective/statement, iteration, parent/inspiration
  metadata, and run workspace context without including unbounded archive source in the prompt.
- **FR-1503**: Agent responses MUST be normalized from either a bounded source string or a JSON object
  containing `source`, optional `filename`, and optional metadata.
- **FR-1504**: Non-success Agent results, malformed responses, oversized prompts, and adapter
  invocation failures MUST become bounded `EvolutionError` failures; no invalid candidate is archived.
- **FR-1505**: Candidate evaluation MUST continue through the independent `CandidateEvaluator`
  boundary. Agent text alone MUST NOT make a candidate valid or best.
- **FR-1506**: The CLI MUST accept `--agent-command`, role, and required capability options as an
  alternative to `--generator-command` for `loop` and `population`.
- **FR-1507**: Agent commands MUST be explicit absolute executables, use the Feature 014 JSON
  stdin/stdout protocol, and remain optional; existing generator/evaluator and OpenEvolve commands
  remain backward compatible.
- **FR-1508**: Agent-backed generation MUST use run-relative workspaces and bounded request/response
  sizes; it MUST NOT discover or persist global Agent configuration.

## Success Criteria

- **SC-1501**: A fixture Agent can generate candidates for loop and population runs using only the
  repository and an explicit command, with the same archive/evaluator evidence as command mode.
- **SC-1502**: Rejected and malformed Agent output never becomes a valid or best candidate.
- **SC-1503**: Existing evolution, delegation, and legacy CLI tests remain green.
- **SC-1504**: A parent process can invoke the CLI with one explicit Agent command and recover the
  durable run using the existing run ID/workspace.

## Out of scope

- Using the same Agent as an evaluator without an independent validation boundary.
- Automatic discovery of Agents, remote queues, model gateways, or service APIs.
- Replacing the native strategies or changing OpenEvolve's external command contract.
