# Implementation Plan: Built-in Algorithm Role DAG

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Add a deterministic role-plan factory and an opt-in `solve --role-dag` switch. The controller keeps
the existing compiler/promotion path but accepts a plan factory, allowing the role plan to be
attached to the same intake run before the normal scheduler executes it.

## Decisions

1. **Opt-in compatibility** — `build_algorithm_plan` and existing four-stage plans are unchanged;
   `build_algorithm_role_plan` is selected explicitly by the CLI and library caller.
2. **Role authority in prompts** — No database migration is needed. Safe task IDs and bounded
   prompts carry role identity; the controller remains the only contract authority.
3. **Independent review** — Evaluator and reviewer are separate scheduler tasks and receive only
   verified dependency artifacts. They use the normal baseline evaluator unless a caller configures
   a stronger evaluator profile.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Standard-library plan factory only. |
| Durable State | Pass | Existing attach-plan transaction and scheduler. |
| Runtime Adapter Isolation | Pass | No role-specific runtime assumptions. |
| Artifact-First Verification | Pass | Existing dependency artifact handoff and evaluator events. |
| Bounded Autonomy | Pass | Fixed role count, prompts, IDs, and DAG. |
| Recovery | Pass | Existing retry/cancel/resume path unchanged. |
