# Data model: strict role evidence

Role evidence is an attempt-local artifact. The SQLite artifact row remains the durable index:

| Field | Value |
| --- | --- |
| `kind` | `role_evidence` |
| `path` | `tasks/<physical-task>/<attempt>/<declared-path>` |
| `size` | regular-file byte size, bounded by `MAX_ARTIFACT_BYTES` |
| `sha256` | SHA-256 of the file bytes |
| `task_id` | physical scheduler task that owns the role |

The built-in role contracts are:

| Role | Acceptance rule | Required path | Shape |
| --- | --- | --- | --- |
| DataDiscovery | `data_profile_valid` | `data/processed/data-profile.json` | `{schema_version:"1", inputs:[{path,format,row_count,columns,issues}], notes?}` |
| ProblemFormulator | `artifact_valid` | `solve/problem-formulation.md` | non-empty UTF-8 text |
| Solver | Feature 031 `output_valid` | `output/...` | declared JSON/JSONL/CSV/text output |
| Evaluator | `evaluation_report_valid` | `evaluate/evaluation.json` | existing `EvaluationReport` |
| Reviewer | `artifact_valid` | `evaluate/review.md` | non-empty UTF-8 text |

Validation evidence contains only rule names, safe paths, counts, formats, and scalar metadata. It
does not contain role-file contents or source-machine paths. A failed attempt may retain a hashed
role file for audit, but delivery checks that the artifact belongs to the task's successful result
attempt.
