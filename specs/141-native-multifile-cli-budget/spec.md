# Feature Specification: Native automatic multi-file CLI candidate budget propagation

**Created**: 2026-09-19
**Status**: Completed and validated offline; no campaign registration or provider request
**Input**: Feature 136 candidate-generation budgets, Feature 140 durable generation receipts,
and the current `solve --evolve --multi-file` path

## Problem

Feature 136 and Feature 140 provide an authority-bound candidate-generation budget and a durable
`agent_candidate_generation` receipt, but before this feature the native automatic multi-file conversational CLI did
not construct that budget. That path created `AgentCandidateGenerator` without a
`CandidateGenerationBudget`; the runtime therefore has only its ordinary loop ceiling and Feature
140 cannot retain a bound generation receipt. Feature 139 cannot honestly register its proposed
12-step candidate budget until this shared product path can receive and persist that value.

The existing `--agent-runtime-max-steps` option is a runtime/model-loop setting. It is not a
candidate-generation authority, is not persisted as the candidate budget, and may be unavailable
for adapters that do not use the repository Agent loop. Reusing it would conflate two distinct
ceilings and make a registered candidate budget unverifiable.

## User scenarios

### US1 - Select one explicit budget for automatic multi-file generation (P1)

An operator starts a new native automatic multi-file solve with
`--candidate-generation-max-steps N`. The CLI validates the value before creating a run or
calling a model, freezes it in the evolution handoff, and passes it to every native candidate
generation request. The candidate budget is independent of preparation, ordinary request, run
wall-clock, evaluator, and `--agent-runtime-max-steps` settings.

### US2 - Continue a handoff without changing generation authority (P1)

`resume` and `answer` restore the persisted candidate budget. An explicit continuation may repeat
the exact value, or omit it and use the persisted value. A different value, a newly supplied value
for a legacy handoff that has no candidate budget, or a mode switch fails before preparation,
child creation, provider request, or candidate generation.

### US3 - Preserve legacy and standalone behavior (P1)

An automatic multi-file solve that omits the new option retains the current no-candidate-budget
behavior. Explicit `evolve-bundle`, `evolve`, explicit bundle profiles, command generators, and
external producer paths retain their existing controls and are not silently assigned this budget.
The new option cannot be used to imply a budget in those paths.

## Requirements

### CLI and validation

- **FR-001**: Add the explicit option `--candidate-generation-max-steps` to the conversational
  `solve`, `resume`, and `answer` parsers. Its value is a positive integer in
  `[1, MAX_CANDIDATE_TOOL_STEPS]` (currently 200); booleans, zero, negatives, non-integers,
  non-finite values, and out-of-range values are rejected before run creation or runtime setup.
- **FR-002**: The option is valid only for native automatic multi-file mode
  (`--evolve --multi-file`, with the existing native population and automatic evaluator
  constraints). Supplying it without `--multi-file`, with an explicit `--bundle-profile`, an
  evaluator/producer command, a non-population strategy, or a non-evolution solve is rejected
  before Store mutation. The option is not added to the standalone `evolve-bundle` interface by
  this feature.
- **FR-003**: The resolved candidate step value is immutable for one handoff. It is validated
  before preparation and before any child workspace or provider request is admitted. The bounds
  and error category are stable and do not expose paths, prompts, credentials, or provider text.

### Handoff and authority propagation

- **FR-004**: A new automatic handoff persists the explicit value in its bounded
  `evolution_requested` payload with a clear source marker (for example, `explicit`). No local
  path, secret, prompt, or model response is persisted. When the option is omitted, the payload
  omits the candidate-budget field and retains legacy behavior; implementation must not inject a
  default budget into old or new handoffs.
- **FR-005**: `resume`, `answer`, and the conversational argument overlay restore the persisted
  value. An explicitly supplied value must exactly match it. A legacy handoff without the field
  rejects a newly supplied value rather than acquiring a budget during continuation. Omission on
  continuation continues to use the stored value, including the stored absence.
- **FR-006**: For automatic native multi-file generation, construct one immutable
  `CandidateGenerationBudget` before the `AgentCandidateGenerator` is invoked. Its
  `max_tool_steps` is the resolved CLI value, its `timeout_seconds` is the persisted/resolved
  candidate request timeout (`--timeout`, 600 seconds in Feature 139's future registration), and
  its base identity is `candidate-generation`; the generator may derive per-request identities as
  defined by Feature 136.
- **FR-007**: Pass that budget through both fresh and resumed conversational
  `solve --evolve --multi-file` construction paths. The runtime receives the candidate budget as
  its authority-bound `max_tool_steps` and budget identity. The model, workspace, returned
  metadata, and ordinary runtime defaults cannot increase or replace it.
- **FR-008**: A configured Agent-loop profile remains a hard safety ceiling as defined by Feature
  136. `--agent-runtime-max-steps` remains a separate runtime-loop setting and is neither renamed,
  overwritten, nor used as the candidate-budget field. Existing atomic whole-batch rejection,
  parser-gated completion, and Feature 140 receipt ordering remain unchanged.
- **FR-008a**: Runtime diagnostics may count remaining steps against a lower explicit profile
  ceiling, while the completed candidate receipt counts against the frozen candidate authority.
  When the runtime metadata provides a complete, consistent non-negative `(effective maximum,
  used, remaining)` tuple with `used + remaining == effective maximum <= candidate authority`,
  the generator may project receipt remaining as `candidate authority - used`. The effective
  runtime maximum must be a positive integer. Incomplete, malformed, inconsistent, or larger
  maxima must not be normalized into valid completion evidence. The receipt schema and its
  exact arithmetic validation remain unchanged, and this projection never enlarges the runtime
  execution ceiling. Runtime-forwarded failure diagnostics retain their existing effective
  maximum and cannot contain completed candidate identity.

### Scope decision for other CLIs

- **FR-009**: `evolve-bundle` and `_prepare_bundle_generator()` are explicitly out of scope for
  this option. Their explicit generator/runtime controls remain unchanged, including the existing
  `--agent-runtime-max-steps` loop setting. They must not begin emitting a candidate budget merely
  because this feature is installed. Extending the standalone bundle CLI requires a separate SDD
  with its own handoff and receipt contract.
- **FR-010**: Single-file conversational evolution, deterministic/command generators, OpenEvolve
  producer imports, and external producer seed paths remain unchanged. The option cannot silently
  alter their request, execution, evaluator, selection, or delivery behavior.

### Boundaries

- **FR-011**: This feature is offline implementation and validation only. It does not create a
  registration, call a provider, execute provider-generated source, run Feature 139, reopen Feature 131 or
  134, or compare WebAgent/OpenEvolve/Shinka outcomes.
  Repository-owned synthetic candidate and evaluator fixtures may execute locally to verify the
  existing end-to-end product path.
- **FR-012**: No database migration, global runtime ceiling change, retry/repair policy, token/cost
  accounting, or new campaign budget is introduced. Feature 139 may use the explicit option in a
  later fresh registration after this product change is pushed and independently validated.

## Acceptance criteria

1. Parser and preflight fixtures accept valid integer values, reject invalid values before Store or
   runtime construction, and reject the option in every unsupported mode listed above.
2. A new automatic multi-file request with `--candidate-generation-max-steps 12` persists exactly
   `12` and its source marker in `evolution_requested`; no secret, path, or prompt enters the
   payload. Omission persists no candidate-budget field.
3. Fresh and resumed automatic bundle construction pass an immutable budget with `max_tool_steps=12`,
   `budget_id="candidate-generation"` at the generator boundary, and the resolved request
   timeout. Feature 136's per-request identity derivation and Feature 140's durable receipt then
   observe the same authority.
4. `resume`/`answer` with the same value or omission succeed through policy validation; a changed
   value or a value added to a legacy handoff fails before preparation, child creation, provider
   request, or candidate execution.
5. `--agent-runtime-max-steps` remains independent, profile ceilings remain enforced, and a whole
   tool batch that exceeds the candidate budget is still rejected atomically with no retry or
   fitting-prefix execution.
6. Existing standalone `evolve-bundle`, explicit profile, single-file, deterministic, command,
   and producer tests pass without new candidate-budget fields or behavior.
7. Focused/shared regressions, static checks, Specify checks, diff checks, and Feature 131/134
   byte/SHA inventories pass. No provider request, real campaign evaluator invocation, or
   provider-generated-source execution occurs.

## Non-goals

This feature does not choose an empirically optimal step ceiling, guarantee candidate completion,
change model prompts, raise runtime/profile ceilings, expose usage or quality, add standalone
bundle support, or authorize the Feature 139 real run. The explicit 12-step value belongs to the
future Feature 139 registration; it is not a product-wide default.
