# Quickstart: Unified Evolution Benchmark Adapters

Compare all three explicit strategies:

```bash
lunar-agent benchmark contract.json \
  --strategy loop --strategy population --strategy openevolve \
  --generator-command "/absolute/path/to/generator" \
  --evaluator-command "/absolute/path/to/evaluator" \
  --openevolve-command "/absolute/path/to/openevolve-wrapper" \
  --max-rounds 3 --population-size 4 --seed 7 \
  --json --home .lunar
```

The OpenEvolve wrapper receives the generated config path as its final argument and must write the
candidate/result envelope described in [the contract](contracts/openevolve-benchmark.md). The
report continues if that wrapper fails, so native measurements remain available.
