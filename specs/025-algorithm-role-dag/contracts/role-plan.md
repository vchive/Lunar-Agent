# Contract: `build_algorithm_role_plan`

```python
def build_algorithm_role_plan(
    goal: str, contract: AlgorithmProblemContract
) -> PlanDocument: ...
```

The returned document starts at version 1, embeds the canonical contract, and contains exactly the
five fixed role IDs in dependency order. It must be accepted by `PlanDocument` and
`AlgorithmProblemContract` before being attached to a run.
