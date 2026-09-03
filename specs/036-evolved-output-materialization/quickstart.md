# Quickstart: Evolved Output Materialization

Use an OpenAI-compatible runtime whose contract compiler declares a data output. The generated
candidate protocol is intentionally small: a self-contained Python program reads from `data/raw/`
and writes the exact declared files under `output/` when invoked directly.

```bash
lunar-agent solve "read orders.csv, optimize routes, and return output/routes.csv with item_id and route_id" \
  --input ./orders.csv \
  --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 \
  --model local-model \
  --evolve --strategy population --max-rounds 3 \
  --json --home .lunar
```

The response contains stable parent outputs only after materialization succeeds:

```json
{
  "status": "succeeded",
  "run_status": "succeeded",
  "algorithm_outputs": [
    {"path": "output/routes.csv", "kind": "output", "sha256": "…", "size": 42}
  ],
  "evolution": {
    "status": "succeeded",
    "materialization": {"status": "succeeded", "outputs": [{"path": "output/routes.csv"}]}
  }
}
```

Inspect and deliver the parent run:

```bash
lunar-agent status <intake-run-id> --json --home .lunar
lunar-agent deliver <intake-run-id> --json --home .lunar
```

On failure, inspect the linked materialization result and bounded process evidence before deciding
whether to start a new mission with a changed contract/runtime:

```text
<evolution-workspace>/evolution/materialization/result.json
<evolution-workspace>/evolution/materialization/<candidate>-<digest>/execution.json
```

The repository-owned deterministic version of this scenario is
`tests/test_evolved_output_materialization.py::test_solve_evolve_materializes_reports_and_delivers_output`;
it also verifies that credentials are not inherited and a resumed run does not execute twice.
