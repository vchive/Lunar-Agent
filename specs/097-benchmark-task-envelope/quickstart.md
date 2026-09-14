# Offline validation

```sh
lunar-agent benchmark-task validate task.json \
  --contract contract.json --input-root ./public-input --json
```

The command only parses the bounded task envelope, verifies contract and input digests, and reports
its envelope/comparison digests. It does not initialize `.lunar`, run SkyDiscover/LLM4AD, call a
model/evaluator, or trust external scores. Keep the contract, input root, model profile and exact
evaluator identity unchanged for later comparison.
