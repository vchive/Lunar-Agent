# Data Model: Artifact Acceptance Contracts

## Acceptance Contract

An acceptance value is one of:

1. Legacy non-empty string: shorthand for `result_contains`.
2. Legacy object `{ "contains": "text" }`: shorthand for `result_contains`.
3. A canonical rule object below.

Exactly one key is allowed per canonical rule.

| Rule | Value | Pass condition |
| --- | --- | --- |
| `result_contains` | string | Candidate result includes text. |
| `artifact_exists` | run-relative string | A regular file exists under this attempt workspace. |
| `artifact_text_contains` | `{path, contains}` | UTF-8 artifact is within byte limit and includes text. |
| `json_parse` | run-relative string | UTF-8 artifact is within byte limit and parses as JSON. |
| `json_has_keys` | `{path, keys}` | Parsed JSON object has all listed top-level string keys. |
| `all` | non-empty array of rules | Every child passes. |
| `any` | non-empty array of rules | At least one child passes. |

The initial bounds are: 20 KiB serialized contract, 32 leaf/composite rules, depth 8, 8 KiB text
or key values, 512-byte paths, 16 required keys, and 256 KiB inspected artifact files.

## Evaluation

`Evaluation` remains backward compatible:

| Field | Type | Meaning |
| --- | --- | --- |
| `passed` | boolean | Combined base profile and acceptance decision. |
| `evidence` | tuple of strings | Compact existing human-readable evidence. |
| `reason` | string | Short aggregate reason. |
| `details` | JSON object | Additive bounded structured evaluator/rule tree. |

`task_evaluated` adds a `details` field. `status --json` adds a task-level `evaluation` object
containing the latest such event payload. No SQLite table/column changes are required.

## Safety invariants

- A contract stores no executable code, URL, environment-variable lookup, or command.
- Every artifact path must be a non-empty relative path without `.` or `..` segments and must
  resolve below the supplied non-symlink attempt workspace.
- Evidence reports rule kind, declared safe path, pass/fail, and reason; it does not embed artifact
  contents.
- Credential-like text is rejected in contract values before a run is created.
