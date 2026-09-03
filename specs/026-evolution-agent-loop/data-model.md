# Data Model: Tool-Capable Evolution Agent Loop

No database migration is required. `EvolutionConfig` continues to store only credential-safe
fingerprints. The fingerprint input additionally includes:

```json
{"agent_runtime_loop":true,"max_steps":40,"allow_exec":false,"memory":false,"session_history":false}
```

When session history is enabled, the existing JSONL transcript is placed under the candidate
attempt workspace and is subject to the existing artifact/path limits.

