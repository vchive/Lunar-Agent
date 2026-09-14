# Data model

The operator supplies canonical UTF-8 JSON (sorted keys, two-space indentation, trailing newline),
limited to 16 KiB. Duplicate keys, nonfinite numbers, extra/missing keys and unsafe nodes are rejected.
Schema 1 has exactly these 14 keys:

| Key | Binding |
| --- | --- |
| `schema_version` | String `"1"` |
| `parent_run_id`, `evolution_run_id`, `task_id` | Exact existing parent, linked evolution child and unique child task |
| `launch_intent_sha256` | SHA-256 of the canonical 090 intent, including contract, strategy, candidate path and runner fingerprint |
| `candidate_id`, `candidate_sha256` | Exact candidate identity and source digest |
| `attempt_path`, `execution_path` | Canonical final attempt and its `execution.json` |
| `execution_sha256`, `execution_size` | Original execution bytes and bounded positive byte count |
| `device`, `inode` | Exact regular-file identity; integers in `[0, 2**64)` |
| `nonce` | 32–128 characters from `[A-Za-z0-9._~-]`, unique across this Store |

The 091 execution journal optionally embeds this complete object as `attestation`; the extended
journal is limited to 24 KiB. Existing journal bytes remain unchanged for normal runner registration.
The journal is reconstructed against the live launch, execution bytes and file identity on every
recovery, including recovery without the original operator receipt file.

One `materialization_execution_attested` event has the fixed ID
`event-materialization-execution-attested-<sha256(parent + NUL + child)>`. Its payload contains the
receipt plus `receipt_sha256` and `journal_sha256`. The 091 prepared event has an additional
`attestation_sha256` only for this path. These two events are inserted in the same FULL transaction.
Execution artifact and committed events retain their existing schema. There is no table migration,
standalone receipt writer, external identity verification or new execution artifact format.

A retained attestation without its prepared event, or an attested prepared event without its
attestation, is invalid. A different nonce cannot replace a child's receipt; the same nonce cannot
be reused for another owner. Identical receipt replay is idempotent only with intact matching
journal/ledger evidence and no downstream evidence. All records remain retained without GC.
