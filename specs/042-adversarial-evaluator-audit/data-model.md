# Data Model: Adversarial Evaluator Audit

## Audit suite

`audit.json` uses the same probe-suite contract as `probes.json`:

```json
{
  "schema_version": "1",
  "constraint_coverage": ["serve-all"],
  "probes": [
    {
      "name": "audit-valid-low-cost",
      "constraint_id": null,
      "expected_validity": 1,
      "files": [{"path": "data/raw/orders.csv", "content": "..."}]
    }
  ],
  "score_order": [
    {"better": "audit-valid-low-cost", "worse": "audit-valid-high-cost"}
  ]
}
```

Names need only be unique within their own suite. The suite is canonicalized for storage; synthetic
contents remain local bundle evidence and are never copied into candidate generation workspaces.

## Manifest extension

```json
{"audit_sha256": "..."}
```

`bundle_sha256` covers the new field together with contract, objective, evaluator, compiler probes,
and private profile digests. The manifest protocol is `frozen-evaluator-bundle-v2`, and the exact
bundle file set becomes:

- `objective.md`
- `evaluator.py`
- `probes.json`
- `audit.json`
- `input-profile.json`
- `manifest.json`
