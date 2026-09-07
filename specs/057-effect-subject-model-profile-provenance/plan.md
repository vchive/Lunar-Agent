# Implementation Plan: Effect Subject Model Profile Provenance

1. Add acceptance tests for subject profile loading, limits, receipt telemetry, and profile
   mismatch/recovery rejection.
2. Thread an optional `ModelProfile` through the effect subject CLI and adapter, applying bounded
   timeout/step/token/cost policy without changing score authority.
3. Add canonical profile identity to subject requests, receipts, trial configuration identities,
   and deep-round resume validation.
4. Verify that credentials and private harness data never enter subject artifacts or command
   arguments.
5. Run focused and full tests, lint, compilation, build, Specify checks, and diff checks.
