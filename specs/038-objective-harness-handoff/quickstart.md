# Quickstart: Objective Harness Handoff

Write an executable evaluator that receives the candidate path as its first argument, reads sibling
`data/raw/`, `output/`, and `execution.json`, then prints one strict `EvaluationReport` JSON object.
For a non-negative cost minimization problem, one valid utility is
`combined_score=1/(1+cost)` while `detailed_scores.cost` retains the raw minimizing value.

```bash
lunar-agent solve "optimize routes and write output/routes.csv" \
  --input ./orders.csv \
  --runtime openai-compatible --endpoint http://127.0.0.1:11434/v1 \
  --model local-model --evolve --strategy population \
  --evaluator-command "/absolute/python /absolute/score_routes.py" \
  --json --home .lunar
```

Resume with the same explicit command:

```bash
lunar-agent solve --resume --run-id <intake-run-id> \
  --runtime openai-compatible --endpoint http://127.0.0.1:11434/v1 \
  --model local-model --evolve \
  --evaluator-command "/absolute/python /absolute/score_routes.py" \
  --json --home .lunar
```

The deterministic repository scenario is:

```bash
uv run pytest -q tests/test_objective_harness_handoff.py
```
