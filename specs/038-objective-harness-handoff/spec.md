# Feature Specification: Objective Harness Handoff

**Feature Branch**: `038-objective-harness-handoff`
**Created**: 2026-09-03
**Status**: Implemented

## Context and scope

Feature 037 makes every native conversational candidate execute against verified inputs and pass
its output contract before evaluation. The remaining selection weakness is objective authority:
`solve --evolve` always asks an Agent evaluator for quality, even when the owner already has a
deterministic local scorer for cost, accuracy, constraint violations, or benchmark performance.
The low-level `evolve` command accepts an evaluator command, but the conversational handoff does
not, so callers must abandon the high-level contract compiler and durable parent/child delivery
path to use an exact harness.

This feature lets native conversational evolution use an explicit local evaluator command. Lunar-
Agent still generates candidates through its repository runtime, executes and validates them
through Feature 037, then invokes the harness with the candidate path. The harness reads only the
candidate workspace it is explicitly given and returns the existing strict `EvaluationReport`.
Its non-negative `combined_score` remains the higher-is-better archive selection value, so
minimization harnesses return an inverse or otherwise normalized utility while retaining raw cost
in `detailed_scores`. Final delivery remains Feature 036's
separate clean-room execution.

## User stories and acceptance scenarios

### User Story 1 — Select by a real objective function (P1)

1. Given `solve --evolve --evaluator-command`, every executable native loop/population candidate is
   scored by that command after local process/output validation.
2. The harness receives a candidate path whose sibling workspace contains verified `data/raw/*`,
   `output/*`, and `execution.json`, allowing exact data-dependent validation and scoring.
3. A model evaluator is not invoked, and a harness-selected winner is still independently
   re-executed before parent output promotion.

### User Story 2 — Fail closed and keep credentials out (P1)

1. Malformed JSON, invalid report schema, timeout, non-zero exit, or oversized harness output makes
   that candidate locally invalid without accepting a model claim.
2. Conversational harness processes receive a minimal environment and do not inherit model API
   keys or arbitrary parent environment entries.
3. The durable handoff stores only a SHA-256 profile fingerprint and a configured/not-configured
   marker; raw command arguments and source-machine paths do not enter strategy state or events.

### User Story 3 — Preserve detach and recovery semantics (P1)

1. Detached solve propagates the explicit harness command to the local child process.
2. Resume requires the same command fingerprint. Because raw commands are not persisted, a caller
   must supply the command again; missing or changed commands fail before claiming evolution work.
3. Answering a compiler question may defer the evolution handoff until the explicit command is
   supplied through `solve --resume`, while ordinary runtime-evaluated runs remain automatic.

## Functional requirements

- **FR-3801**: Add `--evaluator-command` to high-level `solve` and `answer`, valid only with native
  `--evolve` loop/population handoffs.
- **FR-3802**: Reuse `CommandCandidateEvaluator` and the existing strict `EvaluationReport` schema;
  do not create a second scoring model.
- **FR-3803**: Run the harness only after `ContractCandidateRunner` succeeds and makes verified
  inputs/outputs/execution evidence available in the candidate workspace.
- **FR-3804**: Allow `CommandCandidateEvaluator` to accept an explicit environment. The high-level
  handoff must use only deterministic non-secret locale/encoding entries.
- **FR-3805**: Fingerprint the harness profile for resume without serializing raw arguments. Reject
  missing, newly added, or changed commands relative to the persisted handoff.
- **FR-3806**: Propagate the command through detached local execution without placing API keys in
  the command or environment exposed to the harness.
- **FR-3807**: Preserve direct `evolve`, OpenEvolve, runtime Agent evaluation, loop/population,
  source-only contracts, and final output materialization behavior.

## Success criteria

- **SC-3801**: A two-candidate conversational fixture whose model evaluator would prefer the wrong
  answer selects the lower real cost through an explicit local harness and delivers its data.
- **SC-3802**: The harness observes verified inputs/outputs but cannot observe `FAMOU_API_KEY` or an
  unrelated parent environment sentinel.
- **SC-3803**: Bad harness output and command drift fail closed; valid resume retains the same
  archive and fingerprint.
- **SC-3804**: Full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- Synthesizing an exact objective harness from arbitrary natural language.
- Installing domain solvers, benchmark datasets, containers, or remote evaluation services.
- Giving an untrusted harness stronger OS isolation than the local owner's explicit command already
  has; container/sandbox adapters remain optional future integrations.
