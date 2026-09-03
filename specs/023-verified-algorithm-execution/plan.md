# Implementation Plan: Verified Algorithm Candidate Execution

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Add a standard-library command runner and a composable execution-aware evaluator while preserving
the existing candidate/evaluator protocols. The controller will index execution evidence and the
CLI will expose an explicit runner option. Provenance and detached propagation will use the same
credential-safe fingerprint boundary as Feature 022.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Python standard library; existing pytest/Ruff development tools

**Storage**: Run-relative JSON evidence and existing SQLite artifact ledger

**Testing**: pytest, Ruff, compileall, git diff check, Specify prerequisite check

**Target Platform**: Local macOS/Linux/Windows-compatible process boundary

**Project Type**: Python library and CLI

**Constraints**: Explicit absolute commands only; no shell; bounded timeout/output/path; no new
runtime dependency; preserve legacy evaluator behavior.

## Constitution Check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Standard-library subprocess boundary; no harness dependency. |
| Runtime Adapter Isolation | Pass | Runner is a narrow injected protocol. |
| Local-First and Durable State | Pass | Evidence is run-relative and indexed by existing ledger. |
| Artifact-First Verification | Pass | Evaluator remains authoritative and report is schema validated. |
| Bounded Autonomy | Pass | Timeout, output, path, and cancellation guards apply. |
| Secret Safety | Pass | State/fingerprint excludes command contents and credentials. |

## Structure Decision

```text
src/famou/evolution.py       # CandidateExecution, CandidateRunner, command runner/evaluator wrapper
src/famou/cli.py             # --candidate-runner-command and detached propagation
src/famou/controller.py      # execution artifact indexing where needed
tests/test_evolution.py      # runner unit/integration tests
tests/test_cli.py            # CLI wiring, conflicts, detach, provenance
specs/023-verified-algorithm-execution/
```

No database migration is required.
