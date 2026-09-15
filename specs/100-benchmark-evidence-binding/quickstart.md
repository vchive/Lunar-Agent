# Offline evidence binding

Build a Feature 099 result with `evidence_path` and `evidence_size` for each arm, then validate it
against the frozen plan and the directory containing those files:

```bash
lunar-agent benchmark-comparison validate-result plan.json result.json \
  --contract contract.json --input-root ./public-input \
  --model-profile-sha256 "$MODEL_PROFILE_SHA256" \
  --evaluator-fingerprint "$EVALUATOR_SHA256" \
  --evidence-root ./evidence --json
```

Python callers can use `bind_benchmark_comparison_result_evidence(result, plan, evidence_root)`.
The operation only reads bounded local files. Without `--evidence-root`, legacy digest-only receipts
continue to validate for migration compatibility.
