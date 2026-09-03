# Data Model: Runtime-Backed Evolution Agents

No SQLite migration or new durable table is required. The existing `EvolutionConfig` stores only
credential-safe adapter fingerprints:

```json
{
  "generator_fingerprint": "<sha256>",
  "evaluator_fingerprint": "<sha256>"
}
```

The digest input includes runtime kind, explicit command identity (when applicable), endpoint,
model, role, name, and required capabilities. API keys and raw runtime arguments are excluded from
persisted state. Detached children reconstruct the same profile from non-secret CLI arguments and a
process environment variable for the key.
