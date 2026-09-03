# Quickstart: Runtime Profile Benchmark

Run the one-shot profile:

```bash
lunar-agent benchmark contract.json --strategy loop --strategy population \
  --agent-runtime openai-compatible \
  --agent-runtime-endpoint http://127.0.0.1:11434/v1/chat/completions \
  --agent-runtime-model your-local-model \
  --max-rounds 3 --population-size 4 --seed 7 \
  --json --home .lunar
```

Then run the same command in another workspace with:

```bash
  --agent-runtime-loop --agent-runtime-session-history --agent-runtime-max-steps 40
```

Compare the two `benchmark.json` files. The loop profile can also opt into
`--agent-runtime-allow-exec` and `--agent-runtime-memory`; both are disabled by default.
