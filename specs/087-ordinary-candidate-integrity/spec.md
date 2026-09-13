# Feature 087: Ordinary Candidate Integrity

**Feature Branch**: `087-ordinary-candidate-integrity`

**Created**: 2026-09-13

**Status**: Complete and independently reviewed (2026-09-14)

## Problem and goal

Native population offspring currently persist a source and an `EvaluationReport`, but do not
persist a cryptographically bound receipt for the exact source bytes or for the evaluator context
that produced the report. A source, evaluator, contract, or execution runner can therefore drift
between a first run and resume without a durable ordinary-candidate check.

This feature gives ordinary `population` candidates the same integrity properties already used by
verified imported material: a versioned receipt, source and lineage binding, evaluator authority,
dependency/environment/runner fingerprints, atomic sidecars, and fail-closed resume validation.

## Scope and authority

- The local evaluator remains the only score authority. A receipt records only the bounded,
  normalized `EvaluationReport` fields returned by that evaluator.
- A receipt binds `candidate_id`, source SHA-256, contract SHA-256, evaluator kind and fingerprint,
  declared dependency and environment identities, runner and generator identities, and the
  parent/generation/iteration/island lineage.
- Every newly persisted ordinary candidate has `record.json` and `receipt.json`; the archive line
  carries a compact integrity projection. Source, receipt, record, archive and state are written
  in an order that cannot make an incomplete candidate look resumable.
- Evaluator exceptions, timeouts, worker uncertainty, malformed reports, and source mutation do
  not create a receipt or synthetic evaluator prose. The existing fixed offspring outcome codes
  remain authoritative for those failures.
- A well-formed structured report with `validity=0` is still a completed evaluation. It receives a
  receipt with score zero, remains outside best/active selection, and keeps only normalized error
  codes with fixed messages.
- A generation-zero candidate after iteration zero is accepted only when the validated outcome
  journal binds it to a complete batch and no valid candidate existed before that batch. This
  preserves empty-population retries without permitting arbitrary parentless lineage.
- Existing loop and imported seed records remain readable. An old ordinary archive with no
  receipt is legacy-unverified and cannot be resumed or silently upgraded into a new population.

## Requirements

### FR-087-01 Receipt schema

Define a bounded, canonical schema version for ordinary receipts. It contains the candidate and
lineage identity, source/contract/evaluator/dependency/environment/runner/generator fingerprints,
and the controlled evaluator report fields. `receipt_sha256` is the SHA-256 of the canonical
payload excluding that field. Unknown fields, malformed digests, non-finite numbers, and altered
report fields are rejected.

### FR-087-02 Atomic ordinary persistence

After source staging and evaluation, hold a no-follow descriptor and require its bytes, inode, link
count, mode, size, mtime, ctime, and path identity to remain stable through sidecar and archive
publication. Apply the same rule to optional execution evidence. Snapshot mutable evaluator report
data at callback return. Persist the source, receipt sidecar, record, and archive line through
bounded private files. A candidate is visible to resume only after the complete receipt and record
exist and the archive line is durably appended.

### FR-087-03 Resume gate

Resume validates the ordinary integrity schema, run authority, archive digest, source bytes,
sidecar receipt, record projection, candidate lineage, and all configured identities before calling
the generator or evaluator. Drift in source, contract, evaluator, dependency, environment, runner,
generator, receipt, record, archive, ordinary authority/archive digest, outcome binding, or the
enumerated deterministic population projection fails closed. For modern ordinary-integrity state,
`active_ids`, `best_candidate_id`, `rng_seed`, `last_migration_iteration`, and `stagnation` must equal
the population projection rebuilt from the validated archive. Their numeric types and the status
conditions derived from that projection are checked exactly. A required outcome-binding group
cannot be removed wholesale while the modern marker remains visible. Once an ordinary integrity
marker is established the writer retains it in every later state, including a seeded first
offspring batch that ends failed-only with no ordinary record; a state carrying both the modern
marker and `seed_admission` must retain its outcome binding.

### FR-087-04 Failure and recovery

Failed generation/evaluation, source or execution mutation, and uncertain worker outcomes leave no
archive-visible ordinary receipt. A complete durable offspring batch may be finalized once without
replay, including recovery from a stale regular state temporary file. An incomplete batch remains
governed by the existing outcome journal and cannot be inferred from an orphan source tree. Archive
append failures roll back to the previous size and fsync that rollback; if rollback durability is
itself unknown, fixed publication-unknown evidence is raised and the sidecars are retained for
diagnosis without becoming resumable candidates.

### FR-087-05 Compatibility

`Candidate`, `CandidateArchive`, `StrategyResult`, and historical loop/seed readers retain their
existing public shape. New integrity fields are additive and optional for in-memory/manual
candidates. Legacy ordinary archives are readable for inspection and result reporting but require
explicit migration outside this feature before active resume.

### FR-087-06 Privacy and bounds

Receipts and state contain no evaluator exception text, credentials, raw command arguments, prompt
content, or external score prose. All JSON, paths, source bytes, report details, and metadata stay
within existing bounded limits. Credential-like metadata keys are rejected. Archive, outcome,
source, state, receipt, and record reads are bounded and no append may grow its file beyond the
corresponding reader limit.

## Acceptance scenarios

1. A deterministic native population run writes one ordinary receipt per evaluated candidate;
   recomputing its canonical digest succeeds and the archive/state projections agree.
2. Changing source bytes, any identity, lineage field, sidecar, record, archive line, state
   authority, active population, best candidate, RNG seed, migration watermark, stagnation value,
   structurally inconsistent status, or required outcome-binding group while a modern marker is
   present causes resume to fail before generator/evaluator invocation.
3. An evaluator that rewrites and restores the candidate source, mutates source or execution
   evidence during publication, times out, raises worker uncertainty, or returns an invalid report
   produces no archive-visible receipt and only the existing fixed outcome code.
4. A crash before archive publication leaves no resumable candidate; a crash after a complete
   candidate publication can finalize the outcome batch without replay.
5. A legacy ordinary archive can be read and ranked for display, while active resume fails with a
   fixed legacy-integrity error. Verified `seed-*` sidecars and the sealed 074/076/078/082 trees
   remain byte-for-byte unchanged.

## Non-goals

This feature does not execute a model, external evolution framework, remote backend, scheduler, or
benchmark campaign, and it makes no effectiveness or WebAgent parity claim. Dependency and
environment fingerprints describe only the identities explicitly declared by the caller or the
native protocol fallback; they do not prove transitive package provenance or host immutability.
No portable filesystem transaction can exclude a same-user process that deliberately escapes its
process group and mutates files after publication. Resume validation remains fail-closed for drift
that does not also replace or recompute every hash-bound artifact consistently. Receipts have no
external signature or HMAC and do not provide authenticity against a same-user process able to
rewrite source, receipt, record, archive, and state as one coordinated set. A pure verified-seed
checkpoint before any ordinary candidate transaction belongs to Feature 084's seed boundary.
Coordinated removal of all three ordinary marker fields, the complete outcome/failed binding group,
and the journal can recreate that same pure-seed shape; with no ordinary record it is
indistinguishable from the Feature 084 checkpoint and is not rejected by Feature 087 alone.
Within an ordinary state, arbitrary unknown top-level fields are not integrity claims, and there is
no external commitment for every status/error pair. In particular, an empty initialization with
`candidate_failed` can have structurally indistinguishable running and failed representations if an
actor coordinates both fields. Changes to population ranking, trim, migration, or family-selection
rules require an integrity-schema version bump or an explicit migration before old projections are
resumed.
