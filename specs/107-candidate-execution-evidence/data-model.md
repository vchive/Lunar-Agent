# Data model

Each retained record is bounded to 16 KiB; the admission-bound input file table is hashed under
the existing 128 KiB declaration ceiling.

The caller supplies a new physical `attempt_path` whose parent already exists:

```text
attempt_path/
  launch-intent.json
  result.json
  completed.json
```

Each file may have a corresponding `.NAME.tmp` during publication. Any retained temporary node is
interruption evidence and makes inspection uncertain; it never authorizes replay or implicit repair.

Canonical bytes use compact sorted JSON:
`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)`
encoded as UTF-8 **without a trailing newline**. Each schema and read has an explicit bounded size.
Duplicate keys, non-finite numbers, unexpected fields and noncanonical bytes fail closed.

The intent binds plan/admission/bundle/contract digests, source/input file-table digests, the
workspace/input/attempt directory device/inode identities and a random
nonce. Plan/admission digests commit to full command/environment/source/input declarations without
persisting their local values. The nonce identifies a new authorized attempt, not a signed identity.

The result embeds the existing `CandidateExecutionRun.to_dict()` projection and its canonical
payload digest, and binds the intent digest. The exact result-file bytes have their own digest
for completion binding; a digest must not self-reference its containing canonical bytes. The
projection omits raw stdout/stderr and contains only bounded status, exit code, duration, output
byte counts, fixed error, declaration digests, counts and relative entrypoint. Byte-count semantics
must remain those actually provided by Feature 106.

The completion descriptor binds both intent and result using exact raw canonical SHA-256, byte
size and observed regular-file device/inode. It is published only after those files and the
directory chain have been synced. Presence alone is insufficient: inspection rechecks every binding.

Public record completeness and process outcome are independent. A completed record of a failed
process is valid telemetry, not an accepted candidate. A valid intent missing result/completion or
accompanied by a temporary node is uncertain; invalid schema, unsafe nodes or inconsistent
identities are fixed errors. Neither inspection case grants execution or recovery authority.

The inspector requires the intended plan/admission and checks their complete canonical identities.
It does not require original source/input paths or bytes to remain unchanged after execution.
Local inode values establish consistency of this retained record, not portable process identity,
signatures, external attestation, evaluator acceptance or scores. No Store/ledger/recovery schema
is introduced.

## Exact schemas

All three files have `schema_version: "1"`. Protocol values are respectively
`lunar-candidate-execution-launch-intent-v1`, `lunar-candidate-execution-result-v1`, and
`lunar-candidate-execution-completion-v1`.

- Intent has `protocol`, `schema_version`, `binding`, `workspace_identity`, `input_identity`,
  `attempt_identity`, `nonce`. Each identity has unsigned 64-bit `device` and `inode`. The nonce
  is 64 lowercase hexadecimal characters. `binding` has `workspace_plan_sha256`,
  `admission_sha256`, `bundle_sha256`, `contract_sha256`, `source_file_table_sha256`, and
  `input_file_table_sha256`. File table hashes cover sorted complete declaration descriptors.
- Result has `protocol`, `schema_version`, `launch_intent_sha256`, `runner_result`,
  `runner_result_sha256`. The last field hashes only canonical `runner_result`.
- Completion has `protocol`, `schema_version`, `launch_intent`, `result`. Each file descriptor
  has `sha256`, `size`, `device`, `inode` for the exact final regular file.

`CandidateExecutionRecord.to_dict()` has `status: recorded`, `launch_intent_sha256`,
`result_sha256`, `completion_sha256`, `runner_result_sha256`, and `runner_result` for a complete
record. An incomplete observation has `status: uncertain` and may have `launch_intent_sha256`
when that intent was valid. A caller can pin `expected_completion_sha256` on inspection; an
incomplete record cannot satisfy that pin. An empty or temp-only intent directory is uncertain.
Completion without a result is inconsistent and rejected.

The ordinary two-hardlink interval between final link and temporary unlink is accepted only as
uncertain evidence when the intent's temporary name refers to the same inode. Complete final
records require one link. Extra nodes, symlinks, FIFOs and external hardlink aliases are rejected.
