# Feature Specification: Artifact Acceptance Contracts

**Feature Branch**: `008-artifact-acceptance-contracts`
**Created**: 2026-09-02
**Status**: Implemented

## Goal

Make a task's acceptance criteria an independently executable local contract rather than a
worker's natural-language claim. Contracts inspect only the candidate result and files beneath the
current attempt workspace, return bounded structured evidence, and remain compatible with the
existing string and `{ "contains": "..." }` plan syntax.

## User Scenarios & Testing

### User Story 1 - Verify Observable Output Artifacts (Priority: P1)

As a local owner or parent Agent, I want a plan task to declare files, text, and JSON structure
that must exist before its output is accepted, so a non-empty model response alone cannot complete
an artifact-producing task.

**Why this priority**: Independent verification is the core effect-layer gap after durable plans,
routing, and budgets.

**Independent Test**: Run a mock task with a contract requiring a generated JSON artifact and
observe a passing `task_evaluated` event only when the file parses and has required keys.

**Acceptance Scenarios**:

1. **Given** an attempt workspace with `report.json`, **When** a task requires that file to parse
   and expose `summary` and `sources`, **Then** the task succeeds and stores rule-level evidence.
2. **Given** the same contract and malformed or absent output, **When** evaluation runs, **Then**
   the task fails, its dependent tasks remain blocked, and `deliver` rejects the run.
3. **Given** a legacy string or `{ "contains": "..." }` acceptance value, **When** it is used,
   **Then** it retains its existing result-text behavior.

### User Story 2 - Keep Verification Local and Bounded (Priority: P1)

As a local owner, I want malformed, oversized, secret-bearing, or escaping contracts rejected
before work is created so verification does not become an execution or data-exfiltration channel.

**Why this priority**: The verifier handles untrusted plan data and must preserve the project's
bounded-autonomy guarantees.

**Independent Test**: Submit invalid contracts through both `PlanTask` and legacy `start` task
input; neither may create a run or read a file outside the task workspace.

**Acceptance Scenarios**:

1. **Given** a path containing `..`, an absolute path, or a symlink that resolves outside the
   workspace, **When** evaluation or validation occurs, **Then** it fails closed with no external
   file content in evidence.
2. **Given** a contract above the rule/depth/text/file-byte limits or containing credential-like
   text, **When** it is parsed, **Then** it is rejected before a task attempt is claimed.

### User Story 3 - Let Parent Agents Audit the Decision (Priority: P2)

As a parent Agent, I want each task's latest structured evaluation available through existing JSON
status and event outputs, so I can decide whether to patch/replan without re-reading arbitrary
logs.

**Independent Test**: Run a contract-bearing task and inspect `status --json` and `events --json`;
both expose a bounded contract tree with pass/fail observations.

## Edge Cases

- `all` evaluates every child so evidence explains all failed requirements; `any` evaluates every
  child but passes when at least one child passes.
- A JSON file may parse successfully but fail the required-key check; keys are top-level only in
  this version.
- Binary, invalid UTF-8, unreadable, directory, or oversized text artifacts fail the relevant
  rule without leaking file content.
- Existing SQLite rows serialize object acceptance rules as JSON text and continue to load.
- A plan patch/replan may carry the same validated contract; completed task definitions remain
  immutable under the existing Feature 006 rules.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-801**: Support local declarative result-text, artifact-exists, artifact-text-contains,
  JSON-parse, JSON-required-top-level-keys, `all`, and bounded `any` rules.
- **FR-802**: Keep non-empty string and `{ "contains": string }` acceptance syntax backward
  compatible as result-text containment.
- **FR-803**: Reject unknown rule shapes, unsafe paths, invalid types, credential-like content,
  excessive nesting/rules, and excessive inspected bytes before durable work is created.
- **FR-804**: Confine every file inspection to the current attempt workspace and never execute
  shell commands, model calls, plugins, or network requests while evaluating.
- **FR-805**: Emit a structured, bounded evaluation tree alongside the existing human-readable
  evidence and persist it in `task_evaluated` events and `evaluation.json`.
- **FR-806**: Expose the latest evaluation summary per task in `status --json` without changing
  the Runtime Adapter contract.
- **FR-807**: Preserve Feature 001–007 CLI, plan, patch/replan, recovery, delivery, and evaluator
  injection behavior.
- **FR-808**: Remain single-user and local-first; add no HTTP/SSE endpoint, worker queue,
  multi-tenancy, cloud sandbox, or mandatory Hermes/OpenCode/Codex dependency.

## Key Entities

- **Acceptance Contract**: A bounded declarative rule tree stored with one plan task.
- **Acceptance Evaluator**: The local interpreter for a validated contract and one attempt
  workspace.
- **Rule Evidence**: A pass/fail tree of rule kinds and safe metadata, persisted with an evaluation
  decision.

## Success Criteria *(mandatory)*

- **SC-801**: All supported leaf and composite-rule fixtures produce deterministic decisions and
  evidence without a model or network dependency.
- **SC-802**: 100% of traversal, malformed JSON, oversized, secret-bearing, and unsupported-rule
  fixtures fail closed before task execution or external reads.
- **SC-803**: A failed acceptance contract prevents delivery in every integration fixture while
  prior hashed artifacts remain inspectable.
- **SC-804**: `status --json` and `events --json` expose evaluation details below 20 KiB per task
  on bounded contracts.
- **SC-805**: The full existing test suite, lint, compilation, and a CLI quickstart continue to
  pass on Python 3.11+.

## Assumptions

- Version 1 verifies only the current task attempt workspace; cross-task requirements remain
  explicit scheduler dependencies and verified artifact handoff.
- JSON key checks are top-level to keep the schema legible and evaluation predictable.
- Semantic scoring, visual validation, browser testing, and model-as-judge evaluation are later
  optional adapters, not part of this safe baseline.
