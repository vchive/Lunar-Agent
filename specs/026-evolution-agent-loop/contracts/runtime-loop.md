# Contract: Evolution Runtime Loop Options

```text
--agent-runtime-loop
--agent-runtime-max-steps N
--agent-runtime-allow-exec
--agent-runtime-memory
--agent-runtime-session-history
```

The loop switch requires `--agent-runtime openai-compatible`. `N` is a positive bounded integer
(maximum 200). All other evolution generator/evaluator contracts remain unchanged.

