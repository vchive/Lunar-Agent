# Implementation Plan: Agent Solver Portfolio

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Reuses local adapters and standard-library CLI. |
| Local-First and Durable State | Pass | Ordered portfolio digest is in existing evolution state. |
| Runtime Adapter Isolation | Pass | Strategies still see only `CandidateGenerator`. |
| Artifact-First Verification | Pass | Every proposal uses the existing independent evaluator. |
| Bounded Autonomy | Pass | Fixed adapter count, command bounds, prompt/output limits. |
| Test-First Recovery and Small Surface | Pass | Focused round-robin and resume conflict tests. |

## Structure

```text
src/famou/agent_evolution.py  # portfolio composition bridge
src/famou/cli.py              # repeatable portfolio command option
tests/test_agent_evolution.py # rotation and failure tests
tests/test_cli.py             # CLI and fingerprint tests
README.md                     # local multi-agent usage
docs/architecture.md         # portfolio seam
```

No database migration is required.
