# Quickstart: Contract-Driven Algorithm Playbooks

No new option is required. Use an Agent-backed native strategy:

```bash
lunar-agent solve "minimize route cost and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --compile-evaluator --strategy population \
  --population-size 4 --offspring-per-iteration 2 --islands 2 \
  --max-rounds 5 --json --home .lunar
```

Every solver generation receives `algorithm_playbook` beside `search_directive`. For routing, seed
rounds are allocated across distinct standard-library-capable routing families when the solver
returns the requested `family_tag` in its experiment declaration. Repair/refine preserve selected
lineage where possible; all proposals still pass independent execution and evaluator gates.

Deterministic repository scenarios:

```bash
uv run pytest -q tests/test_contract_driven_algorithm_playbooks.py \
  tests/test_adaptive_search_orchestration.py tests/test_verified_experiment_memory.py
```
