# Implementation plan

1. Define a provenance-carrying `ProducerBundleDraft` DTO.
2. Reverify bundle source bytes through the canonical candidate bundle verifier.
3. Decode the verified files into `CandidateDraft.from_files` without copying or writing.
4. Reject duplicate IDs, cross-bundle path reuse, invalid roots, tampering, and invalid drafts.
5. Export the adapter and add provider-free regression coverage.
