# Feature 086: Remote Material Handoff

**Feature Branch**: `086-remote-material-handoff`

**Created**: 2026-09-13

**Status**: Complete and independently reviewed (2026-09-13)

## Problem and goal

Feature 084 defines a transport-free remote evolution lifecycle, and the producer envelope
defines the local exact-evaluator boundary. A completed `RemoteExperimentState` currently stops at
score-free material references, so an integration owner still has to hand-build a producer
envelope. That gap makes it easy for a future backend adapter to bypass identity pins or treat a
remote completion as a local score.

This feature adds one offline bridge: a completed, reconciled remote state is converted to the
existing `lunar-producer-result-v1` envelope and admitted through the same local evaluator path as
OpenEvolve and ShinkaEvolve. It adds no transport, scheduler, remote client, score authority, or
new candidate schema.

## Scope and authority

- Only `status=completed` with a reconciled experiment ID and at least one material is importable.
  `unknown`, `submitted`, `running`, `failed`, and `cancelled` states fail closed.
- Callers pin the contract, producer ID/fingerprint, and local exact-harness evaluator
  fingerprint. The state is untrusted input; its producer identity must match those pins. The
  current `RemoteExperimentState` lifecycle DTO does not carry the submit request's contract
  digest, so the caller is responsible for obtaining a state for the intended contract; the
  bridge binds the supplied digest to the local re-evaluation.
- Only `candidate_source` material references are accepted. Every referenced file is read below a
  caller-supplied local material root, and regular-file, size, SHA-256, UTF-8, symlink, FIFO, and
  path-confinement checks remain enforced by the generic producer admission boundary.
- Remote timestamps, attempt counts, raw state identity, and material-reference metadata are
  digest-only external evidence. A validated generic-safe experiment ID may remain as the opaque
  `producer_run_id` provenance label; it is never a score or candidate identity. A remote completion
  or score-like metadata can never create a local `EvaluationReport`, ranking entry, archive record,
  or population member without the injected local evaluator.
- If a previous state is supplied, the bridge first applies `reconcile_remote_state`; it never
  calls a backend and never retries an uncertain operation.
- Any caller-supplied `staging_root` must be a sibling tree disjoint from `material_root` (including
  resolved filesystem aliases), so local admission cannot create temporary files in the
  synchronized material tree.

## Acceptance scenarios

1. A completed fake remote state with valid local material is converted and admitted by a local
   exact evaluator. The resulting seed has `origin_kind=external`, the pinned producer identity,
   the opaque experiment ID as provenance, and a locally generated receipt.
2. A completed state carrying a high remote score in an out-of-band fixture remains provenance
   only; the local evaluator's score is the only admitted score. No raw remote payload is retained.
3. Unknown/non-terminal/failed/cancelled states, missing experiment IDs, producer identity drift,
   unsupported material kinds, and invalid reconciliation fail with fixed errors before evaluator
   invocation. Because the lifecycle DTO has no contract digest, a contract mismatch is detectable
   only when the caller binds the observation to its retained submit request; the bridge always
   checks the supplied contract before local evaluation.
4. Missing, changed, symlinked, FIFO, oversized, path-escaping, or digest-mismatched material
   files fail closed. An all-invalid local evaluation preserves the generic
   `SeedAdmissionError(code="no_usable_seeds")` result semantics. The bridge makes no backend call
   and does not mutate the remote root; an overlapping staging root is rejected before admission.
5. A Shinka SQLite fixture can be exported to the generic envelope and admitted through the same
   local evaluator path, proving both producer paths converge without external execution.

## Requirements

- **FR-086-01**: Expose an object-level producer-envelope admission helper without changing the
  existing file-envelope API or its error codes.
- **FR-086-02**: Convert only a pinned, completed `RemoteExperimentState` into a generic producer
  envelope; preserve material digests and the generic envelope's bounded lineage slots while
  discarding remote score prose. The current remote material DTO has no parent-lineage field, so
  remote imports leave `ProducerMaterial.lineage` empty rather than inferring lineage from a path
  or experiment ID.
- **FR-086-03**: Route every remote material through `admit_producer_envelope` and the injected
  exact evaluator before returning `SeedAdmissionResult`.
- **FR-086-04**: Preserve the remote DTO's unknown/reconciliation semantics and perform no network,
  subprocess, scheduler, or model operation.
- **FR-086-05**: Keep Feature 084/085 Draft, ordinary offspring integrity separate as Feature 087,
  and preserve 074/076/078/082 sealed artifacts byte-for-byte.

## Limits

The bridge verifies files available in the supplied local material root; it does not fetch remote
references or prove transitive dependencies, remote billing, or remote evaluator correctness. A
caller must obtain and reconcile the state through its own explicitly supplied backend adapter.
This feature makes no effectiveness claim and does not authorize a real framework or campaign.
