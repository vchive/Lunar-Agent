# Feature 152 quickstart

```python
from lunar_evolution import build_producer_bundle_admission_plan

plan = build_producer_bundle_admission_plan(
    drafts,
    contract_sha256=contract.digest(),
    evaluator_kind="exact_harness",
    evaluator_fingerprint=evaluator_sha256,
    runner_fingerprint=runner_sha256,
    dependency_sha256=dependency_sha256,
    environment_sha256=environment_sha256,
)
print(plan.digest())
```

This call only validates and binds the batch. It does not run or publish candidates.
