# Feature Specification: Domain Routing, Solver/Evaluator Profiles, and Budgets

**Feature Branch**: `007-domain-routing-solver-evaluator`
**Created**: 2026-09-02
**Status**: Implemented

## Goal

Make complex local runs choose an explicit domain strategy and bounded execution budget. Routing is
deterministic and runtime-neutral; profiles are injectable; every decision is persisted and exposed
to parent Agents as stable JSON. Existing one-step runs and Feature 006 plans remain compatible.

## User Scenarios & Testing

### User Story 1 - Route a Goal to the Smallest Useful Domain (Priority: P1)

As a local user or parent Agent, I want a goal classified as `general`, `data`, `research`, or
`coding` with evidence so the controller can select appropriate defaults without a specific runtime.

**Independent Test**: Route representative English and Chinese goals; ambiguous goals fall back to
`general` with lower confidence and no unsafe capability.

**Acceptance Scenarios**:

1. Spreadsheet/CSV/aggregation goals return `domain=data`, a data evaluator, and matched evidence.
2. Source-code/test/bug goals return `domain=coding` and coding solver/evaluator profiles.
3. Explanatory or ambiguous goals return `domain=general` without invented capabilities.

### User Story 2 - Execute with Injectable Solver and Evaluator Profiles (Priority: P1)

As a developer, I want domain profiles replaceable independently of the Runtime Adapter so Hermes
sessions, OpenAI-compatible calls, subprocesses, and mocks share one control plane.

**Independent Test**: Inject a rejecting evaluator profile, execute a run, and verify it cannot be
delivered; the default registry preserves legacy non-empty behavior.

**Acceptance Scenarios**:

1. A routed run without a custom evaluator uses the selected profile and persists structured evidence.
2. A caller-supplied evaluator/profile override is honored without changing the runtime adapter.
3. Unknown or unsafe profile metadata fails before durable work is written.

### User Story 3 - Govern Long-Running Work with Auditable Budgets (Priority: P1)

As a local owner, I want limits on tasks, attempts, tool steps, elapsed runtime, and artifact bytes
so a long-running agent remains bounded and can be resumed or replanned after controlled failure.

**Independent Test**: Exceed each limit and inspect the `budget_exceeded` event, blocked state, and
JSON status payload.

**Acceptance Scenarios**:

1. If the next task would exceed `max_tasks` or `max_attempts`, no attempt is claimed and the run
   fails with a structured budget event.
2. If a session emits more tool steps than allowed, the controller fails closed.
3. If artifact bytes exceed the budget, the run fails while prior artifacts remain inspectable.

### User Story 4 - Inspect Routing, Profiles, and Limits (Priority: P2)

As a parent Agent, I want one JSON status response to include route, profiles, budget, and evidence.

**Independent Test**: Create legacy and planned runs and verify stable bounded metadata via
`status --json`.

## Edge Cases

- Multiple domain signals use deterministic precedence and preserve bounded evidence.
- Goals containing secrets are rejected before routing metadata is persisted.
- Limits are positive integers/finite seconds; invalid values are rejected atomically.
- Budget failure during retry or cancellation races never overwrites a terminal task result.
- Existing databases without route columns are upgraded additively.
- Feature 006 plans may specify a budget object; omitted values inherit route defaults.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-701**: Expose a deterministic runtime-neutral router returning bounded JSON fields `domain`,
  `reason`, `confidence`, `required_capabilities`, `solver_profile`, `evaluator_profile`, `budget`,
  and `evidence`.
- **FR-702**: Support `general`, `data`, `research`, and `coding`, with deterministic `general`
  fallback.
- **FR-703**: Register named Solver/Evaluator profiles validated for bounded text and credentials,
  injectable without runtime-specific imports.
- **FR-704**: Select the route evaluator unless a caller explicitly supplies an evaluator override;
  legacy `NonEmptyEvaluator` remains available.
- **FR-705**: Support max tasks, attempts, tool steps, runtime seconds, and artifact bytes; enforce
  limits fail-closed and record structured events.
- **FR-706**: Enforce budgets before claiming work and after runtime/artifact events, preserving prior
  artifacts and preventing delivery after failure.
- **FR-707**: Persist route, profiles, budget, and evidence with additive SQLite migrations and expose
  them in `status --json`.
- **FR-708**: Preserve existing run/resume/plan/patch/replan/deliver, adapters, memory, transcript,
  recovery, cancellation, and JSON contracts.
- **FR-709**: Remain local-first; add no HTTP/SSE, multi-tenancy, remote queues, billing, or
  mandatory Hermes/OpenCode/Codex dependency.

## Key Entities

- **RouteDecision**: Immutable bounded classification and selected profile/budget references.
- **SolverProfile** / **EvaluatorProfile**: Named domain strategy and structured evaluator factory.
- **BudgetSpec**: Positive execution limits and serialization contract.
- **BudgetExceeded**: Structured failure reason emitted to the run ledger.

## Success Criteria *(mandatory)*

- **SC-701**: Routing fixtures classify at least 95% of representative goals correctly and 100% of
  ambiguous fixtures as `general`.
- **SC-702**: Injected evaluator profiles reject results and prevent delivery in 100% of fixtures;
  all pre-feature tests continue to pass.
- **SC-703**: Every budget limit has a fail-closed fixture, persisted `budget_exceeded` event, and
  inspectable prior artifacts.
- **SC-704**: `status --json` exposes route/profile/budget metadata under 20 KiB without credentials.
- **SC-705**: Feature 006 databases upgrade additively and all existing plan/recovery tests pass.

## Assumptions

- Deterministic heuristics come first; model-assisted routing can later implement the same contract.
- Profiles describe policy and verification, not process spawning.
- A budget applies to one run and is inherited by replans unless a new validated budget is supplied.
- SQLite and local files remain the only required durable dependencies.
