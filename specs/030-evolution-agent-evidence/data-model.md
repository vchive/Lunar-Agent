# Data Model: Evolution Agent Evidence

## Agent evidence event

An observer event is a bounded JSON object:

```json
{
  "role": "solver",
  "adapter": "openai-compatible",
  "task_id": "generation-00000001-0001",
  "path": "evolution/agent/generations/00000001-0001/session-transcript.jsonl",
  "kind": "evolution_agent_transcript",
  "size": 1234
}
```

Lifecycle events add `phase`, `turn`, `tool_call_count`, `success`, or `output_bytes` as
appropriate. They never include prompt text, assistant content, tool output, API keys, or endpoint
credentials.

## Artifact kinds

- `evolution_agent_transcript`: a redacted session transcript emitted by a runtime Agent.
- `evolution_agent_artifact`: another explicitly declared Agent output.

Paths are relative to the run workspace, regular files, and free of symlink components. Existing
`artifact_recorded` events carry the artifact ID, digest, and size; an additional
`evolution_agent_artifact` event carries the role/adapter provenance.
