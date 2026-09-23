# Feature 153 data model

```text
ProducerBundlePublicationJournal
  schema_version / protocol
  journal_id
  run_id / parent_task_id / task_id
  admission_sha256
  archive_prefix_sha256
  base_archive_sha256 / base_state_sha256
  contract_sha256
  evaluator_kind / evaluator_fingerprint
  runner_fingerprint
  dependency_sha256 / environment_sha256
  budget_sha256
  strategy / population_config_sha256 / num_islands
  candidates[]                  # plan order, fixed candidate IDs and state mapping
  state                         # prepared | executing | publishing | published | failed | unknown
  publication_phase             # preflight | staged | committed | recovery_required
  terminal_marker_sha256?
  archive_after_sha256?
  state_after_sha256?
  journal_sha256                 # hash payload with this field omitted

ProducerBundlePublicationCandidate
  candidate_id
  bundle_id / bundle_sha256
  parent_id? / generation / iteration / island_id
  preparation_receipt_sha256
  execution_receipt_sha256?
  evaluation_receipt_sha256?
  publication_receipt_sha256?
  status                        # planned | rejected | admitted | unknown
```

The journal also records bounded byte digests and no-follow file identities (device, inode, size,
and timestamps) for the base and after archive/state snapshots. Its own digest is computed over
the canonical payload with `journal_sha256` omitted. Its prefix digest covers canonical
archive bytes in append order, `state.json`, strategy configuration, active mapping, and any
seed-commit marker. The journal is an authority and recovery record. It contains no producer-
reported score and does not replace the native execution, evaluation, or archive record schemas.
