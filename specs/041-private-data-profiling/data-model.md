# Data Model: Private Data Profiling

## Input profile

```json
{
  "schema_version": "1",
  "files": [
    {
      "path": "data/raw/orders.csv",
      "format": "csv",
      "size": 1234,
      "sha256": "...",
      "row_count": 47,
      "fields": [
        {"name": "order_id", "type": "string", "null_count": 0, "unique_count": 47},
        {"name": "cost", "type": "number", "null_count": 2, "unique_count": 41}
      ]
    }
  ]
}
```

For text, `fields` is empty and `line_count` is included. For JSON objects representing one record,
`row_count=1`; JSON arrays and JSONL must contain objects. Field order is deterministic. Values,
samples, extrema, distributions, local source paths, and original filenames outside `data/raw/`
are forbidden.

## Manifest extension

```json
{"input_profile_sha256": "..."}
```

`bundle_sha256` is recomputed over this field with the existing contract/objective/evaluator/probe
digests. The frozen directory contains `input-profile.json` in addition to the Feature 040 files.
