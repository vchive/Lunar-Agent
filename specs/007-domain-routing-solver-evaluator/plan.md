# Implementation Plan: Domain Routing, Solver/Evaluator Profiles, and Budgets

## Architecture

Add three runtime-neutral modules: `routing.py` (deterministic classification), `profiles.py`
(named solver/evaluator registry), and `budget.py` (validated limits and usage checks). The
controller selects route metadata before creating durable work, stores it in additive run columns,
and emits a `route_selected` event. Evaluator selection remains dependency-injected; the default
profile registry preserves `NonEmptyEvaluator`.

## Data Model

Runs gain nullable `route_domain`, `route_reason`, `route_confidence`, `solver_profile`,
`evaluator_profile`, `route_evidence`, and `budget` columns through additive migrations. `Run` and
`status --json` expose these fields. Budget failures are events and terminal run failures; no new
service or queue is introduced.

## Phases

1. Define and validate route/profile/budget contracts with unit tests.
2. Add SQLite migration and controller integration while preserving legacy signatures.
3. Enforce task/attempt/time/artifact budgets and observe agent tool-step events.
4. Expose status/route CLI JSON and document quickstart/contracts.
5. Run full tests, Ruff, and local quickstart; commit as `vchive` and push `main`.

## Complexity Tracking

No new dependency or service. The only additive complexity is nullable metadata and a small
deterministic policy layer; callers can continue passing a custom evaluator/runtime.
