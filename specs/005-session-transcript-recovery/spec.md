# Feature Specification: Session Transcript Recovery

**Feature Branch**: `005-session-transcript-recovery`

**Created**: 2026-09-01

**Status**: Implementing

**Input**: Close the long-running-session gap in the Hermes-inspired local agent.

## Goal

Persist a bounded, redacted conversation transcript under the run workspace so a resumed task can
continue its previous model/tool context across attempts. This is local session continuity, not a
WebAgent phase or a remote conversation service.

## User Scenarios & Testing

### User Story 1 - Resume Conversation Context (Priority: P1)

As a user, I can resume a task after a runtime failure or `ask_user` pause and the next model turn
can see the recent prior conversation and tool results.

**Independent Test**: A fixture model produces a tool call, the first attempt fails/pauses, and a
second attempt receives the persisted assistant/tool messages before the continuation prompt.

### User Story 2 - Keep History Bounded and Local (Priority: P1)

As a local user, I can inspect the transcript file, with per-message and total-size limits, without
any transcript being sent unless session history is explicitly enabled.

**Independent Test**: Oversized messages are truncated, the transcript is capped to recent entries,
and a configured API key does not appear on disk.

### User Story 3 - Preserve Scheduler Semantics (Priority: P2)

As a user, I can use transcript recovery with plans, retries, detached runs, memory, cancellation,
and artifact hashing without changing the controller's task ownership.

**Independent Test**: A retrying task has one stable transcript artifact and existing dependency
ordering remains unchanged.

## Functional Requirements

- **FR-501**: The session runtime MUST support an explicit session-history opt-in and a stable
  run/task transcript path.
- **FR-502**: The transcript MUST be JSONL, bounded per message and in total, and retain only recent
  valid messages when compaction is required.
- **FR-503**: Transcript content MUST redact the configured API key and MUST remain below the run
  workspace; it MUST not be written to SQLite events or controller logs.
- **FR-504**: On a retry/resume with history enabled, the runtime MUST load the bounded transcript
  before appending the continuation prompt, while avoiding duplicate system messages.
- **FR-505**: Controller MUST index the transcript as one run artifact when it exists, including when
  a session pauses for input.
- **FR-506**: Detached `run`/`answer` MUST propagate the session-history setting without putting an
  API key in argv.
- **FR-507**: Existing behavior remains unchanged when session history is not enabled.

## Non-Goals

- Server-side conversation storage, vector retrieval, or automatic transcript summarization by a
  second model.
- Silent history injection into model requests.
- Replacing the DAG scheduler or adding WebAgent lifecycle phases.

## Success Criteria

- **SC-501**: A resumed fixture conversation receives prior tool context and completes without a
  duplicate system message.
- **SC-502**: Transcript files remain within configured bounds and contain no configured credential.
- **SC-503**: All previous memory, ask_user, scheduler, and runtime tests remain green.
