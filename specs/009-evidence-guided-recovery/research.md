# Research: Evidence-Guided Recovery Proposals

## Decision 1: Propose, never mutate

**Decision**: `recover` is an observation/control recommendation command. It does not invoke
`resume`, alter a task, revise a plan, raise a budget, call a Runtime Adapter, or make a model call.

**Rationale**: The durable ledger can prove that work failed, but it cannot safely infer the owner's
authority to retry an external runtime, relax a cost/time boundary, or revise acceptance. Existing
`patch`, `replan`, `answer`, and `resume` already implement intentional state transitions.

**Alternatives considered**:

- Automatically retry/replan: rejected because it hides state changes and can repeat side effects.
- Let a model explain failures: deferred because it adds provider dependence and can expose local
  artifacts or secret-bearing errors.

## Decision 2: Keep recovery policy deterministic and adapter-neutral

**Decision**: A new pure `RecoveryPolicy` consumes domain objects and persisted event payloads. It
does not import runtime implementations or evaluator internals.

**Rationale**: A mock, subprocess agent, Hermes-inspired session, or parent-driven runtime must get
the same recovery decision from the same durable evidence.

## Decision 3: Preserve raw evidence in existing records; use controlled evidence in proposals

**Decision**: Proposals reference only IDs, statuses, event/rule kinds, and known budget limit names.
Raw error text, prompts, user answers, model output, and artifact contents are not copied.

**Rationale**: Existing evaluation/input artifacts remain the audit source. A new recovery record
must not become a credential or sensitive-content amplification channel.

## Decision 4: Content-derived idempotency

**Decision**: Canonical proposal JSON is SHA-256 fingerprinted. The fingerprint defines both event
ID and `recovery/proposals/<fingerprint>.json` path.

**Rationale**: Calls are safe to repeat and an evolving run naturally produces a different proposal
without a schema migration or a mutable latest-proposal table.

## Decision 5: Patch guidance rather than an executable patch

**Decision**: Acceptance failure on a versioned plan yields `propose_patch` with target logical task,
current plan revision, and required operation type; it does not invent a replacement prompt or
weaken the acceptance contract.

**Rationale**: A syntactically executable patch that merely repeats the old prompt is misleading;
inventing task instructions is a planning/model decision. The existing versioned-plan CLI supplies
the mutation boundary once a parent has inspected bounded evaluation evidence.
