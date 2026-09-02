# Feature Specification: Algorithm Problem Contract and Solver/Evaluator Workspace

**Feature Branch**: `012-algorithm-problem-contract`
**Created**: 2026-09-02
**Status**: Draft

## Goal

Give Lunar-Agent a self-contained representation for algorithmic decision and prediction
problems. A validated contract will be the hand-off between conversational intake and later
solver/evaluator roles, while the local workspace keeps input data, candidate programs, independent
evaluation, and business outputs visibly separate. This is the first algorithm layer; it does not
yet execute an evolution strategy.

## Local evidence used

This specification is grounded in the local WebAgent v2.5 materials and source tree:

- `面经/合集/项目二-伐谋WebAgent与Workspace.md` (Clarify → PLAN → Build → independent evaluation);
- `面经/07-伐谋WebAgent对话式决策算法-模拟面试.md` (problem formulation, validity first,
  anytime output);
- `面经/06-伐谋Workspace程序演化算法-模拟面试.md` (program candidates, frozen evaluator,
  archive/population separation);
- `codesets/baidu/acg-fm/webagent/agent_configs/opencode-v2.5-base/agents/data-discovery.md`,
  `data-cleaner.md`, and `famou-evaluate.md` (role boundaries and workspace conventions).

## User Scenarios & Testing

### User Story 1 — Register a complete algorithm problem (Priority: P1)

As a local user or parent Agent, I want to turn a clarified optimization/prediction request into a
machine-checkable problem contract so a solver cannot silently invent business constraints.

**Why this priority**: Without a stable problem contract, all later solver, evaluator, and
evolution work can optimize the wrong objective.

**Independent Test**: Load a valid scheduling, routing, or forecasting contract and inspect the
canonical JSON; load contracts with an unsafe input path, an unproven hard constraint, or an invalid
objective direction and verify they are rejected before a run is created.

**Acceptance Scenarios**:

1. **Given** a contract with a supported problem type, objective, input schema, provenance-backed
   constraints, and deliverables, **When** it is loaded into a plan, **Then** the canonical contract
   is retained in the plan revision and can be read without a runtime call.
2. **Given** a hard constraint with no `user_confirmed`, `data_observed`, or
   `explicit_assumption` source, **When** the contract is validated, **Then** creation fails closed
   with no partial run or plan revision.

### User Story 2 — Isolate solver and evaluator work (Priority: P1)

As a solver/evaluator implementer, I want a predictable local workspace with separate raw data,
processed data, candidate code, evaluator code, and business output directories so roles can work
without reading each other's private context or overwriting source inputs.

**Why this priority**: WebAgent's strongest reliability boundary is role and context separation;
the local version must make that boundary concrete before adding program evolution.

**Independent Test**: Start a run with an algorithm contract and verify the required directories,
path confinement, and a manifest artifact; verify a raw input remains unchanged when a processed
file is written.

**Acceptance Scenarios**:

1. **Given** a valid contract, **When** the run is created, **Then** the workspace contains
   `data/raw`, `data/processed`, `solve`, `evaluate`, `output`, and `evolution` boundaries and no
   path points outside the run workspace.
2. **Given** a path containing `..`, an absolute path, or a symlink escape, **When** a workspace
   artifact is registered, **Then** the operation fails closed and the ledger remains consistent.

### User Story 3 — Define an independent validity-first evaluation result (Priority: P1)

As a parent Agent, I want a structured evaluator result that distinguishes feasibility from quality
so an attractive but invalid candidate can never be delivered as a valid solution.

**Why this priority**: Local acceptance checks currently verify files and text, but algorithm tasks
need independently recomputed constraints and a frozen score contract before evolution can be safe.

**Independent Test**: Validate evaluation reports for valid/invalid candidates and assert that
`validity=0` forces `combined_score=0`, while malformed scores, negative combined scores, or missing
error evidence are rejected.

**Acceptance Scenarios**:

1. **Given** a candidate violating one hard constraint, **When** its evaluator report is loaded,
   **Then** `validity` is `0`, `combined_score` is `0`, and the violating constraint is present in
   bounded `error_info`.
2. **Given** a valid candidate with quality metrics, **When** its report is loaded, **Then** the
   report preserves non-negative combined score, metric direction, and detailed scores without
   trusting natural-language claims as proof.

### User Story 4 — Choose an evolution strategy without coupling the runtime (Priority: P2)

As a local owner, I want the problem contract to declare whether later improvement should use the
lightweight conversation-style loop or an explicit population search, while keeping both strategies
behind the same candidate/evaluator boundary.

**Why this priority**: WebAgent's loop is a good default for interactive budgets, while OpenEvolve /
Workspace-style population search is useful for long local runs. Recording the choice now prevents
future strategy code from leaking into the runtime adapter.

**Independent Test**: Load contracts with omitted, `loop`, and `population` strategy settings and
verify canonical defaults/validation; unknown strategies are rejected without executing work.

### User Story 5 — Preserve local and parent-Agent interoperability (Priority: P2)

As a local owner, I want to run Lunar-Agent directly without a parent Agent; as Codex, Hermes,
OpenClaw, or another local parent Agent, I want to invoke the same binary as a CLI/JSON child
process and continue a durable run later without installing a machine-wide runtime or a service.

**Independent Test**: Invoke existing `plan` and `status --json` commands with a contract and
verify additive metadata; run a legacy plan without a contract and verify unchanged behavior; invoke
the detached form, exit the caller, and use the returned run ID with `resume`.

**Acceptance Scenarios**:

1. **Given** a contract-bearing plan and no parent Agent, **When** a user runs the local CLI, **Then**
   the run completes (or pauses for input) using only repository-owned state and the configured
   runtime adapter.
2. **Given** a parent Agent launches `lunar-agent ... --json` as a child process, **When** it reads
   stdout, **Then** it receives a machine-readable run/status payload and no user-global Hermes,
   OpenCode, or Codex state is required.
3. **Given** a parent Agent launches a detached run, **When** the parent exits and later calls
   `resume <run-id>`, **Then** the same SQLite ledger, plan revision, workspace, and contract
   metadata are used to continue the run.

## Edge Cases

- A contract may contain no test/holdout data yet; it records the omission rather than inventing a
  hidden dataset.
- A minimization objective is accepted but its evaluator-facing combined score must still be
  non-negative and higher-is-better after normalization.
- Empty or duplicate constraint IDs, duplicate input paths, unsupported problem types, unknown
  provenance values, and unknown evolution strategies are rejected atomically.
- A contract is valid when no optional evolution settings are present; no candidate archive is
  created until a later feature requests it.
- Replanning may change an unstarted contract, but a completed task's contract and acceptance remain
  immutable under existing plan revision rules.
- Existing plans and runs without an algorithm contract continue to use the current generic route,
  evaluator, artifact layout, and JSON fields.

## Requirements

- **FR-1201**: The system MUST accept an optional algorithm problem contract attached to a versioned
  plan, with a supported problem type: `scheduling`, `routing`, `packing`, `assignment`,
  `forecasting`, `network_flow`, or `continuous`.
- **FR-1202**: The contract MUST record a bounded problem statement, input file references and
  schema, decision variables or prediction target, primary objective direction, hard constraints,
  soft constraints, success criteria, deliverables, and explicit assumptions.
- **FR-1203**: Every hard/soft constraint MUST carry a provenance source from
  `user_confirmed`, `data_observed`, or `explicit_assumption`; unsourced constraints MUST be
  rejected before durable work is created.
- **FR-1204**: Contract paths MUST be portable relative paths below the run workspace; credentials,
  absolute paths, traversal components, symlink escapes, and unbounded text MUST be rejected.
- **FR-1205**: A contract-bearing run MUST materialize separate `data/raw`, `data/processed`,
  `solve`, `evaluate`, `output`, and `evolution` workspace boundaries plus a machine-readable
  manifest that identifies the contract revision.
- **FR-1206**: The system MUST define a structured evaluation report with `validity` in `{0,1}`,
  non-negative higher-is-better `combined_score`, optional non-negative `quality`, detailed scores
  with direction metadata, and bounded `error_info`; `validity=0` MUST imply
  `combined_score=0`.
- **FR-1207**: The evaluator contract MUST distinguish format/execution errors from candidate
  constraint violations and MUST support independent constraint evidence without requiring a
  solver to self-report its score.
- **FR-1208**: A contract MAY select `loop` (default) or `population` evolution, but strategy
  execution is out of scope for this increment and both strategies MUST share the contract/evaluator
  boundary defined here.
- **FR-1209**: Contract and workspace metadata MUST be visible through existing plan/status JSON
  additively; legacy plans MUST remain readable and executable.
- **FR-1210**: Solver and evaluator roles MUST remain runtime-neutral and callable through the existing
  local Runtime Adapter; this feature MUST NOT add HTTP/SSE, queues, billing, multi-tenancy, or a
  mandatory Hermes/OpenCode/Codex installation.
- **FR-1211**: Lunar-Agent MUST support three equivalent local invocation forms: direct standalone
  CLI execution, parent-Agent child-process execution through bounded stdin/stdout JSON, and
  detached execution followed by durable `resume`; none may require a parent Agent or a
  machine-global provider installation.

## Key Entities

- **AlgorithmProblemContract**: Immutable problem formulation, provenance-backed constraints, and
  selected evolution strategy.
- **ConstraintSpec**: One hard or soft rule with source and verification mode.
- **ObjectiveSpec**: Primary objective direction and optional normalized metrics.
- **AlgorithmWorkspaceManifest**: Run-relative directory and contract revision metadata.
- **EvaluationReport**: Validity-first structured result emitted by an independent evaluator.

## Success Criteria

- **SC-1201**: 100% of valid contract fixtures for all seven supported problem types round-trip to
  canonical JSON without changing objective, provenance, path fields, or strategy selection.
- **SC-1202**: 100% of invalid path, secret, missing-provenance, duplicate-ID, unknown-strategy,
  and score-invariant fixtures fail before a run/plan row is committed.
- **SC-1203**: Every contract-bearing run has all six workspace boundaries and a manifest whose
  contract digest matches the stored plan revision.
- **SC-1204**: 100% of invalid evaluation fixtures enforce `validity=0` and
  `combined_score=0`; valid reports preserve bounded metric evidence.
- **SC-1205**: All pre-012 tests and a legacy plan quickstart pass unchanged, and parent-Agent JSON
  remains parseable with only additive fields.

## Assumptions

- Clarification and domain-specific field discovery happen before a contract is submitted; this
  feature validates and stores the result rather than conducting a conversation itself.
- The local owner supplies or authorizes input files; this feature does not copy arbitrary files
  into the workspace automatically.
- A parent Agent is an optional caller, not a runtime dependency. The same run ledger and JSON
  contract are used whether the process is launched by a person, a script, or another Agent.
- A later Solver/Evaluator Agent feature will implement actual data discovery, executable evaluator
  loading, and candidate program execution on top of these contracts.
- A later evolution feature will implement `loop` first and `population` second behind one strategy
  interface; `evolution/` is reserved but intentionally empty in this increment.
