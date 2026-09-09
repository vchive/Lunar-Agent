# Plan: Budget-Guided Fixed Measurement

1. Prepare a new campaign and two isolated attempts from only the frozen public ledger.
2. Reuse the validated standalone runner, replacing repeated CC Switch loads with a single parent
   environment snapshot and adding source/config/runner drift rejection before dispatch.
3. Check the local exact harness dependencies and imported source location without model calls.
4. Freeze manifest, runner and source/input hashes; publish registration before execution.
5. Start both slots once, wait for completion, and retain all results and safe diagnostics.
6. Validate receipts and artifact presence, aggregate fixed-denominator counts, review offline,
   and document the actual result. No additional test runs of the unchanged product are required.

## Contracts and recovery

The manifest is immutable; progress and final slots are separate files. Each runner retains the
existing normal request's run_index=1 because it is an independent single-case invocation; outer
campaign slot index identifies the two disjoint workspaces. There is no automatic resume/relaunch.
The wrapper uses process environments only for credentials and discards raw stdout/stderr.

Use the existing SDK environment, suite, profile and exact adapter validators. Check source digests,
not current git HEAD alone, because documentation-only registration may be committed after the
implementation commit. New runner plumbing is frozen and disclosed as part of the protocol.

## Local reproduction

Machine-local campaign scripts and hashes are under `.lunar/real-eval-glm-5.1-variant-v2-20260909/`.
The launcher refuses to run after its started marker; summary/audit is a separate read-only operation.
Completed evidence can be inspected without CC Switch access or provider calls.

## Complexity

No product runner/schema migration. Existing comparative model guard remains intact. Fixed sample
size, shared-provider concurrency and bundled runtime changes limit causal and population claims.
