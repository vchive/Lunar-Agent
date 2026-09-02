# Quickstart: Verified Feedback in Agent Evolution

Run a solver Agent with an independent evaluator:

```bash
lunar-agent evolve contract.json --strategy loop \
  --agent-command "/absolute/path/to/solver-wrapper --json" \
  --evaluator-agent-command "/absolute/path/to/evaluator-wrapper --json" \
  --json --home .lunar
```

On each later generation, the solver prompt contains a bounded `evaluation_feedback` projection
for recent candidates. It can use constraint error codes/messages and metric scores as evidence;
the candidate source and evaluator logs remain in the run workspace and are not copied into the
prompt.
