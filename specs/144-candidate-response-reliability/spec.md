# Feature 144: Candidate response protocol and failure diagnostics

**Created**: 2026-09-21
**Status**: Implemented and verified offline; continuation of Features 110/136/140/141

## Problem and scope

Feature 139 ended with two failed generation receipts (`worker_failed`, then
`malformed_candidate`), no accepted candidate and primary/joint 0/1. Its audit records prose and
Markdown around JSON and object values where experiment arrays were required. This does not
prove a unique model failure cause. Current bundle guidance describes those arrays ambiguously,
and the general AgentLoop system prompt asks for a final summary while bundle generation asks
for JSON. Runtime failure phases are discarded at the receipt boundary; three existing reason
aliases can also be rejected by that boundary instead of retaining the actual failure.

Continue the existing architecture with a small product SDD. Make the existing bundle response
contract explicit for each invocation and preserve bounded failure observations. Do not change
the parser, infer success from scratch files, repair historical responses, add retries, increase
budgets, add provider-specific APIs, or launch a real campaign in this feature.

## Acceptance stories

1. A native bundle generation request declares `lunar-evolution-bundle-generation-v1`. A supporting
   AgentLoop receives invocation-local system guidance that the final answer is only the strict
   bundle JSON. Its generic summary instruction cannot override this requirement. Model tools,
   request count and budget enforcement stay unchanged. Subsequent ordinary requests do not
   inherit the protocol, including when session history or a custom system prompt is used.
2. The generation prompt contains a parser-valid minimal bundle example and an optional full
   experiment example. `change_tags` is a nonempty array of unique strings; `target_metrics` is
   a nonempty array of `{metric, direction}` objects. An omitted experiment is allowed. Examples
   demonstrate shape, not a solution or claimed score; complete source and task constraints
   remain necessary. Large-context fallback retains the same response instructions.
3. Strict parser rejection of prose, fences, duplicate keys, invalid arrays, incomplete source,
   unsafe paths and forged metadata remains unchanged. A rejected response cannot create a
   completed receipt or enter execution/scoring. Valid runtime budget counts survive parser
   failure instead of becoming unknown merely because the result was not passed to projection.
4. A failed invocation produces one durable failed receipt with a fixed reason and, where
   observed, an allowlisted phase and typed model failure cause. Unknown exceptions retain
   `worker_failed`; no arbitrary exception text, URL, response, source or secret is persisted in
   these fields. Timeout, cancellation, tool failure and budget rejection remain failures.
5. Existing transient `timeout`, `tool_failed`, `empty_response` aliases normalize to the
   established canonical receipt reasons. Historical canonical schema-1 payloads without new
   optional fields and their event IDs stay unchanged. Read-only inspection must reject a
   mutated noncanonical retained event, unbound identity, unknown fields or illegal causes.

## Compatibility and limits

`AgentRequest.response_protocol` is optional and accepts only the known bundle protocol or None.
Serialize it only when set. RuntimeAgentAdapter passes it only to a runtime explicitly declaring
the keyword; legacy runtimes and command adapters still receive the explicit user prompt. No
protocol is inferred from arbitrary prompt text, roles or candidate budget presence. Single-file,
general tasks, isolated preparation, provider-neutral adapters and parser authority stay intact.

Receipt schema 1 gains optional bounded diagnostic fields, not a new candidate identity or
success condition. Only failed/unknown receipts retain optional `phase` / `failure_cause`; completed receipts
keep their original canonical field set and reject failure causes. Transient completed response
phase remains nonpersistent. Allowed phases are model_turn/tool/tool_batch/response/run; model
causes reuse the nine fixed MODEL_FAILURE_REASONS values, never arbitrary strings.
Only repository-owned typed evidence supplies model causes; unrecognized
evidence is not reclassified by prose. Source/hash binding and existing budget arithmetic remain
authoritative. Feature 131/134/139 inventories and measured results are immutable.

Offline acceptance establishes correct instructions and evidence flow, not a measured improvement
in model reliability. A later real test needs fresh registration and fixed product/model/budgets.
Feature 142 Phase C and Feature 143 T009 remain separate scopes.
