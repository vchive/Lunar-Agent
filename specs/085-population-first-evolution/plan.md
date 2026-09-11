# Plan: Population-First Evolution

## Dependency gate

Feature 085 depends on the verified seed admission and external-result revalidation defined by
Feature 084. Default-selection and compatibility-stub work may be prepared first, but Feature 085
must not be declared complete until Feature 084's admission, receipt, resume, and external material
tests pass. Population initialization and the OpenEvolve path must consume that implementation
rather than creating a second seed or score contract.

## Technical approach

Separate active strategy construction from historical strategy parsing. New `EvolutionSpec`,
`EvolutionConfig`, conversational `solve --evolve`, standalone `evolve`, and `benchmark` requests
resolve to `population` unless the caller explicitly selects `openevolve`. An explicit `loop`
request fails with the fixed `loop_strategy_retired` code before a run, workspace, archive,
generator, evaluator, or worker is created.

Keep `LoopStrategy` importable for library compatibility as a read-only/non-mutating stub. Its
`run()` and `resume()` methods raise the fixed retirement outcome without creating or changing
evolution state. Historical contract, candidate, archive, result, and effect-trial readers
continue to recognize the literal `loop` tag; active configuration and candidate writers reject it.
Historical inspection uses the existing readers, not an executable legacy search loop.

After Feature 084 admission succeeds, initialize `PopulationStrategy` from the atomically admitted
subset. Preserve each identity-derived seed ID, local evaluator receipt, handoff/provenance
fingerprints, `generation=0`, `iteration=0`, `parent_id=null`, and deterministic island assignment.
An empty admitted subset fails before generator or active-state mutation. Resume revalidates the
same material and fingerprints before selection. Only an admitted population may produce
offspring. A formal iteration advances only when at least one configured offspring completes
generation and evaluation and every attempt in that iteration has a durable controlled outcome. A
failed-only batch records failure evidence without being reported as a completed formal iteration.

Keep Feature 084's CLI import surface narrow: `--seed-manifest` is an optional path on the generic
`evolve` command and is valid only for population. When present it requires
`--seed-dependency-sha256`, `--seed-environment-sha256`, and an explicit local exact
`--evaluator-command`. The active contract supplies the contract digest and the selected evaluator
command supplies the evaluator fingerprint; its admission kind is the fixed `exact_harness`, not
the fingerprint domain label. All four identities must match the manifest before staging. Digest
flags without a manifest fail before workspace or run creation. This feature does not add the
seed-manifest option to staged Master→Build or benchmark construction. The admitted count must not
exceed `population_size`.

Keep OpenEvolve as an explicit subprocess material producer. Its candidate source, producer metadata, and any
external evaluation enter the Feature 084 seed handoff as untrusted material. A local exact
`--evaluator-command` and matching receipt are mandatory before Lunar ranking or delivery. The
producer runs in a mode-0700 system temporary workspace with bounded configuration and discarded
stdout/stderr. Only admitted source plus digest-only evidence/metadata summaries cross into the
canonical archive; the external command, raw score, checkpoint, and run ID never become canonical
Lunar state. A completed resume does not invoke the producer again. It rebuilds admission from the
canonical source and sidecar, reruns the local evaluator, and verifies the receipt, provenance, and
configuration identities before returning the prior result.

The benchmark selector accepts active strategies only and defaults to one `population` run.
Explicit population/OpenEvolve comparisons share the local evaluator while retaining separate
workspaces and provenance. `AgentLoopRuntime`, `--agent-loop`, and `--agent-runtime-loop` remain
model/tool runtime controls inside a population generator or evaluator invocation; they do not map
to an evolution strategy.

## Files and structure

- `src/famou/algorithm.py`: new contract defaults and active-versus-legacy strategy validation.
- `src/famou/evolution.py`: population admission integration, iteration outcomes, OpenEvolve local
  revalidation, legacy readers, and the importable non-mutating `LoopStrategy` stub.
- `src/famou/conversational.py`, `src/famou/controller.py`, and `src/famou/cli.py`: population defaults,
  early retired-strategy rejection, generic-evolve-only optional seed-manifest/identity wiring, and
  runtime-loop separation.
- `src/famou/benchmark.py`: active strategy set and population-only default.
- `src/famou/seed_handoff.py`: reused from Feature 084 without a parallel admission schema.
- Focused tests in `tests/test_algorithm.py`, `tests/test_evolution.py`, `tests/test_cli.py`,
  `tests/test_conversational_evolution.py`, `tests/test_benchmark.py`, and existing Agent/runtime and
  sealed effect-trial regression suites.
- `README.md`: active population/OpenEvolve examples while retaining historical feature and effect
  protocol descriptions.

## Failure and compatibility boundaries

- `loop_strategy_retired` is deterministic and credential-safe; it does not copy an arbitrary
  exception into state.
- Reading a historical loop artifact never authorizes `run()` or `resume()` and never rewrites its
  strategy tag to population.
- Missing, invalid, or changed seed receipts fail before generation and do not consume iteration 0
  or create an active population.
- A seed manifest without both current identity digest flags and an explicit exact evaluator, either
  digest flag without a manifest, a manifest on OpenEvolve, or an admitted set larger than the
  configured population fails before active-state mutation.
- Candidate generation failure, evaluator timeout, worker unknown, and run failure remain distinct
  durable outcomes; none can be inferred as a valid candidate or completed iteration.
- OpenEvolve's reported evaluation is provenance only. Omitting local evaluation fails before the
  external result can enter ranking or final delivery.
- Feature 051 and the 074/076/078/082 sealed artifacts keep their historical protocol bytes and
  statistics. `AgentLoopRuntime` and ordinary `--agent-loop` behavior remain executable.

## Verification

Use failure-first offline fixtures for all defaults, retired-loop paths, legacy parsing, verified
seed initialization/resume, iteration accounting, OpenEvolve score rejection, benchmark selection,
and runtime-loop compatibility. Run focused tests, the full regression suite, Ruff, compileall,
Specify prerequisite checks, `git diff --check`, and sealed-artifact digest checks. Do not run a
model, provider, WebAgent, real OpenEvolve process, remote backend, company evaluator, or campaign.

## Complexity tracking

This feature removes an active strategy and joins an already specified admission boundary. It does
not add a network client, framework dependency, new scoring authority, database migration, or
effectiveness claim. Any real framework adapter or measurement remains a separate feature.
