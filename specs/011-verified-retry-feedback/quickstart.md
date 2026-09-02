# Quickstart: Verified Retry Feedback

Create a plan with an acceptance contract and use a runtime/evaluator that fails once. The second
attempt's prompt artifact contains the bounded failed-rule feedback:

```bash
lunar-agent plan retry-plan.json --runtime openai-compatible --agent-loop \
  --endpoint http://127.0.0.1:11434/v1 --model local --home .lunar --json

lunar-agent status <run-id> --home .lunar --json
```

Inspect `tasks/<task-id>/<attempt-2>/prompt.md` in the run workspace. The original task request is
followed by `Retry feedback from the previous verified attempt`; no plan or budget is changed by
the retry. If the failure occurred before evaluation, the feedback uses generic runtime-failure
guidance rather than copying the provider error.
