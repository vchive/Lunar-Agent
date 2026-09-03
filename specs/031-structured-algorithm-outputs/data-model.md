# Data Model: Structured Algorithm Outputs

## `OutputSpec`

```json
{
  "path": "output/routes.csv",
  "format": "csv",
  "fields": ["item_id", "route_id"],
  "required": true,
  "description": "One assignment per order"
}
```

| Field | Type | Rules |
|---|---|---|
| `path` | string | portable relative path, strictly below `output/`, max 512 bytes |
| `format` | enum | `json`, `jsonl`, `csv`, `text` |
| `fields` | string array | max 32 unique safe field names; empty for `text` |
| `required` | boolean | defaults to `true`; absent optional files are allowed |
| `description` | string | optional, max 512 bytes |

`AlgorithmProblemContract.outputs` is a tuple of `OutputSpec` values, max 32 entries with unique
paths. Empty/missing outputs is omitted from canonical JSON for compatibility with older digests.

## Artifact lifecycle

```text
tasks/<task>/<attempt>/output/x.csv
        │ independent output_valid check
        ▼
<run>/output/x.csv  ── SHA-256 ── artifacts(kind=output)
```

The ledger row contains `path`, `sha256`, `size`, `kind`, task ID, and timestamps. The promotion
event contains only bounded path/format/field/size metadata. `status --json` returns these rows in
the existing `artifacts` array; `deliver` includes their paths in its evidence and requires all
required rows for an output-bearing contract.
