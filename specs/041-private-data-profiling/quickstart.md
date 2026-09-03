# Quickstart: Private Data Profiling

Use the existing compiled-evaluator path with staged CSV/JSON/JSONL/text inputs:

```bash
lunar-agent solve "minimize route cost and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --compile-evaluator --json --home .lunar
```

Before evaluator compilation, Lunar-Agent validates the staged digest and writes a structural
`evaluator-bundle/input-profile.json`. The model sees counts, field names, missing/unique counts,
and scalar types—not input rows, string values, extrema, or source-machine paths.

The deterministic repository scenario is:

```bash
uv run pytest -q tests/test_private_data_profile.py tests/test_frozen_evaluator_bundle.py
```
