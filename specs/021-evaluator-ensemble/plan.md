# Implementation Plan: Independent Evaluator Ensemble

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Reuses local Agent adapters and standard library. |
| Local-First and Durable State | Pass | Reports remain in candidate archive and existing result files. |
| Runtime Adapter Isolation | Pass | Ensemble implements only `CandidateEvaluator`. |
| Artifact-First Verification | Pass | Validity requires unanimous independent reports. |
| Bounded Autonomy | Pass | Fixed member count, strict report bounds, isolated workspaces. |
| Test-First Recovery and Small Surface | Pass | Focused consensus, median, failure, and CLI tests. |

## Structure

```text
src/famou/agent_evolution.py  # ensemble composition and aggregation
src/famou/cli.py              # repeatable evaluator portfolio option
tests/test_agent_evolution.py # consensus and isolation tests
tests/test_cli.py             # CLI conflicts and fingerprints
README.md                     # evaluator ensemble usage
docs/architecture.md         # verification topology
```

No database migration is required.
