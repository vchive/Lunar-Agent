# Feature Specification: Conversational Evolution Handoff

**Feature Branch**: `035-conversational-evolution-handoff`  
**Created**: 2026-09-03  
**Status**: Implemented

## Context and scope

The `solve` command currently compiles a conversational algorithm contract and executes a fixed
DAG, while `evolve` requires a hand-authored contract file. This split makes the strongest local
search path awkward for a user or parent Agent: the contract has to be copied between commands,
and staged input data is not carried into the evolution workspace. This feature adds an explicit
`solve --evolve` handoff without making evolution mandatory and without coupling Lunar-Agent to a
provider or a machine-wide Hermes/OpenCode/Codex installation.

The handoff keeps two durable local runs: the conversational run remains the canonical intake and
contract record, and a linked evolution run owns the candidate archive, strategy state, and best
candidate. The conversational plan is recorded but its ordinary DAG tasks are explicitly
superseded because the requested evolution strategy replaces that execution path. Staged input
artifacts are copied by digest into the evolution workspace. A bounded link event lets callers
poll either run and resume safely.

## User stories and acceptance scenarios

### User Story 1 — Evolve directly from a natural-language objective (P1)

1. Given a valid conversational compiler response, when `solve --evolve` is invoked, then Lunar-
   Agent creates a canonical intake run and a linked evolution run using the compiled contract.
2. The selected `loop`, `population`, or explicit `openevolve` strategy is run through the existing
   validity-first archive and evaluator boundary. No global Agent installation is inspected.
3. JSON output contains the intake `run_id`, `evolution_run_id`, strategy status, workspace, and
   best candidate path when one exists.

### User Story 2 — Preserve data and recovery boundaries (P1)

1. Every staged `input_data` artifact is copied into the linked evolution workspace with the same
   relative path, byte size, and SHA-256 digest; the original machine path is never persisted.
2. Resuming the same `solve` invocation does not create a second evolution run or mix strategy
   configuration with an existing archive.
3. If evolution fails, the intake contract remains inspectable and the linked failure is reported;
   no unverified candidate is promoted as a result.

### User Story 3 — Keep the feature opt-in and backward compatible (P2)

1. Existing `solve`, `evolve`, `run`, and library APIs behave exactly as before when `--evolve`
   is absent.
2. Runtime-backed evolution uses the explicitly selected solve runtime as separate solver and
   evaluator role adapters. `mock` remains deterministic for local tests; production runtimes are
   still explicitly configured.
3. `--detach` propagates the opt-in and all non-secret strategy settings to the child process;
   credentials are passed only through the existing environment mechanism.

## Functional requirements

- **FR-3501**: Add an opt-in `solve --evolve` mode and bounded strategy controls for strategy,
  rounds, stagnation, population, islands, migration, seed, and timeout.
- **FR-3502**: Compile and validate the conversational contract before creating an evolution run;
  preserve the intake run ID and record one idempotent link event containing only run IDs, strategy,
  and the contract digest.
- **FR-3503**: Supersede unstarted generated-plan tasks with an explicit audit event instead of
  silently leaving them runnable; never supersede a running task.
- **FR-3504**: Copy only verified `input_data` artifacts into the evolution workspace using
  confined, atomic writes and digest/size verification. Re-copying identical bytes is idempotent;
  conflicting bytes fail closed.
- **FR-3505**: Construct solver and evaluator role adapters over the repository-owned runtime and
  execute the existing `EvolutionStrategy` implementation. Evaluator JSON remains authoritative.
- **FR-3506**: Return linked evolution status and result metadata from `solve --json`; status and
  events remain independently queryable with either run ID.
- **FR-3507**: Detached resume rejects changed compiler/runtime or evolution fingerprints using the
  existing state validation and never stores raw commands, prompts, endpoint credentials, or model
  responses in strategy state.
- **FR-3508**: Keep `evolve CONTRACT` and all existing CLI/library surfaces backward compatible.

## Success criteria

- **SC-3501**: A mock `solve --evolve --strategy loop --json` run produces one linked evolution run
  with a completed strategy result and a valid best candidate.
- **SC-3502**: Staged inputs appear in the linked workspace with matching digest/size metadata and
  no source-machine path.
- **SC-3503**: Repeated resume/polling observes the same link and does not duplicate runs or
  candidate IDs; changed strategy settings are rejected before claiming work.
- **SC-3504**: Existing full tests, lint, compile, diff, and Specify checks remain green.

## Out of scope

- Merging the two SQLite runs into a distributed job graph or adding HTTP/SSE, queues, or a
  service plane.
- Inferring an OpenEvolve executable, installing providers, or discovering Hermes/OpenCode/Codex/
  OpenClaw state.
- Promoting a candidate's source into algorithm `output/` files without an explicit output contract
  and independent output evaluator.
