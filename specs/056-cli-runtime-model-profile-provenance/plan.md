# Implementation Plan: CLI Runtime Model Profile Provenance

1. Add SDD acceptance tests for profile loading, CLI option validation, detached propagation, and
   fingerprint sensitivity.
2. Implement bounded JSON profile loading and wire the profile into ordinary CLI agent loops.
3. Include a credential-free profile digest in runtime/compiler identity and detached propagation.
4. Run focused/full tests, lint, compilation, build, Specify checks, and diff checks.
