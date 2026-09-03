# Quickstart: Frozen Evaluator Bundle

Compile and freeze an independent local evaluator before native search:

```bash
lunar-agent solve "minimize route cost and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --compile-evaluator --strategy population \
  --max-rounds 5 --json --home .lunar
```

The compiler must provide synthetic probes covering every hard constraint plus two valid solutions
whose score order matches the objective. Lunar-Agent runs those probes before candidate generation,
freezes and hashes the accepted bundle, and reuses it on resume.

The deterministic repository scenario is:

```bash
uv run pytest -q tests/test_frozen_evaluator_bundle.py
```
