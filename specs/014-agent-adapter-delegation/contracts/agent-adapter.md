# Agent Adapter Contract

## Request

`AgentRequest` is serialized as one JSON object with `run_id`, `task_id`, `role`, `prompt`,
`required_capabilities`, `workspace`, and `timeout`. A command adapter writes exactly one JSON
request to stdin and sets its working directory to `workspace`.

## Response

The preferred response is one JSON object:

```json
{
  "status": "succeeded",
  "text": "bounded result text",
  "artifacts": ["relative/path.txt"],
  "metadata": {"key": "value"},
  "error": null
}
```

`status` defaults to `succeeded`; `text` defaults to the JSON `result` field when present. A
non-empty bounded plain-text stdout is normalized to the same shape. Absolute paths, `..` segments,
malformed JSON, empty output, oversized output, non-zero exit, and timeout are errors.

## Lifecycle

The controller selects and claims a task, emits `agent_selected` and `agent_started`, invokes the
adapter, records the normalized result and declared artifacts, evaluates the result, then emits
`agent_finished` or `agent_failed`. Cancellation wins races with late results. The adapter does not
receive Store handles and cannot settle a run.

## Selection

Adapters are explicitly registered by name. A request is compatible only when `role` is declared and
every requested capability is declared. A preferred incompatible adapter is an error; without a
preference, deterministic name ordering chooses the first match.
