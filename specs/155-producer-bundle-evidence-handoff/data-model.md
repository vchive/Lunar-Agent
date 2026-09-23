```text
ProducerBundleExecutionReceipt
  schema_version / protocol
  candidate_id / bundle_sha256
  plan_sha256 / admission_sha256 / completion_sha256
  launch_intent_sha256 / result_sha256 / runner_result_sha256 / cleanup_sha256
  status / runner_status / cleanup_status
  receipt_sha256

ProducerBundleEvaluationReceipt
  schema_version / protocol
  candidate_id / bundle_sha256
  plan_sha256 / admission_sha256 / completion_sha256 / evaluation_sha256
  binding / sanitized report / output_contract_valid / harness_invoked
  status / receipt_sha256

ProducerBundlePublicationArtifact
  native source_files / record / receipt
  execution_receipt / evaluation_receipt
  execution_receipt_sha256 / evaluation_receipt_sha256 / publication_receipt_sha256
```
