# Implementation Plan: Runtime-Backed Evolution Agents

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Reuses repository runtimes and standard-library adapters. |
| Runtime Adapter Isolation | Pass | Evolution still consumes only Agent protocols. |
| Local-First and Durable State | Pass | Existing archive/ledger remain canonical. |
| Artifact-First Verification | Pass | Evaluator report bridge remains authoritative. |
| Bounded Autonomy | Pass | Existing prompt, timeout, command, and state bounds apply. |
| Secret Safety | Pass | Runtime keys never enter fingerprints or detached argv. |

## Structure

```text
src/famou/cli.py                 # runtime profile options, adapters, fingerprints, detach
tests/test_cli.py                # runtime-backed and provenance acceptance tests
README.md                        # standalone runtime evolution quickstart
docs/architecture.md             # runtime adapter topology
specs/022-runtime-backed-evolution/ # SDD contract and implementation record
```

No database migration is required.
