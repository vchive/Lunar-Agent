# Data Model: Evidence-Guided Recovery

## Recovery Proposal

`RecoveryProposal` is an immutable, JSON-serializable local decision.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | string | Proposal schema version (`"1"`). |
| `action` | enum | `none`, `retry`, `ask_user`, `propose_patch`, `propose_replan`, or `stop`. |
| `run_id` | string | Durable run identifier. |
| `run_status` | string | Status observed while deciding. |
| `plan_id`, `plan_version` | optional | Current revision reference, if one exists. |
| `task_id`, `plan_task_id` | optional | A physical scheduler task and logical plan task target. |
| `rationale` | string | Bounded generic explanation. |
| `evidence` | string array | At most 16 controlled identifiers/state/rule codes. |
| `questions` | string array | At most four generic questions for `ask_user`. |
| `guidance` | object | Action-specific, non-executable next-step metadata. |
| `fingerprint` | string | SHA-256 of canonical payload excluding itself. |
| `artifact_path` | optional string | Run-relative indexed audit artifact path, added on persistence. |

## Action Guidance

| Action | Guidance shape | Mutation performed by recovery? |
| --- | --- | --- |
| `none` | `{}` | No |
| `retry` | `{"command":"resume"}` | No |
| `ask_user` | `{"input_request":true}` or `{"runtime_configuration":true}` | No |
| `propose_patch` | `{"required_operation":"update_task","target":"logical-id","inspect":["evaluation"]}` | No |
| `propose_replan` | `{"preserve_verified_artifacts":true,"inspect":["budget"|"failed_tasks"]}` | No |
| `stop` | `{"terminal":true}` | No |

## Durable Records

For each distinct canonical proposal:

1. An indexed artifact exists at `recovery/proposals/<fingerprint>.json`, attached to the targeted
   task (or the first run task where no single target exists) with kind `recovery`.
2. An idempotent `recovery_proposed` event stores the proposal object and artifact path. The event
   ID is `event-recovery-<run-id>-<fingerprint-prefix>`.
3. `status --json` returns the most recent event payload under `recovery`.

No SQLite schema change is needed: events already support structured payloads and artifacts already
have a run/task ownership reference and SHA-256 index.

## Classification Precedence

1. Succeeded → `none`; cancelled → `stop`.
2. Waiting input → `ask_user`.
3. Ready/uncertain work on a non-terminal run → `retry`.
4. `budget_exceeded` → `propose_replan`.
5. Failed acceptance evaluation on a versioned plan → `propose_patch`.
6. Configuration/authority-shaped runtime failure → `ask_user`.
7. Other failed/blocked/unplanned work → `propose_replan` (or `ask_user` when no plan exists).

The policy intentionally does not expose raw error messages or artifact contents.
