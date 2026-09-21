# Offline exact plan validation

Create a new receipt explicitly with `BenchmarkComparisonResult.from_plan(plan, arms)`. Store its
JSON and keep the canonical `plan.digest()` alongside the independently frozen measurement plan.
This factory records declarations; it does not run or certify a measurement.

```python
from lunar_evolution import BenchmarkComparisonResult, parse_benchmark_comparison_plan

plan = parse_benchmark_comparison_plan("plan.json")
# arms contains the caller's independently obtained ComparisonArmResult summaries.
receipt = BenchmarkComparisonResult.from_plan(plan, arms)
payload = receipt.to_dict()
plan_pin = plan.digest()  # canonical plan SHA-256, not a hash of pretty-printed JSON bytes
```

```bash
lunar-evolution benchmark-comparison validate-result plan.json result.json \
  --contract contract.json --input-root ./public-input \
  --model-profile-sha256 "$MODEL_PROFILE_SHA256" \
  --evaluator-fingerprint "$EVALUATOR_SHA256" \
  --plan-sha256 "$PLAN_SHA256" --evidence-root ./evidence --json
```

Successful output has `plan_bound: true` and `evidence_bound: true`. Omit `--evidence-root` to check
only plan/receipt identities and public inputs. Legacy receipts still validate without a caller
plan pin and report `plan_bound: false`; validation never silently upgrades them.

Task, plan, result, input and evidence paths must use physical directories without symlink ancestors
or `..`. On macOS use the actual directory rather than `/tmp` or `/var` aliases.

Offline regression:

```bash
.venv/bin/python -m pytest -o addopts='' -q tests/test_benchmark*.py
```
