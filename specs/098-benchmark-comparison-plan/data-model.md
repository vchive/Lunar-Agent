# Data model

`BenchmarkComparisonPlan` uses protocol `lunar-benchmark-comparison-v1` and schema `1`. It has a
common contract/model/evaluator/budget binding and at least two named arms. Each arm embeds one
`BenchmarkTaskEnvelope`; benchmark framework name and release remain arm provenance only.

All arms must share the task envelope comparison digest and common condition fields. The derived
comparison ID hashes the common workload/conditions and excludes arm names, scores, generation IDs
and run IDs. Admission returns only immutable IDs and per-arm envelope digests after local input and
caller pin checks.
