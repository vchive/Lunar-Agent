# Plan

Add a pure evaluator_diagnostics module with an immutable, strictly validated diagnostic and
bounded serialization. Keep no untrusted free text. A typed EvaluatorPreparationError extends the
existing bundle error and preserves established exception messages for compatibility; only its
validated diagnostic is persisted. Instrument native response/preflight boundaries and map lower
process/report/evidence checks by type/control flow, never by exception text. Preserve original
parsers, model prompts, successful return values and frozen file formats.

Automatic solve adds optional local_failure to the existing failed observation, emitting schema 2
only for valid typed local diagnostics. Its stage mirrors the local diagnostic. Readback requires
strict schema/key/value/stage/category/recoverable/parent/attempt validation and a matched start;
malformed optional data falls back to the existing coarse validation failure without exposing it.
Schema 1 remains unchanged. Cancellation overrides optional detail; no local error enables retries.
No database migration or new artifact/sidecar is needed, and there is no constitution exception.

Alternatives rejected: retaining traceback/generated probes leaks unnecessary data; parsing old
messages is brittle; one broad catch claiming a specific cause fabricates certainty; moving checks
or rerunning probes would change execution. Retain a coarse fallback for unclassified local errors.

Write independent tests and use existing automatic solve/status/CLI fixtures, review mappings and
backward compatibility, run focused regression and the 112 quickstart, freeze implementation and
run the two-stage full regression. Recheck historical bytes, document limits, commit and push.
