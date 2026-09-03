# Feature Specification: Frozen Evaluator Bundle

**Feature Branch**: `040-frozen-evaluator-bundle`
**Created**: 2026-09-03
**Status**: Implemented

## Context and scope

Feature 038 accepts an owner-written objective harness, while Feature 039 feeds its verified results
back into candidate refinement. For a conversational problem without an existing scorer, Lunar-
Agent still falls back to a model verdict on every candidate. WebAgent's stronger pattern is to
formulate an objective and evaluator once, validate them before search, freeze their business
meaning, and require all later rounds to improve the solution rather than relax the judge.

This feature adds an explicit `--compile-evaluator` mode for native conversational evolution. A
separate runtime turn produces a strict local bundle: human-readable objective, restricted Python
evaluator, declared hard-constraint coverage, synthetic validity probes, and score-order probes.
Lunar-Agent statically validates the evaluator, executes every probe, hashes and freezes the bundle,
then uses it as the independent candidate evaluator. Resume reloads the same digest-bound bundle;
it never asks the model to silently rewrite scoring semantics.

## User stories and acceptance scenarios

### User Story 1 — Compile an exact local judge before search (P1)

1. Given `solve --evolve --compile-evaluator`, the runtime receives the immutable contract and
   returns one strict evaluator-bundle envelope before any candidate is generated.
2. The evaluator reads already executed candidate inputs/outputs and returns the canonical
   `EvaluationReport`; it cannot replace the Feature 037 process/output gate.
3. Valid candidates are ranked by the frozen bundle rather than a fresh model evaluator opinion.

### User Story 2 — Prove validity and ordering before trusting the judge (P1)

1. Every contract hard constraint has a named counterexample probe that the evaluator rejects with
   the matching error code.
2. At least two valid probes establish one strict better-than score ordering consistent with the
   stated objective.
3. Missing coverage, malformed probes, unsafe source, failed execution, wrong validity, invalid
   reports, or reversed/equal scores abort before evolution begins and leave no trusted bundle.

### User Story 3 — Freeze, recover, and audit locally (P1)

1. Objective, evaluator source, probe manifest, and bundle manifest are persisted below the intake
   workspace, SHA-256 indexed, and made read-only after preflight.
2. Strategy state stores only the bundle fingerprint. Resume verifies every file digest and reuses
   the existing bundle without another compiler call; tampering fails before candidate evaluation.
3. Bundle subprocesses use isolated Python, a minimal non-secret environment, closed stdin, bounded
   output, and timeout. No service, tenant, cloud queue, or machine-wide Agent installation exists.

## Functional requirements

- **FR-4001**: Add `--compile-evaluator` to conversational `solve`/`answer`, valid only with native
  `--evolve` and mutually exclusive with an explicit evaluator command.
- **FR-4002**: Define and strictly parse a bounded bundle envelope containing `objective`,
  `evaluator_source`, exact constraint coverage, probes, and score-order assertions.
- **FR-4003**: Restrict evaluator Python imports and dangerous dynamic execution constructs before
  writing or running source; require a normal script entry point and the candidate-path protocol.
- **FR-4004**: Materialize synthetic probe workspaces using only confined `data/raw/*` and
  `output/*` files, canonical successful `execution.json`, and bounded UTF-8 contents.
- **FR-4005**: Require two valid probes, strict declared score ordering, and one matching invalid
  probe for every hard constraint. Parse all outputs through `EvaluationReport`.
- **FR-4006**: Persist and hash objective/evaluator/probe/manifest files atomically, make them
  read-only, index them as run artifacts, and include the bundle fingerprint in strategy config.
- **FR-4007**: On resume, load and digest-verify the frozen bundle instead of regenerating it.
  Reject missing, symlinked, malformed, writable, or tampered bundle files.
- **FR-4008**: Preserve model evaluators, owner commands, callback generators, loop/population,
  OpenEvolve, execution grounding, final materialization, detach, and parent-Agent JSON behavior.

## Success criteria

- **SC-4001**: A two-candidate conversational fixture selects the genuinely better objective value
  through one compiled evaluator call and never invokes the ordinary model evaluator.
- **SC-4002**: Counterexample, score-order, unsafe-source, malformed-report, and tamper tests fail
  closed before an untrusted score influences selection.
- **SC-4003**: Resume reuses the identical bundle fingerprint and performs zero recompilation.
- **SC-4004**: Full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- Claiming generated evaluation code is an OS security sandbox; explicit container adapters remain
  a future hardening option.
- Automatically changing evaluator business semantics after evolution has started.
- Exposing evaluator source or synthetic probe answers to the solver generation workspace.
