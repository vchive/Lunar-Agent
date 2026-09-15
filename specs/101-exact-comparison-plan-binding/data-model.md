# Data model

`BenchmarkComparisonResult` appends `plan_sha256: str | None = None` to its Python DTO. Serialization
omits the field for legacy receipts. If supplied in JSON, the key must have a valid non-null SHA-256.
The result ID hashes its existing protocol/comparison ID/arm payload plus this pin when present.

`from_plan(plan, arms)` derives the pin and result ID, requiring exact arm coverage. It is a factory
for explicitly creating a new declaration, not an admission or execution operation.

`admit_benchmark_comparison_result(..., expected_plan_sha256=None)` preserves legacy compatibility.
A supplied expected pin requires a pinned receipt and equality with the canonical input plan digest.
CLI `plan_bound` is true only when the receipt contains a verified pin; `evidence_bound` retains
its independent meaning. SHA-256 alone is not an external attestation or authentication mechanism.
