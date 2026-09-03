# Data Model: Reproducible Evolution Benchmark

`BenchmarkReport` is a bounded JSON object:

```json
{
  "schema_version": "1",
  "contract_sha256": "<64 hex chars>",
  "config": {"strategies": ["loop", "population"], "max_rounds": 3},
  "runs": [
    {
      "strategy": "loop",
      "status": "completed",
      "elapsed_ms": 12,
      "evaluated_candidates": 3,
      "valid_candidates": 3,
      "best_score": 8.0,
      "workspace": "strategies/loop",
      "archive": "strategies/loop/evolution/archive.jsonl",
      "error": null
    }
  ]
}
```

Paths are relative to the benchmark root. `generator_fingerprint` and `evaluator_fingerprint`
are optional 64-character SHA-256 values; raw commands, endpoint URLs, API keys, and model output
are not serialized into the report.
