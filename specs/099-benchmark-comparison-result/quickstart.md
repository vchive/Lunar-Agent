# Offline result validation

Use `parse_benchmark_comparison_result(...)` to read a bounded canonical JSON receipt, then call
`admit_benchmark_comparison_result(result, plan)` to ensure every planned arm appears exactly once.
The functions only validate bytes and identities; they do not run benchmark code.
