# Offline result validation

Use `parse_benchmark_comparison_result(...)` to read a bounded canonical JSON receipt, then call
`admit_benchmark_comparison_result(result, plan)` to ensure every planned arm appears exactly once.
The functions only validate bytes and identities; they do not run benchmark code.

The static CLI performs the same checks without initializing Lunar:

```bash
lunar-agent benchmark-comparison validate-result plan.json result.json \
  --contract contract.json --input-root ./public-input \
  --model-profile-sha256 "$MODEL_PROFILE_SHA256" \
  --evaluator-fingerprint "$EVALUATOR_SHA256" --json
```
