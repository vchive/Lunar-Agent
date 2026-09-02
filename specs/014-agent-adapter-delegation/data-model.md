# Data Model: Agent Adapter and Role Delegation

## `AgentRequest`

Immutable request crossing the worker boundary:

| Field | Type | Constraints |
|---|---|---|
| `run_id` | string | non-empty identifier |
| `task_id` | string | non-empty identifier |
| `role` | string | non-empty, bounded role name |
| `prompt` | string | non-empty and bounded to 64 KiB |
| `required_capabilities` | tuple[string] | unique, bounded, safe names |
| `workspace` | absolute `Path` | existing run-scoped directory |
| `timeout` | float or null | positive and bounded when supplied |

## `AgentResult`

Normalized immutable result:

| Field | Type | Constraints |
|---|---|---|
| `adapter_name` | string | registered adapter identity |
| `role` | string | request role |
| `status` | enum string | `succeeded`, `failed`, or `cancelled` |
| `text` | string | bounded to 1 MiB |
| `artifacts` | tuple[string] | run-relative paths only |
| `metadata` | dict[string, scalar] | bounded key/value count and bytes |
| `error` | string or null | bounded and present for failed/cancelled results |

## `AgentAdapter`

Protocol implemented by workers. It declares `name`, `roles`, and `capabilities`, and provides
`run(AgentRequest) -> AgentResult`, `cancel()`, `process_info()`, and
`set_process_observer(callback | None)`.

## `AgentRegistry`

In-memory explicit registry keyed by unique adapter name. Selection requires the requested role and
all required capabilities. A preferred name is checked first and is never silently replaced when
it is incompatible. Otherwise compatible adapters are sorted by `(name, class name)`.

## `DelegationRecord`

The durable projection is intentionally represented by existing tables rather than a new schema:

- `attempts.runtime` stores adapter name;
- `events` stores `agent_selected`, `agent_started`, `agent_finished`, and `agent_failed` payloads;
- `artifacts` stores prompt, result, evaluation, and worker-declared files with SHA-256 hashes;
- `tasks` and `runs` remain the authority for terminal state.

No worker-owned table or global configuration is introduced.
