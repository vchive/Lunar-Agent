# Feature Specification: Tool-Capable Evolution Agent Loop

**Feature Branch**: `026-evolution-agent-loop`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Allow repository-owned evolution Agents to inspect and test candidates through tools

## Context and scope

Features 022–025 made runtime-backed evolution and role DAGs available, but runtime-backed solver
and evaluator calls still use one-shot text turns. WebAgent/Hermes-style algorithm work benefits
from a bounded loop that can inspect files, run tests, and iterate before returning a candidate or
report. This feature exposes that loop explicitly for evolution's repository-owned
OpenAI-compatible runtime.

The loop is opt-in and remains local. Tools are the existing `LocalToolRegistry`; command execution
is no-shell and disabled unless explicitly enabled. The controller/evolution archive remains the
authority, and a loop cannot directly set validity or bypass candidate/evaluator schemas.

## User stories and acceptance scenarios

### User Story 1 — Iterate on a candidate with local tools (P1)

1. **Given** `--agent-runtime openai-compatible --agent-runtime-loop`, **when** a solver runs,
   **then** the model can make bounded file/read/write/tool calls in its candidate workspace and
   returns through the existing strict candidate bridge.
2. Tool steps are bounded by `--agent-runtime-max-steps`; command execution is available only with
   `--agent-runtime-allow-exec` and remains no-shell.

### User Story 2 — Keep evaluator authority independent (P1)

1. A loop-backed evaluator can inspect candidate/evidence and return only a schema-validated
   `EvaluationReport`; malformed or missing reports fail closed as before.
2. Solver loop output cannot alter archive ranking, validity, provenance, or controller state.

### User Story 3 — Resume and secrets remain safe (P1)

1. Detached evolution propagates loop settings and rejects changed loop/runtime fingerprints.
2. Session transcripts and tool outputs remain bounded artifacts; API keys are redacted and never
   placed in argv or evolution state.
3. Existing one-shot runtime, command, Agent, population, OpenEvolve, and non-evolution CLI paths
   remain unchanged.

## Functional requirements

- **FR-2601**: Add an explicit evolution runtime-loop option for OpenAI-compatible runtime-backed
  solver/evaluator seams.
- **FR-2602**: The loop MUST reuse `AgentLoopRuntime` and `LocalToolRegistry`; no new runtime or
  external dependency is allowed.
- **FR-2603**: Loop settings MUST be bounded and validated before run creation; exec, memory, and
  transcript features require explicit opt-in.
- **FR-2604**: Runtime fingerprints and detached propagation MUST include loop settings without
  persisting API keys or raw response contents.
- **FR-2605**: Loop-backed generation/evaluation MUST continue through
  `AgentCandidateGenerator`/`AgentCandidateEvaluator` and all existing schema/evaluator guards.
- **FR-2606**: Runtime adapter calls MUST attach durable context and optional transcript paths so
  tool calls can resume within the candidate attempt workspace.

## Success criteria

- **SC-2601**: A fake OpenAI-compatible model that performs a tool call can generate a candidate
  through `evolve --agent-runtime-loop`.
- **SC-2602**: Exceeding loop steps, disabled exec, malformed tool calls, and evaluator reports fail
  closed with bounded evidence.
- **SC-2603**: Detached loop settings propagate and changed settings are rejected on resume.
- **SC-2604**: Existing full tests pass without a new runtime dependency.

## Out of scope

- Automatic harness discovery, unrestricted shell/sandboxing, remote queues, or parallel model
  sessions.
- Making loop mode the default for existing runtime-backed evolution; compatibility requires opt-in.

