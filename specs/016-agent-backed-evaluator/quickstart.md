# Quickstart: Agent Solver and Evaluator

Use two explicit commands to keep proposal and verification roles separate:

```bash
lunar-agent evolve contract.json --strategy loop \
  --agent-command "/absolute/path/to/solver-wrapper --json" \
  --evaluator-agent-command "/absolute/path/to/evaluator-wrapper --json" \
  --json --home .lunar
```

The evaluator Agent must return one JSON `EvaluationReport` object in its `text` field. The report
is schema-validated and validity-first before it can influence selection.
