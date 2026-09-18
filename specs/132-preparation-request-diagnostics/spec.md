# Feature 132: Observable evaluator generation request failures

Feature 131's evaluator compiler model request timed out, but ordinary solve/status only retained
`runtime_error`. The runtime already observes a bounded reason, optional HTTP status, local phase,
elapsed time, deadline and last transport milestone. Preserve that safe evidence through compiler
and auditor preparation failures so users can distinguish request failure from local evaluator
execution failure without consulting private campaign sidecars.

## Acceptance

1. Project only the direct, concrete ModelRequestFailure and its concrete typed evidence. Never
   parse exception prose, traverse causes or infer provider queueing, token usage or remote work.
2. Store optional request_failure in preparation schema 3; its fixed schema 1 shape contains reason,
   response_status, request_observation and transport_observation (nullable observations). Strictly
   validate enum, integer, field and phase/reason relationships. Bad optional typed observations
   drop to less detail; bad persisted details drop to nonrecoverable coarse validation failure.
3. Bind restored details to one exact preceding start, the parent, attempt, runtime category and
   compiler/auditor stage. Cancellation, terminal parent, input drift and verified preparation win.
   Schema 1 runtime and schema 2 local failures remain compatible. Diagnostics grant no reuse.
4. Solve/resume/answer JSON and text/JSON status expose validated details. Timeout guidance says
   this is a model request timeout and that remote completion/usage are unknown. Explicit recovery
   may issue new requests; no automatic retries or larger deadlines are introduced.
5. Preserve durable parent running state and existing effective failed state: Feature 116
   intentionally keeps accepted contracts recoverable. No database migration or terminal-state
   rewrite. Status reads cause no requests, artifact changes or event writes.
6. Offline tests cover compiler/auditor failure, bounded local transport, tampered observations,
   interruption, precedence, explicit recovery and terminal idempotency. Frozen measurements and
   private captured responses are not modified or executed. No real model call in this feature.
