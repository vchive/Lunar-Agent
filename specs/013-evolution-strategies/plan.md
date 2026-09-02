# Implementation Plan: Local Evolution Strategies

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/013-evolution-strategies/spec.md`

## Summary

Add a runtime-neutral local evolution layer on top of Feature 012's algorithm contract and
validity-first evaluator. The first slice provides a durable filesystem archive and native loop and
population strategies; an optional adapter runs an explicitly configured OpenEvolve command without
making that package mandatory. The run ledger remains owned by Lunar-Agent and all strategy results
use one JSON contract.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Python standard library; optional external OpenEvolve executable only

**Storage**: Run-relative `evolution/` archive/state JSON plus existing SQLite run ledger

**Testing**: pytest, Ruff, compileall, deterministic generator/evaluator fixtures

**Target Platform**: Local macOS/Linux/Windows-compatible Python environment

**Project Type**: Standalone local CLI/library

**Performance Goals**: Strategy bookkeeping under 100 ms per candidate for bounded fixture runs;
external command runtime is governed by an explicit timeout

**Constraints**: No service or global agent dependency; paths confined to run workspace; bounded
candidate and report sizes; evaluator is frozen per run

**Scale/Scope**: One strategy per algorithm run; population and island counts are bounded by config

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Loop and population use only stdlib; OpenEvolve is optional. |
| Local-First and Durable State | Pass | Archive and state are run-relative and atomically persisted. |
| Runtime Adapter Isolation | Pass | Generator/evaluator are injected; strategies do not discover agents. |
| Artifact-First Verification | Pass | Only schema-validated evaluation reports can become best. |
| Bounded Autonomy | Pass | Rounds, population, output size, timeout, and paths are bounded. |
| Test-First Recovery and Small Surface | Pass | Deterministic fixtures cover each strategy and adapter failure. |

## Design decisions

1. Add `openevolve` to the strategy selector as an optional execution mode while retaining the
   Feature 012 default of `loop`. Existing contracts without an evolution field remain unchanged.
2. Keep strategy code in a new `src/famou/evolution.py` module. It owns candidate value objects,
   archive persistence, selection, and the OpenEvolve process adapter, but not task scheduling.
3. Use injected `CandidateGenerator` and `CandidateEvaluator` protocols. The existing Runtime
   Adapter can be wrapped later, while deterministic tests can supply pure callbacks.
4. Persist source files below `evolution/candidates/<id>/` and append candidate records to
   `evolution/archive.jsonl`; atomically replace `evolution/state.json` after each iteration.
5. Keep all strategy result fields additive and JSON-safe so a parent Agent can invoke a library
   entry point now and the CLI can expose it without changing legacy run output.
6. Use a simple code-token novelty measure for population diversity. Do not add embeddings, Ray,
   HTTP/SSE, billing, or a remote Workspace in this feature.

## Project Structure

### Documentation (this feature)

```text
specs/013-evolution-strategies/
├── spec.md
├── research.md
├── data-model.md
├── contracts/
├── quickstart.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```text
src/famou/
├── algorithm.py          # existing contract/evaluation boundaries
├── evolution.py          # candidate, archive, loop/population, OpenEvolve adapter
├── policy.py             # existing plan contract and additive strategy value
└── cli.py                # existing CLI; strategy metadata remains additive

tests/
├── test_evolution.py     # deterministic strategy and adapter tests
├── test_algorithm.py     # existing contract regression tests
└── test_cli.py           # additive CLI regression tests
```

**Structure Decision**: Keep the existing single-project layout. The strategy module is a library
boundary and does not own the controller's DAG scheduler. OpenEvolve is isolated behind a local
subprocess adapter.

## Phases

1. Create and validate the SDD contracts and deterministic fixtures.
2. Implement shared candidate/archive state and the loop strategy.
3. Implement bounded population selection with optional islands/migration.
4. Implement the explicit-command OpenEvolve adapter and strategy selector.
5. Integrate additive metadata into algorithm workspace/CLI seams where safe.
6. Run tests, Ruff, compileall, and the quickstart; update documentation.

## Complexity Tracking

No constitution violation. The external adapter is optional and remains behind a subprocess
boundary; no remote service or new mandatory dependency is introduced.
