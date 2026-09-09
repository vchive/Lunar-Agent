# Plan: Fixed-Budget Independent Measurement

1. Freeze the campaign manifest and identity hashes, explicitly excluding the prior exploratory GLM
   pilot from the denominator.
2. Prepare two isolated, non-overwriting attempt directories using the existing single-case runner.
3. Execute each slot exactly once with unchanged model, prompt, tools, and budget; retain failures.
4. Audit request, public projection, receipts, diagnostics, harness boundaries, source hashes, and
   slot status without reading or persisting credentials or raw process output.
5. Derive a denominator-aware summary: planned, started, subject receipt, harness started/completed,
   scored, valid, failed, unresolved, and usage-known counts. Keep unknown values null.
6. Record the result and update HANDOFF; do not infer model or framework quality from this two-slot
   sample and do not calculate a baseline delta.

## Complexity tracking

No new dependency, service, adapter, runner schema, or product code is introduced. The protocol is
deliberately separate from comparative trials because no matching GLM per-run baseline exists.
