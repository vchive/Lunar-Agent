# Acceptance Contract v1

`tasks[].acceptance` is a local-only declarative contract. It is evaluated after the selected
profile evaluator passes and before the controller marks the attempt successful.

```json
{
  "all": [
    {"result_contains": "report written"},
    {"artifact_exists": "report.json"},
    {"json_has_keys": {"path": "report.json", "keys": ["summary", "sources"]}}
  ]
}
```

## Rule syntax

```text
rule := {"result_contains": text}
      | {"contains": text}                         # legacy alias only
      | {"artifact_exists": relative_path}
      | {"artifact_text_contains": {"path": relative_path, "contains": text}}
      | {"json_parse": relative_path}
      | {"json_has_keys": {"path": relative_path, "keys": [text, ...]}}
      | {"all": [rule, ...]}
      | {"any": [rule, ...]}
```

Top-level legacy forms are also accepted:

```json
"done"
```

```json
{"contains": "done"}
```

## Rejection rules

- Rule objects must have exactly one recognized key; unknown metadata is rejected.
- Paths are relative to the current attempt workspace, may not be absolute, may not contain `.` or
  `..` components, and may not resolve through a symlink outside the workspace. The attempt
  workspace itself may not be a symlink.
- Contracts and values have the limits in `data-model.md`; credential-like text is rejected.
- A file must be a regular UTF-8 file and no larger than the configured inspection bound for text
  or JSON rules.

## Evaluation output

Every `task_evaluated` event has the existing `passed`, `reason`, and `evidence` fields plus:

```json
{
  "details": {
    "base": {"kind": "non_empty", "passed": true},
    "acceptance": {
      "rule": "all",
      "passed": true,
      "children": [
        {"rule": "artifact_exists", "path": "report.json", "passed": true}
      ]
    }
  }
}
```

The detailed tree remains bounded by the input rule bounds and contains no artifact contents.
