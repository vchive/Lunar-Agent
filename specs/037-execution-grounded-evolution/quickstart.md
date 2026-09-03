# Quickstart: Execution-Grounded Conversational Evolution

Run a native conversational search as before:

```bash
lunar-agent solve "optimize routes and write output/routes.csv" \
  --input ./orders.csv \
  --runtime openai-compatible --endpoint http://127.0.0.1:11434/v1 \
  --model local-model --agent-loop --allow-exec \
  --evolve --strategy population --max-rounds 3 \
  --json --home .lunar
```

No new runner flag is needed on this high-level path. Inspect the linked child:

```bash
lunar-agent status <evolution-run-id> --json --home .lunar
```

Each candidate contains `execution.json`; valid contract outputs are indexed as
`candidate_execution_output`. These are search evidence only. The parent receives `kind=output`
files only after the selected winner passes a separate final materialization run.

Direct low-level evolution keeps the explicit adapter surface:

```bash
lunar-agent evolve contract.json \
  --generator-command /absolute/generator \
  --candidate-runner-command /absolute/runner \
  --evaluator-command /absolute/evaluator --json
```

The deterministic repository scenario is:

```bash
uv run pytest -q tests/test_execution_grounded_evolution.py
```

It proves native loop/population gating, copied input integrity, prompt redaction, evidence
indexing, source-only compatibility, resume tamper rejection, and separate final materialization.
