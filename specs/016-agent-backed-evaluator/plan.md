# Implementation Plan: Agent-Backed Evaluator

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | No external Agent package is required. |
| Local-First and Durable State | Pass | Existing archive/state and SQLite controller remain authoritative. |
| Runtime Adapter Isolation | Pass | Evaluator bridge implements only `CandidateEvaluator`. |
| Artifact-First Verification | Pass | Structured reports are validated before archive selection. |
| Bounded Autonomy | Pass | Explicit executable, bounded prompt, strict JSON, and timeout. |
| Test-First Recovery and Small Surface | Pass | Focused success/failure and CLI compatibility tests. |

## Structure

```text
src/famou/agent_evolution.py  # AgentCandidateEvaluator
src/famou/cli.py              # evaluator-agent CLI options
tests/test_agent_evolution.py # evaluator bridge tests
tests/test_cli.py             # evaluator-agent CLI test
```

No database migration is required.
