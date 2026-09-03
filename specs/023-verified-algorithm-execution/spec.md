# Feature Specification: Verified Algorithm Candidate Execution

**Feature Branch**: `023-verified-algorithm-execution`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Replace model-reported algorithm scores with bounded execution evidence

## Context and scope

Lunar-Agent already archives candidates and validates a structured `EvaluationReport`, but an
evaluator command or Agent can still report a score without exposing how the candidate was run. This
feature adds a runtime-neutral candidate execution boundary. An explicitly configured local runner
executes one candidate in its run-scoped workspace, records bounded evidence, and makes that
evidence available to the existing independent evaluator seam. Existing evaluator and generator
commands remain compatible; callers opt in to execution-backed evaluation.

The feature is deliberately local and single-process from the controller's perspective. It does
not add a service, a global sandbox dependency, a model evaluator, or a new algorithm language.
Resource enforcement is limited to portable process, timeout, output, workspace, and artifact
guards; stronger OS-specific sandboxing remains an optional future adapter.

## User Stories & Testing

### User Story 1 - Run a candidate with bounded local evidence (Priority: P1)

As an algorithm owner, I want a candidate program to run through an explicit local command so that
the evaluator can see real exit status and bounded output instead of trusting a solver claim.

**Independent Test**: A fixture runner receives a candidate path, runs it in the candidate workspace,
and returns a bounded `CandidateExecution` with exit code, duration, and output metadata.

**Acceptance Scenarios**:

1. **Given** a valid candidate and an explicit absolute runner command, **When** execution succeeds,
   **Then** the run records a relative execution evidence file with bounded stdout/stderr metadata.
2. **Given** a runner timeout, non-zero exit, empty executable, or workspace escape, **When** the
   candidate is executed, **Then** execution fails closed without importing an unverified result.

### User Story 2 - Evaluate only with execution evidence (Priority: P1)

As a parent Agent, I want an evaluator command to consume the candidate and its execution evidence
so that validity and quality remain independent from the candidate generator.

**Independent Test**: A fixture evaluator reads the execution evidence, returns a valid report for a
successful candidate, and returns an invalid report when the runner failed; the invalid candidate is
retained in the archive but cannot become best.

**Acceptance Scenarios**:

1. **Given** a successful execution, **When** the evaluator runs, **Then** it receives stable
   candidate and evidence paths and its schema-validated report enters the normal archive.
2. **Given** a failed or malformed execution, **When** evaluation is attempted, **Then** the
   resulting report has `validity=0`, `combined_score=0`, and bounded error evidence.

### User Story 3 - Preserve existing evolution and recovery (Priority: P1)

As an existing Lunar-Agent user, I want command-only, Agent-backed, population, OpenEvolve, and
detached runs to keep their current behavior while execution-backed evaluation is opt-in and
resumable.

**Independent Test**: Existing evolution tests remain green; an execution-backed detached run
resumes with the same runner/evaluator fingerprints and rejects changed command identity.

## Functional Requirements

- **FR-2301**: The library MUST expose a runtime-neutral `CandidateRunner` and immutable bounded
  `CandidateExecution` result.
- **FR-2302**: The command runner MUST invoke only an explicit absolute executable with an argument
  array, candidate path input, run-relative working directory, timeout, and bounded stdout/stderr.
- **FR-2303**: A runner MUST never return an unconfined artifact path; declared artifacts MUST be
  regular files below the candidate attempt workspace and receive the existing SHA-256 treatment.
- **FR-2304**: Execution evidence MUST include status, exit code when available, duration, and
  bounded output metadata; raw output MUST be redacted/bounded before it is persisted or added to a
  report.
- **FR-2305**: An execution-aware evaluator adapter MUST expose stable relative candidate/evidence
  paths to an existing evaluator command without changing the legacy command protocol.
- **FR-2306**: Runner failure, timeout, malformed evidence, evaluator failure, or non-finite report
  values MUST fail closed with `validity=0` and `combined_score=0`.
- **FR-2307**: Execution-backed candidates MUST use the same append-only archive, validity-first
  selection, artifact hashing, cancellation, retry, budget, and detached resume behavior as native
  loop and population strategies.
- **FR-2308**: Runner and evaluator command/profile identity MUST be represented by credential-safe
  SHA-256 fingerprints; raw commands and credentials MUST NOT be written to strategy state.
- **FR-2309**: Existing generator/evaluator/callback/OpenEvolve APIs and CLI behavior MUST remain
  backward compatible when no candidate runner is configured.

## Success Criteria

- **SC-2301**: A successful fixture candidate is executed and evaluated through a bounded local
  runner, with execution evidence and a validated report archived under the run workspace.
- **SC-2302**: 100% of runner timeout, non-zero exit, malformed output, path escape, and evaluator
  failure fixtures fail closed and never select an invalid candidate.
- **SC-2303**: Existing evolution, Agent, portfolio, ensemble, OpenEvolve, callback, detach, and
  resume tests remain green without a new runtime dependency.
- **SC-2304**: An execution-backed detached run resumes only with matching runner/evaluator
  provenance and stores no raw command or credential in state.

## Out of scope

- Automatic discovery of test commands, datasets, interpreters, Hermes/OpenCode/Codex/Claude Code,
  or operating-system sandbox tools.
- A universal candidate language, generic optimizer DSL, or model-generated evaluator authority.
- Remote queues, HTTP/SSE, multi-tenancy, billing, or a WebAgent service plane.
- Hard memory/CPU isolation that is not portable across supported local platforms.

## Assumptions

- The local owner trusts an explicitly configured runner executable and supplies any language/runtime
  setup it needs.
- An evaluator command remains responsible for domain-specific objective and constraint
  computation; this feature only supplies verified execution evidence.
- Stronger deterministic evaluator construction and conversational contract compilation build on this
  boundary in later SDD features.
