# Feature 153 data model

```text
ProducerBundlePublicationJournal
  schema_version / protocol
  journal_id
  admission_sha256
  archive_prefix_sha256
  contract_sha256
  evaluator_kind / evaluator_fingerprint
  runner_fingerprint
  dependency_sha256 / environment_sha256
  candidates[]                  # plan order, fixed candidate IDs
  state                         # prepared | executing | publishing | published | failed | unknown
  journal_sha256

ProducerBundlePublicationCandidate
  candidate_id
  bundle_id / bundle_sha256
  preparation_receipt_sha256
  execution_receipt_sha256?
  evaluation_receipt_sha256?
  publication_receipt_sha256?
  status                        # planned | rejected | admitted | unknown
```

The journal is an authority and recovery record. It contains no producer-reported score and does
not replace the native execution, evaluation, or archive record schemas.
