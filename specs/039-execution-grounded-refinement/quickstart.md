# Quickstart: Execution-Grounded Refinement

Run any native conversational evolution with at least two rounds:

```bash
lunar-agent solve "optimize routes and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --strategy loop --max-rounds 3 --json --home .lunar
```

After each candidate is executed, the next solver turn receives a bounded, redacted summary of its
source, execution result, verified output metadata, and independent evaluation. It does not receive
raw input rows or output contents. Population runs apply the same envelope to parents,
inspirations, and recent archive candidates.

The deterministic repository scenario is:

```bash
uv run pytest -q tests/test_execution_grounded_refinement.py
```
