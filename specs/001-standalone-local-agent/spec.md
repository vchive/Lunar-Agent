# Feature Specification: Standalone Local Famou Agent

**Feature Branch**: `001-standalone-local-agent`

**Created**: 2026-09-01

**Status**: Complete

**Input**: User description: "Create a standalone local Famou Agent that does not depend on a
machine-wide Hermes environment and can resume long-running work."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run and Resume a Local Task (Priority: P1)

As a single user, I can submit a goal from a local CLI and later resume it after the terminal or
controller process stops, without losing the task state or generated files.

**Why this priority**: Durable execution is the minimum value of a local Famou Agent. Without it,
the agent is only a chat wrapper and cannot handle long-running work.

**Independent Test**: Start a run with the deterministic test runtime, interrupt it after state is
persisted, invoke `resume` with the run ID, and observe a terminal success plus a readable artifact.

**Acceptance Scenarios**:

1. **Given** an initialized local data directory, **When** the user runs a goal, **Then** the CLI
   prints a run ID and persists the goal, task, and event history in SQLite.
2. **Given** a run with a task in progress, **When** the process is interrupted and the user invokes
   `resume`, **Then** the controller recovers the task and continues without duplicating its final
   result.
3. **Given** a successful run, **When** the user requests status, **Then** the CLI reports the run,
   task state, attempt count, and artifact locations.

### User Story 2 - Execute and Verify a Multi-Step Plan (Priority: P2)

As a user, I can execute a plan composed of dependent tasks, keep outputs as local artifacts, and
require a verifier to confirm each task before the run is considered complete.

**Why this priority**: Planning and independent verification turn durable execution into a Famou
workflow instead of a single opaque model call.

**Independent Test**: Provide a two-task plan where the second task depends on the first, run the
mock runtime, and verify that the second task receives the first artifact and the evaluator controls
the final status.

**Acceptance Scenarios**:

1. **Given** a plan with dependencies, **When** a ready task succeeds, **Then** dependent tasks are
   scheduled only after its verified artifact is available.
2. **Given** an evaluator rejection, **When** the controller processes the result, **Then** the task
   is marked failed or returned for replanning and the run is not reported as successful.

#### Plan input contract

The local CLI accepts a JSON plan with a run goal and an acyclic task graph. A minimal plan is:

```json
{
  "goal": "prepare a report",
  "tasks": [
    {"id": "research", "title": "Research", "prompt": "Collect facts"},
    {"id": "write", "title": "Write", "prompt": "Draft the report", "depends_on": ["research"]}
  ]
}
```

`run --plan plan.json` validates unique task IDs, dependency references, and cycles before any
runtime is invoked. Tasks without dependencies enter the ready queue; dependent tasks remain
waiting until every dependency is verified successful. A task receives the relative paths and
bounded text previews of verified dependency artifacts in its runtime prompt.

### User Story 3 - Use a Self-Contained Runtime Boundary (Priority: P3)

As a user, I can install the repository into an isolated environment and choose a bundled test
runtime or an explicitly configured external runtime without having Hermes installed globally.

**Why this priority**: Runtime independence prevents hidden machine-specific behavior and makes the
repository reproducible for other users.

**Independent Test**: Create a clean virtual environment, install the project, run the mock runtime,
and confirm that no `.hermes` directory, global executable, network, or model credential is needed.

**Acceptance Scenarios**:

1. **Given** a clean Python environment, **When** the documented bootstrap command is run, **Then**
   the CLI starts and the mock runtime completes a task.
2. **Given** no Hermes installation, **When** the user selects the mock runtime, **Then** the run
   remains fully functional and reports no missing external runtime.

### User Story 4 - Call a Configured Model Directly (Priority: P2)

As a local user, I can point Lunar-Agent at an OpenAI-compatible endpoint (including a local model
server) and execute tasks without installing Hermes, OpenCode, or Codex.

The endpoint and model are explicit configuration. The adapter sends one non-streaming chat request
per task, parses the candidate text, and never persists the API key in SQLite, events, artifacts, or
controller logs. A missing endpoint, malformed response, HTTP error, or timeout becomes a structured
attempt failure subject to the normal retry policy.

### Edge Cases

- A process may stop after claiming a task but before writing its result; recovery must mark the
  attempt uncertain and retry it safely.
- A completion event may be delivered more than once; applying it repeatedly must not duplicate
  attempts, artifacts, or state transitions.
- A runtime may exceed its timeout or return an empty result; the controller must record a failure
  and apply the configured retry policy.
- An artifact path must remain inside the run workspace; path traversal attempts must be rejected.
- A missing or malformed runtime command must produce an actionable error without corrupting the run.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST provide an isolated bootstrap path that installs declared runtime
  dependencies and does not require a machine-wide Hermes, OpenCode, or Codex installation.
- **FR-002**: The system MUST create a durable run record, root task, workspace, and append-only event
  history before invoking an Agent Runtime.
- **FR-003**: The system MUST expose CLI commands to run a goal, resume a run, inspect status, inspect
  events, and cancel a run.
- **FR-004**: The controller MUST recover tasks left in a running state after interruption and MUST
  avoid duplicating a terminal result when resuming.
- **FR-005**: The system MUST store large outputs and logs as files under a run-scoped artifact
  directory and record their metadata in the durable store.
- **FR-006**: The system MUST expose a Runtime Adapter contract and include a deterministic mock
  runtime for tests and offline smoke runs.
- **FR-007**: The controller MUST support a configured subprocess runtime without importing or
  discovering a global Hermes environment.
- **FR-008**: Task success MUST be decided by structured evaluator output when an evaluator is present;
  a Worker claim alone MUST NOT be sufficient.
- **FR-009**: Retries, timeouts, cancellation, approvals, and runtime errors MUST be represented in
  structured events and visible through status inspection.
- **FR-010**: The first release MUST remain local and single-user; public networking, multi-tenancy,
  distributed queues, and remote service deployment are out of scope.
- **FR-011**: Every operational CLI command MUST support a machine-readable `--json` mode in which
  stdout contains one JSON value and diagnostics are written to stderr.
- **FR-012**: The `run` command MUST accept `-` as the goal argument and read the goal from stdin so
  a parent Agent can invoke Lunar-Agent without shell-escaping long prompts.
- **FR-013**: The `run --detach --json` command MUST persist the run and return its durable run ID
  before task execution begins; the child controller MUST write its output under the run workspace.
- **FR-014**: A plan MUST be persisted before execution, and its dependency graph MUST be acyclic;
  malformed plans MUST fail without creating a partially initialized run.
- **FR-015**: Detached execution MUST persist its controller process ID/group ID. `cancel` MUST
  request termination of that process group and reject late runtime results after the run is
  cancelled.
- **FR-016**: Each evaluator decision MUST be persisted as a structured JSON audit file and an
  event; a rejected decision MUST prevent a successful run settlement.
- **FR-017**: The repository MUST include an `openai-compatible` Runtime Adapter implemented with
  the Python standard library. It MUST accept an explicit endpoint and model and support local or
  remote OpenAI-compatible servers without discovering Hermes state.
- **FR-018**: API credentials MUST be read only from explicit CLI/environment configuration, sent
  only as an HTTP authorization header, and redacted from all persisted diagnostics.
- **FR-019**: The HTTP adapter MUST parse a non-streaming OpenAI chat response and reject malformed,
  empty, non-2xx, or timed-out responses as `RuntimeExecutionError`.

### Key Entities

- **Run**: A user's long-running goal, its lifecycle status, workspace, budget, and timestamps.
- **Task**: A unit of work belonging to a run, with an objective, dependencies, lifecycle state,
  attempts, and acceptance criteria.
- **Attempt**: One invocation of a Runtime Adapter for a task, including runtime identity, timing,
  heartbeat, retry count, and outcome.
- **Event**: An immutable, idempotently applied record of a state transition or operational fact.
- **Artifact**: A file or structured output produced by a task, addressed by a run-scoped path and
  content hash.
- **Approval**: A pending or resolved authorization for an action that exceeds the active policy.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a clean machine with Python 3.11+, a user can bootstrap the project and complete a
  mock-runtime run in under 2 minutes without a global Agent Runtime installation.
- **SC-002**: After an induced controller interruption, 100% of recovery tests restore the run to a
  correct terminal state without duplicate terminal events or artifacts.
- **SC-003**: A status command returns the current run and task state in under 1 second for a local
  ledger containing at least 10,000 events.
- **SC-004**: Every successful mock-runtime run has at least one artifact with a recorded path and
  content hash that can be opened independently of model context.
- **SC-005**: The P1 workflow can be demonstrated using no network, model credentials, or user-global
  Hermes files.
- **SC-006**: A parent Agent can start a run and inspect its terminal state by parsing one JSON line
  from `run --json` and one JSON value from `status --json`, without importing Lunar-Agent Python
  modules.
- **SC-007**: A parent Agent can start a detached mock run and receive a valid run ID in under one
  second, then observe the run transition through `status --json` without keeping the parent process
  attached.
- **SC-008**: A valid two-task plan executes in dependency order, and the dependent task can locate
  the predecessor's verified result artifact from its prompt/workspace.
- **SC-009**: A local test HTTP endpoint can complete a run through `openai-compatible` with no
  Hermes/OpenCode/Codex installation or third-party runtime library.

## Assumptions

- Users have Python 3.11 or newer and can create a virtual environment; the project will document a
  `uv` path and a standard-library fallback.
- Real model execution is supplied by an explicitly configured Runtime Adapter; the initial release
  does not bundle model weights.
- A local user is not an adversarial tenant; the safety boundary is intended to prevent accidental
  side effects and credential leakage.
- A background launch agent and graphical UI are later enhancements; `resume` is the initial recovery
  contract.
