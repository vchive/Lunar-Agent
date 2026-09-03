# Quickstart: Verified Algorithm Candidate Execution

Use an explicit local runner with the existing evaluator command. The runner receives the candidate
path; the evaluator receives the same path and can read the sibling `execution.json` evidence.

```bash
lunar-agent evolve contract.json --strategy loop \
  --generator-command "/absolute/path/to/generator" \
  --candidate-runner-command "/absolute/path/to/run-candidate" \
  --evaluator-command "/absolute/path/to/evaluate-candidate" \
  --json --home .lunar
```

The runner is opt-in. Without `--candidate-runner-command`, historical generator/evaluator and
Agent-backed evolution behavior is unchanged. On success, inspect
`evolution/candidates/<id>/execution.json`, the normal archive record, and the validated result.
