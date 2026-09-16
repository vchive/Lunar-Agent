# Plan

1. Reuse AlgorithmProblemContract, OutputSpec and EvaluationReport semantics, Feature 107
   inspection, descriptor-relative private trees and Feature 106 process-group cleanup.
2. Add an exact evaluator specification with implementation size/hash, evaluator ID, argv,
   explicit environment and bounded time/report/artifact limits; use its fingerprint in admission.
3. Validate declarations and pins in memory, then inspect successful execution, held root
   identities, current source/input bytes and harness bytes before creating a private evaluation.
4. Capture declared outputs through no-follow bounded descriptors. Retain inputs, outputs,
   harness and canonical request in a new private tree; independently validate output format.
5. Run the harness once against that tree with bounded raw-byte capture. Parse its full report
   strictly, recheck observations and publish report plus manifest. Preserve allocated directories
   on failure; re-evaluation uses a different directory and never re-executes the candidate.
6. Provide read-only complete-manifest inspection, public APIs, CLI, deterministic process and
   failure tests, runnable quickstart and updated readiness/handoff documentation.

## Decisions and alternatives

Snapshot at evaluation time because existing execution records contain no output snapshots.
Do not reinterpret them as process-exit proof. Copy bytes for the harness instead of merely
hashing mutable original paths. Reuse the structured format checker on captured bytes, with
strict JSON decoding for JSON/JSONL. Do not reuse the old evaluator that runs candidates again.

Separate durable evaluation directories keep the original execution record immutable. This is
a local result API, with future archive/control-plane integration explicitly deferred. No new
runtime dependencies, database migration or constitution exception is required.
