# Feature Specification: Master Policy and Plan Contracts

**Feature Branch**: `006-master-policy-plan-contract`

**Created**: 2026-09-02

**Status**: Draft

**Input**: WebAgent branch research and product direction: carry over the useful Master policy,
plan, patch, and replan behavior into the standalone local Lunar-Agent without reproducing the
WebAgent service or fixed stage machine.

## Goal

Give Lunar-Agent a durable control-plane contract for deciding whether to answer directly, ask for
bounded input, execute a plan, patch a plan, replan, or deliver a result. Complex work gains the
auditable structure that made WebAgent effective, while simple questions remain fast and do not
enter an unnecessary workflow. The contract is local, versioned, runtime-neutral, and consumable by
the existing DAG scheduler and parent Agents through JSON.

## User Scenarios & Testing

### User Story 1 - Choose the Smallest Useful Action (Priority: P1)

As a local user, I want a goal to be classified as a direct answer, an input request, or planned
work so that the agent spends orchestration effort only when the goal needs it.

**Why this priority**: Policy selection is the entry point for every later planning and delivery
capability and prevents WebAgent's fixed-stage overhead on simple requests.

**Independent Test**: Submit a short explanatory goal and a multi-step artifact goal; inspect the
JSON decisions and verify that only the latter creates a plan.

**Acceptance Scenarios**:

1. **Given** a self-contained explanatory goal, **When** policy evaluation runs, **Then** it returns
   `action=answer` with a rationale and creates no run or plan.
2. **Given** a goal with multiple observable outputs or dependencies, **When** policy evaluation
   runs, **Then** it returns `action=execute_plan` and a valid versioned plan.
3. **Given** missing information that materially changes the result, **When** policy evaluation
   runs, **Then** it returns `action=ask_user` with at most four bounded questions.

### User Story 2 - Execute an Auditable Versioned Plan (Priority: P1)

As a user or parent Agent, I want the plan's constraints, evidence, tasks, acceptance, and
verification rules persisted with versions so that work can be resumed and reviewed without
reconstructing model context.

**Why this priority**: A durable plan is the bridge between Master reasoning and the existing local
DAG scheduler; it is also the main effect-layer advantage observed in WebAgent v2.5.

**Independent Test**: Create a plan, execute it through the controller, restart, and retrieve the
same plan version, task graph, and decision through the CLI JSON contract.

**Acceptance Scenarios**:

1. **Given** a valid plan, **When** it is attached to a run, **Then** the plan document and
   `execute_plan` decision are stored atomically and the scheduler can execute its tasks.
2. **Given** an invalid plan with duplicate IDs, unknown dependencies, empty prompts, or a cycle,
   **When** it is submitted, **Then** it is rejected before any run, plan, or orphan task is stored.
3. **Given** a completed run, **When** a parent Agent requests status, **Then** the response includes
   the current plan ID/version, decision action, and bounded evidence without secrets.

### User Story 3 - Patch or Replan After New Evidence (Priority: P1)

As a user, I want new facts or failed verification to update the plan without losing its history or
creating duplicate work.

**Why this priority**: WebAgent's patch/replan behavior is essential for long-running tasks where
the first plan is incomplete; it must be explicit and recoverable locally.

**Independent Test**: Apply a valid patch to version 1, reject a stale patch, then create version 2
through replan and verify both versions and reasons remain queryable.

**Acceptance Scenarios**:

1. **Given** plan version 1, **When** a patch references version 1 and valid operations, **Then** a
   new version is persisted with parent version 1 and the scheduler sees the updated DAG.
2. **Given** a patch based on an old version, **When** it is applied after another update, **Then**
   it is rejected with no partial changes.
3. **Given** evidence that invalidates assumptions, **When** replan is requested, **Then** a new
   plan version is created, the prior version remains immutable, and a structured event records the
   reason and evidence.

### User Story 4 - Deliver Verified Results (Priority: P2)

As a user, I want delivery to distinguish verified artifacts from explanations or failed attempts
so that the agent never presents an unverified failure as success.

**Independent Test**: Mark one task invalid and one task valid, request delivery, and verify the
decision is `deliver` only when acceptance and verification pass; otherwise it remains failed or
asks for a replanning action.

**Acceptance Scenarios**:

1. **Given** all required tasks have passing evaluations, **When** delivery is selected, **Then** the
   response lists run-relative artifacts and verification evidence.
2. **Given** a failed or invalid evaluation, **When** delivery is requested, **Then** no successful
   delivery decision is emitted and the failure reason remains visible.

## Edge Cases

- A plan with an empty goal, empty task prompt, duplicate task ID, unknown dependency, self-edge, or
  cycle is rejected atomically.
- A patch operation targeting a missing task or dependency is rejected atomically.
- More than four clarification questions, oversized evidence, or unbounded rationale is rejected or
  bounded before persistence.
- A plan, patch, or decision that contains an API key or credential-like value is redacted/rejected;
  secrets must not enter SQLite, artifacts, events, logs, or process arguments.
- Concurrent patch requests use optimistic version checks; only one matching base version can win.
- A process restart between plan write and task execution must recover the latest committed version
  without duplicating a run or event.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-601**: The controller MUST expose a policy decision model with actions `answer`, `ask_user`,
  `execute_plan`, `patch_plan`, `replan`, and `deliver`, plus bounded rationale and confidence.
- **FR-602**: Simple self-contained goals MUST be answerable without creating a plan or run; complex
  goals MUST be representable as a validated plan document consumed by the existing DAG scheduler.
- **FR-603**: A plan document MUST contain a schema version, stable plan ID, monotonically increasing
  version, optional parent version, goal, hard/soft constraints, objective, evidence, assumptions,
  tasks, acceptance, verification, and delivery metadata.
- **FR-604**: Plan task IDs MUST be unique safe path segments; task prompts MUST be non-empty;
  dependencies MUST resolve to tasks and form an acyclic graph.
- **FR-605**: Plan creation MUST be atomic with run/task creation; invalid input MUST leave no run,
  task, plan, or event rows behind.
- **FR-606**: A plan patch MUST declare a base plan ID/version, reason, evidence, and bounded
  operations; the base version MUST match before any operation is applied.
- **FR-607**: Supported patch operations MUST include add/remove/update task, add/remove dependency,
  update acceptance, and update constraints. Every resulting plan MUST pass all plan validation.
- **FR-608**: Replan MUST create a new immutable version linked to its parent and retain the reason,
  evidence, and prior version for inspection.
- **FR-609**: Policy decisions, plan versions, patches, and replans MUST emit idempotent structured
  events and be available through local CLI JSON without requiring Python imports.
- **FR-610**: `status --json` and a dedicated plan inspection command MUST expose the current plan
  version, decision action, bounded rationale, and run-relative evidence/artifact paths.
- **FR-611**: The controller MUST preserve existing runtime adapter isolation, retries, recovery,
  cancellation, artifact hashing, interactive input, memory opt-in, and transcript behavior.
- **FR-612**: The implementation MUST remain local-first and must not add HTTP/SSE, multi-tenant
  services, remote queues, billing, or a mandatory Hermes/OpenCode/Codex dependency.

### Key Entities

- **PlanDocument**: Immutable, versioned description of goal, constraints, evidence, task DAG,
  acceptance, verification, and delivery metadata.
- **PlanTask**: A scheduler task with stable ID, prompt, dependencies, and acceptance criterion.
- **PolicyDecision**: A bounded action selection with rationale, confidence, questions, and plan
  reference.
- **PlanPatch**: Optimistic-concurrency update against one plan version with typed operations.
- **PlanRevision**: Stored parent/child relationship between immutable plan versions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-601**: At least 95% of self-contained one-step goals return `answer` without plan creation in
  the policy fixture suite.
- **SC-602**: 100% of invalid plan and stale patch fixtures are rejected atomically with zero orphan
  runs, tasks, revisions, or events.
- **SC-603**: A valid three-task plan can be resumed after process restart and reports identical plan
  ID/version and dependency order through JSON status.
- **SC-604**: Every successful delivery response contains at least one hashed run-relative artifact
  and corresponding verification evidence; failed evaluations never produce `deliver` success.
- **SC-605**: Policy and plan inspection responses remain under one second for a run with 10,000
  events and 100 plan revisions on a local workstation.
- **SC-606**: Fixture tests find no configured API key or credential value in plan rows, events,
  artifacts, logs, or detached process arguments.

## Assumptions

- A local controller process remains the sole writer for a run, while SQLite optimistic checks guard
  accidental concurrent parent-Agent requests.
- The existing task DAG validator remains the source of truth for scheduler-safe task dependencies;
  the plan layer adapts to it rather than duplicating execution semantics.
- Policy heuristics may initially be deterministic and injected by a runtime/model later; this
  feature defines the durable contract, not a new planning model.
- Clarification is bounded to four questions per decision and can use the existing `answer` flow.
- The feature is implemented in Python 3.11+ with standard-library storage and CLI interfaces.

