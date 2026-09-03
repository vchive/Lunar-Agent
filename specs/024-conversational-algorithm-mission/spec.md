# Feature Specification: Conversational Algorithm Mission

**Feature Branch**: `024-conversational-algorithm-mission`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Let a user describe an algorithmic objective without hand-writing `contract.json`

## Context and scope

Feature 012 introduced a validated `AlgorithmProblemContract`, and Features 013–023 added local
evolution, role adapters, independent evaluation, and bounded candidate execution. This feature
adds the missing intake surface: `solve "…"` compiles a natural-language objective into a strict
contract and a durable execution plan. The compiler is runtime-neutral and may use the repository
mock, an explicit subprocess, or an OpenAI-compatible endpoint. No Hermes/OpenCode/Codex discovery
or service plane is introduced.

The controller remains the source of truth. A missing material decision pauses the same run in
`awaiting_input`; `answer` writes a run-relative answer artifact and resumes compilation. A
compiled contract is persisted as an immutable artifact and attached to a version-1 `PlanDocument`
with an algorithm-focused task DAG. The generated contract is still validated by the existing
schema before any task is scheduled.

## User stories and acceptance scenarios

### User Story 1 — Describe an algorithm problem conversationally (P1)

As a local user, I want to say what I need in ordinary language so that Lunar-Agent can produce a
reviewable algorithm contract and plan.

1. **Given** a valid compiler response, **when** `solve` is invoked, **then** the run stores a
   canonical contract, plan document, compiler evidence, and returns their paths in JSON.
2. **Given** malformed JSON, an invalid contract, or an unsafe value, **when** compilation runs,
   **then** the run fails closed and no plan task is executed.

### User Story 2 — Clarify missing information durably (P1)

As a user, I want the agent to ask concise questions instead of inventing hard constraints,
objectives, or input fields.

1. **Given** a compiler response with `status=needs_input`, **when** `solve` runs, **then** the
   same run becomes `awaiting_input`, writes a bounded request artifact, and returns the questions.
2. **Given** a pending request, **when** `answer RUN_ID …` is invoked, **then** the answer is
   hashed as a local artifact, the compiler receives it, and the same run continues to contract
   compilation and plan execution.
3. The compiler MUST reject a compiled response that has unresolved questions or lacks provenance
   for constraints and assumptions; it MUST never silently turn unknown facts into user-confirmed
   hard constraints.

### User Story 3 — Execute and resume the generated plan (P1)

As a parent Agent or local owner, I want the compiled mission to use the existing scheduler and
artifacts so that retries, cancellation, status, and delivery work exactly like hand-authored
plans.

1. A successful compilation creates a version-1 plan whose task IDs are stable and whose DAG is
   acyclic; role tasks receive the contract and only verified dependency artifacts.
2. Detached `solve` returns a run ID and propagates non-secret compiler settings. Resume rejects a
   changed compiler identity, while API keys and raw prompts remain out of durable strategy state.
3. `status --json` exposes compiler state, contract digest, plan revision, and pending input.

## Functional requirements

- **FR-2401**: Expose a runtime-neutral `ContractCompiler` protocol and immutable bounded
  compilation result.
- **FR-2402**: Accept only a strict JSON envelope with `compiled` or `needs_input` status; compiled
  payloads MUST pass `AlgorithmProblemContract.from_dict` and a generated `PlanDocument` validator.
- **FR-2403**: Bound goal, response, question, and answer sizes; redact configured credentials;
  reject non-finite, secret-like, path-escaping, and unknown contract data.
- **FR-2404**: `needs_input` MUST contain one to four questions and no executable plan; the
  controller MUST persist the request and pause the same task/run.
- **FR-2405**: A compiled mission MUST persist canonical `contract.json`, `plan.json`, and a
  compiler manifest with SHA-256 digests under the run workspace and index them as artifacts.
- **FR-2406**: The generated plan MUST preserve contract provenance and use a bounded algorithm DAG
  (`data_discovery → formulate → solve → verify`) with no cycles or invented dependencies.
- **FR-2407**: Contract compilation MUST happen before generated plan tasks execute. Existing
  scheduler retry, cancellation, artifact hashing, and resume semantics remain authoritative.
- **FR-2408**: CLI `solve` MUST support `--runtime mock|subprocess|openai-compatible`, `--command`,
  endpoint/model/API-key options, `--detach`, `--resume`, and `--run-id`; `answer` MUST resume it.
- **FR-2409**: Detached propagation and manifests MUST store only credential-safe compiler
  fingerprints; raw commands, endpoint credentials, and model response text MUST not enter state.
- **FR-2410**: Existing `run`, `plan`, `evolve`, `delegate`, and library APIs remain backward
  compatible when `solve` is unused.

## Success criteria

- **SC-2401**: A fixture runtime can compile a valid routing/assignment contract and generated plan;
  the normal controller executes it and `status --json` exposes the durable evidence.
- **SC-2402**: 100% of malformed envelope, invalid contract, unresolved-question, secret, and
  path-escape fixtures fail closed without executing plan tasks.
- **SC-2403**: A fixture `needs_input` response pauses and resumes the same run after `answer`,
  retaining the answer and compiler artifacts.
- **SC-2404**: Existing full tests and detached/recovery tests remain green without new runtime
  dependencies.

## Out of scope

- Automatic dataset discovery, code execution, candidate evolution, or domain-specific evaluator
  construction; those remain explicit later stages/adapters.
- A mandatory LLM provider, Hermes/OpenCode/Codex dependency, remote queue, HTTP API, or UI.
- Claiming semantic truth for model-generated constraints; provenance and user confirmation remain
  explicit contract fields.
