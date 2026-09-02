# Data Model: Master Policy and Plan Contracts

## PlanDocument

An immutable, versioned control-plane description of a complex goal.

| Field | Type | Rules |
|---|---|---|
| `plan_id` | string | Stable safe identifier |
| `version` | integer | Starts at 1; strictly increases within a run/plan lineage |
| `parent_version` | integer/null | Previous immutable revision, required for patch/replan after v1 |
| `schema_version` | string | Currently `1` |
| `goal` | string | Non-empty, bounded to 8 KiB |
| `hard_constraints` / `soft_constraints` | string[] | At most 32 entries, each bounded |
| `objective` | string/object | JSON-serializable, bounded |
| `evidence` / `assumptions` | string[] | Bounded provenance notes; no secrets |
| `tasks` | PlanTask[] | Non-empty, unique IDs, acyclic dependencies |
| `acceptance` / `verification` / `delivery` | object | Bounded JSON metadata |
| `created_at` | timestamp | UTC |

## PlanTask

Logical task mapped to one existing scheduler task.

| Field | Type | Rules |
|---|---|---|
| `id` | string | Unique safe path segment within a plan; stable across revisions |
| `title` | string | Bounded human label |
| `prompt` | string | Non-empty, bounded runtime input |
| `depends_on` | string[] | Existing task IDs only; no cycles |
| `acceptance` | string/object/null | Passed to existing evaluator |

## PolicyDecision

An immutable action selection associated with a run or standalone goal.

| Field | Type | Rules |
|---|---|---|
| `action` | enum | `answer`, `ask_user`, `execute_plan`, `patch_plan`, `replan`, `deliver` |
| `rationale` | string | Non-empty, bounded, credential-safe |
| `confidence` | number | 0.0–1.0 |
| `questions` | string[] | At most four bounded questions |
| `plan_id` / `plan_version` | string/integer/null | Required for plan actions |
| `evidence` | string[] | Bounded, credential-safe |

## PlanPatch

Optimistic update request containing typed operations (`add_task`, `remove_task`, `update_task`,
`add_dependency`, `remove_dependency`, `update_acceptance`, `update_constraints`).

## SQLite additions

- `plan_revisions(plan_id, run_id, version, parent_version, document, created_at)` with a unique
  `(run_id, version)` key and immutable JSON document. `plan_id` remains indexed for inspection;
  the same reusable plan template ID may appear in multiple independent runs.
- `policy_decisions(id, run_id, action, payload, created_at)` with idempotent event linkage.
- `runs.current_plan_id` and `runs.current_plan_version` point at the latest revision.

Logical plan task IDs are retained in `tasks.plan_task_id`; the physical `tasks.id` is prefixed by
the run ID so legacy global task IDs and repeated plan templates cannot collide. Dependencies in the
task table always use physical IDs, while plan documents and CLI responses use logical IDs.

State invariant: a revision insert, current pointer update, task insertion/update, and corresponding
event either all commit or none commit.
