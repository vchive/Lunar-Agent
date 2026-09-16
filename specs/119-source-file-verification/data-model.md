# Data model and compatibility

New optional constraint field:

```json
{
  "id": "two-files",
  "description": "Deliver at least two Python files.",
  "source": "user_confirmed",
  "verification": "independent",
  "verification_scope": "source",
  "source_check": {"kind": "python_file_count", "minimum": 2}
}
```

source_check is an immutable SourceCheckSpec. Only kind/minimum are accepted; minimum is an
integer 1..64. Null, unknown keys/kinds, booleans and non-source scope fail schema validation.
Omitted source_check remains omitted and preserves old contract identities. Only hard constraints
with this checker are supported; soft source or execution requirements are never silently waived.

Source evidence uses protocol lunar-source-checks-v1, schema_version 1, contract_sha256,
bundle_sha256, source_file_table_sha256, full bundle declaration, ordered checks and boolean validity.
Each check contains id/kind/minimum/observed/passed. Revalidation rebuilds the entire canonical
document from the contract and bound source bundle. Full evidence is limited to 256 KiB to fit
the maximum 128 KiB bundle plus all constraints; a failure report lists at most 32 errors while
evidence retains every failed ID. File names count by exact lowercase .py suffix, including empty
files; no source code is imported or interpreted.

Source-aware evaluation protocol lunar-candidate-evaluation-source-v1 adds boolean
source_constraints_valid and the source-checks.json file descriptor. Requests stay under the
existing protocol with the full new contract. The output harness does not receive the sidecar:
it is written by the controller after the harness finishes. Invalid output schema takes report
precedence; otherwise failed source checks force validity 0/score 0/quality null and skip the harness.
Passing local checks still require a valid output evaluator report. Inspection reruns neither.

Source-aware portable delivery contains evaluation/source-checks.json, the contract, full source
bundle and source bytes. It checks the exact source set/bytes and recomputes the source evidence.
The new protocol lunar-bundle-delivery-source-v1 requires those materials. Unscoped historical
packages retain their old protocol/shape and opacity rules. Parent/child digest pins continue to
bind the selected delivery; portable checks without an expected digest establish consistency,
not authenticity against a complete rewrite of every identity and file.
