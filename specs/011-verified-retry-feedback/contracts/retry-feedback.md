# Contract: Verified Retry Feedback

## Controller behavior

- `LocalController._build_task_prompt(run, task)` remains backward compatible for first attempts.
- For `task.attempts > 0`, it appends one deterministic feedback section based on task-scoped
  persisted events.
- A malformed/oversized event never makes a retry fail; the renderer falls back to generic
  `runtime_failure` guidance.

## Safety bounds

- At most 16 rule/evidence values are rendered.
- Each rendered value is at most 256 UTF-8 bytes and must be a known rule name or a controlled
  evaluator evidence phrase.
- Raw event `reason`, task `last_error`, result text, prompts, artifact contents, and credentials
  are not rendered.
- The rendered feedback section is at most 8 KiB.

## Attempt artifact

Every attempt retains its own `prompt.md`. A retry creates a new attempt directory and therefore a
new prompt hash; the original attempt's prompt/evaluation remains immutable. No new event type or
CLI field is required.
