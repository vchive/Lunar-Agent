# Research: Standalone Local Famou Agent

## Decision 1: Keep the controller independent from Hermes

**Decision**: Define a small Python `Runtime` protocol in the repository. Ship a deterministic
`MockRuntime` and a configured `SubprocessRuntime`; add Hermes-inspired session behavior in the
repository itself and keep a direct Hermes adapter optional until the controller
contract is stable.

**Rationale**: Hermes' process-local lifecycle is useful for execution but cannot be the durable
source of truth after a restart. A repository-owned protocol avoids accidental imports from
`~/.hermes`, permits offline tests, and keeps OpenCode/Codex/Hermes replaceable.

**Alternatives considered**:

- Direct Hermes plugin: rejected for P1 because it couples installation, lifecycle, and credentials
  to a machine-wide environment.
- Reimplement a complete model Agent Loop: rejected because it expands maintenance before durable
  scheduling and recovery are proven.
- OpenClaw as the host controller: deferred; its Flow/Swarm are useful but add a host API and version
  lifecycle that this standalone repository should not require.

## Decision 2: SQLite plus filesystem artifacts

**Decision**: Use one SQLite database with WAL mode for metadata/events and a run-scoped directory
for prompts, logs, results, and generated files.

**Rationale**: This is sufficient for a single local user, survives process restarts, is inspectable
with standard tools, and avoids distributed infrastructure. Large content is not pushed into the
database or model context.

**Alternatives considered**:

- JSON-only state: rejected because atomic transitions, queries, and idempotency are fragile.
- PostgreSQL/Redis/Kafka: rejected as service complexity outside the local product boundary.

## Decision 3: Event idempotency and recovery are first-class

**Decision**: Every state transition emits an event with a caller-provided event ID. Startup recovery
converts stale `running` tasks to retryable state and records the recovery event.

**Rationale**: Long-running local work is expected to be interrupted. Idempotent event insertion and
conditional state updates prevent duplicate terminal results when resume is called more than once.

**Alternatives considered**:

- Rely on runtime session reattachment: rejected because external runtimes differ in restart support.
- Periodic snapshots only: rejected because snapshots lose the audit trail and make recovery races
  difficult to reason about.

## Decision 4: CLI first, no local web server in P1

**Decision**: Expose `run`, `resume`, `status`, `events`, and `cancel` through `python -m famou`.

**Rationale**: A CLI is easy to bootstrap, script, test, and inspect over SSH. A TUI or localhost UI
can be added after the state contract is stable.

**Alternatives considered**:

- Browser UI first: rejected because it adds a server lifecycle and does not improve recovery.
- Desktop shell first: rejected because packaging would obscure the controller contract.

## Decision 5: Standard library core with optional development tooling

**Decision**: Keep runtime dependencies to the Python standard library. Use `pytest` and `ruff` only
as development dependencies and document `uv` plus `venv` bootstrap paths.

**Rationale**: A clean machine can run the mock workflow without internet after Python is available,
and no package can silently import a user's global Hermes installation.

**Alternatives considered**:

- Add Hermes as a mandatory package: rejected until its distributable API and version pin are part of
  the repository's own compatibility promise.
