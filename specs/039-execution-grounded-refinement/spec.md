# Feature Specification: Execution-Grounded Refinement

**Feature Branch**: `039-execution-grounded-refinement`
**Created**: 2026-09-03
**Status**: Implemented

## Context and scope

Features 037 and 038 make candidate selection depend on real execution, declared outputs, and an
independent evaluator or deterministic objective harness. The solver that creates the next
candidate, however, currently sees only archive identity, score, and simplified evaluator errors.
It cannot inspect the bounded source that produced the score, the concrete process/output-contract
failure, or metadata for outputs that were actually verified. Native loop therefore risks repeated
sampling instead of evidence-guided refinement.

This feature projects persisted candidate evidence into the next Agent generation prompt. Parent,
population inspirations, and recent archive entries share one data-only refinement envelope:
bounded/redacted source, validated `execution.json` status and error evidence, verified output
metadata, and the existing independent `EvaluationReport` projection. Raw input rows and output
contents never enter the prompt. The archive and candidate workspace remain canonical, so resume
reconstructs the same context without new mutable state.

## User stories and acceptance scenarios

### User Story 1 — Repair from real failure evidence (P1)

1. Given a first loop candidate that fails execution or an output contract, the next Agent prompt
   includes its bounded source plus the concrete, sanitized execution status/error.
2. The next proposal can repair the failed behavior and become a valid, independently evaluated
   candidate rather than merely receiving another unconstrained sample.
3. Successful candidates expose only verified artifact path, size, and SHA-256 metadata, never raw
   output contents.

### User Story 2 — Use the same evidence in population search (P1)

1. Population parents and inspirations receive the same refinement envelope as loop parents.
2. Recent archive summaries use the same projection, allowing a solver to avoid known failures and
   reuse successful structure across islands.
3. Resumed runs reconstruct evidence from archived candidate workspaces and do not depend on an
   in-memory previous model turn.

### User Story 3 — Preserve a safe local boundary (P1)

1. Candidate source, controlled error text, paths, and evaluator messages are bounded and secrets
   are redacted before entering a generation prompt; stdout/stderr enter only as byte counts.
2. Raw staged inputs, raw generated outputs, unsafe symlinks, oversized/malformed execution files,
   and unhandled adapter exception details are not exposed.
3. Direct callback and command generators keep their existing `GenerationRequest` behavior; this
   feature changes only Agent prompt construction.

## Functional requirements

- **FR-3901**: Extend Agent candidate summaries with a versioned, data-only refinement evidence
  envelope reconstructed from the candidate archive workspace.
- **FR-3902**: Include a bounded/redacted source excerpt, full-source SHA-256, byte count, and a
  truncation marker for each safely readable candidate.
- **FR-3903**: Parse only regular, non-symlink, bounded `execution.json` evidence through
  `CandidateExecution`; expose status, exit code, duration, stdout/stderr byte counts, controlled
  error category, and only validated artifact names. Candidate-controlled stream contents stay out.
- **FR-3904**: For execution-validated artifacts also declared by the problem output contract,
  expose path, byte count, and SHA-256 after confinement and symlink checks. Never expose file
  contents or inspect undeclared/unvalidated output files.
- **FR-3905**: Apply the evidence projection consistently to parent, inspirations, and recent
  archive candidates in loop and population prompts, including after resume.
- **FR-3906**: Redact known credential patterns and enforce per-field, per-item, and total prompt
  bounds. Unsafe or unavailable evidence must degrade to a stable reason category, not abort the
  entire search or disclose raw internal exceptions.
- **FR-3907**: Keep `evaluation_error` adapter failures generic and preserve existing callback,
  command-generator, evaluator, execution, materialization, and service-free local behavior.

## Success criteria

- **SC-3901**: A deterministic two-round conversational fixture repairs a failed first candidate
  after observing source and execution/output-contract evidence in the second prompt.
- **SC-3902**: Tests prove prompts contain no raw input row, raw output body, API secret, or injected
  evaluator exception detail.
- **SC-3903**: Loop, population, and resumed generation reconstruct equivalent evidence envelopes
  from persisted workspaces.
- **SC-3904**: Full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- Adding chain-of-thought, raw transcripts, raw datasets, or raw output tables to prompts.
- Changing candidate ranking, evaluator authority, population selection, or OpenEvolve internals.
- Persisting a second refinement database or introducing a remote/service execution layer.
