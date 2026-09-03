# Quickstart: Local Solver Portfolio

Use two explicit solver commands in a population run:

```bash
lunar-agent evolve contract.json --strategy population \
  --agent-portfolio-command "/absolute/path/to/solver-a --json" \
  --agent-portfolio-command "/absolute/path/to/solver-b --json" \
  --evaluator-agent-command "/absolute/path/to/evaluator --json" \
  --json --home .lunar
```

Generation calls use solver-a, solver-b, solver-a, and so on. Both commands share the configured
solver role and capabilities. The independent evaluator still decides validity and best candidate;
the ordered portfolio fingerprint is checked during resume.
