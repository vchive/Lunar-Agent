# Data Model: Runtime Profile Benchmark

`BenchmarkConfig` gains an optional credential-safe profile:

```json
{
  "runtime_profile": {
    "kind": "openai-compatible",
    "loop": true,
    "max_steps": 40,
    "allow_exec": false,
    "memory": false,
    "session_history": false
  }
}
```

Endpoint, model, command, API key, prompts, and model output are not persisted. The generator and
evaluator fingerprint fields continue to carry the canonical SHA-256 identities used by resume
checks.
