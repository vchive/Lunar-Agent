# Implementation Plan: Evidence-Guided Recovery Proposals

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)

## Summary

Introduce a pure deterministic recovery policy over the existing SQLite ledger, persist each
distinct advisory proposal as an event plus hashed local artifact, and expose it through the
runtime-neutral CLI/status JSON boundary. No task state, plan revision, runtime, or budget changes
occur as part of diagnosis.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: Python standard library; no new dependency
**Storage**: Existing SQLite events/artifacts and run workspace JSON; no migration
**Testing**: pytest and Ruff
**Target Platform**: Local macOS/Linux CLI process
**Performance Goals**: O(tasks + events) deterministic proposal; at most 16 evidence values and one
small JSON artifact per distinct proposal
**Constraints**: no Runtime Adapter/model/tool/shell/network invocation; no raw failure-data copying;
preserve CLI JSON compatibility
**Scale/Scope**: one local run and one proposal decision at a time

## Constitution Check

| Principle | Result | Design response |
| --- | --- | --- |
| Standalone distribution | Pass | Standard library only. |
| Local-first and durable state | Pass | Existing SQLite ledger plus run-relative proposal artifact. |
| Runtime Adapter isolation | Pass | Policy consumes durable data only. |
| Artifact-first verification | Pass | Recovery preserves evaluation evidence and hashes its proposal audit file. |
| Bounded autonomy | Pass | Advisory-only, no execution/mutation, generic non-secret evidence. |
| Test-first/small surface | Pass | One policy module, controller persistence seam, CLI/status addition and fixtures. |

## Project Structure

```text
src/famou/
├── recovery.py            # pure RecoveryPolicy and immutable proposal contract
├── controller.py          # calculate and persist advisory recovery proposal
└── cli.py                 # recover command and additive status field

tests/
├── test_recovery.py       # policy, persistence, idempotency, authority fixtures
└── test_cli.py            # parent-agent JSON boundary

specs/009-evidence-guided-recovery/
├── spec.md
├── research.md
├── data-model.md
├── contracts/recovery-proposal.md
├── quickstart.md
├── plan.md
└── tasks.md
```

## Phases

1. Define classification precedence, public JSON shape, idempotency, and fixtures.
2. Implement the pure policy and test the decision matrix without a runtime.
3. Persist distinct proposals using existing artifact/event primitives; add CLI and status exposure.
4. Document operator flow, run all verification, commit with `vchive`, and push `main`.

## Complexity Tracking

No exception is required. A generic autonomous replanner is intentionally excluded because it
would violate explicit authority and increase the local control-plane surface.
