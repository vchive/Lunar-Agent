# Data model

- `CandidateSourceFile(path, size, sha256)`: immutable descriptor for one source file.
- `CandidateSourceBundle(contract_sha256, entrypoint, files, schema_version, protocol)`: independent
  immutable bundle with sorted descriptors, canonical JSON and SHA-256 identity.
- `VerifiedCandidateSourceBundle(bundle, bundle_sha256, file_count, total_bytes)`: in-memory metadata
  returned after declared bytes verify. It carries no source bodies or evaluation authority.
- `CandidateBundleError`: fixed `candidate_bundle_*` code, without input paths or source text.

`parse_candidate_source_bundle(path_or_mapping)` strictly parses a bounded manifest;
`validate_candidate_source_bundle(bundle)` reconstructs the complete DTO without IO;
`verify_candidate_source_bundle(bundle, source_root=..., contract_sha256=...,
expected_bundle_sha256=...)` first checks identity and then observes declared files. The expected
bundle pin is optional; the contract pin and source root are required. No self-referential digest
field is serialized in the manifest.

Fixed error codes use the `candidate_bundle_` prefix: `invalid`, `too_large`, `path_unsafe`,
`contract_mismatch`, `identity_mismatch`, `root_unsafe`, `source_missing`, `source_unsafe`,
`source_changed`, and `source_encoding_invalid`. Malformed, unreadable or unsafe manifest files
map to `invalid`; raw manifests over 128 KiB map to `too_large`. A valid manifest's size/hash drift
maps to `source_changed`. CLI contract parsing maps to `candidate_bundle_contract_invalid`.
