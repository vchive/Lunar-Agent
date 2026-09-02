# Feature Specification: Verified Retry Feedback

**Feature Branch**: `011-verified-retry-feedback`  
**Created**: 2026-09-02  
**Status**: Draft

## Goal

Make bounded retries useful for long-running local work by carrying the previous attempt's
structured verification outcome into the next attempt prompt. Lunar-Agent should close the
solve→evaluate→correct loop without allowing a runtime to mutate a plan, relax acceptance, or see
unbounded/private failure data.

## User Scenarios & Testing

### User Story 1 — Correct a failed acceptance check (Priority: P1)

As a local owner, I want a retried task to know which acceptance rule failed so the next attempt can
fix the artifact instead of repeating the same output.

**Independent Test**: A fixture evaluator rejects the first result for a missing artifact and a
fixture runtime succeeds only when the second prompt contains bounded verification feedback.

### User Story 2 — Recover from a runtime failure safely (Priority: P1)

As a parent Agent, I want a runtime retry to receive a generic recovery instruction while raw
errors remain in the existing ledger and are not copied into model prompts or new artifacts.

**Independent Test**: The first runtime invocation raises a credential-shaped/configuration error;
the second invocation receives only a generic runtime-failure marker and the persisted task error
remains inspectable.

### User Story 3 — Preserve plan and attempt auditability (Priority: P1)

As a reviewer, I want each retry prompt to show the attempt number and evidence source so I can
explain why the agent changed course, while the original prompt and evaluation artifacts remain
immutable.

**Independent Test**: Prompt artifacts for attempt 1 and attempt 2 are distinct; the second contains
feedback metadata, and no plan revision or acceptance contract changes.

### User Story 4 — Keep parent-Agent JSON stable (Priority: P2)

As Codex, Hermes, OpenClaw, or another parent Agent, I want retry feedback to be visible through
the existing task prompt/evaluation artifacts without requiring a new service or callback API.

**Independent Test**: Existing run/resume/status JSON contracts and Feature 001–010 fixtures remain
unchanged; only additive event metadata may be introduced.

## Requirements

- **FR-1101**: When a task is retried after a failed evaluation, its next prompt MUST include a
  bounded feedback section derived from the latest failed `task_evaluated` event.
- **FR-1102**: Feedback MUST contain only controlled fields: attempt number, evaluation status,
  failed acceptance rule names, bounded evaluator evidence, and a generic correction instruction.
  It MUST NOT copy prompts, result text, artifact contents, credentials, or raw runtime errors.
- **FR-1103**: When a task retries after a runtime/tool/factory failure with no failed evaluation,
  its next prompt MUST include a generic `runtime_failure` feedback marker and correction guidance;
  the raw error remains only in the task/attempt ledger records.
- **FR-1104**: Feedback MUST be capped at 8 KiB and at most 16 evidence/rule entries. Oversized or
  malformed persisted evidence MUST be ignored or reduced deterministically, never fail prompt
  construction.
- **FR-1105**: The original task prompt MUST remain unchanged in SQLite and remain the first section
  of every retry prompt. Attempt-specific feedback is written only to that attempt's prompt artifact.
- **FR-1106**: Feedback MUST NOT change the plan revision, task acceptance, budget, retry count, or
  runtime adapter contract. A retry still follows the existing `retry_task` and `claim_task` flow.
- **FR-1107**: Concurrent workers MUST build feedback from their own task/event history and MUST NOT
  read another task's evaluation or attempt output.
- **FR-1108**: Existing single-worker and isolated-worker behavior, cancellation, recovery, and CLI
  JSON fields MUST be preserved. No remote queue, service endpoint, or mandatory external Agent
  dependency may be added.

## Success Criteria

- **SC-1101**: Failed acceptance fixtures succeed on a later attempt when the runtime requires the
  feedback section, with both attempts and evaluations durably indexed.
- **SC-1102**: Runtime-failure fixtures receive only generic feedback; credential-like raw errors do
  not appear in retry prompt artifacts or model request payloads.
- **SC-1103**: Prompt feedback is deterministic, bounded, and isolated for at least 100 repeated
  retries and parallel tasks.
- **SC-1104**: Existing tests plus new retry-feedback and CLI regression tests pass with no change to
  default one-shot behavior.
- **SC-1105**: Ruff, Python 3.11+ compilation, and the local quickstart pass.

## Non-Goals

- Automatic plan mutation, acceptance weakening, or budget expansion.
- Model-generated replanning or a new evaluator service.
- Persisting a second copy of raw runtime output or error text.
