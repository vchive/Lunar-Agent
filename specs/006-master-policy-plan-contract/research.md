# Research: Master Policy and Plan Contracts

## Decision 1: Port WebAgent effects, not its service architecture

**Decision**: Keep Master policy as a local deterministic/injectable domain service. Reuse the
existing controller, SQLite ledger, artifact store, evaluator, and Runtime protocol. Do not add
HTTP/SSE, gateway registration, remote queues, multi-tenancy, billing, or OpenCode plugin APIs.

**Rationale**: The WebAgent branches show that measurable quality comes from routing, structured
clarification, plan provenance, schema-driven outputs, independent evaluation, and explicit
evolution. Its deployment machinery is irrelevant to a single-user local Agent and would violate
Lunar-Agent's standalone constitution.

**Alternatives considered**:

- Recreate the complete fixed WebAgent stage machine: rejected because simple questions would pay
  unnecessary intake/clarify/verify overhead and Hermes-style sessions need flexible continuation.
- Make OpenCode the controller: rejected because it would reintroduce a host-specific runtime
  dependency and weaken the CLI boundary used by Codex/OpenClaw/Hermes.

## Decision 2: Immutable revisions plus optimistic concurrency

**Decision**: Every plan update creates an immutable revision. `PATCH` requires the current plan ID
and version; `REPLAN` creates a new version with explicit reason/evidence. A single SQLite
transaction checks the base version and inserts the revision and event.

**Rationale**: This mirrors WebAgent's explicit evolution lifecycle while remaining restart-safe and
inspectable. A stale parent Agent cannot silently overwrite a newer plan.

**Alternatives considered**:

- In-place JSON replacement: rejected because it loses provenance and makes crash recovery ambiguous.
- A separate plan service: rejected as unnecessary local infrastructure.

## Decision 3: Reuse the task graph validator and table

**Decision**: Plan tasks are normalized through the existing `Store._validate_plan_tasks` rules and
then inserted into the existing task table. Plan JSON is retained in a separate revision table so
legacy `--plan` users and the scheduler remain backward-compatible.

**Rationale**: One graph validator prevents drift between planning and execution, while an additive
schema migration avoids rewriting existing databases.

## Decision 4: Deterministic policy heuristic first

**Decision**: Ship a small heuristic policy that classifies direct explanations as `answer`, goals
with explicit missing decisions as `ask_user`, and goals mentioning multiple steps/files/checks as
`execute_plan`. Expose a Protocol so a model-backed policy can be added later.

**Rationale**: The feature is a durable contract and orchestration seam, not a new planning model.
Deterministic fixtures make recovery and safety tests reproducible.

## Decision 5: Delivery is evidence-based

**Decision**: `deliver` is allowed only for a succeeded run whose tasks have passing evaluator
events and at least one indexed hashed artifact. Delivery returns run-relative paths and bounded
evidence; failures remain failures or trigger `replan`.

**Rationale**: This preserves WebAgent's solver/evaluator separation and the constitution's
artifact-first rule without adding another process.

