# Implementation Plan: Artifact Acceptance Contracts

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)

## Summary

Add a safe in-process acceptance-contract interpreter to the existing evaluator boundary. It
compiles legacy and canonical plan acceptance values before durable work is created, evaluates only
the current attempt workspace, and adds structured rule evidence to existing events/status output.

## Technical Context

**Language/Version**: Python 3.11+ (validated with installed Python 3.13 and compile checks)

**Primary Dependencies**: Python standard library; no new runtime dependency

**Storage**: Existing SQLite event ledger plus run workspace JSON audit file; no schema migration

**Testing**: pytest and Ruff

**Target Platform**: Local macOS/Linux CLI process

**Project Type**: Single-project local CLI/library

**Performance Goals**: Deterministic local contract decision over at most 32 rules and 256 KiB per
inspected file; structured status detail under 20 KiB per task.

**Constraints**: No model/provider call, shell execution, network access, or reads outside the
attempt workspace; preserve current Runtime Adapter and legacy acceptance forms.

**Scale/Scope**: One local run/attempt at a time through the existing controller; no service plane.

## Constitution Check

| Principle | Result | Design response |
| --- | --- | --- |
| Standalone distribution | Pass | Standard library only; no Hermes/OpenCode/Codex requirement. |
| Local-first durable state | Pass | Evidence uses existing events and attempt `evaluation.json`. |
| Runtime Adapter isolation | Pass | Evaluator receives only result/workspace; adapters are unchanged. |
| Artifact-first verification | Pass | Adds independently executable output checks. |
| Bounded autonomy | Pass | Typed rules, path confinement, credentials/size/depth bounds; no execution. |
| Test-first/small surface | Pass | Unit and controller/CLI integration fixtures precede implementation. |

Re-check after implementation: no exception or added dependency is expected.

## Project Structure

```text
src/famou/
├── evaluator.py          # contract parser/interpreter and Evaluation details
├── controller.py         # combines base/profile and acceptance evidence
├── policy.py             # plan task validation boundary
├── store.py              # legacy task input validation boundary
└── cli.py                # status evaluation summary

tests/
├── test_evaluator.py     # contract leaves, composites, bounds, paths
├── test_plan.py          # controller/delivery/replan integration
└── test_cli.py           # parent-agent JSON status contract

specs/008-artifact-acceptance-contracts/
├── spec.md
├── research.md
├── data-model.md
├── contracts/acceptance-contract.md
├── quickstart.md
├── plan.md
└── tasks.md
```

**Structure Decision**: Extend the established single local Python package; persistence already
supports arbitrary structured event payloads, so no database migration or service component is
needed.

## Phases

1. Define contract syntax, safety decisions, and test fixtures in this feature package.
2. Implement bounded compilation/evaluation and validate both plan-entry paths.
3. Add structured base/acceptance evidence to events, audit files, and status JSON.
4. Update docs, run lint/tests/compilation/quickstart, commit as `vchive`, and push `main`.

## Complexity Tracking

No constitution violation. The evaluator gains a small parser/interpreter because independent
artifact verification is a core user-visible safety requirement; a generic plugin or command hook
would increase surface area and violate bounded autonomy.
