# Verified seed handoff data model

`SeedManifest` is a bounded local document with fixed keys and no unknown-field extension. It names a schema version, the target algorithm contract digest, evaluator fingerprint, environment/dependency digest, and at most 32 candidate records. Each record references a regular source artifact of at most 512 KiB, declared lineage, and optional external provenance. Canonical metadata is at most 8 KiB and serialized archive records remain within the existing 64 KiB limit. Source and dependency content are hashed before evaluation; 084 verifies declared dependency/environment digests but does not install dependencies or claim famou-v2 enrichment equivalence.

`SeedIdentity` is derived from source digest, contract digest, evaluator fingerprint, dependency/environment digest, and normalized lineage. It is stable across resume and independent of a famou-v2 experiment ID. A collision with different material is a hard error.

`EvaluatorReceipt` is produced by the local evaluator. It includes receipt version, candidate ID, source digest, contract digest, evaluator kind and fingerprint, dependency/environment digest, validity, combined score, bounded structured fields, and a receipt digest over this canonical payload. A receipt from another evaluator or an external score is advisory metadata and cannot admit a candidate; replay is accepted only when every identity field matches the current run.

`SeedProvenance` records `source_kind` (`local` or `famou-v2`), lineage, source/material digests, optional opaque remote experiment ID, and external evidence labels. It never stores credentials, prompts, unbounded remote JSON, or exception text.

`RemoteExperimentState` contains only an opaque experiment ID, an idempotency key, lifecycle state (`submitted`, `running`, `completed`, `cancelled`, `failed`, `unknown`), bounded timestamps/attempt counters, and material references. Legal transitions are `submitted→running|unknown|cancelled`, `running→completed|failed|unknown|cancelled`, and terminal states are immutable except an `unknown→running|completed|failed` reconciliation with the same remote ID. `completed` means the remote service reported completion; it never means local score acceptance. Submit is idempotent by key; status/sync are read/reconcile operations; continue/cancel reject terminal IDs.

All records are bounded, JSON serializable, and versioned. Existing `Candidate.metadata` and archive/state files carry a compact provenance projection; the local receipt remains the scoring authority and is rechecked on resume.


An admitted `Candidate` uses `generation=0`, `iteration=0`, `parent_id=null`, `strategy="population"`,
and a deterministic island selected by the sorted admitted identity list modulo the configured island
count. Its `code_path` is run-relative and its metadata contains the versioned handoff fingerprint,
source/material digests, provenance projection, and local receipt digest. Staging is private until
all seeds pass admission; only then are archive append and active-state updates committed.
