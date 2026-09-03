# Data Model: Unified Evolution Benchmark Adapters

`BenchmarkConfig` adds an optional strategy command map:

```json
{
  "strategy_commands_sha256": {
    "openevolve": "<64 hex chars>"
  }
}
```

Raw executable arguments are not serialized. The OpenEvolve adapter config adds a bounded `budget`
object containing the common rounds, stagnation, population, offspring, islands, migration, seed,
and timeout values. The benchmark report remains schema version `1` and keeps per-strategy paths
relative to its root.
