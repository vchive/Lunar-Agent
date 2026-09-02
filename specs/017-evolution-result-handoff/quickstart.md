# Quickstart: Consume a Verified Evolution Result

Run an evolution strategy with explicit solver and evaluator commands:

```bash
lunar-agent evolve contract.json --strategy loop \
  --generator-command "/absolute/path/to/generator-wrapper" \
  --evaluator-command "/absolute/path/to/evaluator-wrapper" \
  --json --home .lunar
```

The JSON result contains `workspace` and `best_candidate_path`. The path is relative to the
workspace and can be opened by a parent process only after checking the run status is completed:

```text
candidate = Path(result["workspace"]) / result["best_candidate_path"]
```

For an all-invalid run, `best_candidate_id` and `best_candidate_path` are both `null`.
