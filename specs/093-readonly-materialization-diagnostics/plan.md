# Plan

Use a dedicated diagnostic module and CLI dispatch before `_config()`. Keep normal controller,
Store and all five recovery protocols unchanged. Do not reuse recovery functions or controller
construction merely to obtain read access: both can initialize storage or create locks.

Add a small bounded database-snapshot helper. Capture main/WAL identity and presence, copy their
bytes with no-follow regular-file reads to private temporary storage, and verify identity again.
Open the copy only, allowing SQLite to reconstruct its own WAL index there. Query runs/tasks and
relevant evidence with row/payload/step bounds. Exclude source SHM bytes and decline rollback
journals. Copying avoids the WAL sidecar writes possible with source `mode=ro`; `immutable=1`
is unsuitable because it can omit committed WAL data. Temporary storage is always cleaned up.

The diagnostic reader validates fixed protocol paths and bounded JSON records, opens existing
locks without creation and detects observed-file changes. Build stage observations and compare
available receipt/file digests, without invoking full acceptance or promotion checks. Missing
evidence is actionable inventory rather than permission to reconstruct it. Report fixed codes
and counts instead of raw ledger payloads or execution errors.

## Complexity and alternatives

Using `status` or `recover` would initialize storage; the latter may propose mutations. A generic
Store read-only refactor would touch unrelated paths. A private SQLite copy is justified by the
strict requirement to preserve source DB and sidecar bytes/entries. Limits keep this local and
bounded; large or actively changing databases may require a later inspection. No dependency,
migration, automatic repair, artifact export or constitution exception is required.
