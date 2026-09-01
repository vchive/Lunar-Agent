# Implementation Plan: Session Transcript Recovery

**Branch**: `005-session-transcript-recovery` | **Date**: 2026-09-01

## Summary

Add a repository-owned JSONL transcript with explicit opt-in. `HermesSessionRuntime` appends each
message as the conversation advances; a bounded loader restores recent messages on another attempt.
The controller supplies one stable path per run/task and indexes it as an artifact. No transcript
content is added to events, and no history is loaded when the flag is absent.

## Design

```text
Controller(run, task)
  └─ set_session_path(run/tasks/<task>/session.jsonl)
          |
HermesSessionRuntime (--session-history)
  ├─ load bounded/redacted messages
  ├─ append user / assistant / tool messages
  └─ compact to recent valid JSONL entries
          |
ArtifactStore -> one stable session artifact
```

The transcript is deliberately local and inspectable. It is a continuation aid, not a replacement
for explicit memory: durable facts still use `remember_memory`, and session history is a separate
per-task opt-in.

## Constitution Check

- Local-First and Durable State: PASS — transcript lives below the configured run workspace.
- Runtime Adapter Isolation: PASS — only the session runtime reads/writes transcript messages.
- Bounded Autonomy: PASS — message and file caps prevent unbounded context growth.
- Credential Safety: PASS — API key redaction and explicit history opt-in.
- Artifact-First Verification: PASS — controller hashes the stable transcript artifact.
