# Feature 079: Typed Model Failure Evidence

**Status**: Complete; independently reviewed and integrated after the Feature078 evidence seal.

## Problem and P1 story

Feature 076's postal attempt ended after entering Build with a version 1 subject diagnostic:
`stage=model`, `code=model_failed`, `http_status=null`, 24 observed successful model responses and
31 tool-result events. It has no accepted subject receipt or independent harness score. The
available diagnostic does not distinguish a transport failure from rejected response content.
The historical failure cause cannot be recovered by introducing new instrumentation afterwards.

The current runtime knows which request or response-validation boundary fails, but its bounded
subject diagnostic preserves only selected exception types. The observer follows at most eight
`__cause__` links and retains `HTTPError.code` or a directly chained `TimeoutError`. A null HTTP
status means that no such status was retained; it does not establish that no response arrived,
that the request did not time out, or that the provider caused the failure.

As an operator of a new subject invocation, I need a fixed, credential-free observation of the
failed model request so I can distinguish transport and response-validation failures without
changing result authority or turning an incomplete attempt into a scored result.

## Acceptance criteria

1. Add repository-owned typed evidence at the existing `OpenAICompatibleRuntime.complete`
   failure boundaries. Its only fields are a fixed `reason` and a nullable integer
   `response_status`. Reasons are exactly `http_error`, `transport_timeout`, `transport_error`,
   `invalid_json`, `invalid_response_shape`, `empty_response`, `invalid_tool_calls`,
   `invalid_model_identity`, and `invalid_usage`. These describe observed local boundaries,
   not root causes, provider fault or retry eligibility.
2. The response status is copied only from an observed `HTTPError.code` or `response.getcode()`
   value with exact integer type in 100..599; otherwise it is null. Never coerce, clamp, parse
   status text, read headers for diagnostic data, or infer a status from an exception message.
   A response read failure can retain a previously observed status; a protocol failure after
   a 200 response can therefore report `response_status=200` without changing top-level
   `http_status` semantics.
3. Extend the score-free sidecar with version 3 and exactly one additional top-level key,
   `model_failure`. That object has exactly `reason` and `response_status`. Version 3 is emitted
   only for a model-stage failure carrying valid exact repository-owned error and evidence
   types. Keep all existing top-level fields, counters, bounds and classifications unchanged.
   In particular, retain the existing `code` and `http_status` result of legacy classification;
   a timeout wrapped only in `URLError.reason` may gain `transport_timeout` evidence while its
   old top-level `code` remains `model_failed`.
4. Accept existing version 1 and 2 diagnostics unchanged. Unknown model exceptions, invalid typed
   evidence and unavailable evidence fall back safely to the existing classification, without
   exception text or arbitrary attributes supplying evidence. An unsupported observed status is
   projected to null under criterion 2; an invalid status inside forged typed evidence discards
   that entire evidence and preserves a version 1 diagnostic. Version 3
   validates only `stage=model`, `code` in `model_failed`/`model_http_failed`/`timeout`, and the
   reason/status consistency rules stated in the plan. It cannot contain a budget object.
5. Classify rejected top-level JSON values, `choices`/choice/`message` structural failures and
   malformed tool calls at their existing failure boundary. Preserve every currently accepted
   provider response shape, fallback, missing-field default, tool ID default, content conversion,
   usage rule and rejection outcome. For example, malformed `choices` with an accepted fallback
   response must still succeed. A valid empty content structure remains `empty_response`; do not
   reject a previously accepted response merely to make classification simpler.
6. Derive transport detail only from exception types at the known transport boundary. If a
   `URLError.reason` is itself an exception, bounded type inspection may classify a timeout;
   string reasons and arbitrary object attributes provide no diagnostic evidence. Preserve
   existing exception chaining and the RuntimeExecutionError-compatible failure boundary.
7. Diagnostic bytes remain at most 4096 bytes and retain request digest, mode, run and round
   binding, safe bounded reads, exclusive publication, stale-evidence rejection and collection
   behavior. Never serialize raw exceptions, class names from arbitrary errors, endpoint URLs,
   request/response bodies, headers, prompts, model output, tool arguments, paths, credentials,
   usage estimates, scores or arbitrary metadata. Diagnostic failure never masks subject failure.
8. The agent loop, parser acceptance rules, shared ledger, deadlines, prompts, tool permissions,
   checkpoint/resume policy, success receipts and native normal/deep/staged scoring authority
   remain unchanged. No retry, replacement, fallback output, new model call, provider probe,
   candidate promotion or harness dispatch is added. Failed complete-request usage stays unknown;
   observed status and failure reason are never billing evidence.
9. Failure-first tests use actual loopback HTTP requests through the standard-library runtime
   plus deterministic exception fixtures and native subject/trial boundaries. They must prove
   the reason/status projection, preservation of accepted response forms, no secret leakage,
   safe malformed-evidence fallback and no harness/score after subject failure.
10. All work stays in the isolated `codex/model-failure-evidence` worktree based on `fba6ab8`.
    Root reviewed this spec and authorized isolated implementation before Feature 078 launch.
    Feature 078 does not contain this change; its registered source/scripts/tests/inputs remain
    frozen while its measurement runs. Integration is root-owned after its evidence seal. Feature 076 and 078
    records are neither rewritten nor retrospectively classified by this feature.

## Non-goals and limits

No response content logging, request timing instrumentation, transport retry policy, OS sandbox,
provider protocol migration, usage recovery or additional response validation is introduced.
The observed reason does not prove why a network or provider failed, whether a saved file is a
valid candidate, or whether a different policy would have succeeded. An absent optional sidecar
continues to be acceptable for external subjects and conveys no diagnosis.
