# Feature Specification: Runtime-Backed Evolution Agents

**Feature Branch**: `022-runtime-backed-evolution`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Use Lunar-Agent's repository-owned runtime directly in algorithm evolution

## Context and scope

Native `loop` and `population` evolution currently require a generator/evaluator command or an
explicit Agent wrapper. That keeps the seams portable, but a standalone local installation still
needs a second wrapper process before it can use its own configured model runtime. This feature adds
an explicit `--agent-runtime` option to `evolve`. The selected repository runtime is adapted into
the existing strict solver and evaluator bridges; no Hermes, OpenCode, Codex, OpenClaw, PATH
discovery, service, or new dependency is introduced.

One runtime configuration may fill either or both unbound seams. Explicit command/Agent options
remain available for mixed solver/evaluator setups and take precedence for their respective seam.
Supplying a runtime while both seams are already explicitly configured is rejected as ambiguous.

## User Stories & Testing

### User Story 1 - Run evolution with the repository runtime (Priority: P1)

As a standalone local user, I want `evolve` to call an explicitly selected local runtime directly
so that I can solve algorithm problems without installing or wrapping Hermes/OpenCode/Codex.

**Independent Test**: A deterministic runtime fixture generates a candidate and returns a strict
evaluation report through the normal Agent bridges; the candidate is archived and selected.

### User Story 2 - Mix runtime and explicit adapters (Priority: P1)

As a local owner, I want to use the repository runtime for one role and an explicit command for the
other role so that solver and evaluator policies can evolve independently.

**Independent Test**: Runtime-backed solver plus command evaluator, and command solver plus
runtime-backed evaluator, both complete; conflicting options fail before run creation.

### User Story 3 - Preserve durable detached recovery (Priority: P1)

As a parent Agent, I want a detached runtime-backed evolution to resume with the same provider
profile without persisting credentials or raw configuration.

**Independent Test**: Detached propagation includes runtime settings, state stores only a digest, and
changing runtime kind/endpoint/model/profile is rejected on resume.

## Functional Requirements

- **FR-2201**: The CLI MUST accept an explicit `--agent-runtime` choice of `mock`, `subprocess`, or
  `openai-compatible` for native `loop` and `population` strategies.
- **FR-2202**: Runtime-backed solver/evaluator calls MUST use `RuntimeAgentAdapter` and the existing
  strict `AgentCandidateGenerator` / `AgentCandidateEvaluator` bridges.
- **FR-2203**: `--agent-runtime` MAY fill either or both missing seams; explicit command/Agent
  options MUST remain valid for the other seam.
- **FR-2204**: The CLI MUST reject runtime options with OpenEvolve, reject an unused runtime when
  both seams are explicit, and reject conflicting options for one seam before run creation.
- **FR-2205**: Runtime kind, endpoint, model, command identity, and role/capability profile MUST be
  represented by credential-safe SHA-256 fingerprints in resume state. API keys MUST NOT be
  persisted in state or command arguments used for detached children.
- **FR-2206**: Detached runtime-backed evolution MUST propagate non-secret runtime configuration;
  secret keys MUST be passed through an environment variable only.
- **FR-2207**: Existing command, single-Agent, portfolio, OpenEvolve, callback, and legacy CLI
  behavior MUST remain unchanged.

## Success Criteria

- **SC-2201**: A standalone runtime-backed loop completes using only repository code and an
  explicit runtime configuration.
- **SC-2202**: Mixed runtime/command role configurations complete and preserve strict evaluation.
- **SC-2203**: Resume rejects changed runtime provenance while no key or raw endpoint is written to
  strategy state.
- **SC-2204**: Existing full test suite remains green with no new runtime dependency.

## Out of scope

- Automatic provider/model discovery, global Hermes/OpenCode/OpenClaw configuration, remote queues,
  multi-tenancy, or a new model protocol.
- Runtime-specific prompt formats beyond the existing bounded Agent request.
- Replacing explicit solver portfolios or evaluator ensembles.
