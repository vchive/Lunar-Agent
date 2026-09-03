# Contract: Input Staging

`--input SOURCE[=DEST]` is accepted by `solve` and `run`:

```bash
lunar-agent solve "route these orders" \
  --input /absolute/path/orders.csv \
  --input /absolute/path/vehicles.json=vehicles.json \
  --runtime openai-compatible --agent-loop --json
```

The resulting run contains:

```text
data/raw/orders.csv
data/raw/vehicles.json
```

Each file is recorded as `kind=input_data`. A repeated request with identical bytes is a no-op;
different bytes at the same destination are rejected. The runtime receives a copy below its
attempt workspace and can access it with `read_file`, `run_command` (when explicitly enabled), or
ordinary subprocess file I/O.
