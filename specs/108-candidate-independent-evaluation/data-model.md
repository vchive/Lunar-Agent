# Data model

## Evaluator specification

`CandidateEvaluationSpec` has canonical protocol `lunar-candidate-evaluator-v1`, schema
version `1`, and exactly these fields:

| Field | Meaning |
| --- | --- |
| `harness_sha256`, `harness_size` | Exact implementation bytes, nonempty UTF-8 without NUL, at most 1 MiB. |
| `command` | Absolute executable followed by bounded arguments. |
| `evaluator_id` | Report identity; defaults to `exact`. |
| `environment` | Explicit environment mapping; empty by default. |
| `timeout_seconds` | Positive finite time limit, at most 86,400 seconds. |
| `max_output_file_bytes` | Per-output snapshot limit, at most 16 MiB. |
| `max_total_output_bytes` | Total output snapshot limit, at most 64 MiB. |
| `max_report_bytes` | Fixed at 32 KiB per captured stream (stdout and stderr separately). |

The default output limits are both 16 MiB. Parsing rebuilds DTOs and strictly decodes at most
128 KiB of UTF-8 JSON. Duplicate keys, unknown fields, invalid Unicode and nonfinite numbers
are rejected. Strings supplied to the parser are JSON content, never paths.

`digest()` hashes compact sorted canonical UTF-8 JSON. `pin()` returns
`CandidateEvaluatorPin("command-exact-v1", digest())` for execution admission. The digest binds
the harness descriptor, invocation, report identity, protocol and limits. It does not bind the
interpreter binary or the host dependency closure.

`candidate_output_contract_sha256(contract.outputs)` hashes the validated output declarations
sorted by their paths. Outputs use the existing `OutputSpec` formats (`json`, `jsonl`, `csv`,
`text`), required/optional status and field rules. This evaluation path requires between 1 and
32 distinct, portable output paths under `output/`.

## Harness request and snapshot

The evaluator runs with its new private evaluation directory as cwd. The invocation is:

```text
<command...> evaluator.py request.json
```

The source harness is retained as `evaluator.py`; the configured interpreter defines its
language. Declared inputs are copied to `inputs/<input target>` and present outputs retain
their declared `output/...` paths. Candidate source and original local paths are not included.
The harness must leave this tree unchanged, create no extra files and emit its report to stdout.

`request.json` uses protocol `lunar-candidate-evaluation-request-v1`, schema version `1`, and
`observation: "evaluation-time"`. It contains the reconstructed algorithm contract, evaluator
specification, admitted input table, sorted output presence/size/SHA-256 table, and a binding
object with these digests:

- Workspace plan, execution admission, source bundle and algorithm contract.
- Source file table and input file table.
- Launch intent and completed execution record.
- Evaluator fingerprint and output contract.

The retained request does not replace execution evidence. Evaluation requires the original
attempt to be recorded and successful, checks workspace/input root identities against its
launch intent, and rechecks declared source/input bytes before invoking the harness.

## Report and completion manifest

The harness writes exactly one strict UTF-8 JSON `EvaluationReport` to stdout, with all seven
fields present: `schema_version`, `evaluator_id`, `validity`, `quality`, `combined_score`,
`detailed_scores`, `error_info`. The parser rejects unknown fields and duplicate keys,
nonfinite numbers, incorrect evaluator identity and reports exceeding 32 KiB. `quality` may
be null. Invalid reports require a zero combined score and explanatory `error_info`.

The output format check runs independently. Missing or malformed required outputs produce
a zero-score invalid report with code `output_contract_failed`; the harness is not launched.
An optional output is permitted to be absent, but a present optional output must validate.

`report.json` retains the raw harness stdout bytes, including any accepted surrounding JSON
whitespace. If the output contract fails, it contains a canonical generated invalid report.
Only a successfully validated evaluation publishes `evaluation.json`. That canonical manifest
uses protocol `lunar-candidate-evaluation-v1`, schema version `1`, and contains:

- `observation: "evaluation-time"` and the evaluation directory device/inode identity.
- The request binding object.
- A file table with byte size, SHA-256, device and inode for each retained snapshot file,
  request, harness and raw report.
- The parsed report, `output_contract_valid` and `harness_invoked`.

The evaluation digest is SHA-256 of the exact canonical manifest bytes. The manifest excludes
its own file descriptor and digest. Public metadata includes status `evaluated`, observation,
evaluation digest, binding, report and the two validation booleans. It includes no local path.

Inspection verifies the manifest, strict request/report schemas, all retained file descriptors
and bytes, the output contract, evaluator fingerprint and exact set of tree entries. It can
operate after original workspace/input files change or disappear. An incomplete directory is
an error; inspection never repairs it or launches a process. Evaluation preserves allocated
directories after failures and creates a fresh directory for every retry.

Original file observations are rechecked before manifest publication. Once complete, the manifest
binds the retained snapshot; later original workspace changes do not invalidate that snapshot.
Filesystem sync/readback failures can leave a complete record even if the caller did not receive
success. Inspection is the read-only way to determine whether it is complete and consistent.
Without a saved expected digest, inspection checks local consistency rather than authenticity.

These are local execution/evaluation records. They do not introduce Candidate, Store, receipt,
archive, population selection, recovery authority, attestation or benchmark results.
