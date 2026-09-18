# Plan

Add a small evaluator_request_diagnostics module that validates a fixed score-free projection of
the existing ModelRequestFailure evidence. Reuse runtime constants and the transport normalizer;
keep request bytes, timing, prompts and model parameter defaults unchanged. Local runtime errors
without trustworthy model evidence retain schema 1. A malformed optional observation never masks
the original exception or changes its classification.

EvaluatorBundleRuntimeError carries a copied projection obtained at each direct compiler/auditor
runtime boundary. Automatic preparation records schema 3 only after existing continuation/input
checks permit its runtime failure classification. Reads require exact keys and a unique matching
start; invalid detail fails closed to the existing safe coarse failure. The schema 3 payload adds
only request_failure to schema 1. Its schema 1 value has exactly reason, response_status,
request_observation, transport_observation and schema_version. Request observation uses phase,
elapsed_ms, request_timeout_ms; transport uses the existing three-field protocol.

CLI projects these observations into existing preparation JSON and displays them in text status,
with a fixed timeout hint. Preserve existing durable run enums, effective failed status and explicit
resume; changing running to terminal failed would contradict Feature 116 and prevent recovery.
Future measurement success HTTP status projection remains separate; no frozen result is rewritten.

Alternatives rejected: infer remote activity from wait_response_headers; increase timeouts without
evidence; add streaming/provider options in a diagnostics patch; automatically retry; parse arbitrary
exception strings; make a transient preparation error permanently fail the accepted contract.
No dependencies, migration or constitution exceptions. Offline verification includes targeted
diagnostic/recovery tests, the Feature 112 quickstart, two-stage full regression, Ruff, compileall,
Specify prerequisites, independent review and historical evidence byte checks.
