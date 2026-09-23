# Feature 155: producer bundle execution/evaluation evidence handoff

**Status**: provider-free implementation slice

## Problem

The native multi-file pipeline retains a plan, admission, execution attempt, and independent
snapshot evaluation for each candidate. Feature 153's publication artifact currently accepts only
opaque receipt digests, so a caller can accidentally bind a digest to unrelated bytes or lose the
per-candidate evidence when staging a producer batch.

## Outcome

Project one already persisted, native multi-file candidate into canonical execution and evaluation
receipts and a Feature 153 publication artifact. The projection is read-only and reuses the native
inspectors; it never starts a process, invokes an evaluator, or retries an uncertain attempt.
Feature 153 stages the two receipts as sidecars and verifies their canonical digests. Native
`record.json` and `receipt.json` remain unchanged.

## Contract

- Execution receipt fields bind candidate/bundle, plan, admission, launch intent, result,
  completion, runner-result, and cleanup digests. Only a recorded successful runner with verified
  cleanup is projectable; unknown, timeout, or cleanup-unknown evidence fails closed.
- Evaluation receipt fields bind candidate/bundle, plan, admission, completion, evaluation digest,
  evaluator binding, report, output-contract validity, and harness invocation. The report is the
  native sanitized report; producer claims are not used as authority.
- Both receipt digests cover canonical JSON with the receipt digest omitted. Unknown fields,
  duplicate/oversized/non-canonical values and digest drift are rejected.
- `MultiFileCandidatePipeline.build_publication_artifact` and `publication_artifact` are read-only
  adapters. They revalidate source, plan, admission, execution, and evaluation evidence before
  constructing `ProducerBundlePublicationArtifact`.
- Feature 153 stores optional `execution-receipt.json` and `evaluation-receipt.json` beside native
  candidate sidecars. Nested entrypoints retain sidecars beside the entrypoint; legacy root
  fixtures remain valid. Manifest descriptors bind every staged byte.

## Non-goals

This feature does not launch producers, change the publication journal schema, alter native
candidate identity or score semantics, or claim that a producer campaign ran.

## Acceptance

1. Receipt DTOs round-trip canonically and reject status, cleanup, schema, unknown-field, and digest
   tampering.
2. A real provider-free pipeline candidate with verified cleanup yields both receipts and a
   publication artifact without execution/evaluation replay.
3. Unknown cleanup cannot produce an execution receipt.
4. Feature 153 stages and recovers root and nested source layouts while preserving native sidecars.
5. Focused tests, Ruff, compileall, and existing publication/recovery regressions pass.
