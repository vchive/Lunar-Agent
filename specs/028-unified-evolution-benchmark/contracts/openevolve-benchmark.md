# Contract: OpenEvolve Benchmark Adapter

For a selected `openevolve` strategy, `BenchmarkConfig` must provide a non-empty command tuple whose
first token is an existing absolute executable. Lunar-Agent invokes it as:

```text
<command> <strategy-workspace>/evolution/external/openevolve/config.json
```

The config contains `schema_version`, the canonical `contract`, a strategy-local `workspace`, a
relative `result_path`, and a bounded `budget` projection. The command must create `result.json`
under that workspace. `result.json` must contain a confined relative `candidate_path`; it may include
one strict `EvaluationReport` object. No stdout format is accepted as a result substitute.
