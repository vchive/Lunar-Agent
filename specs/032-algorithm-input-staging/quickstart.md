# Quickstart: Algorithm Input Staging

Start a mission with real local data:

```bash
lunar-agent solve "根据订单和车辆数据设计配送路线" \
  --input ./orders.csv \
  --input ./vehicles.json=vehicles.json \
  --runtime openai-compatible --agent-loop \
  --endpoint http://127.0.0.1:11434/v1/chat/completions \
  --model your-local-model --json --home .lunar
```

The response returns `input_data` metadata. `status --json` lists the same rows under `artifacts`
and the convenience field `algorithm_outputs` remains reserved for produced result files. Every
task attempt receives verified copies under its private `data/raw/` directory.

For a detached run, stage inputs before the child starts; resuming with the same arguments is
idempotent:

```bash
lunar-agent solve "analyze orders.csv" --input orders.csv --detach --runtime mock --json
lunar-agent solve --resume --run-id <run-id> --input orders.csv --runtime mock --json
```
