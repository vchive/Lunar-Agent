# Data Model: Agent Solver Portfolio

No new SQLite table is required.

The existing `EvolutionConfig.generator_fingerprint` stores a SHA-256 digest over a canonical
ordered portfolio descriptor:

```json
{
  "kind": "portfolio-generator",
  "commands": [["/absolute/solver-a", "--json"], ["/absolute/solver-b", "--json"]],
  "name": "evolution-agent",
  "role": "solver",
  "required_capabilities": ["read_files"]
}
```

Only the digest is persisted. Adapter selection is request-local and round-robin.
