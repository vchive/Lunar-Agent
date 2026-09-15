`ComparisonArmResult` keeps the Feature 099 fields and optionally adds:

```json
{
  "evidence_path": "sky/receipt.json",
  "evidence_size": 1234
}
```

The two fields are all-or-none. `evidence_path` is relative to the caller's `evidence_root` and is
limited to 1024 UTF-8 bytes; `evidence_size` is an integer from 0 through 16 MiB. `evidence_sha256`
continues to identify the exact bytes. The optional fields are included in canonical result JSON and
therefore in `result_id`.
