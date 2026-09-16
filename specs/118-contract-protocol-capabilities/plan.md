# Implementation plan

Keep framing local to conversational intake. Validate the original bounded response first, unwrap
only the exact documented transport fence, then strictly decode and run the existing envelope
and schema validators. Runtime invocation and fallback policies do not change.

Extend ConstraintSpec with an optional verification_scope. Omit it when absent so historical
contract bytes/digests round-trip unchanged. Validate explicit values and include the declaration
in compiler shape/prompt guidance. Reuse the existing contract digest binding throughout bundles.

Add a typed evaluator capability error with only validated IDs/scopes, and a pure preflight helper.
Invoke it before compile/load side effects for both bundle modes: their synthetic probes can test
only declared input/output evidence. Keep full coverage rules for every admitted hard constraint.
Do not infer scope from descriptions, verification strength or result_fields.

Persist capability diagnostics through existing preparation start/failure events, with a fixed
category and bounded shape. Revalidate observations on status reads, preserve cancellation and
terminal precedence, and render a concise explanation in text status. No schema migration or
new retry workflow. Legacy observations retain their previous exact shape.

Alternatives rejected: permissive JSON repair/retries; filtering partial constraints; pretending
file hashes/counts establish execution behavior; adding a broad source sandbox in this change.
Tests cover positive framed/raw paths, negative framing/JSON, explicit versus legacy scope,
no-call preflight, persisted CLI diagnostics, and normal/resumed delivery. Run the 112 quickstart
and full regression after implementation freezes. No constitution exceptions or dependencies.
