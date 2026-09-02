# Implementation Plan: Agent-Backed Evolution

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Agent support uses existing stdlib-only adapter contracts. |
| Local-First and Durable State | Pass | Native archive/state and controller SQLite remain unchanged. |
| Runtime Adapter Isolation | Pass | Bridge is a separate adapter of `CandidateGenerator`. |
| Artifact-First Verification | Pass | Candidate source is independently evaluated before selection. |
| Bounded Autonomy | Pass | Prompt, workspace, output, capabilities, and timeout are bounded. |
| Test-First Recovery and Small Surface | Pass | Fixture Agent tests cover success and fail-closed paths. |

## Structure

```text
src/famou/agent_evolution.py  # Agent -> CandidateGenerator bridge
src/famou/evolution.py        # unchanged strategy/evaluator boundary
src/famou/cli.py              # --agent-command alternative for evolve
tests/test_agent_evolution.py # bridge tests
tests/test_cli.py             # evolve Agent command regression
```

## Phases

1. Implement the bridge and bounded response normalization.
2. Add CLI options and preserve command-generator/OpenEvolve behavior.
3. Add focused tests, docs, full regression, and fixture quickstart.

No database migration is required.
