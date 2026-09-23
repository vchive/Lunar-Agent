# Feature 150 data model

## `BundleGroup`

```text
bundle_id: bounded identifier
entrypoint: safe relative path
material_paths: 1..64 safe relative paths
```

`bundle_id` values are unique within one preparation call. `entrypoint` must occur exactly in
`material_paths`; paths are unique within a group and cannot occur in another group.

## `VerifiedProducerBundle`

```text
bundle_id: BundleGroup.bundle_id
bundle: CandidateSourceBundle
bundle_sha256: canonical CandidateSourceBundle digest
file_count: number of verified files
total_bytes: sum of declared file sizes
producer_fingerprint: envelope/caller producer pin
producer_id: envelope producer ID, if available
envelope_sha256: canonical producer envelope digest
```

The `bundle` contains the contract digest, entrypoint, and sorted source file table. Source bytes
are read for verification and are not retained in this DTO. Producer evidence and producer scores
are provenance only.

## Fixed failures

`ProducerBundleHandoffError` exposes only a fixed `code`, including invalid grouping, duplicate or
reused paths, undeclared paths, identity/contract mismatch, unsupported material kind, invalid
status, and unsafe root. Existing `CandidateBundleError` codes are preserved for source integrity
failures.
