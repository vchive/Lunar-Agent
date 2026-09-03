# Data Model: Built-in Algorithm Role DAG

The feature adds no database fields. A generated `PlanDocument` contains these logical task IDs:

```text
data_discovery → problem_formulator → solver → evaluator → reviewer
```

`PlanDocument.algorithm_problem` remains the canonical validated contract. Each role's prompt is
bounded by the existing `PlanTask` limits; physical scheduler IDs are still namespaced by run ID in
SQLite, and dependency artifacts are passed through `LocalController._build_task_prompt`.
