# Feature 084: Verified Seed Handoff and Evolution Backend Boundary

**Feature Branch**: `084-verified-seed-handoff`

**Created**: 2026-09-11

**Status**: Draft

**Input**: Local review of famou-v2 `product/dev`, WebAgent 2.5 evolution control, and Lunar's existing population evolution path.

## Problem and goal

famou-v2 starts with executable `initial_programs`, re-runs enrichment and evaluation locally, and refuses to start when no seed is usable. WebAgent 2.5 delegates deep evolution to a remote famou-v2 service through an experiment control plane. Lunar currently has a local population strategy, but it has no typed handoff for importing an externally produced candidate with its lineage, evaluator evidence, producer identity, and environment assumptions. This feature adds a framework-neutral local handoff boundary for local subprocess producers such as OpenEvolve and for remote evolution backends. It also documents an opt-in remote backend contract without changing the staged Master→Build path or treating any external score as a Lunar score.

### User Story 1 - Admit only locally verified seeds (Priority: P1)

An operator can place candidate artifacts and framework-neutral provenance in a local seed manifest. Provenance declares `origin_kind`, `producer_id`, `producer_fingerprint`, and an optional `producer_run_id` without embedding framework-specific payloads. Lunar validates identity, source bounds, dependency metadata, lineage, and provenance, then runs the configured local evaluator. External evidence and record metadata are reduced to a fixed digest-only summary before canonical persistence. Only candidates with a fresh local evaluator receipt enter the initial population; an external score alone is never sufficient, whether it came from a local OpenEvolve subprocess or a remote backend.

**Why this priority**: A cold or invalid population is the immediate failure mode. The evaluator must remain the authority before any evolution strategy can use a candidate.

**Independent Test**: Feed a fixture manifest to the adapter with zero, one valid, and one invalid seed. Verify invalid seeds are rejected, one valid seed is admitted, and an all-invalid manifest fails before a strategy starts.

**Acceptance Scenarios**:

1. **Given** a bounded manifest whose source, dependencies, and provenance are valid, **When** the local evaluator returns a valid receipt, **Then** the adapter emits one candidate with a stable ID, deterministic generation/iteration/island fields, an evaluator receipt reference, and a bounded producer projection.
2. **Given** one valid seed and one seed with a missing source, dependency verification failure, invalid receipt, or evaluator validity other than `1.0`, **When** every record has been adjudicated, **Then** the invalid seed is excluded with a fixed safe reason and the admitted subset is committed atomically without exposing partial population updates during processing.
3. **Given** that the admitted subset is empty because every seed is excluded or has no score, **When** initialization is validated, **Then** initialization fails closed and no generator, remote backend, or population mutation is made after the evaluator gate.

### User Story 2 - Resume and evolve with auditable provenance (Priority: P1)

An operator can start or resume Lunar's existing local population strategy with admitted seeds and later inspect which source, evaluator receipt, environment, and parent lineage produced each candidate. Restarting the run preserves the seed identity and does not silently re-admit a changed artifact.

**Why this priority**: Population selection, checkpoint recovery, and exact scoring are useful only when the origin and validity of each candidate remain auditable.

**Independent Test**: Start a fixture population with one verified seed, persist a checkpoint, mutate the source or evaluator fingerprint, and resume. The unchanged fixture resumes; the changed one is rejected with a contract mismatch before selection.

**Acceptance Scenarios**:

1. **Given** an admitted seed and a population checkpoint, **When** the run resumes with matching contract and evaluator fingerprint, **Then** the seed remains active with the same candidate ID.
2. **Given** a changed source digest, dependency lock, evaluator fingerprint, contract digest, or canonical provenance fingerprint, **When** resume is attempted, **Then** it fails closed without adding a duplicate candidate.
3. **Given** a seed admission or local evaluator failure, **When** initialization persists state, **Then** the failed seed is not counted as usable, not inserted into the active population, and no formal iteration is consumed. Later rollout retry semantics remain a separately specified change.

### User Story 3 - Keep remote evolution backends explicitly optional (Priority: P2)

An integration owner can describe a remote evolution experiment, such as a future famou-v2 integration, using a typed `submit`/`status`/`sync`/`continue_experiment`/`cancel` boundary. The boundary records backend identity and material provenance, but remote output is imported only as an untrusted seed candidate pending local exact-harness re-evaluation. The default CLI remains local and performs no network call.

**Why this priority**: WebAgent's current deep-evolution path is a remote control plane, not a drop-in local Agent runtime. Making that distinction explicit prevents accidental coupling and false Lunar leaderboard claims.

**Independent Test**: Use a fake backend fixture to assert request/response schemas and lifecycle reconciliation. Verify default construction has no backend and a remote result cannot produce a local score or population entry without the local evaluator receipt.

**Acceptance Scenarios**:

1. **Given** an explicit remote backend configuration, **When** submit is called, **Then** the request contains bounded experiment metadata and returns an opaque remote ID without secrets.
2. **Given** a remote result with an external score but no local receipt, **When** sync imports it, **Then** it is retained as provenance-only material and is not ranked or scored locally.
3. **Given** the default local CLI path, **When** an evolution run is created, **Then** no remote backend is instantiated and no network request occurs.

## Edge Cases

- Empty, duplicate, oversized, path-escaping, symlinked, or non-regular seed artifacts fail before evaluator execution.
- A seed whose declared dependency or environment digest cannot be verified is not admitted; the receipt records a bounded failure code, never exception text or credentials. This feature does not install dependencies.
- Two manifests that claim one identity but contain different source or environment digests are rejected as an identity collision.
- A remote experiment that times out, returns no ID, or cannot reconcile status remains `unknown`; the adapter does not invent completion, score, or cost.
- An OpenEvolve or other external result that includes an evaluation but no matching local receipt remains provenance-only.
- An external candidate may be valid under its producer's evaluator but still fail the current contract's exact harness; it is excluded from the population and remains provenance-only.

## Requirements

### Functional Requirements

- **FR-001**: System MUST accept a bounded local seed manifest containing candidate source, source digest, stable identity, lineage, dependency/environment metadata, framework-neutral provenance (`origin_kind`, `producer_id`, `producer_fingerprint`, and optional `producer_run_id`), and optional external evidence. For `origin_kind=external`, evidence and record metadata MUST normalize to exactly `present`, `score_present`, and `payload_sha256`; raw score values and prose MUST NOT enter canonical state.
- **FR-002**: System MUST re-evaluate every imported seed with the configured local evaluator before creating a `Candidate` or changing population state. External includes local subprocess results such as OpenEvolve as well as material synchronized from a remote backend.
- **FR-003**: System MUST require a structured local evaluator receipt containing contract digest, evaluator fingerprint, evaluator kind, validity, score fields, and receipt digest; every external import MUST use the exact-harness evaluator kind, and external scores are advisory.
- **FR-004**: System MUST fail initialization when no seed has a usable local score, and MUST make zero generator, remote backend, or population mutations after the evaluator gate in that case. The admission evaluator is an explicit injected local contract; any model-backed evaluator remains outside this claim.
- **FR-005**: System MUST persist seed provenance and identity in candidate metadata and checkpoint/archive records, including evaluator kind as well as fingerprint, a compact producer projection, and the safe external summary, subject to existing bounded artifact and secret-safety limits.
- **FR-006**: System MUST reject resume when source, dependency/environment, evaluator, contract identity, or canonical provenance fingerprint no longer matches the persisted handoff. `producer_run_id` remains provenance and MUST NOT replace or determine the candidate ID.
- **FR-007**: System MUST ensure seed admission/evaluator failures do not advance an iteration or enter the active population. Any change to later rollout retry semantics MUST be separately specified and tested; 084 MUST NOT claim current PopulationStrategy already matches famou-v2.
- **FR-008**: System MUST expose a framework-neutral remote backend protocol for `submit`, `status`, `sync`, `continue_experiment`, and `cancel` with opaque IDs and bounded, credential-safe payloads.
- **FR-009**: System MUST keep the remote backend opt-in and absent from default staged and local evolution construction.
- **FR-010**: System MUST route every external candidate, including an explicit local OpenEvolve result and a remote synchronized result, through the configured exact-harness evaluator before local ranking, verify its evaluator fingerprint and receipt digest, and label external scores as provenance-only until then.
- **FR-011**: System MUST preserve 074, 076, 078, and 082 sealed artifacts and must not launch a model, WebAgent, provider probe, company evaluation, or new campaign as part of this feature.

## Key Entities

- **SeedManifest**: bounded input record for one or more candidate artifacts and the handoff contract identity.
- **SeedIdentity**: stable candidate ID derived from source, lineage, contract, evaluator kind and fingerprint, dependency, and environment digests; collision-resistant and independent of producer run IDs.
- **EvaluatorReceipt**: local authoritative validity/score evidence tied to contract and evaluator fingerprints.
- **SeedProvenance**: framework-neutral origin and producer record containing `origin_kind` (`local` or `external`), a bounded `producer_id`, a producer/configuration SHA-256 `producer_fingerprint`, an optional opaque `producer_run_id`, lineage, material references, and a digest-only external evidence summary.
- **RemoteEvolutionBackend**: optional lifecycle protocol for remote experiment control; it never owns local scores or population state.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Offline fixtures demonstrate 100% rejection of invalid, missing, duplicate, and receipt-less seeds before population mutation.
- **SC-002**: A valid seed can be admitted, checkpointed, and resumed with byte-identical identity and matching evaluator/contract fingerprints.
- **SC-003**: Default local construction performs zero remote backend calls and preserves all existing evolution and staged workflow tests.
- **SC-004**: Fake OpenEvolve and remote fixture results with only external scores produce zero local scored candidates until exact local re-evaluation succeeds.

## Assumptions and limits

- The first implementation is local-only for seed admission; no real external evolution framework or famou-v2 service is invoked.
- Existing `EvaluationReport`, `Candidate`, archive, checkpoint, and exact harness contracts remain authoritative and are extended only through bounded metadata or a versioned adapter contract.
- This feature does not claim an effective-solution improvement and does not reopen sealed campaign slots. A future real measurement needs a separate frozen registration.
