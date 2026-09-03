# Quickstart: role evidence

Run the offline specialist workflow:

```bash
lunar-agent solve "设计配送路线" --runtime mock --role-dag --json --home .lunar
```

Inspect the role evidence and independent evaluator report:

```bash
lunar-agent status <run-id> --json --home .lunar
lunar-agent deliver <run-id> --json --home .lunar
```

The JSON status response contains `role_evidence`, whose rows point to hashed files below
`tasks/<task>/<attempt>/`. A custom runtime must create the files in its private attempt workspace;
returning a prose response is insufficient for the four specialist roles.

An evaluator role report has this shape (the values are examples):

```json
{
  "schema_version": "1",
  "evaluator_id": "routing-v1",
  "validity": 1,
  "quality": 0.92,
  "combined_score": 12.4,
  "detailed_scores": {},
  "error_info": []
}
```
