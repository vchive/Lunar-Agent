# Research Notes: Agent Adapter and Role Delegation

## Existing seams

Feature 001--012 already establish a local `Runtime` protocol, a SQLite-owned run/task/attempt
ledger, run-relative `ArtifactStore`, evaluator profiles, and detached `resume`. Feature 013 adds
loop/population evolution strategies and deliberately keeps external OpenEvolve behind an explicit
subprocess boundary. The missing seam is a first-class worker contract: a caller can currently
choose a runtime, but cannot describe a role-bearing worker or use an arbitrary local Agent with a
stable JSON exchange.

## Alternatives considered

### Modify Hermes/OpenCode directly

Rejected. It would make Lunar-Agent depend on a particular installation, configuration layout, and
prompt/event protocol. It also makes recovery and testing depend on a user's global environment.

### Automatically discover CLIs from PATH or home directories

Rejected for both safety and reproducibility. A command that happens to be installed must not
silently receive a user's workspace or credentials. Registration is explicit and deterministic.

### Treat every worker as a `Runtime`

Useful for backwards compatibility, but insufficient as the public delegation model: Runtime has
only prompt/workspace/timeout and has no role, capability, or normalized result identity. The new
contract wraps existing runtimes rather than changing them.

### Add a service/queue protocol

Out of scope. The first release is a single-user local application. A one-request/one-response
stdin/stdout protocol provides interoperability with Codex, Hermes, OpenClaw, OpenCode wrappers,
and shell scripts without a daemon.

## Decisions

1. `AgentAdapter` is runtime-neutral and synchronous; cancellation and process observation are
   optional lifecycle hooks matching the existing Runtime contract.
2. `AgentRegistry` is caller-owned. Only explicitly registered adapters are eligible, and sorting by
   adapter name makes selection reproducible.
3. `CommandAgentAdapter` validates an absolute executable before process creation, never invokes a
   shell, bounds stdout/stderr, and accepts either one JSON object or bounded plain text.
4. Adapter work runs under `tasks/<task>/<attempt>/`; returned artifact paths are run-relative and
   are recorded and hashed by the controller, not trusted as database input.
5. The controller emits selection/start/finish/failure events and remains the only component that
   claims or settles tasks and runs.
6. The CLI exposes a small `delegate` command for parent Agents. Existing `run`, `resume`, and
   evolution commands are unchanged.

## Security and recovery notes

- Prompts and metadata are bounded before crossing the adapter boundary; secrets are never added by
  the registry or command adapter.
- Relative artifact paths are resolved against the attempt workspace and rejected when they contain
  `..`, are absolute, or resolve outside the run workspace.
- A timeout terminates the child and produces a bounded `AgentInvocationError`; malformed output and
  non-zero exit are failures even when the process claims success.
- A late result after cancellation is discarded using the existing controller/store race handling.
