# Feature 156 data model

```text
ProducerAttestationConsumption
  schema_version / protocol
  consumption_id / launch_id / journal_id
  run_id / parent_task_id / task_id
  intent_sha256 / attestation_sha256 / nonce
  executable_sha256 / executable_size / executable_device / executable_inode
  consumed_at_unix_ns / previous_receipt_sha256?
  consumption_sha256

ProducerProcessRegistration
  schema_version / protocol
  launch_id / journal_id / run_id / parent_task_id / task_id
  intent_sha256 / attestation_sha256 / executable_identity
  execution_binding                         # darwin-immutable-snapshot | pathname_unbound
  execution_snapshot_relative_path?
  execution_snapshot_sha256 / execution_snapshot_size
  pid / pgid / session_id / owner_lock_sha256
  gate_protocol / registered_at_unix_ns
  registration_sha256

ProducerStreamEvidence
  stream                         # stdout | stderr
  bytes_observed / sha256 / truncated
  capture_status                 # complete | limit_exceeded | unknown
  stream_sha256

ProducerEnvelopeEvidence
  relative_path / sha256 / bytes
  device / inode / mtime_ns / ctime_ns
  identity_before / identity_after
  read_status                    # stable | changed | missing | unknown
  envelope_sha256

ProducerExecutionReceipt
  schema_version / protocol
  launch_id / journal_id / run_id / parent_task_id / task_id
  intent_sha256 / attestation_sha256 / consumption_sha256
  registration_sha256 / executable_identity
  execution_binding / execution_snapshot_relative_path?
  execution_snapshot_sha256 / execution_snapshot_size
  pid / pgid / gate_released
  request_timeout_seconds / max_requests / output_max_bytes / wall_timeout_seconds
  request_count / exit_code?
  stdout_evidence / stderr_evidence
  envelope_evidence?
  cleanup_status / cleanup_sha256?
  status                         # completed | failed | cancelled | unknown | recovery_required
  failure_code?
  previous_receipt_sha256?
  receipt_sha256
```

All digests are lowercase SHA-256 values over bounded canonical JSON with the self-digest omitted,
or over exact file bytes where explicitly named. Identity fields are captured with no-follow
`lstat`/`fstat` and must not be inferred from a path. Durable files are regular single-link files
under the system-derived launch directory; updates use bounded temp files, `fsync`, and an atomic
no-follow rename. Receipt transitions bind the previous receipt digest, so a later launch cannot
overwrite an earlier attempt.

`consumed_at_unix_ns` is audit metadata only and never replaces the monotonic execution deadline.
`session_id` and `owner_lock_sha256` identify the local registration; they do not grant authority
to signal another process. Producer output, stdout, and stderr are represented by bounded sizes
and digests, not arbitrary text.
