# Quickstart: Conversational Algorithm Mission

With a repository-owned mock compiler (useful for smoke tests):

```bash
lunar-agent solve "根据订单数据设计配送路线" --runtime mock --json --home .lunar
```

For a real local model, configure an explicit runtime:

```bash
lunar-agent solve "根据订单数据设计配送路线" \
  --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1/chat/completions \
  --model your-local-model --json --home .lunar
```

If the compiler asks a question, the command returns `status=awaiting_input` and a run ID:

```bash
lunar-agent answer <run-id> "最小化总行驶时间" --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1/chat/completions --model your-local-model \
  --json --home .lunar
```

The run ID does not change. Inspect `status --json` for the compiled contract, plan, artifacts,
and generated task states.
