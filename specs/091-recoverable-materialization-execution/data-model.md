# Data model

The 4 KiB canonical journal is
`evolution/materialization/.execution-publication/journal.json`, with temporary sibling
`.journal.json.tmp`. It contains schema_version, parent_run_id, evolution_run_id, task_id,
launch_intent_sha256, execution_path, execution_sha256, execution_size, artifact_id, device and
inode. execution.json retains the runner's schema 1 bytes and a 64 KiB bound.

Deterministic suffix: SHA-256(parent ID, NUL, child ID). The artifact ID starts with
`artifact-materialization-execution-`; prepared, artifact-recorded and committed event IDs use
`event-materialization-execution-prepared-`, `event-materialization-execution-artifact-recorded-`
and `event-materialization-execution-committed-`. The existing evolved_candidate_executed ID and
payload remain unchanged, including candidate SHA-256 in its ID suffix.
The new event types are `materialization_execution_prepared` and
`materialization_execution_committed`; the artifact event keeps `artifact_recorded`.

Prepared/committed payloads bind parent_run_id, evolution_run_id, owner_task_id, journal_sha256,
launch_intent_sha256, artifact_id, path, sha256 and size. The artifact kind remains
evolved_candidate_execution. All artifact/event rows commit together after exact preparation.

`completed.json` and `.completed.json.tmp` contain the exact journal_sha256 and establish
post-commit evidence. Absence of both permits a wholly absent batch to be completed only with
exact filesystem and SQLite preparation and no downstream publication evidence. Existing
completion nodes forbid batch recreation. Malformed, partial or missing modern evidence is an
error, never an absent/legacy state.
