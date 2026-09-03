# Data Model: Frozen Evaluator Bundle

No SQLite schema migration is required.

## Compiler envelope

```json
{
  "schema_version": "1",
  "objective": "Human-readable frozen objective and formulas.",
  "evaluator_source": "... Python source ...",
  "constraint_coverage": ["serve-all"],
  "probes": [
    {
      "name": "valid-low-cost",
      "constraint_id": null,
      "expected_validity": 1,
      "files": [
        {"path": "data/raw/orders.csv", "content": "id\\na\\n"},
        {"path": "output/routes.csv", "content": "item_id,cost\\na,1\\n"}
      ]
    },
    {
      "name": "missing-order",
      "constraint_id": "serve-all",
      "expected_validity": 0,
      "files": []
    }
  ],
  "score_order": [{"better": "valid-low-cost", "worse": "valid-high-cost"}]
}
```

Probe names are safe unique identifiers. File paths are unique, confined to `data/raw/` or
`output/`, and contain bounded UTF-8 synthetic data. Every hard-constraint ID appears exactly once
as an invalid probe. At least two valid probes and one strict score ordering are required.

## Frozen manifest

```json
{
  "schema_version": "1",
  "protocol": "frozen-evaluator-bundle-v1",
  "contract_sha256": "...",
  "objective_sha256": "...",
  "evaluator_sha256": "...",
  "probes_sha256": "...",
  "bundle_sha256": "..."
}
```

The aggregate digest hashes the other canonical identity fields. Raw model settings, credentials,
absolute paths, and candidate data are absent.

## Persisted request extension

```json
{"compile_evaluator": true}
```

This non-secret marker lets detach/answer/resume select the frozen bundle path. Strategy state binds
only `bundle_sha256` through the existing `evaluator_fingerprint` field.
