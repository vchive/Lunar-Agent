# Feature Specification: Local Evolution Strategies

**Feature Branch**: `013-evolution-strategies`
**Created**: 2026-09-02
**Status**: Implemented
**Input**: Build both WebAgent-style loop and explicit population search locally, with an optional
OpenEvolve adapter. The project must remain standalone and must not require Hermes, OpenCode, Codex,
Famou Workspace, a remote service, or machine-global agent state.

## Context and scope

Feature 012 validates and stores an `AlgorithmProblemContract`, creates the algorithm workspace,
and records `loop` or `population` as a future choice. This feature makes that choice executable
through one runtime-neutral strategy seam. `loop` is the default interactive path; `population` is
an opt-in local search; `openevolve` is an opt-in integration that is only available when an
explicit local OpenEvolve executable is supplied. The canonical run ledger and candidate archive
remain owned by Lunar-Agent in every mode.

## User Scenarios & Testing

### User Story 1 - Run a bounded local evolution loop (Priority: P1) 🎯 MVP

As a local user or parent Agent, I want a problem contract and candidate generator to run a bounded
WebAgent-style evolution loop that evaluates every candidate and returns the best verified candidate
so that useful long-running improvement works without a service.

**Independent Test**: A deterministic generator produces improving and invalid candidates; the loop
persists every candidate and evaluation, stops at the round/stagnation budget, and returns the best
valid candidate rather than the last candidate.

### User Story 2 - Run explicit population search locally (Priority: P1)

As an algorithm user, I want a bounded population strategy with parent selection, archive retention,
and optional islands so structurally different candidates can survive and be refined over multiple
iterations.

**Independent Test**: A deterministic generator and evaluator show that the active population is
bounded, invalid candidates cannot become best, novel candidates are retained when configured, and
the final result is selected from the archive.

### User Story 3 - Use OpenEvolve without making it a dependency (Priority: P2)

As a local owner, I want to delegate a run to an explicitly configured OpenEvolve command when it is
installed, while the normal Lunar-Agent install remains usable when it is absent.

**Independent Test**: A fake executable receives a generated config and writes a valid candidate
result; the adapter imports it into the same archive. An absent or malformed executable fails with a
bounded actionable error before mutating the run ledger.

### User Story 4 - Preserve standalone and parent-Agent interoperability (Priority: P1)

As a direct user or parent Agent such as Codex, Hermes, or OpenClaw, I want to start/resume an
evolution run through the existing local CLI and bounded JSON output, without installing a global
agent runtime or a remote backend.

**Independent Test**: The same strategy can be invoked directly and as a child process; status and
result payloads contain strategy, iteration, candidate count, and best-candidate metadata, and a
detached run can resume from the local workspace.

## Functional Requirements

- **FR-1301**: The system MUST expose a runtime-neutral `EvolutionStrategy` protocol with `run`,
  `resume`, and structured result methods; strategy implementations MUST NOT import Hermes,
  OpenCode, Codex, or a network client.
- **FR-1302**: The strategy selector MUST accept `loop`, `population`, and `openevolve`; omitted
  strategy MUST resolve to `loop`, and unknown values MUST fail before candidate files or ledger
  rows are written.
- **FR-1303**: All strategies MUST consume the validated algorithm contract and a frozen evaluator
  boundary, and MUST emit the shared `EvaluationReport`; `validity=0` candidates MUST never be
  returned as the best candidate.
- **FR-1304**: Every candidate MUST have a stable ID, relative code/artifact path, parent ID when
  applicable, generation, iteration, strategy, evaluation report, and bounded metadata. Candidate
  records and source files MUST be persisted under the run's `evolution/` directory.
- **FR-1305**: The loop strategy MUST create an independent generation context per round, retain all
  evaluated candidates in an archive, stop at max rounds or configured stagnation, and choose the
  best valid archived candidate.
- **FR-1306**: The population strategy MUST maintain a bounded active population plus an append-only
  archive, use objective-aware parent selection, retain the best valid candidate, and support at
  least one diversity-preserving policy without requiring embeddings or third-party packages.
- **FR-1307**: Population parameters MUST be bounded and explicit: population size, offspring per
  iteration, number of islands, and migration interval/rate. The implementation MUST behave
  deterministically under a supplied random seed for a deterministic generator/evaluator.
- **FR-1308**: The OpenEvolve adapter MUST run only an explicit local command, in a run-relative
  working directory with a generated config; it MUST not discover or invoke a machine-global
  installation and MUST import only bounded, schema-validated result files.
- **FR-1309**: The adapter MUST treat the Lunar-Agent run ledger and archive as canonical. External
  strategy logs or checkpoints are auxiliary and MUST NOT silently settle a run as successful.
- **FR-1310**: Existing `plan`, `run`, `resume`, `status --json`, and parent-Agent JSON behavior
  MUST remain backward compatible. Evolution metadata is additive, and legacy plans without an
  algorithm contract MUST continue to work unchanged.
- **FR-1311**: Cancellation, timeout, malformed generator output, evaluator errors, and missing
  candidates MUST fail closed with bounded error evidence and leave prior archive entries intact.
- **FR-1312**: The implementation MUST use only standard-library runtime dependencies. OpenEvolve
  support MAY be exposed as an optional extra/documented executable contract, but installation MUST
  not be required for `loop` or `population`.

## Non-Goals

- Reimplementing the WebAgent HTTP/SSE service, billing, queues, multi-tenancy, or remote Workspace.
- Making a Hermes/OpenCode/Codex installation part of Lunar-Agent's runtime.
- Claiming statistical superiority of population or OpenEvolve without equal-budget experiments.
- Providing a general-purpose arbitrary-code sandbox; solver/evaluator security remains bounded by
  the existing local workspace and runtime contracts.

## Edge Cases

- Empty candidate output, malformed evaluation, non-finite scores, and evaluator exceptions are
  recorded as failed candidate attempts and cannot replace the best candidate.
- A run with no valid candidate returns a structured failed result while preserving all diagnostics.
- Re-running a completed strategy is idempotent unless the caller explicitly creates a new run.
- A population smaller than the number of islands is rejected before execution; migration of zero
  candidates is a no-op.
- An OpenEvolve command that exits non-zero, times out, or writes an unsafe path fails without
  importing partial output.
- Contract or evaluator changes require a new plan revision/run; an existing archive remains tied
  to its contract digest.

## Key Entities

- **Candidate**: One generated solver/program artifact, its lineage, iteration, strategy, and
  structured evaluation report.
- **CandidateArchive**: Append-only run-scoped collection plus an index of all candidate records.
- **PopulationState**: Bounded active candidate IDs, island membership, iteration, seed, and best ID.
- **EvolutionRunContext**: Immutable contract/evaluator/generator inputs and mutable strategy state
  persisted as JSON under the run workspace.
- **StrategyResult**: Structured terminal or in-progress result suitable for CLI JSON and a parent
  Agent.

## Success Criteria

- **SC-1301**: The deterministic loop quickstart completes locally, archives every round, and
  returns the best valid candidate in under one second for ten fixture rounds.
- **SC-1302**: Population tests prove active population never exceeds configured capacity and
  archive count equals the number of evaluated candidates.
- **SC-1303**: Invalid, malformed, or non-finite evaluation output cannot become the best candidate
  and produces bounded evidence.
- **SC-1304**: OpenEvolve adapter tests pass with a fake executable and fail closed when the command
  is absent, without adding an OpenEvolve dependency to the base environment.
- **SC-1305**: Existing test suite and legacy CLI quickstart remain green; strategy metadata is
  additive and parent-Agent JSON remains parseable.
- **SC-1306**: A detached strategy run can be resumed from local state after the caller exits.

## Assumptions

- A later Solver Agent or caller supplies a generator callback/command that produces candidate files;
  this feature defines and validates that boundary rather than embedding a domain-specific solver.
- The existing `EvaluationReport` normalization and validity-first invariant are authoritative.
- Population and loop strategies may use the existing local Runtime Adapter through an injected
  generator, but strategy code itself remains runtime-neutral.
