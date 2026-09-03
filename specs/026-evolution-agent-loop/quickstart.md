# Quickstart: Tool-Capable Evolution Agent Loop

Point evolution at an explicit OpenAI-compatible local model and enable tools:

```bash
lunar-agent evolve contract.json --strategy loop \
  --agent-runtime openai-compatible \
  --agent-runtime-endpoint http://127.0.0.1:11434/v1/chat/completions \
  --agent-runtime-model your-local-model \
  --agent-runtime-loop --agent-runtime-allow-exec \
  --agent-runtime-max-steps 40 --json --home .lunar
```

The solver loop may inspect and modify files in its candidate workspace and run explicitly permitted
commands. The evaluator remains a separate loop/runtime instance and still must return a strict
`EvaluationReport`.

