# Plan

1. Introduce a small read-only profile identity/input-binding helper for conversational runs.
2. Route explicit bundle profiles through existing solve intake, request/resume and linked-child
   logic, using the 110 Agent generator and 109 pipeline. Preserve legacy paths and wire shapes.
3. Add a parent delivery seam that verifies existing links and selected evidence, prepares a pinned
   portable copy and reuses output publication and normal parent delivery without execution.
4. Verify local intake/generation/selection/delivery/resume, input/profile drift, publication
   interruption, output conflicts, budgets and old conversational/materialization regressions.
5. Publish a runnable example and update readiness/handoff; run full checks, commit and push.

Use the existing delivery copy/Store/events and output journal. Do not build another execution
protocol or route bundles through the historical single-file materialization/attestation lifecycle.
