# Quickstart: Solver Scoring Contract

Use the existing compiled-evaluator conversational path:

```bash
lunar-agent solve "minimize route cost and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --compile-evaluator --strategy loop --json --home .lunar
```

After compiler and adversarial preflight, each solver generation sees all canonical constraints and
a `scoring_contract` summary. Its isolated workspace contains read-only `scoring/objective.md` and
`scoring/evaluator.py`. `probes.json`, `audit.json`, and `input-profile.json` remain outside solver
workspaces. Candidate success still requires independent execution, frozen evaluation, output
materialization, and delivery validation.

The deterministic repository scenarios are:

```bash
uv run pytest -q tests/test_solver_scoring_contract.py tests/test_frozen_evaluator_bundle.py
```
