# Implementation Plan: Runtime Model Profile Integration

1. Add failing agent-loop tests for token-budget rejection and cost telemetry.
2. Inject an optional `ModelProfile` and `UsageLedger` into `AgentLoopRuntime`.
3. Apply profile timeout/step limits and translate bounded ledger failures into runtime failures.
4. Preserve existing metadata and exports, then run the repository quality gates.
