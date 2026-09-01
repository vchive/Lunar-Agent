# Feature Specification: Hermes-Inspired Local Agent Core

**Feature Branch**: `003-hermes-inspired-local-agent`

**Created**: 2026-09-01

**Status**: Implementing

**Input**: Product direction clarified by the owner: adapt the useful Hermes execution model for a
standalone local agent, retain long-running memory and existing tools, and add orchestration without
turning Lunar-Agent into a WebAgent service or copying WebAgent's stage machine.

## Direction

Lunar-Agent is a local Hermes-inspired agent, not a WebAgent reimplementation and not a launcher for
the user's installed Hermes. The repository owns the agent loop, tool policy, durable run ledger,
memory, and recovery. Hermes may remain an optional external subprocess adapter, but no code path
discovers or imports a machine-wide Hermes installation.

```text
CLI / parent Agent
        |
        v
LocalController (durable scheduler + recovery)
        |  one or more persisted tasks, optional dependencies
        v
HermesSessionRuntime (continuous model/tool conversation)
        |-- file + command tools (workspace confined)
        |-- explicit memory tools (SQLite, local)
        `-- OpenAI-compatible model adapter
```

The controller provides orchestration by scheduling a validated task graph, retrying failed
attempts, sharing verified artifacts, and resuming after interruption. It does not force every goal
through WebAgent-specific intake, clarification, verification, or delivery phases. A session can
ask the user for more information through the existing parent-Agent/CLI contract in a later
increment.

## User Scenarios & Testing

### User Story 1 - Continue a Long-Running Session (Priority: P1)

As a user, I can resume a run and let the local agent continue with durable task state, files, and
memory instead of starting a fresh opaque completion.

**Independent Test**: An agent stores a progress note, the process is resumed for the same run, and
the memory tool can recall that note without duplicating the task or leaking it outside the local
state directory.

### User Story 2 - Orchestrate Multiple Tasks (Priority: P1)

As a user, I can provide a small dependency graph and have the controller schedule ready tasks,
retry failures, pass verified artifact paths to dependents, and settle the run durably.

**Independent Test**: A two-task plan executes in dependency order; a failed predecessor blocks its
dependent; recovery does not duplicate terminal artifacts.

### User Story 3 - Use Hermes-Style Tools Without Hermes Installed (Priority: P1)

As a user, I can inspect and modify files, optionally execute bounded commands, and use local
memory from a continuous model/tool loop without installing or configuring Hermes globally.

**Independent Test**: A fixture model performs read/write/remember calls followed by a final answer;
all paths stay below the task workspace and command execution is opt-in.

### User Story 4 - Invoke from Another Agent (Priority: P2)

As Codex, OpenClaw, Hermes, or another local agent, I can invoke Lunar-Agent as a CLI/TUI process,
obtain one JSON run handle, and poll status/events while the child continues in the background.

**Independent Test**: `run --detach --json` returns before execution, and `status --json` reports the
same durable run ID and current scheduler state.

## Functional Requirements

- **FR-301**: The repository MUST provide a continuous tool-calling session runtime that is usable
  without a machine-wide Hermes, OpenCode, or Codex installation.
- **FR-302**: The runtime MUST preserve the existing Runtime Adapter `run` contract and support
  structured OpenAI-compatible tool calls through a separate model-turn method.
- **FR-303**: Built-in filesystem tools MUST resolve paths below the active task workspace and
  return bounded UTF-8 output. `run_command` MUST be no-shell and explicitly enabled.
- **FR-304**: The repository MUST provide a local SQLite memory store with global and run-scoped
  entries, bounded lexical recall, and explicit `remember_memory`/`recall_memory` tools.
- **FR-305**: Memory context MUST NOT be silently injected into model requests. A caller MUST opt in
  to memory tools for a run because recalled user data may be sent to a configured endpoint.
- **FR-306**: Memory content MUST be size-limited and API credentials MUST never be written to
  memory, events, artifacts, logs, or process arguments.
- **FR-307**: The durable controller MUST remain the scheduler: it validates dependency graphs,
  dispatches ready tasks, retries according to policy, recovers uncertain attempts, and shares
  verified artifacts with dependent tasks.
- **FR-308**: Detached runs MUST propagate agent-loop, memory, command-policy, endpoint, model, and
  step-limit settings to the child without placing an API key in argv.
- **FR-309**: Existing mock, subprocess, and direct OpenAI-compatible runtimes MUST continue to
  work unchanged when the continuous session mode is not selected.
- **FR-310**: The CLI and JSON output MUST remain stable enough for parent Agents to start, resume,
  cancel, and inspect a run without importing Python modules.

## Non-Goals

- Reproducing Famou WebAgent's Master/Build/Verify/Delivery/Evolution stage machine.
- A hosted service, HTTP/SSE control plane, multi-tenant storage, distributed queue, or UI product.
- Automatic discovery, installation, or mutation of a user's Hermes environment.
- Embeddings/vector search, model training, or mandatory cloud APIs for memory.

## Success Criteria

- **SC-301**: A clean Python 3.11+ environment can run the mock agent without Hermes or network
  access.
- **SC-302**: A local fixture model can complete a multi-turn read/write/memory tool session and
  produce indexed artifacts.
- **SC-303**: Memory recall works after `resume` and remains confined to the configured SQLite home;
  no memory payload is persisted in event logs unless the model explicitly writes it as a tool note.
- **SC-304**: A valid dependency plan executes in order and failed prerequisites block dependents.
- **SC-305**: Detached JSON invocation and status polling remain compatible with parent Agents.
- **SC-306**: All existing regression tests remain green and no test requires external Hermes state.
