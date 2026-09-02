# Implementation Plan: Verified Retry Feedback

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)

## Summary

Project a bounded, task-scoped retry context from existing evaluator events into each subsequent
attempt's prompt artifact. Keep plan/task rows immutable and avoid schema changes or new runtime
interfaces.

## Phases

1. Define the controlled feedback projection, safety bounds, and rendering contract.
2. Implement event projection and prompt rendering in the controller.
3. Add evaluator-failure, runtime-failure, secret-redaction, parallel-isolation, and artifact
   audit tests.
4. Verify all tests, Ruff, compileall, quickstart, update docs, commit and push with `vchive`.

## Constitution Check

| Principle | Result | Design response |
| --- | --- | --- |
| Standalone distribution | Pass | No dependencies or services. |
| Local-first durable state | Pass | Existing task evaluation and prompt artifacts remain authoritative. |
| Runtime Adapter isolation | Pass | Feedback is task-scoped and adapter-neutral. |
| Artifact-first verification | Pass | Retry prompts are separately hashed artifacts. |
| Bounded autonomy | Pass | Feedback guides correction but cannot mutate plans or limits. |
| Test-first/small surface | Pass | One projection helper and focused controller fixtures. |
