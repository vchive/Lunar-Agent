# Feature Specification: Unprofiled Agent-loop budget visibility and completion diagnostics

**Created**: 2026-09-18  
**Status**: Implemented and verified
**Input**: Feature 134 postrun diagnosis and the current `AgentLoopRuntime` contract.

## Problem

`AgentLoopRuntime` always has a finite tool-step ceiling, and a bounded wall timeout may be
provided even when no `ModelProfile` is configured. Today `_budget_messages` returns the original
message list unchanged when no `UsageLedger` exists, so the model cannot see remaining tool calls
or remaining wall time in that mode. This made the Feature 134 candidate failure opaque: the whole
tool batch was rejected at `max_steps`, but the model had no request-local indication of the
remaining allowance. The existing `agent_step_limit_reached` event also carries only coarse counts,
which is insufficient for a typed caller to distinguish an over-limit batch from another runtime
failure.

## Scope

Update the repository-owned agent loop so each normal model request receives a fresh advisory
snapshot, whether or not a profile is configured.

* `tool_steps_remaining` is always present and equals
  `max(0, max_steps - tool_steps)`, including when a `tool_steps_offset` is supplied.
* `remaining_seconds` is present when the invocation has a finite timeout and is otherwise `null`.
  It is calculated from the same monotonic deadline used for admission and is rounded only for the
  request-facing snapshot.
* `command_timeout_seconds` remains the effective bounded command window when execution is
  enabled and a finite wall timeout exists; it is `null` when execution is unavailable or no outer
  timeout is configured.
* Profile-only token and cost fields remain `null` for unprofiled loops. Profiled snapshots retain
  their current fields, guidance, and request semantics byte-for-byte at the contract level.

The snapshot uses the existing `schema_version: "1"` `lunar_runtime_budget` envelope and the
existing guidance. It is appended to a copied system message for the current provider request.
Neither the in-memory replayable `messages` list nor a `SessionTranscript` may contain the
advisory. Repeated requests must receive newly computed values; an earlier snapshot must not be
accumulated or replayed.

When a model response proposes more tool calls than the remaining allowance, preserve whole-batch
admission. Before appending the assistant response to history or executing any tool, emit
`agent_step_limit_reached` and raise a repository-owned typed runtime failure carrying bounded
structured evidence:

* `max_steps`;
* `tool_steps` already accepted before the response;
* `attempted_tool_calls` in the rejected response; and
* `tool_steps_remaining` at admission.

The exception message remains compatible with `agent loop exceeded max steps (N)`. The event keeps
its existing type and fields and adds the same validated integer evidence. No rejected assistant
message, tool call, tool result, artifact, memory write or transcript entry may be produced by the
batch. The provider request that returned the batch is not retried or repaired.

An empty tool-free response remains a failure. A successful final result still requires a nonempty
text response with zero tool calls; a response containing tool calls is subject to the same atomic
admission check even if it also contains text.

## Acceptance criteria

1. An unprofiled loop with `max_steps=K` receives a budget envelope on every normal `run` request,
   with accurate `tool_steps_remaining` before each turn and `null` profile spend fields.
2. A finite `run(..., timeout=T)` exposes a positive, decreasing `remaining_seconds` snapshot;
   an unbounded run exposes `null` without inventing a wall budget. Existing timeout admission and
   tool execution deadlines remain authoritative.
3. Advisory injection copies only the request messages. Provider-visible snapshots never mutate
   replayable messages, durable transcript bytes, or persisted invocation state, and the next
   request contains exactly one current envelope.
4. A configured `ModelProfile` produces the existing advisory shape and ledger enforcement with no
   behavior or telemetry regression. `run_isolated` remains tool-free and does not gain a session
   advisory.
5. A tool batch whose size exceeds the remaining allowance produces one typed step-limit failure
   and one structured event, with no assistant-history append, tool execution, artifact, memory or
   transcript side effect. Admission remains whole-batch and does not execute a fitting prefix.
6. A tool-free nonempty final response succeeds even when the advisory reports zero remaining tool
   steps; an empty final response still fails. No automatic retry or extra model request is added.
7. Existing subject diagnostic classification, controller recovery, profile accounting and Feature
   134 historical evidence remain unchanged. No persistent schema, CLI flag, model profile or
   evaluator identity is introduced by this feature.

## Non-goals and limits

This feature does not raise `max_steps`, change tool execution, predict provider token usage,
guarantee candidate completion, add a token/cost ceiling to unprofiled runs, or infer remote
provider cancellation. A remaining-time advisory is informational; the existing monotonic timeout
check can still reject a request after the snapshot is created. The feature does not rerun the
Feature 134 campaign or change its denominator, report, diagnosis or evidence.
