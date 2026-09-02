# Contract: Algorithm Problem Contract

The existing `plan` command accepts an optional `algorithm_problem` object. The object is validated
before `LocalController.start_plan` writes a run. Unknown keys are ignored only where existing plan
compatibility requires it; the canonical stored representation contains the fields below.

## Minimal example

```json
{
  "algorithm_problem": {
    "schema_version": "1",
    "problem_id": "delivery-routing",
    "problem_type": "routing",
    "statement": "Assign every delivery to a route while minimizing total travel time.",
    "inputs": [
      {
        "path": "deliveries.csv",
        "format": "csv",
        "fields": {
          "delivery_id": "unique delivery identifier",
          "latitude": "decimal latitude",
          "longitude": "decimal longitude",
          "demand": "non-negative demand units"
        },
        "key": "delivery_id"
      }
    ],
    "decision_variables": ["route sequence per delivery"],
    "objective": {"name": "total travel time", "direction": "minimize"},
    "hard_constraints": [
      {
        "id": "serve-each-delivery",
        "description": "Every delivery is served exactly once.",
        "source": "user_confirmed",
        "verification": "independent",
        "result_fields": ["delivery_id", "route_id"]
      }
    ],
    "soft_constraints": [],
    "success_criteria": ["All deliveries appear in the result."],
    "deliverables": ["A route table and a plain-language summary."],
    "assumptions": [],
    "evolution": {"strategy": "loop", "max_rounds": 5, "stagnation_rounds": 3}
  }
}
```

## Validation rules

- `problem_type` and `evolution.strategy` are enum values listed in the data model.
- `inputs[*].path` is a portable run-relative path and cannot contain an absolute prefix, `..`,
  backslash, empty path components, or a credential-like string.
- Input paths and constraint IDs are unique.
- Every constraint has a non-empty description, supported provenance source, verification mode,
  and bounded result-field list.
- Objective direction is exactly `maximize` or `minimize`; metric weights, when present, are
  finite non-negative numbers with a positive total.
- All text, arrays, nested objects, and the complete canonical JSON are bounded. Credential-like
  values are rejected before persistence.
- The contract is pure metadata. It does not grant shell/network access and does not cause a model
  request during validation.

## Compatibility

`algorithm_problem` is optional. A plan that omits it has the exact Feature 001–011 behavior and no
algorithm workspace manifest.
