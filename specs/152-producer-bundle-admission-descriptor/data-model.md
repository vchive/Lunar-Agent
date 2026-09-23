# Feature 152 data model

```text
ProducerBundleAdmissionItem
  bundle_id
  bundle_sha256
  draft_bundle_sha256
  entrypoint
  material_paths
  producer_fingerprint
  producer_id?
  envelope_sha256?

ProducerBundleAdmissionPlan
  schema_version / protocol
  contract_sha256
  evaluator_kind
  evaluator_fingerprint
  runner_fingerprint
  dependency_sha256
  environment_sha256
  bundles[]
  digest() -> admission_sha256
```

The plan contains no producer-reported score or evaluator result. Its digest binds order and all
authority fields for a later publication/resume boundary.
