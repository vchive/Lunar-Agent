# Feature Specification: Controlled Deep-Evolution Feedback Contract

**Feature Branch**: `main`  
**Created**: 2026-09-05  
**Status**: Implemented

## Context and scope

Feature 051 measures a five-round deep trial, but the continuation context is currently only
three scores. The local knowledge-base review shows that WebAgent's useful behavior is the
closed loop of candidate generation, exact evaluation, progress feedback, and another fresh
agent session—not an unrestricted dump of evaluator output. This feature makes that boundary
explicit and auditable while keeping Lunar independent of WebAgent and service infrastructure.

The contract is deliberately a safe projection. It may carry generic allowlisted numeric detail
metrics, a hash-only candidate artifact manifest, a best-round pointer, a bounded failure
category, and a stagnation directive. It must never carry raw evaluator output, private paths,
baseline rows, credentials, or unbounded candidate contents.

## User stories and acceptance scenarios

### User Story 1 — Give each fresh round actionable but bounded feedback (P1)

1. After the private harness evaluates a round, Lunar derives one feedback object from the
   harness receipt and the public candidate workspace.
2. The next fresh subject receives the previous round's feedback object, including only safe
   scores, generic allowlisted metrics, hash-only artifacts, and a bounded directive.
3. A score supplied by the subject, a private harness path, or raw process output can never enter
   the feedback object.

### User Story 2 — Detect stagnation without changing evaluator authority (P1)

1. Lunar compares the current score with the best score observed so far in the same logical run.
2. After a configurable bounded number of non-improving rounds, feedback marks stagnation and
   requests a strategy change; it does not fabricate a score or terminate the run.
3. An invalid candidate or failed extraction gets a distinct repair directive before generic
   stagnation handling.

### User Story 3 — Recover and inspect the exact feedback chain (P1)

1. Every completed round record stores the feedback sent to the next round.
2. Resume validates the feedback schema, round adjacency, artifact digest format, and the frozen
   stagnation configuration.
3. Reports expose feedback directives and stagnation counts without exposing private harness
   contents.

## Functional requirements

- **FR-5201**: Add a versioned, strict deep feedback contract with finite nullable scores,
  bounded generic detail metrics, bounded failure categories, a hash-only candidate manifest,
  best-round metadata, stagnation metadata, and an enumerated directive.
- **FR-5202**: Extend deep subject validation to accept the contract and retain compatibility with
  the old four-field score summary by normalizing it to a safe legacy projection.
- **FR-5203**: The runner MUST derive feedback only after exact private-harness evaluation and
  MUST store it in the immutable round record; the subject receipt remains score-free.
- **FR-5204**: Detail metrics are filtered through a fixed safe-name allowlist and numeric bounds;
  unknown names are dropped rather than forwarded. Raw stderr/stdout and private file paths are
  never forwarded.
- **FR-5205**: Candidate manifests contain at most 64 relative paths with size and SHA-256 only;
  control files, public-case files, receipts, symlinks, and absolute paths are excluded.
- **FR-5206**: Stagnation is based on best-so-far score improvement, has a bounded threshold
  (1–10 rounds), and produces a deterministic repair/change-strategy directive.
- **FR-5207**: Include the stagnation threshold and feedback schema in the frozen trial identity;
  changed values fail closed on resume.
- **FR-5208**: Add a real two-run, five-round deterministic fixture that verifies ten evaluations,
  per-run round curves, and aggregate P50/P90 behavior.
- **FR-5209**: Existing normal effect trials and Feature 051 behavior remain compatible; this
  feature does not add a population evaluator or claim WebAgent prompt identity.

## Success criteria

- **SC-5201**: A subject receives a feedback object that contains no private path, secret, raw
  output, or unallowlisted detail metric.
- **SC-5202**: A deterministic sequence with two stagnant rounds emits a change-strategy directive
  and reports the correct consecutive stagnation count.
- **SC-5203**: A two-run fixture evaluates exactly ten rounds and reports aggregate run-level and
  round-level distributions without mixing best-of-run and best-of-round values.
- **SC-5204**: Tampering with feedback, manifest digests, or frozen stagnation configuration fails
  closed during resume.
- **SC-5205**: Focused/full tests, lint, compileall, build, Specify checks, and diff review pass.

## Out of scope

- Learning a policy, reinforcement learning, or a second population protocol.
- Forwarding evaluator prose, raw tracebacks, private source, baseline rows, or model credentials.
- Claiming that a local feedback loop reproduces WebAgent's service callbacks or full prompt.
