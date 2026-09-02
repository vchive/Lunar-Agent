# Implementation Plan: Agent Adapter and Role Delegation

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)

## Summary

Introduce a small standard-library-only adapter layer that lets Lunar-Agent delegate to explicit
local workers while preserving the existing Runtime, SQLite, evaluator, artifact, and detached-run
boundaries. Add a machine-readable `delegate` CLI for parent Agents.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | No Hermes/OpenCode/OpenClaw/Codex package is imported or discovered. |
| Local-First and Durable State | Pass | Existing SQLite ledger and run workspace remain authoritative. |
| Runtime Adapter Isolation | Pass | Runtime wrapper and command adapter implement one neutral protocol. |
| Artifact-First Verification | Pass | Controller hashes artifacts and invokes the independent evaluator. |
| Bounded Autonomy | Pass | Explicit executable, no shell, bounded I/O, timeout, and path confinement. |
| Test-First Recovery and Small Surface | Pass | Focused registry/command/controller tests plus legacy regression suite. |

## Structure

```text
src/famou/agents.py       # request/result protocols, registry, runtime and CLI adapters
src/famou/controller.py   # optional registry and one durable delegation entry point
src/famou/cli.py          # `delegate --json` parent-Agent interface
tests/test_agents.py      # adapter and protocol tests
tests/test_controller.py  # SQLite delegation and cancellation tests
tests/test_cli.py         # delegate CLI regression tests
```

## Implementation phases

1. Add and validate request/result/registry value objects and contract tests.
2. Implement `RuntimeAgentAdapter` and `CommandAgentAdapter` with bounded subprocess handling.
3. Add controller delegation lifecycle and event/artifact/evaluator integration.
4. Add the explicit command-backed `delegate` CLI while keeping legacy parser behavior intact.
5. Document invocation examples and run all tests, Ruff, compileall, and a fixture quickstart.

## Compatibility and migration

No database migration is required. Adapter identity is stored in existing `attempts.runtime` and
events. Existing Runtime callers continue to use `run(prompt, workspace, timeout)` unchanged.
