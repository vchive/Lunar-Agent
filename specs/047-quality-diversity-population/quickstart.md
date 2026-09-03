# Quickstart: Quality-Diversity Population Selection

No new flag is needed:

```bash
lunar-agent solve "minimize route cost and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --compile-evaluator --strategy population \
  --population-size 6 --offspring-per-iteration 2 --islands 2 \
  --max-rounds 5 --seed 7 --json --home .lunar
```

Feature 046 asks each structured Agent candidate to report its allocated canonical family tag.
Feature 047 uses that tag as a structural niche: active islands retain evaluator-valid family
elites, parents are sampled across family elites, and inspirations prefer valid complementary
families. Unknown tags and legacy plain source continue through score/token-novelty fallback.

Deterministic repository scenarios:

```bash
uv run pytest -q tests/test_quality_diversity_population.py \
  tests/test_contract_driven_algorithm_playbooks.py tests/test_evolution.py
```
