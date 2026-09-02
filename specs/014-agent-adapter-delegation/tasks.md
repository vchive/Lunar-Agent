# Tasks: Agent Adapter and Role Delegation

## Phase 1 — contract and value objects

- [x] T014-01 Add bounded `AgentRequest` and `AgentResult` value objects.
- [x] T014-02 Add `AgentAdapter` protocol, registry selection, and focused unit tests.

## Phase 2 — adapters

- [x] T014-03 Implement Runtime-to-Agent wrapper and lifecycle forwarding.
- [x] T014-04 Implement explicit absolute-command JSON/text adapter with timeout and path checks.
- [x] T014-05 Add malformed-output, non-zero, timeout, and unsafe-artifact tests.

## Phase 3 — controller

- [x] T014-06 Add optional registry injection without changing legacy Runtime behavior.
- [x] T014-07 Implement durable `run_agent` selection, claim, event, artifact, evaluation, and
  cancellation lifecycle.
- [x] T014-08 Add controller SQLite/event/artifact/recovery tests.

## Phase 4 — CLI and delivery

- [x] T014-09 Add `delegate --json` with explicit command/role/capability arguments.
- [x] T014-10 Document parent-Agent invocation and run legacy CLI regression tests.
- [x] T014-11 Run pytest, Ruff, compileall, diff check, and fixture quickstart; mark this feature
  complete with known limitations.
