# Adapter Fingerprint Contract

The fingerprint input is canonical JSON, never persisted directly:

```json
{
  "command": ["/absolute/path/to/solver", "--json"],
  "name": "evolution-agent",
  "role": "solver",
  "required_capabilities": ["read_files", "write_artifacts"],
  "kind": "generator"
}
```

The SHA-256 digest of this sorted representation is stored as `generator_fingerprint` or
`evaluator_fingerprint`. A resume must present the same digest before it can claim the run task.
