# Quickstart: Reproducible Evolution Benchmark

Use one contract and one explicit command pair for a local comparison:

```bash
lunar-agent benchmark contract.json \
  --strategy loop --strategy population \
  --generator-command "/absolute/path/to/generator" \
  --evaluator-command "/absolute/path/to/evaluator" \
  --max-rounds 3 --population-size 4 --seed 7 \
  --json --home .lunar
```

The result includes one isolated workspace and archive per strategy. Re-run with a different
`--workspace` (or omit it to create a new directory) when preserving prior evidence matters.
