# Quickstart: Independent Evaluator Ensemble

Use two explicit evaluator Agents for a local population run:

```bash
lunar-agent evolve contract.json --strategy population \
  --agent-command "/absolute/path/to/solver --json" \
  --evaluator-portfolio-command "/absolute/path/to/evaluator-a --json" \
  --evaluator-portfolio-command "/absolute/path/to/evaluator-b --json" \
  --json --home .lunar
```

Both evaluators inspect the same candidate independently. Validity requires agreement; valid scores
are combined with a median. A disagreement or member failure archives the candidate as invalid.
