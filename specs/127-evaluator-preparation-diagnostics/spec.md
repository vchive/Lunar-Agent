# Feature 127: Bounded local evaluator preparation diagnostics

## Problem and outcome

The 125 diagnostic stopped during local evaluator preparation but retained only EvaluatorBundleError.
Static analysis was needed to distinguish the failed audit from response parsing and self-tests.
Record controller-observed local stage, reason and bounded numeric indices before staging cleanup.
Reuse the existing automatic preparation event/status channel; do not retain generated data.

## Acceptance

1. A strict immutable diagnostic represents compiler_response, auditor_response, compiler_preflight
   or auditor_preflight. Response admission has response_invalid (including source/envelope/suite
   checks). Preflight identifies input_format_invalid, output_schema_invalid, file_set_invalid,
   process_failed, report_invalid, evidence_changed, validity_mismatch, constraint_code_missing,
   score_order_mismatch, or a coarse preflight_failed fallback where precision is unavailable.
2. Diagnostic fields are exactly schema_version, stage, reason, probe_index, input_index and
   order_index. Indices are one-based positions in the parsed suite/contract, bounded by existing
   capacity (64 probes/orderings, 32 input files), with null where inapplicable. No raw input,
   output, source, constraint ID, probe name, file path, score, exception prose or credentials.
3. Both candidate/snapshot invocation and compiler/auditor roles report the observed check without
   parsing exception messages. Input admission still checks the whole suite before any harness.
   Failed preparation retains the strict freeze gate, cleanup, call counts and no automatic retry.
4. Typed failures reach direct callers after cleanup and automatic solve persists the diagnostic
   in its existing failed observation as schema 2. Status/CLI expose only validated details bound
   to the same parent, attempt and matched start. Invalid/unknown details degrade to coarse failure
   and never grant recovery. Generic exception prose or arbitrary attributes cannot supply details.
5. Schema 1 observations retain prior behavior. Runtime failures, cancellation precedence, input/
   contract verification, profile publication, frozen loading and terminal recovery remain intact.
   Diagnostic data is advisory and never authority to resume, freeze, score or publish.
6. Fresh offline tests cover each reason, late input failure, both roles/modes, durable observation,
   tampered details, status/CLI, interruption/cancellation and successful recovery. Preserve historical
   measurement artifacts and denominators; do not execute captured responses or call a real model.

## Limits

Reason describes the local failing check, not provider or business root cause. process_failed does
not claim a precise process exit/timeout/output-limit cause where the native helper coalesces them.
Response failure is deliberately coarse across envelope/source checks. Publication/loading failures
outside these four stages retain generic diagnostics. Any next real run requires its own fixed
registration committed and pushed first; old campaign slots remain closed.
