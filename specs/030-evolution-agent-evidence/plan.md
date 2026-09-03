# Implementation Plan: Evolution Agent Evidence

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Thread the existing bounded Agent runtime lifecycle into the evolution observer. Agent bridge
objects expose a small optional observer setter; native strategies bind it from
`EvolutionContext.observe`. The bridge validates and emits declared artifacts, while the runtime
adapter enriches model/tool lifecycle events and redacts bounded failures. The SQLite controller
records these events and artifacts using the existing `ArtifactStore` and `Store` APIs.

## Technical context

- Python 3.11+, standard library runtime, pytest.
- Existing JSONL evolution archive and SQLite `events`/`artifacts` tables; no schema migration.
- Paths are checked against the run workspace and symlink components are rejected.
- Event payloads contain counts/status/identities only; transcript bytes remain filesystem artifacts.

## Decisions

1. **Observer binding instead of strategy coupling** — strategies remain unaware of Agent classes;
   the base strategy binds optional observers to generators/evaluators.
2. **Artifact event as the handoff** — bridge code validates a result artifact once, then the
   controller records it; this keeps standalone evolution usable without SQLite.
3. **Fail closed for declared artifacts** — a missing, symlinked, or escaping declaration is an
   invalid Agent invocation rather than silently discarded evidence.
4. **No raw output events** — model/tool events carry bounded booleans, counts, and byte sizes;
   transcripts are redacted and stored separately.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | No dependency or external harness discovery. |
| Local-First and Durable State | Pass | Existing SQLite ledger and run-relative files are reused. |
| Runtime Adapter Isolation | Pass | Optional observer is exposed through adapter/bridge seams. |
| Artifact-First Verification | Pass | Transcripts are artifacts; candidate/evaluator contracts stay strict. |
| Bounded Autonomy | Pass | Path, size, event, and secret bounds are enforced. |
| Test-First Recovery | Pass | Tests cover success, unsafe paths, redaction, and compatibility. |

## Project structure

```text
src/famou/agents.py          # runtime event forwarding and artifact safety
src/famou/agent_evolution.py # bridge artifact validation/observer binding
src/famou/agent_loop.py      # bounded runtime failure events
src/famou/evolution.py       # optional observer binding at strategy boundary
src/famou/controller.py      # SQLite artifact/event handoff
tests/test_agent_evolution.py
tests/test_controller.py
```

## Complexity tracking

No new table, dependency, process, or network boundary is introduced.
