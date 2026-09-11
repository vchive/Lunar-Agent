# Plan: Verified Seed Handoff and Evolution Backend Boundary

## Technical approach

Implement a small local adapter around the existing `Candidate`, `EvaluationReport`, archive, and checkpoint contracts in `src/famou/evolution.py`. The adapter reads a bounded JSON manifest, copies candidate source into the run workspace through explicit root-confinement, symlink rejection, atomic-copy, and digest-recheck rules, computes an identity-derived candidate ID, invokes the configured `CandidateEvaluator` through a declared evaluator-kind/fingerprint contract, and returns only locally verified seed records. It must use the same evaluator and contract digest as the target `EvolutionContext`; it must not accept an external score as a substitute. The first implementation verifies declared dependency/environment digests and records them as provenance; it does not claim famou-v2-equivalent dependency installation or enrichment until that separate capability is specified.

Initialization validation remains a separate gate on both fresh runs and resume. It rejects all-invalid/no-score seed sets before `PopulationStrategy.run()` can generate or reactivate an archive record. Add an explicit seed-admission path that persists the identity-derived ID and seeds active population state with deterministic generation=0, iteration=0, parent=null, and island assignment from the sorted identity list; it must not use the sequential generator ID path. Existing later-iteration retry behavior remains unchanged and is covered as a compatibility boundary. Seed metadata is bounded, credential-safe, and persisted in the existing archive/state representation; resume rehashes source/material and compares the canonical handoff fingerprint before selection.

Define a protocol-only `RemoteEvolutionBackend` in a separate module. Its methods use typed bounded request/response records for `submit`, `status`, `sync`, `continue`, and `cancel`. A fake fixture will exercise reconciliation and unknown outcomes. No production network client or service URL is added in this feature. A future adapter may use famou-v2's `famou-ctl`, but it must hand imported material back through the local seed adapter and exact harness.

## Files and structure

- `src/famou/seed_handoff.py`: manifest parsing, identity/provenance records, local evaluator gate, and initialization validation.
- `src/famou/evolution.py`: minimal integration points for verified initial candidates and bounded metadata/checkpoint compatibility; avoid changing retry semantics.
- `src/famou/remote_evolution.py`: protocol and credential-safe lifecycle DTOs only; no network implementation in 084.
- `src/famou/cli.py`: explicit opt-in local seed-manifest argument for the generic `evolve` command, with default behavior byte-compatible; no staged Master→Build option.
- `tests/test_seed_handoff.py`, `tests/test_remote_evolution.py`, and focused evolution regression tests: failure-first fixtures, resume/identity checks, and zero-call default assertions.
- `docs/famou-v2-engine-review-20260911.md`: evidence and limits for the external model.

## Data and security decisions

Seed source is copied into the run workspace; paths, symlink components, size, and regular-file identity are checked before reading. Identity uses canonical source, contract, dependency, and environment digests plus declared lineage. Manifest limits are explicit: at most 32 seeds, 512 KiB per source, 8 KiB canonical metadata, 64 KiB serialized archive records, fixed keys only, and reject unknown fields. Metadata excludes prompts, credentials, arbitrary exception strings, and full remote payloads. External experiment IDs and scores are labels only.

The local evaluator receipt is the only route into ranking. Remote material specifically requires
the exact-harness evaluator kind and its pinned fingerprint; a generic model-backed report is not a
substitute. A remote lifecycle failure is recorded as `unknown` when completion or usage cannot be reconciled. No retries, cost claims, or completion claims are synthesized by the boundary.

## Verification plan

Write failure-first tests for malformed manifests, all-invalid initialization, dependency failure, receipt mismatch, identity collision, changed-source resume, symlink/path escape, oversized metadata, remote unknown status, and default zero backend calls. Then run focused tests, full regression, Ruff, Specify, diff checks, and a local fixture quickstart. Do not run models, WebAgent, external services, provider probes, company evaluation, or a campaign.

## Complexity tracking

The remote protocol is intentionally a type boundary with no transport implementation. Adding a service client now would duplicate WebAgent's control plane and introduce unbounded credentials, timeouts, retries, and score authority before the local receipt contract exists. No database migration is needed; existing archive/state JSON gains only bounded versioned metadata.
The admission evaluator is injected and local by contract; this feature does not infer that a
model-backed evaluator is a deterministic exact harness.
