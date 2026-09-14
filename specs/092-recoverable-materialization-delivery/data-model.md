# Data model

Files under evolution/materialization/.delivery-publication/:
- plan.json and .plan.json.tmp: canonical plan, at most 64 KiB.
- completed.json and .completed.json.tmp: canonical delivery completion, at most 4 KiB.

Plan keys: schema_version, parent_run_id, evolution_run_id, task_id, launch_intent_sha256,
execution_journal_sha256, execution_sha256, result, outputs.
result retains the existing terminal result shape with outputs=[]; it freezes execution and
validation decisions before promotion. outputs is an ordered list of metadata with keys path,
format, fields, required, size, sha256; it excludes artifact_id. A failed planned decision has
no planned outputs. Planned success can result in an explicit publication failure, but never
in changed validation/identity or unplanned output bytes.

The deterministic event ID is event-materialization-delivery-prepared- plus SHA-256(parent ID,
NUL, child ID); type materialization_delivery_prepared, owned by the unique child task. Its
payload binds parent_run_id, evolution_run_id, owner_task_id, plan_path, plan_sha256, plan_size,
execution_journal_sha256 and execution_sha256. No new artifact row or table is needed.

Completion keys are plan_sha256, result_sha256 and result_size. Either completion node signals
that 089 fully committed. It cannot authorize rebuilding missing terminal or execution records.
