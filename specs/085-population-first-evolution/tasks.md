# Tasks: Population-First Evolution

**Dependency**: Feature 084 verified seed admission and external revalidation must pass before
Feature 085 is closed. Preparatory defaults and compatibility work do not waive this gate.

**Tests**: Required and offline. No task runs a real model, external framework, service, company
evaluator, or campaign.

## Phase 1: Freeze compatibility and dependency boundaries

- [ ] T085-01 Freeze active (`population`, `openevolve`) versus historical (`loop`) strategy parsing,
  the `loop_strategy_retired` outcome, and `LoopStrategy` importable non-mutating stub semantics.
- [ ] T085-02 Verify Feature 084's mixed-batch admission, empty-admitted failure, identity-preserving
  resume, framework-neutral provenance, and all-external local evaluator requirements are
  implemented and passing; block Feature 085 closure until they are.
- [ ] T085-03 Record the existing Feature 051/074/076/078/082 protocol and artifact digests used by
  compatibility tests; do not rewrite their manifests, receipts, or summaries.

## Phase 2: Failure-first tests

- [ ] T085-04 [P] Test that contract compilation, `solve --evolve`, standalone `evolve`, and
  `benchmark` default to population with matching configuration fingerprints.
- [ ] T085-05 [P] Test explicit new `loop` requests fail with `loop_strategy_retired` before run,
  workspace, generator, evaluator, worker, archive, or population mutation.
- [ ] T085-06 [P] Test `LoopStrategy` remains importable, `run()`/`resume()` are non-mutating, and old
  loop contracts/candidates/results remain readable without conversion to population.
- [ ] T085-07 Test the optional generic `evolve --seed-manifest` path requires both explicit current
  dependency/environment SHA-256 flags and an exact `--evaluator-command`, initializes an admitted
  subset as deterministic generation-0 population state, rejects admitted counts above
  `population_size`, fails an empty subset at iteration 0, and rejects changed handoff material
  before selection.
- [ ] T085-08 Test candidate failure, evaluator timeout, worker unknown, and enclosing run failure are
  durably distinct and do not consume a successful formal iteration.
- [ ] T085-09 [P] Test OpenEvolve output with an external evaluation but no matching local receipt
  produces no ranked candidate; require an explicit local evaluator in CLI and benchmark paths.
- [ ] T085-10 [P] Test `AgentLoopRuntime`, `--agent-loop`, `--agent-runtime-loop`, and sealed
  effect-trial strategy metadata remain compatible and are not interpreted as active loop search.

## Phase 3: Population-first implementation

- [ ] T085-11 Change new contract, runtime configuration, conversational handoff, standalone CLI,
  and benchmark defaults to population; reject unknown or retired active strategies early.
- [ ] T085-12 Replace executable legacy loop search with the importable non-mutating
  `LoopStrategy` stub while retaining explicit historical deserializers and writer guards.
- [ ] T085-13 Integrate Feature 084 admitted candidates into population initialization with stable
  IDs, receipts, handoff fingerprints, deterministic islands, atomic active-state commit, and the
  generic-evolve-only manifest/dependency/environment identity arguments.
- [ ] T085-14 Run the admission gate on fresh and resume paths and persist controlled offspring/run
  outcomes before advancing a formal iteration; require at least one evaluated offspring and do not
  count a failed-only batch as completed.
- [ ] T085-15 Route OpenEvolve material through Feature 084 and the explicit local exact evaluator;
  remove every external-evaluation override path into Lunar score, rank, or delivery.
- [ ] T085-16 Make benchmark selection population-only by default and permit only explicit
  population/OpenEvolve comparisons with separate workspaces and shared local evaluator authority.

## Phase 4: Documentation and verification

- [ ] T085-17 Update active README examples to population, show OpenEvolve with
  `--evaluator-command`, explain runtime-loop independence, and retain historical feature/effect
  protocol descriptions.
- [ ] T085-18 Run focused Feature 084/085 tests, full regression, Ruff, compileall, Specify, diff
  checks, and sealed-artifact digest checks.
- [ ] T085-19 Record that the change makes no effectiveness claim and defer concrete external
  framework integrations and real measurements to separately frozen features/campaigns.

## Execution order

T085-01–03 establish the boundary. T085-04–10 are failure-first and may proceed in parallel where
marked. T085-11/12 may be prepared before Feature 084 is complete, but T085-02 hard-blocks
T085-13–16 and final closure. T085-17–19 follow the integrated behavior.
