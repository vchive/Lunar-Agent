# Feature Specification: Interactive Session Recovery

**Feature Branch**: `004-interactive-session-recovery`

**Created**: 2026-09-01

**Status**: Implementing

**Input**: Continue the Hermes-inspired local-agent direction with durable long-running sessions.

Feature 005 adds optional transcript replay; the input protocol here remains the durable boundary
used when a session pauses.

## Goal

Allow a model session to pause when it needs a human or parent-Agent answer, return a machine-readable
`awaiting_input` state, and resume the same durable run/task after `answer`. This is a conversational
capability of the Hermes-inspired runtime, not a WebAgent clarification phase.

## User Scenarios & Testing

### User Story 1 - Ask and Resume (Priority: P1)

As a local user or parent Agent, I can see the question a running session needs, answer it later,
and continue the same run without creating duplicate tasks.

**Independent Test**: A fixture model calls `ask_user`, `run --json` returns `awaiting_input`,
`status --json` exposes the question, and `answer` followed by `resume` reaches success with the
answer included in the next model prompt.

### User Story 2 - Preserve Long-Running Context (Priority: P1)

As a user, I can inspect the persisted question/answer files and events after a process restart.

**Independent Test**: Stop after the request, invoke `answer` in a new process, and verify the same
run ID/task ID and bounded answer artifact are used.

### User Story 3 - Keep the Existing Scheduler (Priority: P2)

As a user, I can still use dependency plans, retries, artifact handoff, and cancellation around an
interactive task.

**Independent Test**: A waiting predecessor blocks dependent tasks; after answering and completing it,
the scheduler makes the dependent ready.

## Functional Requirements

- **FR-401**: The domain MUST represent `awaiting_input` as a durable run status and keep the task
  retryable without creating a new run or task.
- **FR-402**: The continuous session MUST expose an `ask_user` tool with a bounded question and
  optional bounded choices. It MUST stop before the next model request.
- **FR-403**: A question MUST be persisted as a run-scoped JSON artifact and a structured event that
  contains no API credential or unbounded content.
- **FR-404**: `status --json` MUST expose the pending question, run/task IDs, and request artifact
  path. Human status output MUST identify that input is required.
- **FR-405**: `answer <run-id> <text>` (or `-` from stdin) MUST persist a bounded answer artifact,
  transition the same task to ready, and resume it using the selected runtime options.
- **FR-406**: The next task prompt MUST include the bounded answer artifact content. The answer MUST
  not be appended to the original task prompt in the database.
- **FR-407**: A waiting task MUST block dependents; cancellation MUST still cancel the run cleanly.
- **FR-408**: Detached propagation MUST continue to work with agent-loop, memory, endpoint/model,
  and command-policy options.

## Non-Goals

- A WebAgent-style intake/clarify/verify/delivery state machine.
- Streaming UI, remote approvals, or multi-user question routing.
- Unbounded conversation transcripts or automatic memory injection.

## Success Criteria

- **SC-401**: A parent Agent can parse one JSON response, answer the same run, and observe terminal
  success without duplicate task creation.
- **SC-402**: Question and answer artifacts are confined below the run workspace and bounded.
- **SC-403**: Existing non-interactive, memory, scheduler, and recovery tests remain green.
