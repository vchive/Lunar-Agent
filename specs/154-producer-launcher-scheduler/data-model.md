# Feature 154 data model

```text
ProducerLaunchIntent
  schema_version / protocol
  launch_id / journal_id
  run_id / parent_task_id / task_id
  admission_sha256 / journal_sha256
  contract_sha256
  evaluator_kind / evaluator_fingerprint
  runner_fingerprint
  dependency_sha256 / environment_sha256
  producer_id / producer_fingerprint
  executable
    root_label / relative_path
    sha256 / size
    device / inode / mtime_ns / ctime_ns
  argv[] / argv_sha256
  working_directory / output_directory
  envelope_path / grouping_sha256?
  request_budget
    timeout_seconds / max_requests
  output_max_bytes
  wall_timeout_seconds
  intent_sha256

ProducerLaunchAttestation
  schema_version / protocol
  launch_id / journal_id
  run_id / parent_task_id / task_id
  intent_sha256
  executable_sha256 / size
  device / inode / mtime_ns / ctime_ns
  nonce
  attestation_sha256

ProducerLaunchAdmission
  status                         # admitted | rejected
  launch_id / journal_id
  run_id / parent_task_id / task_id
  intent_sha256 / journal_sha256 / admission_sha256
  budget_sha256
  executable_sha256 / executable_identity
  derived_output_directory
  attestation_required           # always true for a future process registration

FutureProducerLaunchReceipt      # specified, not implemented by Feature 154
  launch_id / intent_sha256 / attestation_sha256
  pid / pgid / owner_lock_digest
  started_at_observed
  status                         # running | completed | failed | cancelled | unknown
  exit_code?
  envelope_sha256?
  cleanup_status / cleanup_sha256?
```

All digests are lowercase SHA-256 values over bounded canonical JSON or exact file bytes. The
intent and attestation digests omit their own digest field. Paths are normalized relative paths
under system-derived roots; no absolute path, symlink, parent traversal, shell text, credential,
prompt, provider response, or arbitrary traceback is retained.

`FutureProducerLaunchReceipt` is included to make the ownership boundary explicit. The first
Feature 154 implementation must not write it. Its `unknown` and incomplete-cleanup states are
terminal for the launch and cannot be repaired by replaying the producer.
