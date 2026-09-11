# Plan: Verified Seed Handoff and Evolution Backend Boundary

## Technical approach

Implement a small local adapter around the existing `Candidate`, `EvaluationReport`, archive, and checkpoint contracts in `src/famou/evolution.py`. The adapter reads a bounded JSON manifest, copies candidate source into the run workspace through explicit root-confinement, symlink rejection, atomic-copy, and digest-recheck rules, computes an identity-derived candidate ID, invokes the configured `CandidateEvaluator` through a declared evaluator-kind/fingerprint contract, and returns only locally verified seed records. Framework-neutral provenance records `origin_kind`, `producer_id`, a producer/configuration SHA-256 `producer_fingerprint`, and an optional opaque `producer_run_id`; no producer-specific payload enters the canonical schema. The adapter must use the same evaluator and contract digest as the target `EvolutionContext`; it must not accept an external score as a substitute, including an evaluation reported by a local OpenEvolve subprocess. The first implementation verifies declared dependency/environment digests and records them as provenance; it does not install dependencies or claim famou-v2-equivalent enrichment until that separate capability is specified.

Initialization validation remains a separate gate on both fresh runs and resume. It adjudicates every manifest record in private staging, then atomically commits only the admitted subset. A mixed valid/invalid batch admits the valid subset without exposing partial archive or active-state mutation during processing; an empty admitted subset fails before `PopulationStrategy.run()` can generate or reactivate an archive record. Add an explicit seed-admission path that persists the identity-derived ID and seeds active population state with deterministic generation=0, iteration=0, parent=null, and island assignment from the sorted admitted identity list; it must not use the sequential generator ID path. Existing later-iteration retry behavior remains unchanged and is covered as a compatibility boundary. Seed metadata is bounded, credential-safe, and persisted in the existing archive/state representation; resume rehashes the candidate source and compares the canonical handoff and provenance fingerprints before selection. `material_refs` are opaque reference labels: Lunar hashes the normalized reference list for change detection but does not claim to have fetched or verified the bytes named by every reference.

Define a protocol-only, framework-neutral `RemoteEvolutionBackend` in a separate module. Its methods use typed bounded request/response records for `submit`, `status`, `sync`, `continue_experiment`, and `cancel`. Requests and responses identify the backend through bounded producer fields, while synchronized output contains material references and digests rather than authoritative local scores. A fake fixture will exercise reconciliation and unknown outcomes. No production network client, service URL, or concrete framework adapter is added in this feature. A future adapter may use famou-v2's `famou-ctl`, but it must hand imported material back through the local seed adapter and exact harness. Synchronous local frameworks such as OpenEvolve require a separate future engine-adapter protocol rather than being forced into this remote lifecycle.

## Files and structure

- `src/famou/seed_handoff.py`: manifest parsing, identity/provenance records, local evaluator gate, and initialization validation.
- `src/famou/evolution.py`: minimal integration points for verified initial candidates and bounded metadata/checkpoint compatibility; avoid changing retry semantics.
- `src/famou/remote_evolution.py`: protocol and credential-safe lifecycle DTOs only; no network implementation in 084.
- `src/famou/cli.py`: explicit opt-in local seed-manifest argument for the generic `evolve` command, with default behavior byte-compatible; no staged Master→Build option.
- `tests/test_seed_handoff.py`, `tests/test_remote_evolution.py`, and focused evolution regression tests: failure-first fixtures, resume/identity checks, and zero-call default assertions.
- `docs/famou-v2-engine-review-20260911.md`: evidence and limits for the external model.

## Data and security decisions

Seed source is copied into the run workspace; paths, symlink components, size, and regular-file identity are checked before reading. Identity uses canonical source, contract, evaluator kind and fingerprint, dependency and environment digests, plus declared lineage; it does not use `producer_run_id`. The canonical handoff fingerprint also binds the normalized provenance so a changed producer declaration cannot be silently resumed. Manifest limits are explicit: at most 32 seeds, 512 KiB per source, 8 KiB canonical metadata, 64 KiB serialized archive records, fixed keys only, and reject unknown fields. `origin_kind` is exactly `local` or `external`; `producer_id` and an optional `producer_run_id` are bounded safe identifiers of at most 128 characters, and `producer_fingerprint` is lowercase SHA-256 hex. For external origins, evidence and record metadata are each converted to `{present, score_present, payload_sha256}` before canonical persistence. Metadata excludes prompts, credentials, arbitrary exception strings, producer-specific configuration bodies, raw scores and full remote payloads. Producer run IDs remain labels only.

The local evaluator receipt is the only route into ranking. Every external material path, including
an explicit local OpenEvolve result and material synchronized from a remote backend, requires the
exact-harness evaluator kind and its pinned fingerprint; a producer evaluation or generic
model-backed report is not a substitute. A remote lifecycle failure is recorded as `unknown` when
completion or usage cannot be reconciled. No retries, cost claims, or completion claims are
synthesized by the boundary.

## Verification plan

Write failure-first tests for malformed manifests and producer fields, mixed admitted/rejected batches, all-invalid initialization, dependency failure, receipt mismatch, external-score-only OpenEvolve material, identity collision, changed-source/provenance resume, symlink/path escape, oversized metadata, remote unknown status, and default zero backend calls. Then run focused tests, full regression, Ruff, Specify, diff checks, and a local fixture quickstart. Do not run models, OpenEvolve, WebAgent, external services, provider probes, company evaluation, or a campaign.

## Complexity tracking

The remote protocol is intentionally a type boundary with no transport implementation. Adding a service client or concrete local framework adapter now would duplicate control concerns and introduce framework-specific credentials, timeouts, retries, checkpoints, and score authority before the local receipt contract exists. Concrete OpenEvolve, ShinkaEvolve, SkyDiscover, or famou-v2 adapters remain later features and must converge on this seed handoff. No database migration is needed; existing archive/state JSON gains only bounded versioned metadata.
The admission evaluator is injected and local by contract; this feature does not infer that a
model-backed evaluator is a deterministic exact harness.
