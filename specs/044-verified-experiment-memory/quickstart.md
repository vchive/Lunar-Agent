# Quickstart: Verified Experiment Memory

Run either native strategy with an Agent-backed generator:

```bash
lunar-agent solve "minimize route cost and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --compile-evaluator --strategy loop --max-rounds 5 --json --home .lunar
```

Structured solver candidates declare one bounded experiment. From round two onward, the
`experiment_memory` prompt field reports evaluator-measured outcomes and metric deltas from the
append-only archive. Resume reconstructs the same cards without a model distillation call.

The deterministic repository scenarios are:

```bash
uv run pytest -q tests/test_verified_experiment_memory.py tests/test_agent_evolution.py
```
