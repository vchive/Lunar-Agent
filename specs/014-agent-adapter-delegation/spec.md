# Feature Specification: Agent Adapter and Role Delegation

**Feature Branch**: `014-agent-adapter-delegation`
**Created**: 2026-09-02
**Status**: Implemented
**Input**: Give Lunar-Agent a runtime-neutral Agent Adapter and Role Registry so Hermes, OpenCode,
Codex wrappers, OpenClaw, and local commands can act as explicit sub-agents while Lunar-Agent
remains the local control-plane authority.

## Context and scope

Lunar-Agent already has a generic Runtime boundary and native evolution strategies, but it does not
yet model an external Agent as a first-class role-bearing worker. This feature adds that missing
seam without making any external Agent, package, service, or global configuration a dependency.
An adapter is explicitly registered by the caller, selected by role/capability requirements, and
invoked inside a run-scoped workspace. SQLite and the workspace remain the source of truth.

## User Scenarios & Testing

### User Story 1 - Register and select a local sub-agent (Priority: P1)

As a local owner or parent Agent, I want to register explicit Agent adapters with roles and
capabilities so that Lunar-Agent can choose a suitable worker without discovering machine-global
Agent installations.

**Why this priority**: Without a stable adapter/selection contract, Hermes, OpenCode, and other
workers cannot be substituted safely or tested independently.

**Independent Test**: Register two deterministic adapters, request a role and capability set, and
verify that the deterministic selector chooses the preferred compatible adapter and rejects an
unsatisfied request before invoking any worker.

**Acceptance Scenarios**:

1. **Given** two explicitly registered adapters with overlapping capabilities, **When** a caller
   requests a preferred adapter that satisfies the role, **Then** that adapter is selected.
2. **Given** no adapter satisfies the required capabilities, **When** selection is requested,
   **Then** a bounded error is returned and no adapter is invoked.

### User Story 2 - Delegate a durable task to a sub-agent (Priority: P1)

As a local user, I want Lunar-Agent to delegate a task to a selected sub-agent while retaining
workspace, timeout, cancellation, retry, and artifact authority so a worker cannot silently settle
the run.

**Why this priority**: Delegation is the core control-plane value and must preserve existing run
semantics rather than becoming an untracked subprocess shortcut.

**Independent Test**: Execute a task through a fixture adapter, inspect the run workspace and ledger,
and verify that the adapter result is stored as an artifact, evaluated by the controller, and that
failure/cancellation leaves an auditable terminal state.

**Acceptance Scenarios**:

1. **Given** a selected adapter and a ready task, **When** the controller delegates the task,
   **Then** the adapter receives a bounded request containing role, prompt, run ID, task ID, and
   workspace, and the result is recorded in SQLite and the workspace.
2. **Given** an adapter times out or returns an invalid result, **When** delegation settles,
   **Then** the task is failed closed, the raw unbounded output is not copied into the ledger, and
   prior artifacts remain intact.

### User Story 3 - Invoke external CLI Agents through a portable protocol (Priority: P1)

As a parent Agent or script, I want to use an explicit OpenCode, OpenClaw, Codex wrapper, or other
CLI command as a sub-agent through one bounded JSON protocol without installing a specific Agent
runtime in Lunar-Agent.

**Why this priority**: The project must interoperate with several Agent ecosystems while keeping
the base installation standalone and local-first.

**Independent Test**: Run a fake executable that consumes one request JSON object and emits one
bounded result JSON object; verify successful import, malformed output rejection, timeout handling,
and absence of PATH/global discovery.

**Acceptance Scenarios**:

1. **Given** an explicit absolute executable and a valid request, **When** the command completes,
   **Then** its structured result is normalized to the shared AgentResult and its declared artifacts
   are copied only from the run workspace.
2. **Given** a relative, missing, timed-out, or malformed command, **When** invocation is attempted,
   **Then** it fails before accepting a result and exposes only bounded error evidence.

### User Story 4 - Preserve parent-Agent and direct CLI usage (Priority: P2)

As a caller such as Codex, Hermes, or OpenClaw, I want to invoke the same adapter boundary directly
or through Lunar-Agent's JSON CLI and receive stable role, adapter, status, and artifact metadata.

**Why this priority**: Interoperability is valuable only if direct and nested invocation produce the
same durable evidence and machine-readable response.

**Independent Test**: Invoke the adapter library and CLI with the same fixture command and compare
their normalized result fields and workspace artifacts.

**Acceptance Scenarios**:

1. **Given** a JSON CLI delegation request, **When** the command completes, **Then** stdout contains
   one bounded JSON result with run ID, adapter name, role, status, and artifact paths.
2. **Given** a detached delegation, **When** the caller later resumes the run, **Then** the same
   adapter selection and request contract are recovered without requiring a persistent parent session.

## Edge Cases

- Duplicate adapter names, empty roles, unsafe capability strings, and oversized metadata are
  rejected at registration time.
- A preferred adapter that lacks one required capability is not selected as a fallback.
- A worker attempts to write outside the run workspace or returns an absolute artifact path; the
  result is rejected and no external file is indexed.
- A worker exits successfully with empty or malformed stdout; the task fails closed.
- Cancellation races with a late worker result; the run remains cancelled and the late result is
  recorded only as discarded evidence.
- A command exists but is not executable, or a command relies on PATH lookup; invocation is
  rejected before process creation.

## Requirements

### Functional Requirements

- **FR-1401**: The system MUST expose a runtime-neutral `AgentAdapter` contract with explicit name,
  roles, capabilities, bounded request/result types, cancellation, and process information.
- **FR-1402**: The system MUST provide an explicit `AgentRegistry` that rejects duplicate names and
  selects only registered adapters satisfying every requested role/capability; selection MUST be
  deterministic and MUST NOT inspect PATH, user home directories, or remote services.
- **FR-1403**: The system MUST preserve the existing `Runtime` contract through a built-in adapter so
  current mock, OpenAI-compatible, and subprocess runtimes remain usable without migration.
- **FR-1404**: The system MUST provide a bounded CLI subprocess adapter that accepts one JSON request
  on stdin and returns one JSON object or bounded text result on stdout using an explicit executable
  argument list.
- **FR-1405**: The controller MUST retain SQLite run/task/attempt authority when delegating to an
  adapter; an adapter result alone MUST NOT settle a run as successful.
- **FR-1406**: Adapter requests MUST include run ID, task ID, role, prompt, workspace, required
  capabilities, and a bounded timeout; secrets and unbounded transcripts MUST be excluded.
- **FR-1407**: Adapter results MUST normalize text, declared relative artifact paths, adapter/role
  identity, and bounded metadata; artifacts MUST be confined to the run workspace and hashed before
  indexing.
- **FR-1408**: Timeout, cancellation, malformed output, unsafe paths, non-zero exit, and missing
  capability matches MUST fail closed with bounded errors and preserve prior evidence.
- **FR-1409**: Existing `run`, `resume`, `plan`, `status --json`, and evolution commands MUST remain
  backward compatible; role/adapter metadata is additive.
- **FR-1410**: The implementation MUST use only standard-library dependencies and MUST document how
  OpenCode, OpenClaw, Codex wrappers, and Hermes can be supplied as explicit adapters without being
  required installations.

## Key Entities

- **AgentRequest**: Immutable bounded delegation input containing run/task identity, role, prompt,
  capabilities, workspace, and timeout.
- **AgentResult**: Immutable normalized worker output containing text, adapter/role identity,
  relative artifacts, metadata, and optional bounded error.
- **AgentAdapter**: Explicit worker implementation with declared roles/capabilities and lifecycle
  controls.
- **AgentRegistry**: Caller-owned set of named adapters and deterministic selection policy.
- **DelegationRecord**: Durable controller event/artifact projection linking a task attempt to an
  adapter request and normalized result.

## Success Criteria

### Measurable Outcomes

- **SC-1401**: A deterministic registry selects the same adapter for 100 repeated requests with the
  same inputs and never invokes an incompatible adapter.
- **SC-1402**: A successful delegated fixture task produces a normalized JSON result and at least
  one hashed workspace artifact visible through `status --json` and `events --json`.
- **SC-1403**: Relative/missing/non-executable commands, malformed output, timeout, unsafe paths,
  and cancellation all fail closed in focused tests without modifying prior valid artifacts.
- **SC-1404**: Existing test coverage remains green and legacy CLI payloads remain parseable after
  adapter registration and delegation support are added.
- **SC-1405**: A parent process can invoke a delegated task using one JSON request/response exchange
  and recover the same run from a durable run ID after the parent exits.

## Assumptions

- The caller explicitly registers adapters or supplies a command; automatic Agent discovery is out
  of scope.
- Existing Runtime implementations remain valid and can be wrapped without changing their public
  behavior.
- A CLI worker can obey the local JSON stdin/stdout protocol and writes declared artifacts below the
  supplied workspace.
- The local owner trusts explicitly launched worker processes, while path, output, timeout, and
  secret boundaries remain enforced by Lunar-Agent.
- Dynamic remote Agent-to-Agent messaging, billing, queues, and multi-user service concerns remain
  out of scope for this feature.
