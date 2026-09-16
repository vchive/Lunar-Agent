# Feature 108: Multi-file independent evaluation

## User value

Score the declared results of one successfully recorded multi-file candidate without executing
the candidate again. Preserve exactly the input/output bytes given to the pinned evaluator so
the resulting score can subsequently enter candidate selection and final delivery.

## Acceptance scenarios

1. A candidate with a nested entrypoint and helper produces structured output. An independent
   harness checks its constraints and objective using a retained snapshot, returns a strict
   EvaluationReport, and the candidate's launch counter remains one.
2. Missing or malformed required outputs produce an invalid, zero-score report without launching
   the harness. A failed or incomplete execution record never authorizes evaluation.
3. Declaration, contract, evaluator, completion or source/input identity mismatches fail before
   harness launch. Unsafe nodes, byte changes and observed replacements are rejected.
4. A valid report above 16 KiB is accepted up to the 32 KiB report limit. Unknown fields,
   duplicate JSON keys, nonfinite values, invalid UTF-8 and mismatched evaluator IDs are rejected.
5. Evaluation retains snapshots, request, raw report and a canonical evaluation manifest in a
   new private directory. Inspection binds their bytes read-only; incomplete directories cannot
   be repaired or interpreted as accepted scores. No Store/config initialization is needed.

## Boundaries

Outputs are observed at evaluation time, not proven to be the bytes present at process exit.
Feature 107 records remain unchanged. The source and input declarations and current bytes are
rechecked, and workspace/input roots must match the launch intent. The harness receives only
declared inputs and outputs plus contract/metadata, never candidate source or original paths.

The evaluator fingerprint binds its supplied implementation bytes, argv, explicit environment,
protocol, identity and limits. The host interpreter, dependency closure and external effects are
not authenticated or sandboxed. This local trusted-owner execution boundary does not claim
atomic multi-file observation or protection against malicious same-user concurrent writers.

This feature does not register Candidate/receipt/archive, evolve a population, resume unknown
processes, request attestation, invoke a model/provider/framework or produce benchmark claims.
