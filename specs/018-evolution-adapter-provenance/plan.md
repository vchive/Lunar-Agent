# Implementation Plan: Evolution Adapter Provenance

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Uses standard-library hashing and existing CLI. |
| Local-First and Durable State | Pass | Fingerprints are persisted in existing strategy state. |
| Runtime Adapter Isolation | Pass | Identity is supplied by the CLI; strategy sees only config. |
| Artifact-First Verification | Pass | Prevents mixing archives from different evaluators. |
| Bounded Autonomy | Pass | Canonical bounded JSON and fixed-size digest only. |
| Test-First Recovery and Small Surface | Pass | Additive fields with resume mismatch tests. |

## Structure

```text
src/famou/evolution.py  # optional provenance fields and validation
src/famou/cli.py        # canonical adapter fingerprint construction
tests/test_evolution.py # config/state compatibility tests
tests/test_cli.py       # resume drift tests
README.md               # detached/resume guarantee
docs/architecture.md   # durability boundary
```

No database migration is required.
