# Implementation Plan: One-shot Runtime Artifact Envelope

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Teach `OpenAICompatibleRuntime` to parse an opt-in JSON envelope and atomically materialize bounded
text files. Add prompt guidance at the controller boundary and exercise the complete output
promotion path with a fake endpoint.

## Decisions

1. **Runtime-local materialization** — the runtime writes only to the already isolated attempt
   workspace; the controller remains the ledger and promotion authority.
2. **Envelope is optional** — plain text and compiler envelopes preserve their current behavior;
   models may still use `AgentLoopRuntime` for iterative tool calls.
3. **Text-only files** — JSON strings are decoded as UTF-8 content; binary transfer and base64 are
   intentionally excluded to keep inspection and hashing bounds simple.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Standard-library JSON/path handling only. |
| Local-First and Durable State | Pass | Files are attempt-local and existing ledger hashes them. |
| Runtime Adapter Isolation | Pass | Envelope paths cannot escape the attempt root. |
| Artifact-First Verification | Pass | Existing output/role acceptance remains mandatory. |
| Bounded Autonomy | Pass | File count, bytes, metadata, and path components are bounded. |
| Test-First Recovery | Pass | Valid, prose, unsafe, duplicate, and oversized cases are tested. |
