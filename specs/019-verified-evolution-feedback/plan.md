# Implementation Plan: Verified Evolution Feedback

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Uses existing report/archive models. |
| Local-First and Durable State | Pass | Feedback is reconstructed from the local archive on resume. |
| Runtime Adapter Isolation | Pass | Only the Agent prompt bridge changes. |
| Artifact-First Verification | Pass | Feedback is read-only evidence from verified reports. |
| Bounded Autonomy | Pass | Fixed metric/error caps and existing prompt byte limit. |
| Test-First Recovery and Small Surface | Pass | Focused prompt projection and leakage tests. |

## Structure

```text
src/famou/agent_evolution.py  # bounded report projection in generation context
tests/test_agent_evolution.py # feedback and leakage tests
README.md                     # Agent evolution feedback note
docs/architecture.md         # generation/evaluation feedback seam
```

No database migration is required.
