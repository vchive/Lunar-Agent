# Implementation Plan: Interactive Session Recovery

**Branch**: `004-interactive-session-recovery` | **Date**: 2026-09-01

## Summary

Add a small pause/resume protocol to the repository-owned Hermes-inspired session. The runtime raises
a typed input request after `ask_user`; the controller persists the request and changes the run/task
state. The CLI writes an answer artifact and resumes the same task. The existing DAG scheduler
remains the only orchestration layer.

## Design

```text
model -> ask_user(question, choices)
          |
          v
HermesSessionRuntime raises AgentInputRequired
          |
          v
LocalController writes input-request.json and sets awaiting_input
          |
parent Agent/user -> answer RUN_ID TEXT
          |
          v
answer.json -> task ready -> resume -> next prompt includes answer
```

Question and answer bodies are bounded files. Events contain only lengths, choices count, and
run-relative paths. The runtime does not continue making model requests after asking a question.

## Constitution Check

- Local-First and Durable State: PASS — request/answer artifacts live under the run workspace.
- Runtime Adapter Isolation: PASS — only the session runtime knows `ask_user`; the controller owns
  state transitions.
- Bounded Autonomy: PASS — question/answer and model continuation are bounded.
- Artifact-First Verification: PASS — input files are indexed like other run artifacts.
- Parent-Agent Contract: PASS — one JSON status and an `answer` command preserve the durable handle.
