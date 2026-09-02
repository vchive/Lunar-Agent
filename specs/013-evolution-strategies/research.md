# Research: Local Evolution Strategies
## Decision 1: Keep one local strategy seam

**Decision**: Define a small strategy protocol that receives an immutable problem contract, a
candidate generator, and an evaluator, and returns a structured result. The controller and CLI do
not know the selection algorithm.

**Rationale**: Feature 012 already makes the problem contract and evaluator boundary runtime
neutral. A strategy seam lets loop, population, and an optional external adapter share persistence,
budgets, cancellation, and parent-Agent JSON without importing a specific agent runtime.

**Alternatives considered**:

- Put evolution logic in `LocalController`: rejected because it couples scheduler lifecycle to
  candidate selection and makes future strategies difficult to test independently.
- Copy the WebAgent plugin loop: rejected because the local process already owns durable state and
  does not need OpenCode session hooks.

## Decision 2: Implement loop first and population locally

**Decision**: `loop` is the default and uses one fresh generation context per round plus an
append-only archive. `population` is opt-in and maintains a bounded active population with a
score/novelty selector. Both use the same candidate and evaluation records.

**Rationale**: The loop is the lowest-cost path to WebAgent 2.5 effect parity. Population is useful
for long local budgets, but it should be introduced behind the same contract only after the archive
and evaluator invariants are stable. A standard-library diversity score based on normalized code
tokens is sufficient for the first implementation; embeddings would add a dependency and are not
needed to prove the lifecycle.

**Alternatives considered**:

- Only implement population: rejected for interactive tasks because it adds bookkeeping and can
  divide a small budget across too many candidates.
- Treat `--workers` as a population: rejected; workers parallelize independent DAG tasks and have
  no candidate selection semantics.

## Decision 3: OpenEvolve is an optional subprocess adapter

**Decision**: OpenEvolve is invoked only through an explicit executable command supplied by the
caller. Lunar-Agent creates an adapter directory and a bounded JSON config, runs the command with a
timeout, then imports only a validated result file. The base package has no OpenEvolve dependency.

**Rationale**: This preserves standalone installation and avoids duplicate Python dependency trees.
The subprocess boundary also gives cancellation and path confinement a clear owner. Lunar-Agent's
archive and SQLite ledger remain canonical, so an OpenEvolve checkpoint cannot silently mark a run
successful.

**Alternatives considered**:

- Import `openevolve` as a mandatory Python module: rejected because users who only use loop do not
  need it, and provider/dependency conflicts would violate the local-first boundary.
- Call Famou Workspace or `famou-ctl`: rejected because that recreates the service dependency the
  project explicitly excludes.

## Decision 4: Filesystem archive plus atomic JSON state

**Decision**: Candidate source files and records live below the run's `evolution/` directory.
`archive.jsonl` is append-only and `state.json` is replaced atomically after each accepted
iteration. Paths are stored relative to the run workspace.

**Rationale**: The existing SQLite store remains authoritative for task/run lifecycle, while the
strategy archive is large, inspectable, and easy to resume without a schema migration. Atomic
replacement prevents a terminated process from leaving a partially written state file.

**Alternatives considered**:

- Store candidate source in SQLite: rejected due to poor inspectability and unnecessarily large
  transactions.
- Keep only top-k: rejected because low-score but novel candidates are useful for later exploration
  and historical diagnosis.

## Decision 5: Higher-is-better normalized selection

**Decision**: The existing evaluation contract remains authoritative. Candidate selection compares
`validity` first and then non-negative `combined_score`; minimization objectives are normalized by
the caller's evaluator before producing the report.

**Rationale**: This preserves the validity-first invariant and avoids strategy-specific objective
interpretations. A malformed report becomes a failed candidate rather than a selection exception.

**Alternatives considered**:

- Let each strategy interpret objective direction: rejected because it would make loop and
  population incomparable and could reintroduce score hacking.
