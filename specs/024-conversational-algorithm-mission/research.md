# Research: Conversational Algorithm Mission

## Findings

- The existing `AlgorithmProblemContract` is already strict and immutable; reuse it instead of
  creating a second algorithm schema.
- `Store.await_input`/`answer_input` already provide durable pause/resume and bounded answer
  artifacts. The missing operation is attaching a plan to the same run after intake.
- `Runtime.run` is sufficient for a one-turn compiler and keeps Hermes/OpenCode/Codex optional.
- Runtime output is untrusted. Parsing must require an explicit status envelope, bound bytes, and
  validate the nested contract before any scheduler task starts.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Create a second run after compilation | Rejected | Breaks same-run recovery and confuses parent Agents. |
| Let the model directly mutate SQLite | Rejected | Violates controller authority and bounded autonomy. |
| Add a new database table for intake | Deferred | Existing task/input/artifact/event rows are sufficient. |
| Make OpenAI-compatible runtime mandatory | Rejected | Mock/subprocess are required for standalone tests and local tools. |
