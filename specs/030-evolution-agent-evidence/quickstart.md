# Quickstart: Evolution Agent Evidence

Run a local tool-capable evolution with session history:

```bash
lunar-agent evolve contract.json --strategy loop \
  --agent-runtime openai-compatible \
  --agent-runtime-endpoint http://127.0.0.1:11434/v1/chat/completions \
  --agent-runtime-model your-local-model \
  --agent-runtime-loop --agent-runtime-session-history \
  --agent-runtime-max-steps 40 --json --home .lunar
```

Inspect the returned workspace with `lunar-agent status RUN_ID --json` (or the equivalent status
command) and `lunar-agent events RUN_ID --json`. Look for `evolution_agent_artifact`,
`agent_model_turn`, and `agent_tool_result`; transcript files remain under
`evolution/agent/` or each candidate's evaluator workspace.
