# Implementation plan

1. Define the immutable `BundleGroup` and verified result DTOs with bounded identifiers and
   relative paths.
2. Normalize a producer envelope through the existing v1 parser, bind contract and producer
   identity, and reject unsupported material kinds.
3. Construct canonical `CandidateSourceBundle` descriptors from only the explicitly grouped
   materials and reuse the existing read-only source verifier.
4. Export the new API without changing the existing producer handoff module or protocol bytes.
5. Add provider-free tests for successful grouping, provenance, no writes, all grouping and
   identity failures, and source integrity failures.
6. Run focused and related regressions, Ruff, compileall, diff checks, SDD/link checks, and the
   old-name scan. Commit and push the offline slice.
