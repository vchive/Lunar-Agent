# Feature Specification: Evolution Agent Evidence

**Feature Branch**: `030-evolution-agent-evidence`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Persist bounded evidence produced by solver/evaluator Agents during evolution

## Context and scope

Native loop and population evolution can invoke a repository-owned Agent runtime. Those runtime
calls already create bounded session transcripts and emit model/tool lifecycle events, but the
evolution controller currently keeps only candidate, state, and execution evidence. This feature
connects the Agent bridge to the existing SQLite ledger and artifact registry without changing the
runtime-neutral strategy API or introducing a service layer.

## User stories and acceptance scenarios

### User Story 1 — Inspect solver/evaluator evidence (P1)

1. Given a native evolution run using a session-aware Agent runtime, when a candidate is generated
   or evaluated, then its transcript is registered as a run-relative artifact and can be found in
   `status --json` and `events --json`.
2. Given a runtime with tool calls, when the run completes, then bounded model-turn and tool-result
   events identify the role, adapter, and step outcome without storing model output or secrets.

### User Story 2 — Fail closed on unsafe evidence (P1)

1. Given a declared artifact outside the evolution workspace, a symlink, or a missing file, when an
   Agent result is normalized, then that invocation fails closed and no unverified artifact is
   indexed.
2. Given an API key in runtime configuration or an error string, when evidence is persisted, then
   the key is redacted from transcripts, events, and state.

### User Story 3 — Preserve all existing evolution modes (P1)

1. Given deterministic callbacks, command-backed adapters, or OpenEvolve, when evolution runs,
   then existing archive/state/result behavior remains unchanged.
2. Given a resumed run, when a prior transcript exists, then new Agent evidence is appended or
   indexed idempotently without duplicating artifact rows.

## Functional requirements

- **FR-3001**: Agent candidate generators and evaluators MUST validate every declared artifact as a
  regular, run-relative, non-symlink file before exposing it to the evolution controller.
- **FR-3002**: Valid Agent artifacts MUST be reported through the existing evolution observer as
  run-relative paths with role, adapter, and bounded size metadata.
- **FR-3003**: The controller MUST register valid Agent artifacts in SQLite with a distinct
  evolution-Agent artifact kind and emit an idempotent audit event.
- **FR-3004**: Runtime model-turn, tool-result, step-limit, and runtime-failure events MUST flow
  through the same observer and MUST exclude raw model content, prompts, API keys, and large tool
  output.
- **FR-3005**: Transcript and error evidence MUST be bounded and API-key redacted; unsafe paths,
  symlinks, and malformed metadata MUST fail closed.
- **FR-3006**: Existing `loop`, `population`, `openevolve`, command, and callback integrations MUST
  remain backward compatible when no Agent observer is configured.

## Success criteria

- **SC-3001**: A fake tool-capable runtime produces indexed solver and evaluator transcripts plus
  model/tool events in one evolution run.
- **SC-3002**: Unsafe artifact and symlink fixtures are rejected without an artifact row outside
  the run workspace.
- **SC-3003**: API-key values do not occur in artifact content, event payloads, state, or result
  JSON.
- **SC-3004**: Full legacy tests, lint, compile, and Specify checks remain green.

## Out of scope

- Persisting raw prompts, full model responses, tool output, or chain-of-thought.
- Remote event streaming, queues, distributed tracing, or service deployment.
- Changing candidate/evaluation schemas or making an Agent runtime mandatory.
