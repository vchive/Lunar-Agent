# Data Model: Algorithm Problem Contract and Solver/Evaluator Workspace

## AlgorithmProblemContract

The contract is an immutable, JSON-serializable value stored inside a plan revision. It is optional
so all existing generic plans remain valid.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `schema_version` | string | yes | Contract schema version, initially `1` |
| `problem_id` | safe string | yes | Stable identifier within a plan |
| `problem_type` | enum | yes | `scheduling`, `routing`, `packing`, `assignment`, `forecasting`, `network_flow`, or `continuous` |
| `statement` | bounded string | yes | User-confirmed problem formulation |
| `inputs` | array of `InputSpec` | yes | Relative input files and field schema |
| `decision_variables` | bounded string array | yes | Variables or prediction target |
| `objective` | `ObjectiveSpec` | yes | Primary metric and direction |
| `hard_constraints` | array of `ConstraintSpec` | yes | Rules that make a candidate invalid |
| `soft_constraints` | array of `ConstraintSpec` | no | Preferences or secondary metrics |
| `success_criteria` | bounded string array | yes | Observable completion conditions |
| `deliverables` | bounded string array | yes | Business outputs to hand to the user |
| `assumptions` | bounded string array | no | Explicit unresolved/default assumptions |
| `evolution` | `EvolutionSpec` | no | Strategy selection; defaults to `loop` |

### InputSpec

| Field | Type | Meaning |
| --- | --- | --- |
| `path` | portable relative path | Input location below `data/raw` or a contract-approved run-relative path |
| `format` | bounded string | CSV, JSON, Parquet, or another declared format |
| `fields` | object | Field name to bounded semantic/type description |
| `key` | string or null | Optional declared primary key |

Input paths are unique, contain no traversal components, and are never absolute. The contract does
not copy or modify the referenced source file; a later data agent owns that operation.

### ObjectiveSpec

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | bounded string | Primary objective/metric name |
| `direction` | enum | `maximize` or `minimize` |
| `metrics` | bounded array | Optional named metric descriptors used in a combined score |

Each optional metric descriptor contains `name`, `direction`, and a non-negative `weight` whose
weights sum to a positive value. A minimization metric is normalized by the evaluator into the
higher-is-better combined score.

### ConstraintSpec

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | safe string | Stable unique constraint identifier |
| `description` | bounded string | Business rule in plain language |
| `source` | enum | `user_confirmed`, `data_observed`, or `explicit_assumption` |
| `verification` | enum | `independent`, `partial`, or `solver` |
| `result_fields` | bounded string array | Output fields used to verify the rule |

`independent` means recompute from raw/processed input and candidate output. `partial` may compare
against a solver-provided value but must retain a reference source. `solver` is reserved for values
where the solver's numerical certificate is the only meaningful representation; the evaluator must
document the physical basis in its own contract.

### EvolutionSpec

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `strategy` | enum | `loop` | `loop` for fresh-context serial rounds; `population` for explicit candidate search |
| `max_rounds` | positive integer | route budget | Upper bound for future strategy execution |
| `stagnation_rounds` | positive integer | 3 | Future stop condition |

Feature 012 validates and stores this choice but does not execute either strategy.

## AlgorithmWorkspaceManifest

The run-local manifest is a small JSON artifact containing:

```json
{
  "schema_version": "1",
  "problem_id": "routing-demo",
  "plan_id": "plan-…",
  "plan_version": 1,
  "contract_sha256": "…",
  "directories": {
    "raw_data": "data/raw",
    "processed_data": "data/processed",
    "solver": "solve",
    "evaluator": "evaluate",
    "output": "output",
    "evolution": "evolution"
  }
}
```

The digest is calculated from canonical contract JSON, not from mutable files. Directory values are
fixed run-relative paths and cannot be overridden by a model.

## EvaluationReport

| Field | Type | Required | Invariant |
| --- | --- | --- | --- |
| `schema_version` | string | yes | Initially `1` |
| `validity` | integer | yes | Exactly `0` or `1` |
| `quality` | number or null | no | Non-negative when present |
| `combined_score` | number | yes | Finite, non-negative, higher is better; zero if invalid |
| `detailed_scores` | object | yes | Bounded metric values and direction metadata |
| `error_info` | array | yes | Bounded structured violations/errors; empty for a valid candidate |
| `evaluator_id` | safe string | yes | Frozen evaluator contract identifier |

`error_info` entries identify a constraint or format/execution category and contain a bounded reason;
they never require copying raw logs or secrets. A format/execution failure is distinct from a
candidate constraint violation and may be represented as an evaluator error without pretending the
candidate was valid.

## Relationships and lifecycle

```text
PlanRevision 1 ── 0..1 AlgorithmProblemContract
Run 1 ── 1 AlgorithmWorkspaceManifest (when contract is present)
AlgorithmProblemContract 1 ── N ConstraintSpec
AlgorithmProblemContract 1 ── 1 ObjectiveSpec
Future EvolutionRun 1 ── N Candidate ── 1 EvaluationReport
```

The final relationship is reserved for later features. No candidate or population table is created
by Feature 012.
