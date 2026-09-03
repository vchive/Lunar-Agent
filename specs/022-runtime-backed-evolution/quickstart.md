# Quickstart: Runtime-Backed Evolution

Use a repository-owned subprocess runtime directly as the solver and evaluator. The runtime
command receives the bounded Agent prompt on stdin; evaluator output must be a strict
`EvaluationReport` JSON object.

```bash
lunar-agent evolve contract.json --strategy loop \
  --agent-runtime subprocess \
  --agent-runtime-command "/absolute/path/to/local-agent --json" \
  --json --home .lunar
```

For an OpenAI-compatible local server, configure the endpoint and model explicitly:

```bash
lunar-agent evolve contract.json --strategy population \
  --agent-runtime openai-compatible \
  --agent-runtime-endpoint "http://127.0.0.1:11434/v1/chat/completions" \
  --agent-runtime-model "your-local-model" \
  --agent-runtime-api-key "$FAMOU_API_KEY" \
  --json --home .lunar
```

The same runtime profile can fill only the missing seam when the other side is explicit. Resume
checks a credential-safe fingerprint; detached children receive the key through
`FAMOU_AGENT_RUNTIME_API_KEY` rather than their command line.
