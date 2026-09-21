# Quickstart: Content-Addressed Effect Kit

Build a public-only kit from current local case bytes:

```bash
lunar-evolution effect-kit .lunar-evolution/reference-kit \
  --case supply_chain_inventory=/absolute/reference-benchmark/03_assignment/supply_chain_inventory \
  --owner-attested-content-equivalence --json
```

Convert saved historical rows under the explicitly attested content-equivalence evidence level:

```bash
lunar-evolution effect-baseline results.json .lunar-evolution/reference-kit/suite.json baseline.json \
  --experiment-id fmexp-... --requested-model gpt-5.6-sol \
  --effective-model openai/gpt-5.6-sol --model-evidence not_observable \
  --owner-attested-content-equivalence --json
```

Then use `.lunar-evolution/reference-kit/cases/supply_chain_inventory` as Feature 048's case source and the
original private case root only in `effect-harness --case-root`. Model execution still requires an
explicit endpoint/model/key; kit construction itself is offline and credential-free.
