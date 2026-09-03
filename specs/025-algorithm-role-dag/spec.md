# Feature Specification: Built-in Algorithm Role DAG

**Feature Branch**: `025-algorithm-role-dag`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Make conversational algorithm plans explicit about specialist roles

## Context and scope

Feature 024 compiles a natural-language mission and creates a conservative four-stage plan. This
feature adds a reusable five-role DAG for users who want a stronger algorithm workflow without
installing an external harness. It remains a plan composition over the existing controller,
runtime adapter, artifact store, acceptance evaluator, and SQLite ledger.

The role DAG is opt-in through `solve --role-dag` so existing plans and their task IDs remain
backward compatible. The generated role prompts make authority boundaries explicit: data discovery
may report observations, formulation may not change the contract, solver may propose code, evaluator
must independently test the proposal, and reviewer may only summarize verified evidence.

## User stories and acceptance scenarios

### User Story 1 — Run a specialist algorithm workflow (P1)

As an algorithm owner, I want specialist stages to be visible and ordered so that a long-running
mission has clear handoffs and independent review.

1. **Given** a valid contract and `--role-dag`, **when** `solve` compiles it, **then** the plan has
   exactly `data_discovery → problem_formulator → solver → evaluator → reviewer`.
2. Every stage receives only the validated contract and verified predecessor artifacts through the
   existing scheduler; the evaluator and reviewer cannot mutate contract authority.

### User Story 2 — Preserve local independence and recovery (P1)

1. The role DAG uses the selected repository runtime and no Hermes/OpenCode/Codex discovery.
2. Detached runs, retries, cancellation, answer/resume, artifact hashing, and `status --json`
   retain the same semantics as a four-stage conversational plan.
3. A malformed role configuration fails before any generated task is claimed.

## Functional requirements

- **FR-2501**: Expose `build_algorithm_role_plan(goal, contract)` as a runtime-neutral plan factory.
- **FR-2502**: The role plan MUST contain five unique safe task IDs and one acyclic linear DAG:
  `data_discovery`, `problem_formulator`, `solver`, `evaluator`, `reviewer`.
- **FR-2503**: Role prompts MUST state each role's authority, input/output artifact boundary, and
  prohibition on inventing or relaxing contract constraints.
- **FR-2504**: `solve --role-dag` MUST select the role plan before any generated task executes;
  without it, the Feature 024 four-stage plan remains unchanged.
- **FR-2505**: Role plan creation MUST continue to use `PlanDocument` and
  `AlgorithmProblemContract` validators and the existing same-run promotion transaction.
- **FR-2506**: Existing CLI/library behavior and persisted plan revisions remain backward compatible.

## Success criteria

- **SC-2501**: A mock `solve --role-dag` run creates and executes six tasks (intake plus five
  roles), with stable plan IDs and dependency order.
- **SC-2502**: Role prompts contain no raw runtime command, endpoint, credential, or unbounded model
  output; status and artifacts expose only bounded local evidence.
- **SC-2503**: Existing full tests pass and a detached role-DAG run can be resumed with the same
  compiler identity.

## Out of scope

- Automatic role-specific model selection, parallel role execution, population evolution, or a
  domain-specific evaluator implementation.
- A new service, queue, database migration, or external harness dependency.
