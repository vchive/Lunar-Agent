# Quickstart: Adaptive Search Orchestration

No new flag is required:

```bash
lunar-agent solve "minimize route cost and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --compile-evaluator --strategy population \
  --population-size 4 --offspring-per-iteration 2 --islands 2 \
  --max-rounds 5 --json --home .lunar
```

Each Agent generation receives a `search_directive`. Initial population calls explore and diversify;
invalid baselines repair; valid offspring refine or recombine. Directives and tag policy reconstruct
from archive state on resume.

The deterministic repository scenarios are:

```bash
uv run pytest -q tests/test_adaptive_search_orchestration.py tests/test_verified_experiment_memory.py
```
