# Tasks: Verified Seed Handoff and Evolution Backend Boundary

**Input**: `spec.md`, `plan.md`, and the famou-v2/WebAgent review documents.

**Tests**: Required. Every failure boundary below is an offline fixture; no model or network call.

## Phase 1: Foundational contracts

- [ ] T084-01 Freeze the seed manifest, identity, framework-neutral provenance (`origin_kind`, `producer_id`, `producer_fingerprint`, optional `producer_run_id`), evaluator receipt, explicit size/field limits, and initialization gate schemas in `src/famou/seed_handoff.py` and `data-model.md`.
- [ ] T084-02 [P] Define bounded remote lifecycle DTOs and the framework-neutral `RemoteEvolutionBackend` protocol in `src/famou/remote_evolution.py`; expose `submit`, `status`, `sync`, `continue_experiment`, and `cancel`, including explicit unknown/reconciliation states.
- [ ] T084-03 [P] Add fixture helpers for regular files, symlinks, dependency failures, evaluator receipts, fake OpenEvolve material, and fake remote responses under `tests/fixtures/`.

## Phase 2: User Story 1 - Admit only locally verified seeds (P1)

- [ ] T084-04 [P] Write failing tests for malformed/empty/duplicate/path-escaping/oversized seed manifests and invalid origin/producer fields in `tests/test_seed_handoff.py`.
- [ ] T084-05 [P] Write failing tests for missing source, dependency failure, invalid receipt, external-score-only OpenEvolve material, mixed valid/invalid batches, and all-invalid initialization in `tests/test_seed_handoff.py`.
- [ ] T084-06 Implement bounded manifest parsing, transactional safe source staging, identity collision checks, deterministic seed fields, and framework-neutral provenance construction in `src/famou/seed_handoff.py`; adjudicate all records before atomically committing only the admitted subset.
- [ ] T084-07 Implement local evaluator invocation and receipt verification for local and every external producer; return only admitted candidates/drafts and fixed safe failure codes.
- [ ] T084-08 Add an explicit identity-preserving seed-admission path that populates active state, run the initialization gate on fresh and resume paths, and prove zero generator/remote/population calls after the evaluator gate when no seed is usable.

**Checkpoint**: A fixture with one valid seed enters local initialization; all-invalid fixtures fail before any generator/model/backend call.

## Phase 3: User Story 2 - Resume and evolve with auditable provenance (P1)

- [ ] T084-09 [P] Write archive/checkpoint tests for persisted producer metadata, stable IDs independent of `producer_run_id`, and source/dependency/evaluator/contract/provenance mismatch on resume in `tests/test_evolution.py`.
- [ ] T084-10 Add versioned bounded seed provenance and producer projection, canonical receipt digest, source/handoff fingerprints, and a digest of the opaque material-reference list to candidate archive/state serialization in `src/famou/evolution.py`.
- [ ] T084-11 Add resume validation for handoff identity, normalized provenance, rehashed candidate source, the declared material-reference-list digest, and evaluator/contract fingerprints; reject changed source bytes or producer declarations before population selection without claiming that reference targets were fetched.
- [ ] T084-12 Add compatibility coverage for current later-rollout retry behavior and separate tests proving seed admission failures do not advance iteration or enter active population.

**Checkpoint**: Unchanged verified seeds resume byte-stably; changed identity fails closed.

## Phase 4: User Story 3 - Keep remote evolution backends explicitly optional (P2)

- [ ] T084-13 [P] Write fake-backend contract tests for `submit`/`status`/`sync`/`continue_experiment`/`cancel`, missing-ID/timeout/unknown results, producer identity, and credential-safe bounded payloads in `tests/test_remote_evolution.py`.
- [ ] T084-14 Implement protocol validation and reconciliation helpers in `src/famou/remote_evolution.py`; do not add a real transport.
- [ ] T084-15 Add an explicit opt-in seed-manifest path to generic local `evolve` CLI construction; preserve default and staged Master→Build behavior in `src/famou/cli.py`.
- [ ] T084-16 Ensure every external material path, including fake OpenEvolve output and fake remote sync, is routed through the local seed adapter/exact evaluator and cannot directly set `EvaluationReport`, score, archive rank, or population membership.

**Checkpoint**: Fake remote results remain provenance-only until local evaluation succeeds; default CLI makes zero backend calls.

## Phase 5: Verification and documentation

- [ ] T084-17 [P] Add `quickstart.md` for the offline mixed-admission fixture, fake OpenEvolve external-score result, and fake remote reconciliation scenario.
- [ ] T084-18 Run focused and full tests, Ruff, Specify, and diff checks; verify 074/076/078/082 sealed artifacts are byte-identical.
- [ ] T084-19 Record implementation limits and defer concrete OpenEvolve, ShinkaEvolve, SkyDiscover, famou-v2, or other framework adapters and any new measurement to separately frozen features/campaigns.

## Dependencies and execution order

Foundation T084-01/T084-02/T084-03 precedes all stories. T084-04–08 is the MVP. T084-09–12 depends on the seed schema and gate. T084-13–16 depends on the local provenance boundary but remains transport-free. Verification follows all implemented stories.

Parallel work: T084-02/T084-03; T084-04/T084-05; T084-09/T084-13; and T084-17 can proceed in parallel once their contracts exist.

No task launches a model, provider, OpenEvolve, another external evolution framework, WebAgent, company platform, remote famou-v2 service, or new campaign.
