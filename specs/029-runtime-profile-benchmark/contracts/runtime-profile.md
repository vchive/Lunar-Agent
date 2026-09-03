# Contract: Runtime Profile Benchmark

The runtime profile is explicit and bounded:

```text
mock | subprocess(command) | openai-compatible(endpoint, model)
```

`--agent-runtime-loop` is valid only for `openai-compatible`; `--agent-runtime-max-steps` is in
`[1, 200]`; memory, session history, and no-shell exec require loop mode. A profile cannot be
combined with `openevolve` in the same benchmark invocation. Every role receives a fresh profile
instance and enters through `RuntimeAgentAdapter`.
