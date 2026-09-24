# Feature 158 data model

```text
TrustedBootstrapDescriptor
  schema_version / protocol / implementation_version
  bootstrap_sha256 / size / device / inode / mtime_ns / ctime_ns
  allowlist_id / platform_execution_mode

TrustedBootstrapLaunch
  launch_id / journal_id / run_id / parent_task_id / task_id
  intent_sha256 / attestation_sha256
  bootstrap_descriptor_sha256 / target_executable_identity
  gate_protocol / gate_nonce
  launch_sha256

BootstrapHandshakeFrame
  sequence / kind
  launch_sha256 / intent_sha256
  target_executable_identity?
  observed_pid / observed_pgid?
  frame_sha256

TrustedBootstrapEvidence
  launch_sha256 / registration_sha256
  bootstrap_ready_observed
  release_observed
  target_started_observed
  target_start_count
  target_group_identity
  pre_gate_target_work_observed
  status                       # passed | failed | unknown
  failure_code?
  evidence_sha256
```

`kind` is one of `bootstrap_ready`, `target_started`, `target_start_failed`, or `terminal`. Frames
are bounded, canonical, ordered, and no-follow transport records; they contain no producer text,
prompt, credential, provider response, or score. A successful evidence record requires the pinned
bootstrap descriptor, durable Feature 156 registration before release, exactly one release token,
exactly one target start after release, and a retained target process-group identity.

`terminal` is an optional close frame after `target_started`; transport EOF after a valid
`target_started` frame is also a successful handshake close. EOF before target start is a terminal
failure. A terminal close never substitutes for the required target-start evidence.

`pre_gate_target_work_observed=false` is not a free-form claim from the target. It is established
only by the trusted bootstrap state machine plus the controlled fixture's pre/post markers. The
evidence is invalid if bootstrap identity or exact-byte execution is unresolved. The checked-in
fixture uses a same-source descriptor recheck and explicitly reports `fixture-only`; it does not
claim that a pathname recheck closes Feature 156's non-Darwin replacement window.
