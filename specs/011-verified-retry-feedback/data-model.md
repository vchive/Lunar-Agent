# Data Model: Verified Retry Feedback

## Retry Feedback Projection

An ephemeral immutable projection is built per claimed attempt:

| Field | Type | Meaning |
| --- | --- | --- |
| `attempt` | positive integer | New attempt ordinal (`task.attempts`). |
| `source` | enum | `evaluation` or `runtime_failure`. |
| `status` | enum | `failed`. |
| `rules` | string array | Failed/observed acceptance rule kinds, max 16. |
| `evidence` | string array | Short evaluator evidence codes, max 16. |
| `instruction` | string | Generic bounded correction instruction. |

The projection is not stored as a separate table. It is rendered into the run-relative prompt
artifact `tasks/<task-id>/<attempt-id>/prompt.md`, which is already hashed and indexed.

## Rendering contract

```text
<original task prompt>

Retry feedback from the previous verified attempt (attempt N):
- source: evaluation
- status: failed
- failed_rules: artifact_exists, json_has_keys
- evidence: acceptance rule failed, artifact missing
- instruction: Correct the verified failure and produce a complete result. Do not claim success
  until the required artifacts satisfy the task acceptance checks.
```

When no evaluation event is available:

```text
Retry feedback from the previous attempt (attempt N):
- source: runtime_failure
- status: failed
- instruction: The previous attempt did not complete successfully. Inspect the task workspace,
  retry the requested work, and return a complete result.
```

The renderer truncates the complete prompt to 8 KiB only if required by the existing task prompt
bound; the original prompt is preserved as the first section and is never replaced.

## Isolation

The event query is filtered by `task_id` and the prompt artifact is written below that task's
attempt directory. Parallel workers cannot consume another task's feedback.
