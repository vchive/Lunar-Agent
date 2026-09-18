# Feature Specification: Candidate-stage explicit tool budget and completion diagnostics

**Created**: 2026-09-18
**Status**: Implemented and offline-validated
**Input**: Feature 134 postrun diagnosis, Feature 135 runtime budget visibility, and the
current native candidate-generation path.

## Problem

Feature 134 reached candidate generation but all three generation invocations stopped at the
registered `max_steps=4` ceiling. The loop correctly rejected each whole tool batch, but the
candidate boundary collapsed the typed runtime failure into a generic worker/candidate failure.
There was no candidate-specific budget authority separate from the surrounding request and
preparation budgets, and no bounded public distinction between step exhaustion, tool failure,
timeout, an empty final response, and a malformed candidate. Scratch files created before the
rejected batch were not candidates, but the existing outcome did not make that completion boundary
explicit.

Feature 135 now gives ordinary unprofiled loops request-local remaining-step and remaining-time
advice. That visibility is useful but does not select or bind a candidate budget, and it does not
make an incomplete generation a completed candidate. This feature adds the candidate-stage
contract without reopening or interpreting the Feature 134 attempt.

## User scenarios

### US1 - Run one candidate under an explicit, bounded budget (P1)

An evolution invocation needs a tool-step allowance selected for that candidate generation. The
allowance is independent from preparation request/wall budgets, the candidate model wall timeout,
the campaign request ledger, and candidate execution limits. It is fixed before the adapter is
called and cannot be increased by a model response or by a later failure path.

### US2 - Know why candidate generation stopped (P1)

The controller and offline report need a safe, bounded diagnostic that distinguishes whole-batch
tool-step rejection, tool execution failure, timeout, cancellation, an empty final response, a
malformed candidate response, and a completed candidate. Counts and remaining budget are local
observations; provider completion, token use, quality, and candidate correctness are never inferred.

### US3 - Treat completion as an explicit authority boundary (P1)

Generation is complete only after the agent returns nonempty text with no tool calls and the native
candidate parser accepts it as a `CandidateDraft` (including bundle parsing where applicable).
Files written during an unfinished session, a model success claim, or a successful tool round do
not establish a candidate.

## Requirements

### Candidate budget and authority

- **FR-001**: Each candidate-generation invocation receives one positive, finite, bounded
  tool-step budget selected by the owning evolution configuration. The value is explicit in the
  generation path and is independent from preparation request/wall budgets, ordinary request
  timeout, campaign wall/request/token limits, and candidate execution budgets.
- **FR-002**: The effective budget is fixed before the adapter call and is authority-bound to the
  generation task identity, candidate invocation ordinal, generation/iteration, and request
  identity. A model response, workspace file, or untrusted result metadata cannot change it.
  The budget identity and effective value are available to the runtime observer and candidate
  diagnostic; any durable generation event that records the invocation must bind to that identity.
- **FR-003**: The runtime receives the effective candidate budget as its `max_steps` authority.
  Existing whole-batch admission remains atomic: if accepted steps plus a returned batch exceed
  the allowance, reject the complete batch before assistant/transcript append, tool execution,
  artifact publication, or memory mutation.
- **FR-004**: Candidate requests retain the existing bounded wall timeout and monotonic timeout
  admission. The candidate budget does not imply a token/cost budget or a larger wall deadline.
  Remaining-step/time advice may be included in the existing request-copy-only
  `lunar_runtime_budget` envelope, with a stage/scope value that identifies candidate generation.

### Completion and diagnostics

- **FR-005**: Define a stable bounded diagnostic projection for every candidate-generation
  invocation. It contains `schema_version`, budget identity, stage, outcome, effective maximum
  steps, `tool_steps_used`, remaining steps, attempted tool calls when known, and bounded
  elapsed/timeout observations when available. Null means unknown; it must not be represented as
  zero.
- **FR-006**: The diagnostic outcome vocabulary distinguishes at least:
  `completed`, `tool_step_limit_reached`, `tool_execution_failed`, `timed_out`, `cancelled`,
  `empty_final_response`, and `malformed_candidate`. A provider error or unsafe local exception
  may use a bounded `worker_failed` category only when it cannot be classified more precisely.
  The projection must not parse arbitrary exception prose, expose prompts/generated source, or
  infer remote provider work, usage, or quality.
- **FR-007**: `completed` is emitted only after a nonempty tool-free response has been parsed into
  a valid `CandidateDraft`. A response containing tool calls, an empty response, malformed JSON,
  missing source, invalid metadata/experiment, or invalid bundle shape is not complete.
- **FR-008**: A rejected whole tool batch produces exactly one step-limit diagnostic/event for the
  invocation, preserves `AgentStepLimitReached` evidence and existing event compatibility, and
  performs no fitting-prefix execution, repair, retry, second request, hidden budget extension,
  or candidate publication.
- **FR-009**: Tool execution failure, timeout, cancellation, empty final response, and malformed
  candidate are reported at their actual boundary. A later parser failure cannot be relabeled as
  a runtime timeout, and a runtime step-limit failure cannot be relabeled as malformed candidate.
- **FR-010**: Diagnostic emission is bounded, redacted, and side-effect safe. It may be sent to the
  existing evolution observer and returned through the candidate-generation failure boundary, but
  it must not add private prompt/model text, credentials, arbitrary exception bodies, or candidate
  source to durable public state.

### Preservation and measurement boundaries

- **FR-011**: Existing single-file and bundle candidate APIs, deterministic generators, evaluator
  execution, independent scoring, parent delivery, resume checks, and profiled runtime accounting
  remain compatible unless they explicitly opt into the candidate budget field.
- **FR-012**: Feature 134's registration, manifest, postrun diagnosis/report/results/audit,
  evidence inventory, denominator, and failure interpretation remain byte-for-byte unchanged.
  This feature uses offline fixtures only; it does not rerun, resume, append to, or repair that
  campaign.
- **FR-013**: No new real campaign budget, provider setting, model profile, retry policy, or
  historical effect claim is authorized by this specification. A later real campaign requires a
  fresh registration, pushed product and unique slot after this feature is implemented and
  independently reviewed.

## Acceptance criteria

1. A fixture candidate generation receives one fixed, positive candidate tool budget and a distinct
   budget identity; changing preparation or campaign settings cannot silently change it.
2. A `4 + 2` returned tool batch at a four-step allowance yields `tool_step_limit_reached` with
   `tool_steps_used=4`, `attempted_tool_calls=2`, and `tool_steps_remaining=0`; no tool in the
   rejected batch runs and no transcript/history/artifact/memory side effect is created.
3. A fixture with successful tools followed by a nonempty tool-free candidate response yields
   `completed` only after parser acceptance and retains accurate counts.
4. Fixtures independently exercise tool failure, timeout, cancellation, empty final response,
   malformed candidate JSON/shape, and a generic bounded worker failure. Each outcome remains
   distinguishable and does not fabricate usage or quality.
5. Repeated requests expose one current candidate budget advisory per request; source messages,
   replayable transcript, and persisted candidate state contain no stale advisory copy.
6. No automatic retry, response repair, fitting-prefix execution, extra request, budget increase,
   candidate execution, evaluator call, or parent delivery occurs after an incomplete generation.
7. Existing profiled-loop enforcement, `run_isolated`, deterministic generators, and historical
   tests pass. Feature 134 retained files and hashes remain unchanged.

## Non-goals and limits

This feature does not select the correct budget for a future provider, guarantee that a model will
finish a candidate, make tool calls cheaper, predict token/cost usage, cancel remote work, change
the model prompt, raise the shared runtime ceiling globally, execute a fitting prefix, or infer
candidate validity from scratch files. It does not add a durable database migration unless the
existing generation event boundary requires one to bind the already-authoritative identity.
