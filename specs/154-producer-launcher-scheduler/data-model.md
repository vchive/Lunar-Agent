# Feature 154 data model

```text
ProducerLaunchIntent
  schema_version / protocol
  launch_id / journal_id                 # journal_id is reserved, not yet materialized
  run_id / parent_task_id / task_id
  candidate_integrity_authority
    schema_version / contract_sha256 / evaluator_kind / evaluator_fingerprint
    dependency_sha256 / environment_sha256
    runner_fingerprint / generator_fingerprint
  producer_id / producer_fingerprint
  executable
    root_label / relative_path
    sha256 / size / device / inode / mtime_ns / ctime_ns
  argv[] / argv_sha256
  working_directory / output_directory / envelope_path
  request_timeout_seconds / max_requests
  output_max_bytes / wall_timeout_seconds
  intent_sha256

ProducerLaunchAttestation
  schema_version / protocol
  launch_id / journal_id
  run_id / parent_task_id / task_id
  intent_sha256
  executable_sha256 / size / device / inode / mtime_ns / ctime_ns
  nonce
  attestation_sha256

ProducerLaunchPreflight
  schema_version / protocol
  status                         # preflight_passed | rejected
  launch_id / journal_id
  run_id / parent_task_id / task_id
  intent_sha256 / budget_sha256
  executable_sha256 / executable_identity
  derived_output_directory
  registration_attestation_required # future registration condition, not preflight approval

FutureProducerLaunchReceipt      # specified, not implemented by Feature 154
  launch_id / journal_id / intent_sha256 / attestation_sha256
  pid / pgid / owner_lock_digest
  status                         # running | completed | failed | cancelled | unknown
  exit_code? / envelope_sha256?
  cleanup_status / cleanup_sha256?
```

The intent and attestation digests omit their own digest field. All other digests are lowercase
SHA-256 values over bounded canonical JSON or exact file bytes. The authority object is the native
`CandidateIntegrityAuthority` projection; preflight compares every field rather than selecting a
subset. Paths are normalized relative paths under system-derived roots. No absolute path, symlink,
parent traversal, shell text, credential, prompt, provider response, or arbitrary traceback is
retained.

`ProducerLaunchPreflight` is an observation DTO. `preflight_passed` does not grant process or
publication authority and carries no plan or journal content digest. The future receipt is shown
only to make process ownership and unknown-recovery boundaries explicit; this feature must not
write it.
