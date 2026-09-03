# Implementation Plan: Strict Algorithm Role Evidence Contracts

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Reuse the existing declarative acceptance interpreter and artifact ledger. Add three bounded local
rules, attach them only to the built-in specialist role plan, record successful or present role
files as attempt-scoped evidence, and make role-DAG delivery fail closed when those hand-offs are
missing.

## Decisions

1. **Role contracts live in the plan** — role-specific acceptance is serialized with the immutable
   plan, so retries and resume use the same authority without database changes.
2. **One validator boundary** — generic text/JSON checks remain in `evaluator.py`; the existing
   `EvaluationReport` model remains the authority for evaluator reports.
3. **Attempt-local evidence** — role files remain in `tasks/<task>/<attempt>/`; only declared
   algorithm outputs are promoted to `<run>/output/`.
4. **Record before settlement** — a present role file is hashed and indexed even if another rule
   fails, preserving useful audit evidence while delivery still requires a successful task.
5. **Compatibility by opt-in** — only `build_algorithm_role_plan` receives the new acceptance
   contracts; generic/custom plans need to opt in explicitly.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Standard-library validators and local files only. |
| Local-First and Durable State | Pass | Role files and hashes stay in the run workspace/ledger. |
| Runtime Adapter Isolation | Pass | Validators inspect only the private attempt workspace. |
| Artifact-First Verification | Pass | Role acceptance is independent of response prose. |
| Bounded Autonomy | Pass | Fixed paths, fields, bytes, and rule depth. |
| Test-First Recovery | Pass | Valid, missing, malformed, symlink, and legacy cases are covered. |

## Compatibility notes

The four-stage `build_algorithm_plan` remains unchanged to avoid imposing role artifacts on existing
users. It continues to validate Solver outputs from Feature 031. The role plan's `role_evidence`
artifacts are additive and do not change the SQLite schema.
