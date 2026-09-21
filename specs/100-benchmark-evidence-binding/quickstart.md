# Offline evidence binding

Build a Feature 099 result with `evidence_path` and `evidence_size` for each arm, then validate it
against the frozen plan and the directory containing those files:

```bash
lunar-evolution benchmark-comparison validate-result plan.json result.json \
  --contract contract.json --input-root ./public-input \
  --model-profile-sha256 "$MODEL_PROFILE_SHA256" \
  --evaluator-fingerprint "$EVALUATOR_SHA256" \
  --evidence-root ./evidence --json
```

Python callers can use `bind_benchmark_comparison_result_evidence(result, plan, evidence_root)`.
The operation only reads bounded local files. Without `--evidence-root`, legacy digest-only receipts
continue to validate for migration compatibility.

Successful output includes `evidence_bound: true` when the files were checked, or `false` when only
the receipt was checked. Failure returns exit code 2 and a fixed error code, without evidence text
or local paths. Descriptor fields must both be omitted or both non-null. Use physical directory
paths: symlinks in any ancestor are rejected, including `/tmp` or `/var` aliases on macOS.
This also applies to the result JSON path. Result/evidence file paths reject `..` and are limited
to 4096 UTF-8 bytes and 128 components after expansion to an absolute path; the per-arm relative
evidence descriptor retains its 1024-byte limit. These path restrictions tighten file admission,
while valid receipt schemas and identities remain compatible.

Run the offline CLI and file-boundary regression scenarios with:

```bash
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_benchmark_result.py tests/test_benchmark_evidence_cli.py \
  tests/test_benchmark_evidence_files.py tests/test_benchmark_result_validation.py
```
