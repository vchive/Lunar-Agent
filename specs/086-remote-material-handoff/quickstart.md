# Feature 086 offline quickstart

The quickstart uses only temporary files and local fake evaluators.

1. Build a completed `RemoteExperimentState` with one `candidate_source` reference and a matching
   local source file.
2. Call the remote material admission bridge with pinned contract, producer, and exact-harness
   fingerprints. Confirm the evaluator is called once and the returned receipt uses the local
   score.
3. Repeat with `unknown`, `running`, missing-ID, empty, changed-reference, symlink, and digest
   mismatch fixtures. Confirm fixed rejection and zero evaluator/backend calls.
4. Export a Shinka SQLite fixture, pass its result root to the generic producer admission helper,
   and confirm the same local evaluator/seed boundary is used.

No network or external framework is required or allowed by this scenario.
