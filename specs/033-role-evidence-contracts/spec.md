# Feature Specification: Strict Algorithm Role Evidence Contracts

**Feature Branch**: `033-role-evidence-contracts`  
**Created**: 2026-09-03  
**Status**: Implemented  
**Input**: Specialist role prompts currently describe hand-off files, but a successful text response
must not be enough to close a role that claims to have produced evidence.

## Context and scope

The role DAG is useful only when each authority boundary leaves a bounded, machine-checkable
artifact. This feature makes the built-in `DataDiscovery`, `ProblemFormulator`, `Evaluator`, and
`Reviewer` hand-offs explicit contracts. Solver data outputs remain governed by Feature 031. The
controller validates and records role evidence in the attempt ledger; no role can close by merely
claiming that it wrote a file.

The feature is intentionally local and runtime-neutral. It does not add a service, database
migration, model-specific parser, or remote schema registry.

## User stories and acceptance scenarios

### User Story 1 — Data discovery leaves observable evidence (P1)

1. Given a built-in role DAG, when `data_discovery` succeeds, then it has produced
   `data/processed/data-profile.json`.
2. The profile is bounded JSON with schema version, at least one observed input, path/format,
   non-negative row count, columns, and bounded data-quality issues.
3. Missing, malformed, symlinked, or oversized profiles fail the task and can trigger a retry.

### User Story 2 — Independent evaluation is a typed authority boundary (P1)

1. Given a built-in role DAG, when `evaluator` succeeds, then it has produced
   `evaluate/evaluation.json`.
2. The file must be one valid `EvaluationReport`; invalid reports, positive scores on invalid
   candidates, malformed JSON, and prose-only responses fail closed.
3. The report is indexed as a `role_evidence` artifact with bounded metadata and is available to
   dependent Reviewer tasks through the normal artifact hand-off.

### User Story 3 — Formulation and review are durable hand-offs (P2)

1. `problem_formulator` must write non-empty UTF-8 `solve/problem-formulation.md`.
2. `reviewer` must write non-empty UTF-8 `evaluate/review.md`.
3. Role evidence is recorded even when a later task fails, without promoting it as an algorithm
   output or allowing it to satisfy a different role's contract.

## Functional requirements

- **FR-3301**: Built-in role plans MUST attach role-specific acceptance contracts to the four
  non-Solver role tasks; legacy/custom plans remain unchanged unless they explicitly use the new
  acceptance rules.
- **FR-3302**: Add bounded acceptance rules for generic structured artifacts, data profiles, and
  `EvaluationReport` files. Paths remain relative to the private attempt workspace and reject
  traversal, symlinks, unreadable files, and files over the existing inspection limit.
- **FR-3303**: `data_profile_valid` MUST validate the profile shape without reading any user machine
  path or persisting file contents in events.
- **FR-3304**: `evaluation_report_valid` MUST call the existing `EvaluationReport.from_dict`
  invariants; text returned by the Solver/Evaluator MUST NOT bypass the file contract.
- **FR-3305**: The controller MUST record validated role files as `kind=role_evidence` artifacts
  with path, size, and SHA-256 metadata, while preserving append-only attempt history.
- **FR-3306**: Retry feedback MUST identify role-evidence failures with bounded rule names.
- **FR-3307**: `deliver` MUST require role evidence for a role-DAG run and include its stable
  run-relative paths in the delivery decision, while preserving legacy delivery behavior.
- **FR-3308**: The repository MockRuntime MUST emit deterministic valid role fixtures only when the
  role prompts request those built-in paths, so smoke tests remain offline and reproducible.

## Success criteria

- **SC-3301**: A valid mock `solve --role-dag` run contains four `role_evidence` artifacts and a
  `task_evaluated` detail for each corresponding acceptance rule.
- **SC-3302**: Removing or corrupting `evaluate/evaluation.json` causes the evaluator task to fail
  or retry; a prose response alone cannot close the task.
- **SC-3303**: A malformed data profile, formulation, or review fails with bounded evidence and no
  leaked file contents.
- **SC-3304**: Existing generic plans, four-stage conversational plans, output contracts, and
  evolution runs remain compatible.
- **SC-3305**: Full tests, lint, compile, diff, and Specify prerequisite checks pass.

## Out of scope

- Domain-specific constraint execution beyond the existing `EvaluationReport` schema.
- Automatic model selection, remote evaluators, HTTP/SSE, queues, or a new persistence service.
- Replacing `result.txt`; role evidence complements the conversational/audit transcript.
