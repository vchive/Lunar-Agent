# Ordinary candidate integrity data model

## `CandidateReceipt`

The canonical ordinary receipt uses schema version `1` and contains:

```text
schema_version, candidate_id, source_sha256, contract_sha256,
evaluator_kind, evaluator_fingerprint, dependency_sha256,
environment_sha256, runner_fingerprint, generator_fingerprint,
parent_id, generation, iteration, island_id,
report_schema_version, evaluator_id, validity, quality,
combined_score, detailed_scores, error_info, execution_sha256, receipt_sha256
```

`error_info` keeps bounded error codes while replacing evaluator prose with a fixed local message.
The report values are normalized through `EvaluationReport`; `receipt_sha256` covers every field
except itself using sorted, compact JSON with non-finite numbers forbidden. `execution_sha256` is
optional: when an execution-aware evaluator publishes bounded `execution.json` evidence, it binds
that file's exact bytes; it is otherwise `null`. The execution evidence is checked at resume and
must remain inside the candidate directory.

## Candidate projection

An ordinary `Candidate` carries an optional compact `integrity` projection with the schema version,
all authority fingerprints, lineage digest fields, and `receipt_sha256`. Manual/in-memory and
historical candidates may omit it. Newly persisted ordinary records must include it. Imported
verified seeds continue to use their existing `seed_handoff_evidence` and receipt schema without
conversion.

## Run authority

New strategy state includes `candidate_integrity_schema_version`, a canonical
`candidate_integrity_authority` object, and `candidate_archive_sha256`. The authority is uniform
for all ordinary candidates in a run. Missing authority on a legacy ordinary archive is reported as
unverified and blocks active resume.

Modern ordinary-integrity state also carries `active_ids`, `best_candidate_id`, `rng_seed`,
`last_migration_iteration`, and `stagnation` as deterministic projections rather than independent
authority. Resume rebuilds them from the already validated archive: it admits the seed or native
initialization set, replays each completed iteration in order, and applies the existing rank, trim,
migration, best-score, and stagnation rules at the same boundaries. A substituted valid active
candidate, changed best candidate, exact-type RNG drift, migration-watermark drift, stagnation
drift, or structurally inconsistent status therefore fails with
`population state projection mismatch`. Integer projection fields reject booleans and floats even
when Python equality would consider their values equal.

The outcome watermark, watermark digest, archive baseline, start iteration, and schema form one
binding group. Once an ordinary-integrity checkpoint requires that group, deleting every field and
the outcome file fails closed while the modern marker remains visible. An incomplete pending batch
still reports its established incomplete-batch error before projection reconstruction, and an empty
verified-seed population retains its seed-specific error. A pure seed checkpoint before the first
ordinary pending/candidate transaction remains governed by Feature 084 and does not acquire a
Feature 087 population projection retroactively.

After the first ordinary pending state establishes the Feature 087 marker, `_state_payload` carries
that marker group forward monotonically even if the first seeded offspring batch is failed-only and
publishes no ordinary record. A later state containing both the modern marker and `seed_admission`
must therefore retain the outcome binding; removing the outcome file and all binding fields cannot
turn that failed terminal checkpoint back into a replayable pure-seed state while the marker is
present. If an actor coordinates removal of the three marker fields, the complete outcome/failed
binding group, and the journal, a seed-only archive has the same observable shape as the genuine
Feature 084 pre-ordinary checkpoint. Feature 087 has no external commitment that distinguishes
those states and does not claim to detect that coordinated rewrite.

Projection replay intentionally calls the current selection rules. Rank/trim/migration/family
repertoire changes therefore require an integrity schema bump or an explicit state migration; they
must not silently reinterpret an old projection.

## Durable order

The source is staged and opened without following links. Its descriptor remains open across the
evaluator and the complete publication transaction; bytes and stable file/path identity are checked
again around every sidecar, archive append, and fsync boundary. Optional `execution.json` receives
the same held-snapshot treatment. A returned evaluator report is canonically deep-copied before
other code can mutate its nested dictionaries.

The record and receipt are written to private bounded files, their directory chain is fsynced
through the evolution workspace, and the archive line is appended last. The archive and outcome
journals use directory-relative no-follow opens, reject external hardlinks, enforce their total
reader bound before every append, and verify file identity after the write. An append/fsync failure
is truncated to its old size and fsynced. If that rollback cannot be confirmed, the fixed
`ordinary_candidate_archive_publication_unknown` error retains the source and sidecars; without a
canonical archive line they remain diagnostic orphans and are not resumable candidates.

Resume requires causal archive order, source, receipt, record, archive projection, optional
execution evidence, state digest, and the reconstructed population projection to agree. Invalid
reports remain durable but never enter `active_ids`, become parents, or become best candidates.
Parentless generation-zero retries after
iteration zero require a complete outcome batch and proof that no earlier valid population
candidate existed. A regular stale `.state.json.tmp` can be removed before finalizing a complete
pending batch without replay; linked or non-regular temporary entries are rejected.

The state file has no independent signature or HMAC. Structural status checks reject unknown and
projection-inconsistent values, but they do not authenticate every coordinated status/error edit.
An empty initialization carrying `candidate_failed`, for example, can represent a running retry or
a terminal failure with the same archive projection if an actor changes both fields consistently.
Unknown top-level state fields outside the enumerated authority, outcome, and population projections
are not integrity-bearing fields in this schema.

The controller indexes only published sidecars, using these stable artifact kinds:

| Candidate material | Artifact kind |
| --- | --- |
| ordinary `record.json` | `evolution_candidate_record` |
| ordinary `receipt.json` | `evolution_candidate_receipt` |
| imported seed `record.json` | `evolution_seed_record` |
| imported seed `receipt.json` | `evolution_seed_receipt` |

Indexing is additive and idempotent on `(path, kind)`. It is an offline evidence index: it does not
evaluate candidates, treat sidecars as executable outputs, or make orphan/symlinked/oversized files
visible. During controller failure handling, a stale state digest admits only its exact validated
archive prefix; an unjournaled pending suffix is not indexed. The strategy archive and integrity
gate remain authoritative. Seeded controller resume runs this ordinary state/journal/source gate
before re-invoking the local seed evaluator.

## Transient evaluator feedback

`AgentCandidateGenerator` may receive a process-local feedback overlay containing the most recent
evaluator report so the next proposal retains its existing feedback behavior. This overlay is
ephemeral and is never written to `record.json`, `receipt.json`, `state.json`, controller artifacts,
or archive metadata. Durable ordinary evidence contains only the normalized report and fixed,
bounded error information; evaluator exception text, prompts, commands, credentials, and external
score prose do not cross that boundary.
