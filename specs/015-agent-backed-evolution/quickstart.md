# Quickstart: Agent-Backed Loop Evolution

The Agent command is explicit and absolute. It receives one Feature 014 JSON request on stdin and
returns candidate source as plain text or `{\"source\": \"...\"}` JSON. An independent evaluator
command is still required:

```bash
lunar-agent evolve contract.json --strategy loop \
  --agent-command "/absolute/path/to/agent-wrapper --json" \
  --agent-role solver --agent-capability read_files \
  --evaluator-command "/absolute/path/to/evaluator-wrapper" \
  --json --home .lunar
```

The bridge asks the Agent for a candidate, archives its source under the normal evolution archive,
and sends the source to the evaluator. A worker claim is never treated as evaluation evidence.
`population` accepts the same option and adds its normal bounded active population behavior.
